# 02 — Partial Example

**Scenario:** *"Flag services breaching their SLO; treat services with no SLO entry as having a 1% default budget"*

You have the same two queries as Exercise 01 (Prometheus error rate + MySQL SLO targets). Now the requirements have changed:

1. `search` has no SLO row in MySQL — instead of showing NULL, treat it as having a **1% default error budget**
2. Flag each service/timestamp as `is_breaching` (true/false)
3. Filter out rows where the error rate is zero — only show active traffic

Your job: fill in the three `___` blanks in the SQL expression.

---

## The Starter SQL (fill in the blanks)

```sql
SELECT
  A.time,
  A.service,
  A.__value__                                    AS error_rate_pct,
  COALESCE(B.error_budget_pct, ___)              AS effective_slo,
  A.__value__ > COALESCE(B.error_budget_pct, ___) AS is_breaching
FROM A
LEFT JOIN B ON A.service = B.service
WHERE A.__value__ > ___
```

**Three blanks to fill:**
1. `COALESCE(B.error_budget_pct, ___)` — what default SLO applies when the service has no MySQL row?
2. `COALESCE(B.error_budget_pct, ___)` inside the `is_breaching` expression — same default
3. `WHERE A.__value__ > ___` — filter threshold to exclude zero-traffic rows

---

## What's New vs Exercise 01?

| Change | Why |
|---|---|
| `COALESCE(B.error_budget_pct, 1.0)` | `search` has no MySQL row → `B.error_budget_pct` is NULL → COALESCE substitutes `1.0` |
| `is_breaching` boolean column | Derived flag: true when error rate exceeds the effective SLO |
| `WHERE A.__value__ > 0` | Filter rows with no active traffic |

---

## Dashboard Layout

The dashboard has two panels, both driven by the same SQL expression (RefID C). Fill in the blanks once — both panels update together.

**Panel 1 — Error Rate by Service (time series)**
Shows `error_rate_pct` over time with one line per service. The SQL expression output is a long-format table; the `partitionByValues` transformation splits it into one frame per service so Grafana renders separate lines.

**Panel 2 — SLO Breach State by Service (state timeline)**
Shows one row per service with color-coded bands over time: green = within SLO, red = breaching. Same SQL expression, same `partitionByValues` transformation — only `is_breaching` is rendered. `checkout` is excluded because it never breaches (its error rate stays below the 0.1% budget), so the `WHERE A.__value__ > 0` filter combined with the inner join leaves it out.

---

## Import and Complete the Dashboard

1. Import `dashboard-starter.json` from this folder
2. Both panels will show an error — the `___` placeholders are not valid SQL
3. Open **Edit panel → Query tab → RefID C** (either panel — they share the same query)
4. Replace each `___` with the correct value
5. Click **Apply** and verify both panels render

---

## Success Criteria

- **Time series**: separate lines for each breaching service, showing error rate % over time
- **State timeline**: one row per service, green/red bands — `inventory` flips red during spikes, `search` is persistently red
- `search` effective SLO is `1.0` (the COALESCE default, not NULL)
- `checkout` does not appear — its error rate stays below its 0.1% budget, so it is filtered out by `WHERE A.__value__ > 0` after the join

---

## Hints

See `hints.md` for progressive hints. Try for at least 5 minutes before opening the first hint.
