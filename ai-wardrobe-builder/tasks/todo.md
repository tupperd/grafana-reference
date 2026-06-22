# Wardrobe AI — Build Plan & Spec

A small, local wardrobe-builder web app whose real purpose is to learn **Grafana Cloud AI Observability (Sigil)** hands-on. The app calls a local OSS LLM (Ollama) for two AI features and instruments every call with the Sigil SDK so the generations, conversations, tokens/cost, traces, and **evals** show up in Grafana Cloud.

## Objective recap
- Wardrobe catalog CRUD (add / remove / view clothing items).
- Two AI features as **distinct named agents**:
  - `outfit-builder` — picks a good outfit from the catalog with rationale.
  - `shopping-assistant` — proposes a shopping list to fill wardrobe gaps with rationale.
- In-app **LLM judge** (`outfit-judge` / `shopping-judge`) that scores AI outputs — recorded as its own Sigil generation.
- Everything runs locally; only Sigil telemetry leaves the machine to the user's Grafana Cloud stack.
- **Evals are the #1 learning priority**, then generations/conversations, tokens/cost, traces/multi-agent.

## Confirmed decisions (from interview)
| Topic | Decision |
|---|---|
| Grafana Cloud | User has a stack, ready to enable plugin + create `sigil:write` token |
| Language/stack | **Python 3.11+ + FastAPI** + vanilla HTML/JS/CSS frontend |
| Local LLM | **Ollama (fresh install)**, default model `llama3.2:3b` |
| Learning focus | All four; **online evals highest priority** |
| Item fidelity | **Text attributes only** (type, name, color, season, formality, material, notes) |
| Eval depth | **Both** plugin online-eval rules (documented) **and** in-app LLM judge |
| Run shape | **Native + `./run.sh`** (Ollama native for Metal GPU; app in venv) |
| Persistence | SQLite (stdlib `sqlite3`) |
| Auth | Single user/pass in `.env`, cookie session (plaintext OK) |

## Architecture
```
Browser (HTML/JS) ──HTTP──► FastAPI
                               ├─ auth (cookie session)
                               ├─ catalog API ──► SQLite (data/wardrobe.db)
                               └─ AI API ──► llm.py
                                               ├─ OpenAI-compatible client → Ollama (localhost:11434/v1)
                                               └─ Sigil SDK (manual-wrap start_generation)
                                                     ├─ Generation data ──► Grafana Cloud Sigil endpoint
                                                     └─ OTel spans/metrics ──► Grafana Cloud OTLP gateway
```
- **Order matters:** OTel TracerProvider + MeterProvider are created *before* the Sigil client, or traces/metrics are silently lost.
- Each generation captures: full input messages (system + user w/ catalog), full output, `responseId`, `responseModel`, `stopReason`, token `usage`, `conversationId`, `agentName`+`agentVersion`, `userId`, `tags`, `metadata`. This is what makes outputs eval-ready.

## Project structure
```
wardrobe-ai/
  README.md            # setup: Ollama install, model pull, GC plugin enable, token, env, run, eval-rule howto
  .env.example
  .gitignore
  requirements.txt
  run.sh               # venv + deps + launch uvicorn
  app/
    main.py            # FastAPI app + route wiring + startup/shutdown (flush Sigil)
    config.py          # env-driven settings
    auth.py            # light login + cookie session dependency
    db.py              # sqlite schema, CRUD, seed data
    models.py          # Pydantic schemas (Item, OutfitResult, ShoppingResult, EvalResult)
    telemetry.py       # OTel providers + Sigil client (init before use)
    llm.py             # Ollama client + instrumented agent runners + judge
    static/            # index.html, app.js, styles.css (clean modern UI)
  data/                # wardrobe.db (gitignored), seeded on first run
  tasks/todo.md        # this file
```

