# Foo Management — Grafana Cloud OTel Tracing Demo

Simulates Foo Management's on-prem environment (SQL Server, Python API, nightly batch) with
full OpenTelemetry distributed tracing flowing to **Grafana Cloud Tempo**.

```
Browser (traceparent header)
  └─► foo-api  (FastAPI + SQLAlchemy auto-instrumentation)
        └─► sqlserver  (SQL Server 2022)

foo-batch-runner  (manual spans — 6-step EOD close)
  └─► sqlserver

Both services ──► otel-collector ──► Grafana Cloud Tempo
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
| Automatic (every 60s) | Batch runs on a loop in the background |

---

## View in Grafana Cloud Tempo

1. Open **Grafana Cloud → Explore → Tempo**
2. Filter by service name:
   - `{ service.name = "foo-api" }`
   - `{ service.name = "foo-batch-runner" }`
3. Click any trace to see the full waterfall

### Useful TraceQL queries
```
# All batch runs
{ service.name = "foo-batch-runner" }

# Traces where a step breached SLA
{ .foo.batch.sla_breached = true }

# Slow price-securities step
{ .foo.batch.step = "price-securities" && span.duration > 1s }

# Portfolio fetches with large result sets
{ .foo.query.row_count > 5 && service.name = "foo-api" }
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
POST /api/login                    { username, password }
GET  /api/portfolio/{id}           → positions + AUM
GET  /api/trades?portfolio_id={id} → recent trades
POST /api/batch/trigger            → fires EOD batch
```

---

## Architecture Notes

- **OTel propagation**: The browser generates a W3C `traceparent` header on every
  `fetch()` call. Nginx passes it through to `foo-api`, which continues the trace.
- **Service names**: `foo-api` and `foo-batch-runner` appear as distinct nodes in
  Grafana Cloud's service graph / trace view.
- **SQL instrumentation**: `SQLAlchemyInstrumentor` auto-creates child spans for every
  query, showing exact SQL text and duration inside each API span.
- **Batch span hierarchy**: `eod-batch-close` (parent) → 6 named child spans, each
  carrying `foo.batch.*` attributes for TraceQL filtering.

---

## Phase 2 (not in scope here)

The same OTel collector pipeline can be extended for:
- **Metrics → Grafana Cloud Mimir**: add `prometheusremotewrite` exporter
- **Logs → Grafana Cloud Loki**: add `loki` exporter + Python logging handler
- **Dashboards**: import pre-built Grafana dashboards for APM overview
