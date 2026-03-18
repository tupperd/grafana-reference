# 01 — Worked Example

**Scenario:** *"Which services are breaching their error SLO right now?"*

You have two data sources:
- **Query A (Prometheus)** — live error rate % per service, as a time series
- **Query B (MySQL)** — static SLO targets table, one row per service

Neither source alone answers the question. The error rate is in Prometheus; the SLO target is in MySQL. Joining them by service name is impossible with standard Grafana Transformations — it requires a SQL expression.

---

## The Queries

**Query A — Error Rate by Service** (Prometheus)
```promql
sum by (service) (rate(http_requests_total{status_code=~"5.."}[2m]))
/ sum by (service) (rate(http_requests_total[2m]))
* 100
```
Returns one time series per service. The `service` label becomes a column named `service` in the SQL expression.

**Query B — SLO Targets** (MySQL, `format: table`)
```sql
SELECT service, error_budget_pct, p99_threshold_ms, team, tier
FROM slo_targets
```
Returns one row per service. Column names are used directly in the SQL expression.

---

## The SQL Expression (RefID C)

```sql
SELECT
  A.time,
  A.service,
  A.__value__                         AS error_rate_pct,
  B.error_budget_pct                  AS slo_target_pct,
  B.error_budget_pct - A.__value__    AS budget_remaining
FROM A
JOIN B ON A.service = B.service
```

### Line-by-line Explanation

| Line | What it does |
|---|---|
| `A.time` | Keeps the timestamp column (required for time series output) |
| `A.service` | The Prometheus `service` label — exposed as a column in the SQL frame |
| `A.__value__ AS error_rate_pct` | The Prometheus value column — named `__value__` (not `value`) in Grafana 12.2's DuckDB engine |
| `B.error_budget_pct AS slo_target_pct` | MySQL column pulled into the result |
| `B.error_budget_pct - A.__value__ AS budget_remaining` | Derived column: positive = headroom, negative = breach |
| `FROM A` | Prometheus time series — one row per (timestamp, service) |
| `JOIN B ON A.service = B.service` | Inner join on service name — only services with an SLO entry in MySQL appear. `search` is excluded because it has no row. |

### Why JOIN, not LEFT JOIN?

This exercise focuses on services that have defined SLO targets. `search` has no SLO entry in MySQL, so there is nothing to compare against — including it would produce NULL for `slo_target_pct` and `budget_remaining`, making the compliance check meaningless.

Exercise 02 introduces `LEFT JOIN` + `COALESCE` to handle the `search` case explicitly.

### Key Concepts

**Table references:** Each query's `refId` becomes a table name — `A`, `B`, `C`, etc. No `$` prefix.

**Prometheus column names in Grafana 12.2:** The value column is `__value__` (not `value`). The time column is `time`. Label columns use their original names (e.g., `service`). MySQL column names come through as written in your SELECT statement.

**Prometheus label → column:** When Grafana runs a Prometheus query, each label in the result becomes a column. `sum by (service) (...)` produces exactly one label `service`, so `A.service` is available in the SQL.

**MySQL table format:** Setting `format: table` on a MySQL query exposes the SELECT column names directly. `error_budget_pct` in the SQL → `B.error_budget_pct` in the SQL expression.

---

## Expected Output

After importing `dashboard.json` you should see three panels:

1. **Live Error Rate by Service** — time series showing error % per service from Prometheus
2. **SLO Targets** — table showing the 2 MySQL rows (checkout, inventory)
3. **SLO Compliance — SQL Join Result** — table with 5 columns:
   - `time`, `service`, `error_rate_pct`, `slo_target_pct`, `budget_remaining`
   - Only `checkout` and `inventory` appear — `search` is excluded (no SLO row)
   - `budget_remaining` is color-coded: green = headroom, red = breach

---

## Import the Dashboard

1. Go to **Dashboards → Import**
2. Upload `dashboard.json` from this folder
3. Click **Import** (datasources are pre-wired — no mapping needed)

After import, open any panel's **Edit → Query tab** to inspect how the SQL expression target is defined alongside the Prometheus and MySQL queries.
