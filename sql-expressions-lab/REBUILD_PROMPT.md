# Rebuild Prompt — SQL Expressions Lab

Use this prompt to rebuild the lab from scratch. It encodes every pitfall discovered during the original build.

---

## Prompt

Build a Grafana SQL Expressions lab that teaches the cross-datasource join use case: joining a live Prometheus metric stream with a MySQL lookup table using Grafana's `sqlExpressions` feature (DuckDB-backed, public preview in Grafana 12.2).

---

### Scenario

An e-commerce platform runs three services with distinct SLO personalities:

| Service | Error Rate | p99 Latency | SLO in MySQL? |
|---|---|---|---|
| checkout | ~0.08% (under 0.1% budget) | ~150 ms | Yes |
| inventory | ~0.4–1.5% (spikes over 0.5% budget) | ~90 ms | Yes |
| search | ~1.8% (always over budget) | ~320 ms | No — intentionally absent |

`search` having no MySQL SLO entry drives the COALESCE and LEFT JOIN exercises.

---

### Stack

```
docker compose up -d
├── grafana          → localhost:3001  (Grafana 12.2.0-ubuntu, sqlExpressions toggle)
├── prometheus       → localhost:9090  (scrapes metrics-generator)
├── mysql            → localhost:3306  (slo_db.slo_targets, 2 rows)
└── metrics-generator → localhost:8080 (Python, prometheus_client)
```

---

### Datasource provisioning (auto-wired UIDs)

Provision both datasources so dashboard JSON imports without manual mapping:

```yaml
# provisioning/datasources/datasources.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://prometheus:9090
    access: proxy
    isDefault: true

  - name: MySQL
    type: mysql
    uid: mysql
    url: mysql:3306
    database: slo_db
    user: root
    secureJsonData:
      password: grafana
```

---

### Docker Compose

```yaml
services:
  grafana:
    build: ./grafana-build        # custom image — see PITFALL 1
    container_name: sql-lab-grafana
    ports:
      - "3001:3000"
    environment:
      - GF_FEATURE_TOGGLES_ENABLE=sqlExpressions
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=stupid123
      - GF_AUTH_BASIC_ENABLED=true   # required for API auth — see PITFALL 6
    volumes:
      - ./provisioning:/etc/grafana/provisioning
      - grafana-data:/var/lib/grafana  # persist across restarts
    depends_on:
      - prometheus
      - mysql

  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    depends_on: [metrics-generator]

  mysql:
    image: mysql:8
    ports: ["3306:3306"]
    environment:
      - MYSQL_ROOT_PASSWORD=grafana
      - MYSQL_DATABASE=slo_db
    volumes:
      - ./mysql-init:/docker-entrypoint-initdb.d:ro

  metrics-generator:
    build: ./metrics-generator
    ports: ["8080:8080"]

volumes:
  grafana-data:
```

---

### Grafana custom Dockerfile (PITFALL 1 + 2)

```dockerfile
# grafana-build/Dockerfile
FROM grafana/grafana:12.2.0-ubuntu    # MUST be -ubuntu, NOT alpine (see PITFALL 2)

USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/*

ARG DUCKDB_VERSION=v1.2.1
RUN curl -fsSL \
      "https://github.com/duckdb/duckdb/releases/download/${DUCKDB_VERSION}/duckdb_cli-linux-aarch64.zip" \
      -o /tmp/duckdb.zip \
    && unzip /tmp/duckdb.zip -d /tmp/ \
    && mv /tmp/duckdb /usr/local/bin/duckdb \
    && chmod +x /usr/local/bin/duckdb \
    && rm /tmp/duckdb.zip \
    && duckdb --version

USER grafana
```

---

### MySQL init

```sql
-- mysql-init/init.sql
CREATE DATABASE IF NOT EXISTS slo_db;
USE slo_db;

CREATE TABLE slo_targets (
  service          VARCHAR(64) PRIMARY KEY,
  error_budget_pct FLOAT NOT NULL,
  p99_threshold_ms FLOAT NOT NULL,
  team             VARCHAR(64),
  tier             VARCHAR(16)
);

INSERT INTO slo_targets VALUES
  ('checkout',  0.1, 200.0, 'payments', 'critical'),
  ('inventory', 0.5, 300.0, 'catalog',  'standard');
-- 'search' intentionally omitted
```

---

### Metrics generator

Python script using `prometheus_client`. Expose on port 8080. Use a `Counter` for `http_requests_total{service, status_code}` and a `Gauge` for `http_request_duration_seconds{service, quantile}`. Run a background thread that increments counters at realistic rates with noise every second.

---

### Dashboard JSON — critical rules

#### schemaVersion
Use `"schemaVersion": 40` for Grafana 12.2+. (schemaVersion 39 is Grafana 11.x.)

#### Mixed-datasource panels (PITFALL 3)

Any panel that contains queries from more than one datasource (Prometheus + MySQL + `__expr__`) **must** set the panel-level datasource to Mixed:

```json
"datasource": { "type": "datasource", "uid": "-- Mixed --" }
```

Do NOT set the panel datasource to `{ "type": "__expr__", "uid": "__expr__" }` — Grafana will treat all targets as expression queries and reject the Prometheus/MySQL targets with "invalid command type".

#### Prometheus column names in SQL expressions (PITFALL 4)

