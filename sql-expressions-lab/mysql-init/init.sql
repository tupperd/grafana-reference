CREATE DATABASE IF NOT EXISTS slo_db;
USE slo_db;

CREATE TABLE IF NOT EXISTS slo_targets (
  service          VARCHAR(64) PRIMARY KEY,
  error_budget_pct FLOAT       NOT NULL,  -- max allowed error rate as %
  p99_threshold_ms FLOAT       NOT NULL,  -- max allowed p99 latency in ms
  team             VARCHAR(64),
  tier             VARCHAR(16)            -- 'critical' | 'standard'
);

INSERT INTO slo_targets (service, error_budget_pct, p99_threshold_ms, team, tier) VALUES
  ('checkout',  0.1, 200.0, 'payments', 'critical'),
  ('inventory', 0.5, 300.0, 'catalog',  'standard');
-- 'search' is intentionally omitted — drives the COALESCE exercises
