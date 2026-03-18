# Hints — Exercise 02

Work through these in order. Try to solve each blank before opening the next hint level.

---

## Blank 1 & 2: `COALESCE(B.error_budget_pct, ___)`

These two blanks are the same value — the default SLO budget to apply when a service has no MySQL row.

### Hint Level 1 — Conceptual
The scenario says: *"treat services with no SLO entry as having a 1% default budget"*. `COALESCE(value, fallback)` returns `value` when it is not NULL, and `fallback` when it is. What should the fallback be?

<details>
<summary>Hint Level 2 — Syntax</summary>

The default budget is 1%. The `error_budget_pct` column stores values as percentages (e.g., `0.1` for checkout = 0.1%). So the fallback should match that unit:

```sql
COALESCE(B.error_budget_pct, 1.0)
```
</details>

<details>
<summary>Hint Level 3 — Answer</summary>

```
1.0
```

Full expressions:
```sql
COALESCE(B.error_budget_pct, 1.0)           AS effective_slo,
A.__value__ > COALESCE(B.error_budget_pct, 1.0) AS is_breaching
```

**Why the same value in both places?** The `effective_slo` column is just for display. The `is_breaching` comparison needs to use the same fallback so the boolean result is consistent with what's shown in `effective_slo`. If they used different fallbacks, the flag could show "breaching" for a different threshold than the one displayed.
</details>

---

## Blank 3: `WHERE A.__value__ > ___`

### Hint Level 1 — Conceptual
This filter removes rows where there's no meaningful traffic to evaluate. What is the lowest possible error rate for a service that has active traffic? (Hint: it can't be negative.)

<details>
<summary>Hint Level 2 — Syntax</summary>

You want to exclude time windows where the error rate is exactly 0 — which typically means no traffic or no errors at all. The filter is:

```sql
WHERE A.__value__ > 0
```
</details>

<details>
<summary>Hint Level 3 — Answer</summary>

```
0
```

Full WHERE clause:
```sql
WHERE A.__value__ > 0
```

This filters out any timestamp where the Prometheus query returned 0 (or NaN/no data), keeping only rows with active error-generating traffic.
</details>

---

## Complete Solution

```sql
SELECT
  A.time,
  A.service,
  A.__value__                                     AS error_rate_pct,
  COALESCE(B.error_budget_pct, 1.0)           AS effective_slo,
  A.__value__ > COALESCE(B.error_budget_pct, 1.0) AS is_breaching
FROM A
LEFT JOIN B ON A.service = B.service
WHERE A.__value__ > 0
```

---

## Observed Behaviour After Fixing

- `checkout` (~0.08% error rate, 0.1% SLO): `is_breaching = false`
- `inventory` (~0.4–1.5% error rate, 0.5% SLO): `is_breaching` flips true during spikes
- `search` (~1.8% error rate, no SLO → defaults to 1.0%): `is_breaching = true` consistently

This is the core value of `COALESCE` with `LEFT JOIN` — you get a complete, consistent view across all services, even when the lookup table is incomplete.
