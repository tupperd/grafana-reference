# Wardrobe AI 👔🛍️

A small, fully local wardrobe-builder web app whose real purpose is to **learn Grafana Cloud AI Observability (Sigil) hands-on**. You catalog your clothes, then two AI features (powered by a local Ollama model) reason over them, and **every LLM call is recorded as a Sigil generation** so you can explore conversations, tokens/cost, latency, traces, and **evaluations** in Grafana Cloud.

> The LLM and the app run entirely on your machine. The only thing that leaves is telemetry, sent to your Grafana Cloud stack.

## What you get

- **Catalog CRUD** — add / remove / view clothing items (text attributes), backed by SQLite, seeded with a starter wardrobe.
- **Turn-based chat** with two modes (a Stylist / Buyer segmented toggle). Each mode is a persistent conversation: turns reuse one `conversation_id` and prior turns are passed in the generation `input`, so a whole back-and-forth threads together in the Conversations view.
- **The Stylist** (`outfit-builder` orchestrator) — composes an outfit from your closet, fanning out to 3 research sub-agents first: `palette-analyst`, `occasion-decoder`, `silhouette-planner`.
- **The Buyer** (`shopping-assistant` orchestrator) — recommends purchases to fill gaps, fanning out to `gap-auditor`, `trend-advisor`, `value-strategist`.
- **Sub-agent dependency graph** — each sub-agent generation carries `parent_generation_ids=[orchestrator_id]` and shares the conversation, so AI Observability renders an `orchestrator → sub-agent` hub. A **"Deep research" toggle** controls fan-out per turn (auto-on for the first turn of a thread, off for follow-up refinements).
- **In-app LLM judge** (`outfit-judge` / `shopping-judge`) — "Submit to the critic" scores any turn 1-10 with sub-criteria, linked to that turn via `parent_generation_ids` so the evaluation threads under it.

## Architecture

```
Browser (HTML/JS)
   │  HTTP
   ▼
FastAPI  ── auth (cookie session)
   ├── catalog API ──────────► SQLite (data/wardrobe.db)
   └── AI API ── llm.py
                  ├── OpenAI-compatible client ─► Ollama (localhost:11434/v1)   [local model]
                  └── Sigil SDK (start_generation / set_result)
                        ├── generation data ────► Grafana Cloud Sigil endpoint
                        └── OTel spans + metrics ► Grafana Cloud OTLP gateway
```

Two correctness details baked into `app/telemetry.py`:
1. **OTel providers are initialized before the Sigil client** — otherwise `gen_ai.*` metrics/traces are silently dropped.
2. **Graceful degradation** — with the Sigil/OTel env vars unset, the app still runs and the AI features still work; nothing is exported. So you can try the app first, then wire up Grafana Cloud.

## Prerequisites

- **Python 3.10+**
- **Ollama** for the local model.

### Install Ollama + pull the model

```bash
# macOS
brew install ollama
# or download from https://ollama.com/download

ollama serve            # run in its own terminal (or it runs as a service)
ollama pull llama3.2:3b # the default model (small, laptop-friendly)
```

You can use any other Ollama model by setting `OLLAMA_MODEL` in `.env` (e.g. `qwen2.5:3b`, `gemma2:2b`).

## Run it

```bash
cp .env.example .env     # optional edits; works as-is for local-only
./run.sh
```

`run.sh` creates a venv, installs dependencies, preflights Ollama, and serves the app at **http://localhost:8000**. Sign in with the credentials in `.env` (default `admin` / `wardrobe`).

Without Grafana Cloud configured the masthead shows an **`Off air`** pill — the AI features still work, they just aren't exported yet.

## Wire up Grafana Cloud AI Observability

You do this once, in your stack. Everything the app needs is read from `.env`.

### 1. Enable the AI Observability app

In your Grafana Cloud stack: **Connections → search "AI Observability" → enable the app**. Open it and find the **Configuration / Connection** page.

### 2. Create an access policy token

Grafana Cloud → **Access Policies** → create a policy/token with scope:
- `sigil:write` (required — the generation export)
- `metrics:write`, `traces:write`, `logs:write` (for the OTLP traces/metrics path)

### 3. Fill `.env`

From the AI Observability Configuration page:

```ini
SIGIL_ENDPOINT=<API URL shown on the Configuration page>
SIGIL_PROTOCOL=http
SIGIL_AUTH_MODE=basic
SIGIL_AUTH_TENANT_ID=<Instance ID shown on the Configuration page>
SIGIL_AUTH_TOKEN=<glc_... token from step 2>
```

For the traces/metrics dashboards (from **Connections → OpenTelemetry → Configure**):

```ini
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-<zone>.grafana.net/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64(instanceID:token)>"
```

> **Gotcha:** URL-encode the space after `Basic` as `%20`. The Python OTLP/HTTP exporter mishandles a literal space in the header.

Restart `./run.sh`. The masthead pill should flip to a green **`On air`**.

## Where to look in Grafana Cloud

