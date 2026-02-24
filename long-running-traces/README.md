# Foo Management — Grafana Cloud OTel Tracing Demo

Simulates nightly batch jobs with full OpenTelemetry distributed tracing flowing to **Grafana Cloud Tempo**.

```
Browser (traceparent header)
  └─► foo-api  (FastAPI + SQLAlchemy auto-instrumentation)
        ├─► sqlserver  (SQL Server 2022)
        └─► foo-batch  (port 8001)
              ├─► foo-batch-runner       (6-step EOD close; auto-runs every 60 s + on-demand)
              │     └─► sqlserver
              └─► foo-batch-runner-long  (on-demand; ~15 min/step; live status polling)
                    └─► sqlserver

All services ──► otel-collector ──► Grafana Cloud Tempo
```

---

## Quick Start

### 1. Configure credentials
```bash
cp .env.example .env
# Edit .env and fill in your Grafana Cloud values:
#   GRAFANA_CLOUD_OTLP_ENDPOINT
#   GRAFANA_CLOUD_INSTANCE_ID
#   GRAFANA_CLOUD_API_KEY
```

Find these in: **Grafana Cloud → My Account → Your Stack → OpenTelemetry**

### 2. Start the stack
```bash
docker-compose up --build
```

First boot takes ~2 minutes — SQL Server needs time to initialise before the seed runs.

### 3. Open the portal
Navigate to **http://localhost**

Login with: `demo` / `demo123`

### 4. Generate traces

| Action | Trace generated |
|---|---|
| Login + view portfolio | `foo-api` spans → SQL Server queries |
| Click **Run EOD Batch** | `foo-batch-runner` → 6-step waterfall |
| Click **Run Long Batch** | `foo-batch-runner-long` → 6-step waterfall (~15 min/step); UI polls live status |
| Automatic (every 60s) | `foo-batch-runner` batch runs on a loop in the background |

---

## View in Grafana Cloud Tempo
1. Open **Grafana Cloud → Explore → Tempo**
2. Filter by service name:
   - `{ resource.service.name = "foo-api" }`
   - `{ resource.service.name = "foo-batch-runner" }`
   - `{ resource.service.name = "foo-batch-runner-long" }`
3. Click any trace to see the full waterfall

### Useful TraceQL queries
```
# All regular batch runs
{ service.name = "foo-batch-runner" }

# All long-running batch runs
{ service.name = "foo-batch-runner-long" }

# Traces where a step breached SLA
{ .foo.batch.sla_breached = true }

# Slow price-securities step
{ .foo.batch.step = "price-securities" && span.duration > 1s }

# Portfolio fetches with large result sets
{ .foo.query.row_count > 5 && service.name = "foo-api" }

# Long batch by run ID
{ .foo.batch.run_id = "<run_id>" }
```

---

## Simulate an SLA Breach

Set `BATCH_SLOW_STEP` in your `.env` and restart:

```bash
# .env
BATCH_SLOW_STEP=3   # injects 1.5-2.5s extra on step 3 (price-securities)
```

```bash
docker-compose up -d foo-batch
```

In Tempo you'll see the `price-securities` span extend far beyond its 1200ms SLA,
demonstrating cascade impact on downstream steps.

### Long batch step duration

Control how long each step takes in the long-running batch:

```bash
# .env
LONG_BATCH_STEP_SECONDS=60   # default 900 (15 min); use smaller values for demos
```

---

## Services

| Service | URL | Role |
|---|---|---|
| foo-frontend | http://localhost | Nginx + HTML/JS portal |
| foo-api | http://localhost:8000 | FastAPI backend |
| foo-batch | http://localhost:8001 | Batch trigger + health |
| otel-collector | :4317 / :4318 | OTLP receiver → Grafana Cloud |
| sqlserver | :1433 | SQL Server 2022 |

### API endpoints
```
GET  /api/health
POST /api/login                        { username, password }
GET  /api/portfolio/{id}               → positions + AUM
GET  /api/trades?portfolio_id={id}     → recent trades
POST /api/batch/trigger                → fires regular EOD batch (foo-batch-runner)
POST /api/batch/trigger-long           → fires long-running batch (foo-batch-runner-long)
GET  /api/batch/status/{run_id}        → live step status for a long batch run
```

---

## Architecture Notes

- **OTel propagation**: The browser generates a W3C `traceparent` header on every
  `fetch()` call. Nginx passes it through to `foo-api`, which continues the trace.
- **Service names**: `foo-api`, `foo-batch-runner`, and `foo-batch-runner-long` appear
  as distinct nodes in Grafana Cloud's service graph / trace view.
- **SQL instrumentation**: `SQLAlchemyInstrumentor` auto-creates child spans for every
  query, showing exact SQL text and duration inside each API span.
- **Regular batch span hierarchy**: `eod-batch-close` (parent) → 6 named child spans,
  each carrying `foo.batch.*` attributes for TraceQL filtering.
- **Long-running batch**: `foo-api` proxies trigger and status calls to the `foo-batch`
  container. The long batch uses a separate `TracerProvider` with
  `service.name = foo-batch-runner-long` so it appears as its own service in Tempo.
  The UI polls `/api/batch/status/{run_id}` every 5 s to render live step progress.
  Step duration is controlled by `LONG_BATCH_STEP_SECONDS` (default 900 = 15 min).