## Build steps
- [ ] 0. **Verify the real Python Sigil API** from the repo's `examples/getting-started/python` (exact package names, `Client`/`ClientConfig`/`GenerationStart`/`ModelRef`/`start_generation`/`set_result`/`TokenUsage`/message helpers) — do not guess a pre-1.0 API.
- [ ] 1. Scaffold project: `requirements.txt`, `.env.example`, `.gitignore`, `run.sh`, `config.py`.
- [ ] 2. `telemetry.py`: OTel Tracer/Meter providers + OTLP exporters (env-driven), then Sigil `Client`. Safe no-op if Sigil env unset (so app runs even before GC is wired).
- [ ] 3. `db.py` + `models.py`: SQLite schema, CRUD, and seed ~12 realistic sample items so AI features work immediately.
- [ ] 4. `auth.py`: login route, cookie session, `require_user` dependency.
- [ ] 5. `llm.py`: Ollama client (OpenAI-compatible), `run_outfit_builder`, `run_shopping_assistant`, `run_judge` — each a Sigil generation with proper agent name/version/tags/metadata and JSON-structured output parsing.
- [ ] 6. `main.py`: routes — `/login`, `/api/items` (GET/POST/DELETE), `/api/outfit`, `/api/shopping`, `/api/evaluate`, `/health`. Flush Sigil on shutdown.
- [ ] 7. Frontend: catalog view + add/remove, "Build Outfit" / "Shopping Assistant" buttons, results panel with per-result "Evaluate" button + score display. Clean dark UI.
- [ ] 8. `run.sh` + `README.md`: Ollama install (`brew install ollama` / curl), `ollama pull llama3.2:3b`, enable AI Observability plugin, create access policy token (`sigil:write` + traces/metrics/logs write), fill `.env`, run, and **how to configure an online eval rule in the plugin**.
- [ ] 9. **Test locally**: start Ollama, run app, exercise CRUD + both AI features + in-app judge; confirm no SDK errors and generations flush. Add a startup self-check that logs whether Sigil/OTLP are configured.
- [ ] 10. Document the eval workflow (eval-ready fields + plugin online-eval-rule setup) so evals (top priority) are fully exercisable.
- [ ] 11. Share: summary of what was built, how to run, and where to look in Grafana Cloud.

## Verification strategy
- Prove Ollama responds (curl the model once in `run.sh` preflight or a `/health` check).
- Exercise every endpoint end-to-end; assert JSON parses and items persist across restart.
- Confirm Sigil client init + `shutdown()` flush succeed without errors (I can't see the user's GC UI, so I'll verify SDK-side success + log a clear "sent N generations" line; user confirms they appear in the Conversations view).
- Diff: app must run cleanly even with Sigil env *unset* (graceful degradation), and emit telemetry when set.

## Risks / notes
- Pre-1.0 Sigil API may differ from research → step 0 verifies against the real repo example before coding the LLM/telemetry layer.
- Generation data requires outbound network to Grafana Cloud (not routed via local collector) — expected.
- Small local model JSON reliability: prompts will request strict JSON and code will parse defensively (retry/repair once on parse failure).

## Review (filled after implementation)

**Status: built and verified (except live Ollama/Grafana round-trips, which need your machine + stack creds).**

Build steps 0-10 complete. Step 11 (share) = this handoff. GitHub push deferred per your note ("when we're ready, push to GH via tupperd").

### What was verified
- **SDK API match**: introspected installed `sigil-sdk` 0.9.0 — every type/field I coded against exists (`GenerationStart`, `AuthConfig.basic_password/tenant_id/mode`, `GenerationExportConfig`, `ClientConfig.generation_export`, `ModelRef`, `TokenUsage`, `start_generation`->`GenerationRecorder` with `set_result`/`err` + context manager, `Client.shutdown`).
- **Install**: clean `pip install` on Python 3.14 (grpcio/pydantic/etc. all had wheels).
- **App smoke test** (FastAPI TestClient): `/health` 200; unauth -> 401; bad login -> 401; good login -> 200; **12 seed items**; add->delete returns to 12; index served as HTML; **AI endpoint with Ollama down -> clean 503** with actionable message.
- **LLM layer (mocked Ollama)**: `build_outfit` parses fenced JSON and resolves `item_ids`->items (1,5,12 -> Oxford/Chinos/Chelsea Boots); `judge` threads under the parent `conversation_id`; `_extract_json` handles fenced/embedded/garbage with raw-text fallback.
- **Graceful degradation**: with `SIGIL_*`/`OTEL_*` unset, telemetry no-ops and nothing touches the network; a misconfigured/unreachable Sigil endpoint logs and continues without crashing.

### Not yet verified (needs your environment)
- Live Ollama inference quality (Ollama not installed - your chosen path).
- Live export to your Grafana Cloud stack (needs the `sigil:write` token + endpoint in `.env`).

### Two things you do to go live
1. `brew install ollama && ollama serve && ollama pull llama3.2:3b`
2. Enable the AI Observability app on your stack, create a `sigil:write` token, fill `.env` (see README), restart `./run.sh` -> badge flips to "live".
