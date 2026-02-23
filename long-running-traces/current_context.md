# Foo Management Demo — Current Context

## Purpose
Sales demo for Grafana Labs / Grafana Cloud. Simulates an on-prem investment management
platform (VMware/SQL Server environment) with full OpenTelemetry distributed tracing
flowing to Grafana Cloud Tempo. Validates the correlation story: browser → API → SQL
Server → nightly batch workflow.

---

## Architecture

```
Browser (HTML/JS)
    │  HTTP fetch + W3C traceparent header
    ▼
foo-frontend  (Nginx, port 80)
    │  proxies /api/* to foo-api:8000
    ▼
foo-api  (Python FastAPI, port 8000)  ──► otel-collector ──► Grafana Cloud Tempo
    │  SQLAlchemy + pymssql
    ▼
sqlserver  (SQL Server 2022, port 1433)

foo-batch  (Python FastAPI, port 8001) ──► otel-collector ──► Grafana Cloud Tempo
  └─ regular runner:   service.name = foo-batch-runner       (auto, every 60s)
  └─ long runner:      service.name = foo-batch-runner-long  (on-demand, configurable step duration)
```

### Docker Services
| Service | Image | Role |
|---|---|---|
| `sqlserver` | mcr.microsoft.com/mssql/server:2022-latest | Primary DB (runs as root — Docker Desktop workaround) |
| `db-seed` | same MSSQL image | One-shot init.sql seeder, exits after run |
| `otel-collector` | otel/opentelemetry-collector-contrib:latest | Receives OTLP gRPC, exports OTLP HTTP → Grafana Cloud |
| `foo-api` | Python 3.12 FastAPI | Portfolio/trade API, proxies batch triggers |
| `foo-batch` | Python 3.12 FastAPI | EOD batch simulator (regular + long-running modes) |
| `foo-frontend` | Nginx + static HTML/JS | Login + portfolio dashboard |

---

## Key Files

```
foomanagement/
├── docker-compose.yml
├── .env.example
├── .env                          # real credentials (not committed)
├── otel-collector-config.yaml
├── current_context.md            # this file
├── architecture.md               # ASCII architecture diagram
├── services/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── batch/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── batch_runner.py
│   ├── frontend/
│   │   ├── Dockerfile
│   │   ├── nginx.conf
│   │   └── index.html
│   └── db-init/
│       └── init.sql
```

---

## Environment Variables (.env)

| Variable | Purpose |
|---|---|
| `GRAFANA_CLOUD_OTLP_ENDPOINT` | OTLP HTTP endpoint for your Grafana Cloud stack |
| `GRAFANA_CLOUD_INSTANCE_ID` | Numeric instance ID (used as basicauth username) |
| `GRAFANA_CLOUD_API_KEY` | Service account token (MetricsPublisher + TracesPublisher) |
| `MSSQL_SA_PASSWORD` | SQL Server SA password (default: `FooDemo!2024`) |
| `BATCH_SLOW_STEP` | Step number 1–6 to inject SLA-breach latency (leave blank for normal) |
| `LONG_BATCH_STEP_SECONDS` | Seconds per step for long batch mode (default: 900 = 15 min; use 10 for local testing) |

---

## Demo Flows

### 1. Portfolio / Trade Trace
1. Open `http://localhost` → login as `demo / demo123`
2. View portfolio → generates trace: `foo-api` → SQL Server
3. In Grafana Cloud → Explore → Tempo → filter `service.name = foo-api`
4. Full waterfall shows: HTTP route → SQLAlchemy queries

### 2. Regular EOD Batch (short, ~30s)
1. Click **⚡ Run EOD Batch**
2. UI shows step-by-step log and a trace ID immediately
3. In Tempo: filter `service.name = foo-batch-runner`
4. Full 6-span waterfall: load-trades → validate-positions → price-securities → calculate-pnl → generate-reports → close-books
5. Set `BATCH_SLOW_STEP=3` in `.env` + restart `foo-batch` to inject a latency spike on step 3

### 3. Long-Running Batch (configurable duration per step)
1. Click **⏱ Run Long Batch**
2. Progress panel opens immediately showing:
   - Live progress bar (updates every 5s)
   - Per-step status with elapsed time / ETA
   - Trace ID shown immediately for Grafana Tempo lookup
3. In Tempo: filter `service.name = foo-batch-runner-long`
4. Trace builds out in real time — demonstrates long-running job observability
5. For local testing: `LONG_BATCH_STEP_SECONDS=10` → completes in ~60s
6. For customer demo: `LONG_BATCH_STEP_SECONDS=900` → 15 min per step, 90 min total

---

## Batch Steps (both modes)
| # | Step | What it does |
|---|---|---|
| 1 | `load-trades` | SELECT pending trades |
| 2 | `validate-positions` | Check quantities, UPDATE trades → validated |
| 3 | `price-securities` | UPDATE market_value on positions (±0.5% random) |
| 4 | `calculate-pnl` | Aggregate P&L per portfolio |
| 5 | `generate-reports` | INSERT rows into batch_reports |
| 6 | `close-books` | UPDATE trades → settled |

---

## OTel Implementation Notes

- **API**: `FastAPIInstrumentor` (auto-traces all HTTP routes) + `SQLAlchemyInstrumentor` (auto-traces all SQL) + `RequestsInstrumentor` (propagates context on outbound calls). Service name: `foo-api`.
- **Batch (regular)**: Manual spans with `tracer.start_as_current_span()`. Set as global TracerProvider. Service name: `foo-batch-runner`.
- **Batch (long)**: Separate `long_provider` / `long_tracer` — never set as global provider. Service name: `foo-batch-runner-long`.
- **Collector**: `otlphttp/grafana` exporter (not `otlp/grpc`) — required because Grafana Cloud uses full HTTPS URLs. basicauth extension handles credentials.
- **Browser**: Generates W3C `traceparent` header on every `fetch()` call using `crypto.getRandomValues`. Trace ID displayed in UI for direct Tempo lookup.

---

## Known Gotchas / Fixed Issues

| Issue | Fix |
|---|---|
| `msodbcsql18` not available on arm64 | Replaced pyodbc with pymssql (FreeTDS-based, native arm64) |
| SQL Server `/.system` access denied | Added `user: root` to sqlserver service in docker-compose |
| OTel collector `missing port in address` | Switched from `otlp` (gRPC) to `otlphttp` exporter |
| `pkg_resources` missing on Python 3.12 slim | Pinned `setuptools==69.5.1` in both requirements.txt files |
| Frontend serving stale HTML | Must run `docker compose build foo-frontend && docker compose up -d --force-recreate foo-frontend` after any index.html change |
| DB seed entrypoint broken | Use JSON array format for entrypoint, not YAML block scalar |

---

## Quick Commands

```bash
# Start everything
docker compose up --build

# Restart after .env change (batch settings)
docker compose up -d --force-recreate foo-batch

# Rebuild + restart frontend after index.html change
docker compose build foo-frontend && docker compose up -d --force-recreate foo-frontend

# Check all container status
docker compose ps

# Tail batch runner logs
docker compose logs -f foo-batch

# Tail API logs
docker compose logs -f foo-api
```

---

## Demo Credentials
- **URL**: `http://localhost`
- **Username**: `demo`
- **Password**: `demo123`

---
*Last updated: 2026-02-23*
