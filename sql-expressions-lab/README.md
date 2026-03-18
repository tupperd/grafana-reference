# SQL Expressions Lab

SQL expressions let you transform multi-query results with DuckDB-compatible SQL **server-side**, before visualization — enabling joins, calculated columns, and filters across datasource queries without modifying source data.

This lab demonstrates the killer use case: **joining a live Prometheus metric stream with a MySQL lookup table** — something that's impossible with standard Grafana Transformations alone.

This feature is in **public preview** as of Grafana 12.2.0.

---

## Prerequisites

- Docker and Docker Compose
- ~500 MB disk space (images)
- Ports 3001, 9090, 3306, 8080 available locally

---

## Quickstart

```bash
cd sql-expressions-lab
docker compose up -d
```

Wait ~30 seconds for MySQL to initialise, then open [http://localhost:3001](http://localhost:3001) and log in with `admin` / `stupid123`.

**To stop:**
```bash
docker compose down
```

**To stop and remove all data volumes:**
```bash
docker compose down -v
```

---

## What's Running

| Container | URL | Purpose |
|---|---|---|
| Grafana | http://localhost:3001 | Pre-configured with `sqlExpressions` feature toggle, Prometheus + MySQL datasources |
| Prometheus | http://localhost:9090 | Scrapes synthetic metrics every 15 s |
| MySQL | localhost:3306 | `slo_db.slo_targets` lookup table (2 rows) |
| metrics-generator | http://localhost:8080/metrics | Python app emitting `http_requests_total` and `http_request_duration_seconds` |

---

## The Scenario

A fictional e-commerce platform runs three services. Each has a distinct SLO personality:

| Service | Error Rate | p99 Latency | SLO in MySQL? |
|---|---|---|---|
| checkout | ~0.08% (under 0.1% budget) | ~150 ms | Yes |
| inventory | ~0.4–1.5% (spikes over 0.5% budget) | ~90 ms | Yes |
| search | ~1.8% (consistently over any budget) | ~320 ms | **No** |

`search` has no SLO entry in MySQL — this is deliberate. It drives the `COALESCE` and `LEFT JOIN` exercises.

---

## Why SQL Expressions?

| Problem | Without SQL Expressions | With SQL Expressions |
|---|---|---|
| Join Prometheus + MySQL | Impossible with Transformations | `LEFT JOIN B ON A.service = B.service` |
| Calculated column | Calculate field (single datasource) | `B.error_budget_pct - A.__value__ AS budget_remaining` |
| Filter on derived value | Filter by value (post-calc) | `WHERE A.__value__ > 0` |
| Null handling for missing rows | Manual post-processing | `COALESCE(B.error_budget_pct, 1.0)` |

**The core insight:** Prometheus returns one row per timestamp per service label. MySQL returns one row per service. Joining them by the `service` label requires SQL expressions — there is no Transformation that can do this join across two different datasource types.

---

## How Queries Become Tables

When a SQL expression is evaluated:
- Each query's `refId` becomes a table name: `A`, `B`, `C`, etc.
- Prometheus labels (like `service`) become columns alongside `time` and `__value__`
- MySQL table-format results expose column names directly (`service`, `error_budget_pct`, etc.)

```sql
-- A = Prometheus time series: columns are time, __value__, service
-- B = MySQL lookup table: columns are service, error_budget_pct, p99_threshold_ms, team, tier
SELECT A.time, A.service, A.__value__, B.error_budget_pct
FROM A
LEFT JOIN B ON A.service = B.service
```

---

## Lab Structure (Faded Practice)

```
01-worked-example/   → Full SQL with line-by-line explanation — read and explore
02-partial-example/  → SQL with 3 blanks to fill in
03-self-guided/      → Problem statement only; solution in a subfolder
04-ai-dialogue/      → Socratic dialogue prompt for reflection and transfer
```

Work through them in order.

---

## Importing Dashboard JSON Files

1. In Grafana, go to **Dashboards → Import**
2. Click **Upload dashboard JSON file**
3. Select the `.json` file from the exercise folder
4. Click **Import** — datasources are pre-wired via UIDs, no manual mapping needed

---

## Learning Objectives

By the end of this lab you will be able to:

- Write SQL expressions that join a Prometheus time series with a MySQL lookup table
- Explain why this join is impossible with standard Grafana Transformations
- Use `COALESCE` and `LEFT JOIN` to handle services with no SLO entry
- Build a multi-signal SLO health table aggregating error rate and latency in one expression
- Describe how Prometheus labels and MySQL column names map to SQL table columns

---

## Official Documentation

- [SQL expressions (Grafana docs)](https://grafana.com/docs/grafana/latest/panels-visualizations/query-transform-data/expression-queries/)
