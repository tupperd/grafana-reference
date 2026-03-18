# Socratic Dialogue Prompt — SQL Expressions Lab

Copy and paste this entire prompt into a new Claude conversation to begin the dialogue.

---

## Prompt (copy from here)

```
I just completed the Grafana SQL Expressions Lab — four exercises using Prometheus + MySQL datasources to demonstrate cross-datasource joins with DuckDB SQL. Here's what I did:

- Exercise 01: Joined Prometheus error rates (time series, per service) with MySQL SLO targets (lookup table, per service) using JOIN on the service label. Computed budget_remaining = slo_target - actual_error_rate. Services without an SLO entry are excluded by the inner join.
- Exercise 02: Extended the join with LEFT JOIN + COALESCE to assign a 1% default SLO budget to the 'search' service, which has no MySQL row. Added a boolean is_breaching column.
- Exercise 03: Three-way join — two Prometheus queries (error rate + p99 latency) plus MySQL SLO targets — aggregated per service with AVG() and GROUP BY to produce a single SLO health table.

The key insight from the lab: joining a Prometheus time series with a MySQL lookup table by the 'service' label is impossible with standard Grafana Transformations. SQL expressions are the only way to do it server-side.

I want to deepen my understanding through dialogue — not a lecture. Please ask me questions rather than explaining things at me. Challenge my assumptions. If I say something imprecise, ask me to be more specific before correcting me.

Topics I want to explore (pick one to start, then let the conversation guide us):

1. The cross-datasource join question: why exactly can't Grafana Transformations do what SQL expressions can? What would you actually need to implement to add this capability to Transformations?
2. Timestamp alignment: Prometheus returns data at 15-second scrape intervals with possible jitter. MySQL returns a static table with no time column. How does DuckDB handle the JOIN when one side has no Time column at all?
3. The LEFT JOIN design decision: I used LEFT JOIN for MySQL but JOIN for Prometheus. What are the failure modes if I had it backwards?
4. COALESCE and the meaning of NULL: when I wrote COALESCE(B.error_budget_pct, 1.0), what am I asserting about the business meaning of a missing SLO? When might that assumption be wrong?
5. Aggregation and the GROUP BY clause: Exercise 03 uses AVG() across the time window. What does that mean for an SLO compliance decision — is it the right aggregation? What would MAX() or percentile tell me that AVG() doesn't?

Start by asking me a question about whichever topic you think will surface the most useful insight given what I've just done.

When we've covered at least two topics well, close with this transfer challenge:

> Describe a real data problem you've encountered — or can imagine — where SQL expressions could replace three or more Grafana Transformations, or could solve a join that Transformations simply cannot do. Walk me through what the Transformation chain would look like, and then show how the SQL expression collapses it.
```

---

## What to Expect

The first response from Claude should be **a question**, not an explanation. If it starts with a lecture, paste this follow-up:

> "Remember: ask questions first. I want to think through this, not be told the answer."

## Why Socratic Dialogue?

The faded practice exercises built procedural skill (you can write the SQL). Socratic dialogue builds conceptual understanding — you can explain *why* the syntax works, predict edge cases, and transfer the skill to new problems.

Topic 1 (why Transformations can't do cross-datasource joins) is particularly valuable: understanding the architectural reason makes you better at recognising future cases where SQL expressions are the right tool versus when Transformations are sufficient.