When a Prometheus range query is used as input to a SQL expression, the DuckDB table columns are:

```
time          (lowercase)
__value__     (NOT "value", NOT "Value" — it is literally "__value__")
__metric_name__
__display_name__
service       (or whatever labels your query has, lowercase)
```

The `__value__` naming is specific to Grafana 12.2's DuckDB expression engine. Do NOT use `A.value` or `A.Value` — they will fail with `table "a" does not have column "value"`.

To verify the actual column names at any time, run this SQL expression:
```sql
SELECT * FROM A LIMIT 1
```
(Note: `DESCRIBE A` is blocked by Grafana's SQL expression allowlist.)

#### MySQL column names

MySQL table-format query columns come through as written in your SELECT statement — standard lowercase. No special prefixes.

#### Cell color coding in Grafana 12.x (PITFALL 5)

`"custom.displayMode": "color-background"` is the **old Grafana ≤9 API** and is silently ignored in Grafana 12.x.

Use `"custom.cellOptions"` instead:

```json
{
  "id": "custom.cellOptions",
  "value": { "type": "color-background" }
}
```

Full override example for a traffic-light column:
```json
{
  "matcher": { "id": "byName", "options": "budget_remaining" },
  "properties": [
    { "id": "unit", "value": "percent" },
    { "id": "decimals", "value": 3 },
    {
      "id": "thresholds",
      "value": {
        "mode": "absolute",
        "steps": [
          { "color": "red", "value": null },
          { "color": "green", "value": 0 }
        ]
      }
    },
    { "id": "custom.cellOptions", "value": { "type": "color-background" } }
  ]
}
```

---

### Exercise SQL expressions

All SQL must use `__value__` for Prometheus value columns. `time` and label columns are lowercase.

**Exercise 01 (worked example):**
```sql
SELECT
  A.time,
  A.service,
  A.__value__                       AS error_rate_pct,
  B.error_budget_pct                AS slo_target_pct,
  B.error_budget_pct - A.__value__  AS budget_remaining
FROM A
JOIN B ON A.service = B.service
```
Use `JOIN` (not `LEFT JOIN`) to exclude services with no SLO entry.

**Exercise 02 (partial — COALESCE):**
```sql
SELECT
  A.time,
  A.service,
  A.__value__                                      AS error_rate_pct,
  COALESCE(B.error_budget_pct, 1.0)                AS effective_slo,
  A.__value__ > COALESCE(B.error_budget_pct, 1.0)  AS is_breaching
FROM A
LEFT JOIN B ON A.service = B.service
WHERE A.__value__ > 0
```
Three blanks for learners: `1.0`, `1.0`, `0`.

**Exercise 03 (self-guided — three-way join):**
```sql
SELECT
  A.service,
  ROUND(AVG(A.__value__), 3)                     AS avg_error_rate_pct,
  ROUND(AVG(B.__value__) * 1000, 1)              AS avg_p99_ms,
  C.error_budget_pct,
  C.p99_threshold_ms,
  AVG(A.__value__) <= C.error_budget_pct         AS error_slo_met,
  AVG(B.__value__) * 1000 <= C.p99_threshold_ms  AS latency_slo_met
FROM A
JOIN B ON A.time = B.time AND A.service = B.service
LEFT JOIN C ON A.service = C.service
GROUP BY A.service, C.error_budget_pct, C.p99_threshold_ms
ORDER BY avg_error_rate_pct DESC
```

---

### Prometheus queries

```promql
# Error rate % by service (use this for Query A in exercises 01–02)
sum by (service) (rate(http_requests_total{status_code=~"5.."}[2m]))
/ sum by (service) (rate(http_requests_total[2m]))
* 100

# p99 latency in seconds by service (use this for Query B in exercise 03)
http_request_duration_seconds{quantile="0.99"}
```

Both queries: `legendFormat: "{{service}}"`, `range: true`, `instant: false`.

---

### Grafana API — reimport dashboards after edits

```bash
curl -s -X POST http://admin:stupid123@localhost:3001/api/dashboards/import \
  -H "Content-Type: application/json" \
  -d "{\"dashboard\": $(cat path/to/dashboard.json), \"overwrite\": true, \"folderId\": 0}"
```

---

## Pitfall Index

| # | Pitfall | Symptom | Fix |
|---|---|---|---|
| 1 | `grafana/grafana:latest` pulls 11.2 | `sqlExpressions` feature toggle is ignored, DuckDB not found | Pin to `grafana/grafana:12.2.0-ubuntu` |
| 2 | Using Alpine-based Grafana image | DuckDB binary fails with `__res_init: symbol not found` | Use `-ubuntu` variant; Alpine lacks required glibc symbols even with `libc6-compat` |
| 3 | Panel datasource set to `__expr__` on mixed panels | `invalid command type in expression 'A'` | Set panel datasource to `{ "type": "datasource", "uid": "-- Mixed --" }` |
| 4 | Using `A.Value` or `A.value` for Prometheus values | `table "a" does not have column "value"` | Use `A.__value__` — the DuckDB engine exposes it with this internal name |
| 5 | Using `custom.displayMode: "color-background"` | Color coding silently does nothing | Use `custom.cellOptions: { "type": "color-background" }` in Grafana 12.x |
| 6 | Missing `GF_AUTH_BASIC_ENABLED=true` | All API calls return 401 | Add to Grafana environment in docker-compose |
