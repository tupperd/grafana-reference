# Solution — Exercise 03

## The SQL Expression (RefID D)

```sql
SELECT
  A.service,
  ROUND(AVG(A.__value__), 3)                        AS avg_error_rate_pct,
  ROUND(AVG(B.__value__) * 1000, 1)                 AS avg_p99_ms,
  C.error_budget_pct,
  C.p99_threshold_ms,
  AVG(A.__value__) <= C.error_budget_pct            AS error_slo_met,
  AVG(B.__value__) * 1000 <= C.p99_threshold_ms     AS latency_slo_met
FROM A
JOIN B ON A.time = B.time AND A.service = B.service
LEFT JOIN C ON A.service = C.service
GROUP BY A.service, C.error_budget_pct, C.p99_threshold_ms
ORDER BY avg_error_rate_pct DESC
```

---

## How It Works

### Three-way Join

This expression joins data from three different sources:
- `A` (Prometheus) — error rate time series, one row per (timestamp, service)
- `B` (Prometheus) — p99 latency time series, one row per (timestamp, service)
- `C` (MySQL) — SLO lookup table, one row per service

`JOIN B ON A.time = B.time AND A.service = B.service` — inner join to get matching error rate and latency for the same timestamp and service. Both must exist.

`LEFT JOIN C ON A.service = C.service` — outer join so that `search` (which has no MySQL row) still appears in the output with NULL SLO columns.

### AVG() Aggregation

`AVG(A.__value__)` averages the error rate across all timestamps in the time window. Without `GROUP BY`, this would collapse the entire table to one row. The `GROUP BY A.service, ...` clause produces one row per service — which is the goal.

### Unit Conversion

`AVG(B.__value__) * 1000` — Prometheus stores `http_request_duration_seconds` in seconds. MySQL stores `p99_threshold_ms` in milliseconds. The `* 1000` converts the Prometheus value to the same unit before comparing.

### Boolean SLO Flags

`AVG(A.__value__) <= C.error_budget_pct AS error_slo_met` — DuckDB evaluates this as `1` (true) or `0` (false). When `C.error_budget_pct` is NULL (for `search`), the comparison result is also NULL.

### Why search Has NULL SLO Columns

`search` has no row in `slo_db.slo_targets`. The `LEFT JOIN` keeps `search` in the result but fills `C.*` columns with NULL. This makes the missing SLO explicit — you can see at a glance that `search` has no defined targets.

---

## Design Notes

**Why not UNION ALL?** In the original TestData version of this lab, services needed `UNION ALL` because each service was a separate query with no label. Here, Prometheus already returns a `service` label, so a single `GROUP BY service` aggregation replaces the per-service `UNION ALL` blocks.

**What if B has extra labels?** The query `http_request_duration_seconds{quantile="0.99"}` filters to only the p99 quantile, so `B` has exactly one row per (timestamp, service). If you used an unfiltered query, you'd get multiple rows per timestamp and the JOIN would produce duplicates.

**NULLIF for production:** In production, guard the division in the error rate PromQL or use `NULLIF` in SQL:
```sql
ROUND(NULLIF(AVG(A.__value__), 0), 3) AS avg_error_rate_pct
```

---

## Import the Dashboard

Import `solution/dashboard.json` to see the working result. The single panel shows a 3-row table (checkout, inventory, search) with green/red SLO flags.
