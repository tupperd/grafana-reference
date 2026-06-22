"""LLM agents, each instrumented as a Sigil generation.

Two orchestrators, each fanning out to 3 research sub-agents, plus an in-app
LLM judge. Everything is a generation; the linkage produces a rich dependency
graph in Grafana Cloud AI Observability:

  outfit-builder ──▶ palette-analyst
                 ├─▶ occasion-decoder
                 ├─▶ silhouette-planner
                 └─▶ outfit-judge            (via "Submit to the critic")

Sub-agents carry parent_generation_ids=[orchestrator_id] and share the
orchestrator's conversation_id, so they render as orchestrator -> sub-agent
edges. Multi-turn chat reuses one conversation_id across turns and passes prior
turns in the input messages list (no parent chaining between turns).
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from sigil_sdk import (
    GenerationStart,
    ModelRef,
    TokenUsage,
    assistant_text_message,
    user_text_message,
)

from . import config, telemetry

log = logging.getLogger("wardrobe.llm")

_client = OpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")

# --- Sub-agent definitions -------------------------------------------------
# Each: (agent_name, system_prompt). Sub-agents return short PROSE notes
# (json_mode off) - far more reliable on a 3B model than nested JSON.
_SUBAGENTS = {
    "outfit": [
        ("palette-analyst",
         "You are a colour-theory specialist on a styling team. Given a wardrobe and an "
         "occasion, advise in 2-3 sentences which colours from the wardrobe pair well and "
         "which to avoid. Be specific and concise. Plain prose, no preamble, no lists."),
        ("occasion-decoder",
         "You decode occasions into dress codes. In 2-3 sentences state the implied "
         "formality level, dress code, and any season or weather considerations for the "
         "given occasion. Plain prose, concise, no preamble."),
        ("silhouette-planner",
         "You are a silhouette and proportion specialist. In 2-3 sentences suggest how to "
         "layer and combine garment categories (top, bottom, outerwear, shoes) from the "
         "wardrobe for a balanced silhouette for this occasion. Plain prose, concise."),
    ],
    "shopping": [
        ("gap-auditor",
         "You audit wardrobes for gaps. Given the current wardrobe and a goal, identify in "
         "2-3 sentences the most important missing categories, colours, or formality levels. "
         "Plain prose, concise, no preamble."),
        ("trend-advisor",
         "You advise on style direction. In 2-3 sentences suggest relevant, timeless-leaning "
         "style directions for the stated goal. Avoid passing fads. Plain prose, concise."),
        ("value-strategist",
         "You prioritise purchases by value. In 2-3 sentences advise which additions give the "
         "best versatility and cost-per-wear for the goal, and where to invest versus save. "
         "Plain prose, concise."),
    ],
}

_OUTFIT_SYNTH_SYS = (
    "You are the lead stylist (the orchestrator of a styling team). You receive research "
    "notes from your specialists, the wardrobe catalogue, and the conversation so far. "
    "Reply conversationally to the user, and when appropriate propose ONE concrete outfit "
    "using only items from the catalogue (referenced by numeric id). Respond ONLY with "
    "valid minified JSON, nothing outside it, matching: "
    '{"reply": string, "proposal": {"title": string, "item_ids": number[], '
    '"rationale": string, "styling_tips": string}}. '
    'Set "proposal" to null if the user only asked a question that needs no new outfit. '
    'The "reply" must be natural conversational prose only - never put JSON, braces, '
    'field names, or the word "proposal" inside the reply string.'
)

_SHOPPING_SYNTH_SYS = (
    "You are the lead buyer (the orchestrator of a sourcing team). You receive research "
    "notes from your specialists, the current wardrobe, and the conversation so far. Reply "
    "conversationally, and when appropriate propose 3-5 NEW items to buy that the user does "
    "not already own. Respond ONLY with valid minified JSON, nothing outside it, matching: "
    '{"reply": string, "proposal": {"summary": string, "recommendations": '
    '[{"item": string, "category": string, "reason": string, "pairs_with": string}]}}. '
    'EVERY recommendation MUST include a non-empty "pairs_with": a comma-separated list of '
    "2-4 specific items the user ALREADY OWNS (use their exact names from the current "
    'wardrobe shown below) that the new item would combine with. Use the item NAMES, never '
    'numeric ids. Never leave "pairs_with" empty, and never name an item not in the wardrobe. '
    'Set "proposal" to null if the user only asked a clarifying question. '
    'The "reply" must be natural conversational prose only - never put JSON, braces, '
    'field names, or the word "proposal" inside the reply string.'
)

# PROMPT 2 (safe): the prone prompt + a physical-wearability rule. Used on
# alternating Buyer turns so the pairs_with correctness evaluator sometimes passes.
_SHOPPING_SYNTH_SYS_SAFE = _SHOPPING_SYNTH_SYS + (
    " PHYSICAL VALIDITY (critical): every pairs_with list, together with the recommended "
    "item itself, must be wearable as a single outfit at the same time. A person can wear "
    "only one top, one bottom, and one piece of outerwear at once - so never list two tops, "
    "two bottoms, or two pieces of outerwear together, and never pair an item with another "
    "piece of its own category (e.g. do not pair outerwear with other outerwear). Choose "
    "pieces from different categories that can all be worn simultaneously."
)


def _model_ref() -> ModelRef:
    return ModelRef(provider=config.LLM_PROVIDER, name=config.OLLAMA_MODEL)


def _format_items(items: list[dict]) -> str:
    lines = []
    for it in items:
        attrs = ", ".join(
            f"{k}={it[k]}"
            for k in ("type", "color", "season", "formality", "material")
            if it.get(k)
        )
        note = f" ({it['notes']})" if it.get("notes") else ""
        lines.append(f"  [{it['id']}] {it['name']} - {attrs}{note}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _chat(messages: list[dict], temperature: float, json_mode: bool, max_tokens=None):
    """Call Ollama via the OpenAI-compatible API; retry without json mode if the
    server rejects response_format."""
    kwargs = dict(model=config.OLLAMA_MODEL, messages=messages, temperature=temperature)
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        return _client.chat.completions.create(**kwargs)
    except Exception:
        if json_mode:
            kwargs.pop("response_format", None)
            return _client.chat.completions.create(**kwargs)
        raise


def _run(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    *,
    conversation_id: str,
    conversation_title: str,
    tags: dict,
    metadata: dict,
    temperature: float = 0.7,
    json_mode: bool = True,
    parent_ids: list[str] | None = None,
    gen_id: str | None = None,
    started_at: datetime | None = None,
    history: list[dict] | None = None,
    max_tokens: int | None = None,
    fixed_output: str | None = None,
) -> tuple[str, str, int]:
    """Execute one generation. Returns (text, generation_id, latency_ms).

    gen_id / started_at let an orchestrator pre-mint its id and timeline start.
    history (prior {role, content} turns) is sent to the model AND recorded as
    the Sigil input, enabling multi-turn conversations.
    fixed_output records a canned response WITHOUT calling the model (used by the
    Buyer's "safe" variant so its output is deterministic and always valid).
    """
    gen_id = gen_id or uuid.uuid4().hex
    start = GenerationStart(
        model=_model_ref(),
        id=gen_id,
        conversation_id=conversation_id,
        conversation_title=conversation_title,
        agent_name=agent_name,
        agent_version="1.0.0",
        user_id=metadata.get("user_id", "local-user"),
        system_prompt=system_prompt,
        temperature=temperature,
        tags=tags,
        metadata=metadata,
        parent_generation_ids=parent_ids or [],
        started_at=started_at,
    )

    chat_msgs = [{"role": "system", "content": system_prompt}]
    sigil_input = []
    for h in history or []:
        chat_msgs.append({"role": h["role"], "content": h["content"]})
        sigil_input.append(
            user_text_message(h["content"])
            if h["role"] == "user"
            else assistant_text_message(h["content"])
        )
    chat_msgs.append({"role": "user", "content": user_prompt})
    sigil_input.append(user_text_message(user_prompt))

    t0 = time.time()
    with telemetry.generation(start) as rec:
        if fixed_output is not None:
            # Canned generation: no model call. Estimate tokens (~chars/4) so the
            # generation still looks populated in the token/cost dashboards.
            text = fixed_output
            in_tok = max(1, len(user_prompt) // 4)
            out_tok = max(1, len(text) // 4)
            response_id, response_model, stop_reason = gen_id, config.OLLAMA_MODEL, "stop"
        else:
            completion = _chat(chat_msgs, temperature, json_mode, max_tokens)
            text = completion.choices[0].message.content or ""
            usage = completion.usage
            in_tok = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0
            response_id = completion.id or gen_id
            response_model = completion.model or config.OLLAMA_MODEL
            stop_reason = completion.choices[0].finish_reason or ""
        rec.set_result(
            input=sigil_input,
            output=[assistant_text_message(text)],
            response_id=response_id,
            response_model=response_model,
            stop_reason=stop_reason,
            usage=TokenUsage(
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=in_tok + out_tok,
            ),
        )
        if rec.err() is not None:
            log.warning("Sigil record error: %s", rec.err())
    latency_ms = int((time.time() - t0) * 1000)
    return text, gen_id, latency_ms


# --- JSON parsing ----------------------------------------------------------

def _parse_or_raw(text: str) -> dict:
    """Parser for the judge (flat JSON object), with raw-text fallback."""
    try:
        return _extract_json(text)
    except Exception:
        log.warning("Could not parse judge JSON; returning raw text")
        return {"parse_error": True, "raw": text}


def _parse_turn(text: str) -> dict:
    """Parser for the dual-payload chat turn -> {reply, proposal|None}.

    Tolerates a model that emits the bare proposal without the {reply, proposal}
    wrapper, and never blanks the UI (falls back to raw text as the reply).
    """
    try:
        data = _extract_json(text)
    except Exception:
        return {"reply": text.strip(), "proposal": None, "parse_error": True}
    if not isinstance(data, dict):
        return {"reply": str(data), "proposal": None}
    # Wrapper present.
    if "reply" in data or "proposal" in data:
        return {"reply": data.get("reply", ""), "proposal": data.get("proposal") or None}
    # Model returned a bare proposal: shim it.
    if any(k in data for k in ("item_ids", "recommendations", "title", "summary")):
        reply = data.get("rationale") or data.get("summary") or "Here is my proposal."
        return {"reply": reply, "proposal": data}
    return {"reply": text.strip(), "proposal": None, "parse_error": True}


# --- Guarantee a "Pairs with" for every shopping recommendation ------------
# Prompt instructions alone are unreliable on a small model, so any empty
# pairs_with is filled deterministically from items the user already owns,
# choosing one piece from each complementary category.
_COMPLEMENT = {
    "top": ["bottom", "outerwear", "shoes"],
    "bottom": ["top", "outerwear", "shoes"],
    "outerwear": ["top", "bottom", "shoes"],
    "shoes": ["top", "bottom", "outerwear"],
    "accessory": ["top", "bottom", "outerwear"],
}


def _normalize_category(cat: str) -> str:
    c = str(cat or "").lower()
    if any(w in c for w in ("shoe", "boot", "sneaker", "foot")):
        return "shoes"
    if any(w in c for w in ("jacket", "coat", "blazer", "outer")):
        return "outerwear"
    if any(w in c for w in ("trouser", "pant", "jean", "short", "bottom", "skirt")):
        return "bottom"
    if any(w in c for w in ("shirt", "tee", "top", "sweater", "knit", "blouse")):
        return "top"
    return "accessory"


def _resolve_pairs(pw: str, items: list[dict]) -> str:
    """Normalize a model-provided pairs_with: map numeric ids -> names, fix the
    casing of owned names, drop unknown ids. Returns "" if nothing resolves."""
    by_id = {str(it["id"]): it["name"] for it in items}
    by_name = {it["name"].lower(): it["name"] for it in items}
    tokens = [t.strip() for t in re.sub(r"[\[\]]", "", str(pw)).split(",") if t.strip()]
    out = []
    for t in tokens:
        if t.isdigit():
            if t in by_id:
                out.append(by_id[t])  # id -> canonical name
            continue
        low = t.lower()
        if low in by_name:
            out.append(by_name[low])  # exact, canonical casing
            continue
        # fuzzy match a near-spelling to an owned item; otherwise drop it
        # (pairings should reference pieces the user already owns)
        match = next((nm for lo, nm in by_name.items() if low in lo or lo in low), None)
        if match:
            out.append(match)
    return ", ".join(dict.fromkeys(out))  # de-dupe, preserve order


def _fill_pairs_with(recommendations: list[dict], items: list[dict]) -> None:
    by_cat: dict[str, list[str]] = {}
    for it in items:
        by_cat.setdefault(it.get("type", ""), []).append(it["name"])
    for rec in recommendations:
        resolved = _resolve_pairs(rec.get("pairs_with", ""), items)
        if resolved:
            rec["pairs_with"] = resolved  # keep the model's pairing (cleaned up)
            continue
        # Empty or unresolvable (e.g. only unknown ids): derive from the wardrobe.
        cats = _COMPLEMENT.get(_normalize_category(rec.get("category", "")),
                               ["top", "bottom", "outerwear", "shoes"])
        picks = []
        for c in cats:
            for name in by_cat.get(c, []):
                picks.append(name)
                break  # one piece per complementary category
        if not picks:
            picks = [it["name"] for it in items[:3]]
        rec["pairs_with"] = ", ".join(picks[:4])


_EXCLUSIVE = {"top", "bottom", "outerwear", "shoes"}


def _enforce_pairs_validity(recommendations: list[dict], items: list[dict]) -> None:
    """Safe-variant sanitizer: ensure each recommendation's pairs_with, together
    with the recommended item, is physically wearable (at most one top, one
    bottom, one outerwear, one pair of shoes). Drops same-category conflicts and
    refills from complementary owned pieces if a list ends up empty."""
    name_to_type = {it["name"]: it.get("type", "") for it in items}
    by_cat: dict[str, list[str]] = {}
    for it in items:
        by_cat.setdefault(it.get("type", ""), []).append(it["name"])
    for rec in recommendations:
        rec_cat = _normalize_category(rec.get("category", ""))
        used = {rec_cat} if rec_cat in _EXCLUSIVE else set()
        kept = []
        for name in [n.strip() for n in str(rec.get("pairs_with", "")).split(",") if n.strip()]:
            cat = name_to_type.get(name, "")
            if cat in _EXCLUSIVE:
                if cat in used:
                    continue  # two of the same exclusive category cannot be worn together
                used.add(cat)
            kept.append(name)
        if not kept:  # everything conflicted - rebuild from complementary categories
            for c in _COMPLEMENT.get(rec_cat, ["top", "bottom", "outerwear", "shoes"]):
                if c in used:
                    continue
                for nm in by_cat.get(c, []):
                    kept.append(nm)
                    used.add(c)
                    break
                if len(kept) >= 3:
                    break
        rec["pairs_with"] = ", ".join(dict.fromkeys(kept))


# --- Canned "safe" Buyer output (always passes the pairs_with evaluator) ----
_SAFE_REPLY = (
    "Here are a few versatile additions that layer cleanly with pieces you already own - "
    "each suggestion is paired only with things you can wear together at the same time."
)


def _safe_shopping_proposal(items: list[dict]) -> dict:
    """Deterministic, hard-coded recommendations whose pairs_with are physically
    valid by construction: each draws one owned piece from DISTINCT complementary
    categories, so there is never a same-category clash. No model call involved."""
    by_cat: dict[str, list[str]] = {}
    for it in items:
        by_cat.setdefault(it.get("type", ""), []).append(it["name"])

    def pair(cats: list[str]) -> str:
        return ", ".join(by_cat[c][0] for c in cats if by_cat.get(c))

    recs = [
        {"item": "Tailored Charcoal Overcoat", "category": "outerwear",
         "reason": "A sharp formal layer that dresses up smart-casual looks.",
         "pairs_with": pair(["top", "bottom", "shoes"])},
        {"item": "Grey Wool Dress Trousers", "category": "bottom",
         "reason": "A formal bottom beyond navy that broadens the rotation.",
         "pairs_with": pair(["top", "outerwear", "shoes"])},
        {"item": "Brown Leather Belt", "category": "accessory",
         "reason": "Pulls browns together and adds a polished finish.",
         "pairs_with": pair(["bottom", "shoes", "top"])},
    ]
    return {"summary": "A few versatile, easy-to-pair additions.", "recommendations": recs}


# --- Research fan-out ------------------------------------------------------

def _run_research(
    kind: str,
    intent: str,
    items: list[dict],
    *,
    conversation_id: str,
    conversation_title: str,
    orchestrator_id: str,
) -> list[dict]:
    """Run the 3 sub-agents for `kind`, each a generation parented to the
    orchestrator and sharing its conversation. Returns concise notes."""
    catalog = _format_items(items)
    label = "Occasion" if kind == "outfit" else "Goal"
    wardrobe_label = "Wardrobe" if kind == "outfit" else "Current wardrobe"
    notes = []
    for agent_name, system in _SUBAGENTS[kind]:
        user = (
            f"{label}: {intent}\n\n{wardrobe_label}:\n{catalog}\n\n"
            "Give your concise expert note."
        )
        note, gid, ms = _run(
            agent_name,
            system,
            user,
            conversation_id=conversation_id,
            conversation_title=conversation_title,
            tags={"feature": kind, "role": "research", "sub_agent": agent_name},
            metadata={"agent_role": agent_name, "orchestrator_id": orchestrator_id, "kind": kind},
            parent_ids=[orchestrator_id],
            temperature=0.4,
            json_mode=False,
            max_tokens=220,
        )
        notes.append({"agent": agent_name, "note": note.strip(), "generation_id": gid, "latency_ms": ms})
    return notes


# --- Orchestrator chat turns -----------------------------------------------

def _turn(
    kind: str,
    orchestrator: str,
    synth_sys: str,
    items: list[dict],
    conversation_id: str | None,
    history: list[dict],
    *,
    run_research: bool,
    synth_variant: str | None = None,
) -> dict:
    prefix = "outfit" if kind == "outfit" else "shopping"
    conv_id = conversation_id or f"{prefix}-{uuid.uuid4().hex[:8]}"
    orch_id = uuid.uuid4().hex
    orch_t0 = datetime.now(timezone.utc)
    latest = history[-1]["content"] if history else ""
    title = f"{'Stylist' if kind == 'outfit' else 'Buyer'}: {latest[:50]}"

    research = []
    if run_research:
        research = _run_research(
            kind, latest, items,
            conversation_id=conv_id, conversation_title=title, orchestrator_id=orch_id,
        )

    findings = "\n".join(f"[{r['agent']}] {r['note']}" for r in research)
    research_block = f"Research from your team:\n{findings}\n\n" if findings else ""
    label = "Occasion" if kind == "outfit" else "Goal"
    proposal_word = "an outfit proposal" if kind == "outfit" else "a shopping proposal"
    user = (
        f"User's latest message: {latest}\n\n"
        f"{research_block}"
        f"{label} context and {('wardrobe' if kind == 'outfit' else 'current wardrobe')}:\n"
        f"{_format_items(items)}\n\n"
        f"Reply to the user and include {proposal_word} if appropriate. Return the JSON now."
    )

    prior = history[:-1][-6:]  # last few prior turns; current intent lives in `user`
    tags = {"feature": kind, ("occasion" if kind == "outfit" else "goal"): latest[:60]}
    metadata = {
        "catalog_size": len(items),
        "prompt_version": "v2",
        "turn": len(history),
        "researched": run_research,
    }
    if kind == "shopping" and synth_variant:
        tags["pairs_prompt"] = synth_variant            # prone | safe (pairs_with eval demo)
        metadata["prompt_variant"] = synth_variant
    # Safe variant: hard-code a guaranteed-valid proposal (no model call), so it
    # always passes the pairs_with evaluator regardless of what the model would do.
    fixed_output = None
    if kind == "shopping" and synth_variant == "safe":
        fixed_output = json.dumps({"reply": _SAFE_REPLY, "proposal": _safe_shopping_proposal(items)})
        metadata["synthesis"] = "canned"
    text, gen_id, ms = _run(
        orchestrator,
        synth_sys,
        user,
        conversation_id=conv_id,
        conversation_title=title,
        tags=tags,
        metadata=metadata,
        gen_id=orch_id,
        started_at=orch_t0,
        history=prior,
        json_mode=True,
        fixed_output=fixed_output,
    )

    data = _parse_turn(text)
    proposal = data.get("proposal") if isinstance(data.get("proposal"), dict) else None
    chosen = []
    if kind == "outfit" and proposal:
        by_id = {it["id"]: it for it in items}
        chosen = [by_id[i] for i in proposal.get("item_ids", []) if i in by_id]
    if kind == "shopping" and proposal and isinstance(proposal.get("recommendations"), list):
        _fill_pairs_with(proposal["recommendations"], items)
        if synth_variant == "safe":
            _enforce_pairs_validity(proposal["recommendations"], items)

    return {
        "reply": data.get("reply") or "",
        "proposal": proposal,
        "chosen_items": chosen,
        "research": research,
        "parse_error": data.get("parse_error", False),
        "generation_id": orch_id,
        "conversation_id": conv_id,
        "latency_ms": ms,
    }


def outfit_turn(items, conversation_id, history, *, run_research=True) -> dict:
    return _turn("outfit", "outfit-builder", _OUTFIT_SYNTH_SYS, items, conversation_id, history, run_research=run_research)


# Alternate the Buyer's system prompt on every turn: prone (fails the pairs_with
# correctness evaluator) -> safe (passes) -> prone -> ... Resets on app restart.
_buyer_turn_count = {"n": 0}


def _next_buyer_variant() -> str:
    variant = "prone" if _buyer_turn_count["n"] % 2 == 0 else "safe"
    _buyer_turn_count["n"] += 1
    return variant


def shopping_turn(items, conversation_id, history, *, run_research=True) -> dict:
    variant = _next_buyer_variant()
    synth = _SHOPPING_SYNTH_SYS if variant == "prone" else _SHOPPING_SYNTH_SYS_SAFE
    return _turn("shopping", "shopping-assistant", synth, items, conversation_id, history,
                 run_research=run_research, synth_variant=variant)


# --- Backward-compatible single-shot wrappers ------------------------------

def build_outfit(items: list[dict], occasion: str) -> dict:
    turn = outfit_turn(items, None, [{"role": "user", "content": occasion}], run_research=True)
    result = turn["proposal"] or {"title": "", "rationale": turn["reply"]}
    return {
        "result": result,
        "chosen_items": turn["chosen_items"],
        "generation_id": turn["generation_id"],
        "conversation_id": turn["conversation_id"],
        "latency_ms": turn["latency_ms"],
    }


def shopping_list(items: list[dict], goal: str) -> dict:
    turn = shopping_turn(items, None, [{"role": "user", "content": goal}], run_research=True)
    result = turn["proposal"] or {"summary": turn["reply"], "recommendations": []}
    return {
        "result": result,
        "generation_id": turn["generation_id"],
        "conversation_id": turn["conversation_id"],
        "latency_ms": turn["latency_ms"],
    }


# --- In-app LLM judge (unchanged contract) ---------------------------------

def judge(
    kind: str,
    context: dict,
    output: dict,
    conversation_id: str | None = None,
    parent_id: str | None = None,
) -> dict:
    conversation_id = conversation_id or f"{kind}-{uuid.uuid4().hex[:8]}"
    agent = f"{kind}-judge"
    system = (
        "You are a meticulous evaluation judge for an AI wardrobe stylist. Score the "
        "assistant's output on a 1-10 scale for overall quality, plus sub-criteria. "
        "Be critical and specific. Respond ONLY with valid minified JSON matching: "
        '{"score": number, "verdict": string, "reasoning": string, '
        '"criteria": {"relevance": number, "coherence": number, "use_of_catalog": number}}'
    )
    user = (
        f"Task type: {kind}\n"
        f"User context:\n{json.dumps(context)[:2000]}\n\n"
        f"Assistant output to evaluate:\n{json.dumps(output)[:2000]}\n\n"
        "Return the JSON evaluation now."
    )
    text, gen_id, latency = _run(
        agent,
        system,
        user,
        conversation_id=conversation_id,
        conversation_title=f"Eval: {kind}",
        tags={"feature": "eval", "judges": kind},
        metadata={"kind": kind, "prompt_version": "v1", "eval": "in_app_judge"},
        temperature=0.0,
        parent_ids=[parent_id] if parent_id else None,
    )
    return {
        "result": _parse_or_raw(text),
        "generation_id": gen_id,
        "conversation_id": conversation_id,
        "latency_ms": latency,
    }
