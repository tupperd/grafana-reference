# 03 — Self-Guided

**Scenario:** *"Build a full SLO health table for all services"*

Your e-commerce platform runs three services: `checkout`, `inventory`, and `search`. You need a single summary table that shows — per service — the average error rate, average p99 latency, SLO targets, and whether each SLO is currently met.

No starter SQL is provided. Build the expression from scratch.

---

## Queries to Set Up

| RefID | Datasource | Query | Notes |
|---|---|---|---|
| A | Prometheus | `sum by (service) (rate(http_requests_total{status_code=~"5.."}[2m])) / sum by (service) (rate(http_requests_total[2m])) * 100` | Error rate % per service. Columns: `time`, `__value__`, `service` |
| B | Prometheus | `http_request_duration_seconds{quantile="0.99"}` | p99 latency in seconds. Columns: `time`, `__value__`, `service`, `quantile` |
| C | MySQL | `SELECT service, error_budget_pct, p99_threshold_ms, team, tier FROM slo_targets` | SLO lookup table. `format: table` required |

---

## Required Output

A table with exactly these columns:

| service | avg_error_rate_pct | avg_p99_ms | error_budget_pct | p99_threshold_ms | error_slo_met | latency_slo_met |
|---|---|---|---|---|---|---|
| search | ~1.8 | ~320 | NULL | NULL | NULL | NULL |
| inventory | ~0.4–1.5 | ~90 | 0.5 | 300 | (varies) | 1 |
| checkout | ~0.08 | ~150 | 0.1 | 200 | 1 | 1 |

- Ordered by `avg_error_rate_pct DESC`
- `search` has NULL SLO columns — it has no row in MySQL
- `avg_p99_ms` should be in **milliseconds** (Prometheus stores seconds — multiply by 1000)
- `error_slo_met` and `latency_slo_met` are booleans (1/0)

---

## Success Criteria

- [ ] Single SQL expression (RefID D) combining queries A, B, and C
- [ ] Values are aggregated with `AVG()` across the time window — one row per service, not one per timestamp
- [ ] `avg_p99_ms` is in milliseconds (not seconds)
- [ ] `search` appears with NULL for SLO columns (no SLO entry in MySQL)
- [ ] `error_slo_met` and `latency_slo_met` are boolean comparisons
- [ ] Results ordered by `avg_error_rate_pct DESC`

---

## Hints (only if stuck)

1. You need to join A and B on both `time` and `service` (the p99 query also has a `service` label)
2. Use `LEFT JOIN` for the MySQL lookup so `search` isn't dropped
3. Use `GROUP BY A.service, C.error_budget_pct, C.p99_threshold_ms` to aggregate per service
4. `AVG(B.__value__) * 1000` converts seconds to milliseconds
5. `AVG(A.__value__) <= C.error_budget_pct` evaluates to 1 (true) or 0 (false)

---

## Check Your Work

The solution is in `solution/README.md` and `solution/dashboard.json`. Only look after you have a working expression or have spent significant time debugging.

A correct solution produces exactly 3 rows — one per service.
