# Foo Management — Application Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FOO MANAGEMENT DEMO STACK                          │
└─────────────────────────────────────────────────────────────────────────────┘

  YOUR MACHINE (Docker Desktop)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                                                                         │
  │   ┌─────────────────────┐                                              │
  │   │     BROWSER         │                                              │
  │   │  http://localhost   │                                              │
  │   │                     │                                              │
  │   │  • Login form       │                                              │
  │   │  • Portfolio view   │                                              │
  │   │  • Batch trigger    │                                              │
  │   │                     │                                              │
  │   │  JS generates       │                                              │
  │   │  W3C traceparent    │                                              │
  │   │  on every fetch()   │                                              │
  │   └──────────┬──────────┘                                              │
  │              │ HTTP :80  traceparent: 00-<trace-id>-<span-id>-01       │
  │              ▼                                                          │
  │   ┌─────────────────────┐                                              │
  │   │   foo-frontend     │                                              │
  │   │   Nginx :80         │                                              │
  │   │                     │                                              │
  │   │  Serves index.html  │                                              │
  │   │  Proxies /api/* ──────────────────────────────────┐               │
  │   │  (passes headers)   │                             │               │
  │   └─────────────────────┘                             │               │
  │                                                        │ HTTP :8000    │
  │                                                        │ traceparent   │
  │                                                        │ forwarded     │
  │                                                        ▼               │
  │   ┌──────────────────────────────────────────────────────────────┐    │
  │   │                      foo-api  :8000                         │    │
  │   │                      FastAPI + SQLAlchemy                    │    │
  │   │                                                              │    │
  │   │  Auto-instrumented:                                          │    │
  │   │  • FastAPIInstrumentor  → span per HTTP route                │    │
  │   │  • SQLAlchemyInstrumentor → span per SQL query               │    │
  │   │  • RequestsInstrumentor → propagates context outbound        │    │
  │   │                                                              │    │
  │   │  Routes:                                                     │    │
  │   │  POST /api/login          → SELECT users                     │    │
  │   │  GET  /api/portfolio/{id} → SELECT portfolios + positions    │    │
  │   │  GET  /api/trades         → SELECT trades                    │    │
  │   │  POST /api/batch/trigger  ──────────────────────────┐        │    │
  │   └──────────────┬───────────────────────────────────── │ ───────┘    │
  │                  │ SQL (pymssql :1433)                   │            │
  │                  ▼                                       │ HTTP :8001 │
  │   ┌──────────────────────────┐              ┌────────────▼──────────┐ │
  │   │      sqlserver  :1433    │              │   foo-batch  :8001   │ │
  │   │   SQL Server 2022        │              │   Python              │ │
  │   │                          │              │                       │ │
  │   │   Tables:                │◄─────────────│   6-step EOD chain:   │ │
  │   │   • users                │ SQL queries  │   1. load-trades      │ │
  │   │   • portfolios           │ (pymssql)    │   2. validate-pos.    │ │
  │   │   • positions            │              │   3. price-securities │ │
  │   │   • trades               │              │   4. calculate-pnl    │ │
  │   │   • batch_reports        │              │   5. gen-reports      │ │
  │   │                          │              │   6. close-books      │ │
  │   └──────────────────────────┘              │                       │ │
  │                                             │   Runs every 60s +   │ │
  │                                             │   on-demand trigger   │ │
  │                                             └───────────────────────┘ │
  │                                                        │               │
  │          OTLP gRPC :4317 ◄─────────────────────────────┘               │
  │          (foo-api also sends here)                                     │
  │                  │                                                      │
  │                  ▼                                                      │
  │   ┌──────────────────────────────────────────────────────────────┐    │
  │   │               otel-collector  :4317/:4318                    │    │
  │   │               OTel Contrib                                   │    │
  │   │                                                              │    │
  │   │   Receives:  OTLP gRPC (from api + batch)                    │    │
  │   │   Processes: batch (512 spans / 5s)                          │    │
  │   │   Exports:   OTLP HTTP → Grafana Cloud                       │    │
  │   │              debug    → stdout                               │    │
  │   └──────────────────────┬───────────────────────────────────────┘    │
  │                          │                                             │
  └──────────────────────────┼─────────────────────────────────────────────┘
                             │ OTLP HTTP + Basic Auth
                             │ (Instance ID + API Key)
                             ▼
              ┌──────────────────────────────────┐
              │        GRAFANA CLOUD             │
              │                                  │
              │  ┌────────────────────────────┐  │
              │  │         Tempo              │  │
              │  │                            │  │
              │  │  service.name=foo-api     │  │
              │  │  ┌─ POST /api/login        │  │
              │  │  │    └─ SELECT users      │  │
              │  │  └─ GET /api/portfolio/1   │  │
              │  │       ├─ SELECT portfolio  │  │
              │  │       └─ SELECT positions  │  │
              │  │                            │  │
              │  │  service.name=             │  │
              │  │    foo-batch-runner       │  │
              │  │  ┌─ eod-batch-close        │  │
              │  │  │  ├─ load-trades         │  │
              │  │  │  ├─ validate-positions  │  │
              │  │  │  ├─ price-securities ◄──┼──┼── BATCH_SLOW_STEP=3  │
              │  │  │  ├─ calculate-pnl       │  │    injects latency   │
              │  │  │  ├─ generate-reports    │  │                      │
              │  │  │  └─ close-books         │  │
              │  └────────────────────────────┘  │
              └──────────────────────────────────┘
```

## Trace Propagation Path

How a single user action becomes one connected trace end-to-end:

```
  Browser                foo-frontend           foo-api              Tempo
     │                       │                      │                    │
     │──traceparent:──────►  │                      │                    │
     │  00-TRACE_ID-SPAN1-01 │──pass header──────►  │                    │
     │                       │                      │ create root span   │
     │                       │                      │──────────────────► │
     │                       │                      │ create SQL spans   │
     │                       │                      │──────────────────► │
     │                       │                      │                    │
     │                   (one trace, multiple spans, full waterfall)      │
```