Open the **AI Observability** app:
- **Conversations** — each outfit/shopping call appears within a few seconds; click in to see the prompt, response, agent, tokens, and (after you evaluate) the threaded judge generation.
- **Dependency graph** — open a conversation and view dependencies: the orchestrator (`outfit-builder` / `shopping-assistant`) fanning out to its 3 sub-agents, plus the `*-judge`.
- **Agents / filtering** — filter by orchestrators (`outfit-builder`, `shopping-assistant`), sub-agents (`palette-analyst`, `occasion-decoder`, `silhouette-planner`, `gap-auditor`, `trend-advisor`, `value-strategist`), judges (`outfit-judge`, `shopping-judge`), or by the `feature` / `role` / `occasion` / `goal` tags.
- **Tokens / cost / latency** — the `gen_ai.*` metrics power these (needs the OTLP path configured).

## The eval workflow (your priority)

Two complementary paths, both exercised by this app:

**A. In-app LLM judge (built in).** Click **"Submit to the critic"** under any assistant turn. It runs a `*-judge` generation that scores that turn and shows up in AI Observability, threaded under the same conversation via `parent_generation_ids`.

**B. Plugin online eval rules (configured in Grafana Cloud).** Because every generation is recorded **eval-ready** (full input + output messages, model, tokens, agent name, tags), you can attach online evaluation rules in the AI Observability app:
1. In the app, go to the **Evaluations** section and **create a rule**.
2. Scope it (e.g. to agent `outfit-builder`).
3. Pick an evaluator — an **LLM-as-judge** rule (hallucination, relevance, custom rubric), a JSON-schema/regex check, or a heuristic.
4. New matching generations get scored automatically; scores appear on the generation and in the evaluations views.

Tip: tag-based scoping makes it easy to compare, e.g., `outfit` vs `shopping` quality, or A/B two prompt versions by bumping `prompt_version` in `app/llm.py`.

### Simulating evaluator pass/fail (the `pairs_with` demo)

The Buyer (`shopping-assistant`) **alternates its system prompt on every turn** so an online evaluator like `online.pairswith.correctness` (an LLM judge checking that the items in "Pairs with…" are physically wearable together) sees a steady mix of pass/fail:

- **`prone`** (`_SHOPPING_SYNTH_SYS`) — the base prompt; it doesn't forbid same-category pairings, so the **model** regularly proposes impossible combinations (e.g. a new coat paired with an owned blazer — two pieces of outerwear). → **fails** the evaluator.
- **`safe`** — returns a **hard-coded, deterministic proposal** (`_safe_shopping_proposal`) with **no model call at all**. Each recommendation pairs only with owned pieces drawn from *distinct* complementary categories, so it is physically valid by construction and **always passes**, no matter what. The generation is recorded normally (so it still appears and is evaluated) and tagged `metadata.synthesis=canned`.

The toggle (`_next_buyer_variant` in `app/llm.py`) flips `prone → safe → prone → …` and resets on restart. Every Buyer generation is tagged **`pairs_prompt=prone|safe`** (and `metadata.prompt_variant`), so in AI Observability you can group/filter by that tag and watch the evaluator's verdict track the variant: `prone` fails, `safe` always passes.

> Note: the safe variant's deterministic `pairs_with` is built straight from the catalogue, so the `_SHOPPING_SYNTH_SYS_SAFE` prompt and the `_enforce_pairs_validity` sanitizer are no longer on the critical path for it (they remain as the recorded system prompt and a defensive backstop).

## Project layout

```
ai-wardrobe-builder/
├── app/
│   ├── main.py        # FastAPI routes, lifespan (init + flush)
│   ├── config.py      # env-driven settings (.env)
│   ├── telemetry.py   # OTel providers + Sigil client (order-correct, no-op safe)
│   ├── llm.py         # orchestrators + 6 sub-agents + judge; chat turns, pairs_with logic, prone/safe variants
│   ├── db.py          # SQLite + seed data
│   ├── auth.py        # light cookie-session auth
│   ├── models.py      # Pydantic schemas
│   └── static/        # index.html, app.js, styles.css
├── data/              # wardrobe.db (gitignored)
├── requirements.txt
├── run.sh
└── .env.example
```

## Troubleshooting

- **AI calls return 503 / "Is Ollama running?"** — start `ollama serve` and `ollama pull llama3.2:3b`.
- **Pill stays "Off air"** — `SIGIL_ENDPOINT`, `SIGIL_AUTH_TENANT_ID`, and `SIGIL_AUTH_TOKEN` must all be set; restart after editing `.env`.
- **Generations appear but no token/latency dashboards** — that's the OTLP path; set the `OTEL_EXPORTER_OTLP_*` vars (remember `Basic%20`).
- **Model returns messy output** — small models occasionally break JSON; the app extracts the JSON object defensively and falls back to showing raw text. Try a slightly larger model via `OLLAMA_MODEL`.
- **`SSL: CERTIFICATE_VERIFY_FAILED` on export** — some macOS Python installs lack a CA bundle. The app auto-points `SSL_CERT_FILE` at `certifi` (see `app/config.py`); if you still hit it, set `SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())')` before launching.

## Notes

- Security is intentionally minimal (plaintext local credentials) — this is a local learning tool, not a production app.
- Generation data is sent directly to the Grafana Cloud Sigil endpoint (it does not route through a local collector), so outbound network access is required for export.
