"""
Synthetic Prometheus metrics for the SQL Expressions Lab.

Simulates three e-commerce services with distinct SLO personalities:
  checkout  — ~100 req/s, ~0.08% error rate (under SLO budget)
  inventory — ~200 req/s, ~0.6% error rate (occasionally spikes over budget)
  search    — ~500 req/s, ~1.8% error rate (consistently over budget, no SLO entry in MySQL)

Exposes:
  http_requests_total{service, status_code}         Counter
  http_request_duration_seconds{service, quantile}  Gauge (p99 value)
"""

import random
import threading
import time

from prometheus_client import Counter, Gauge, start_http_server

# --- Metrics -----------------------------------------------------------

REQUEST_COUNTER = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "status_code"],
)

P99_LATENCY = Gauge(
    "http_request_duration_seconds",
    "p99 request latency in seconds",
    ["service", "quantile"],
)

# Initialise p99 gauges so they appear in /metrics immediately
for svc in ("checkout", "inventory", "search"):
    P99_LATENCY.labels(service=svc, quantile="0.99").set(0)


# --- Service profiles --------------------------------------------------

SERVICES = {
    "checkout": {
        "base_rps": 100.0,
        "rps_jitter": 10.0,
        "base_error_rate": 0.0008,      # 0.08% — under 0.1% SLO budget
        "error_spike_prob": 0.0,        # no spikes
        "spike_error_rate": 0.002,
        "base_p99_s": 0.150,            # 150 ms
        "p99_jitter_s": 0.020,
    },
    "inventory": {
        "base_rps": 200.0,
        "rps_jitter": 20.0,
        "base_error_rate": 0.004,       # 0.4% baseline — near 0.5% SLO budget
        "error_spike_prob": 0.05,       # 5% chance of a spike each tick
        "spike_error_rate": 0.015,      # 1.5% during spike — over budget
        "base_p99_s": 0.090,            # 90 ms
        "p99_jitter_s": 0.015,
    },
    "search": {
        "base_rps": 500.0,
        "rps_jitter": 50.0,
        "base_error_rate": 0.018,       # 1.8% — consistently over any reasonable SLO
        "error_spike_prob": 0.0,
        "spike_error_rate": 0.030,
        "base_p99_s": 0.320,            # 320 ms
        "p99_jitter_s": 0.040,
    },
}


# --- Simulation loop ---------------------------------------------------

def simulate():
    spike_state = {svc: False for svc in SERVICES}

    while True:
        for svc, profile in SERVICES.items():
            # Determine error rate for this tick
            if random.random() < profile["error_spike_prob"]:
                spike_state[svc] = not spike_state[svc]
            error_rate = (
                profile["spike_error_rate"]
                if spike_state[svc]
                else profile["base_error_rate"]
            )

            # Compute requests this tick (~1 s worth at base_rps + jitter)
            rps = max(1.0, profile["base_rps"] + random.gauss(0, profile["rps_jitter"]))
            total = int(rps)
            errors = int(total * error_rate)
            successes = total - errors

            # Increment counters
            if successes > 0:
                REQUEST_COUNTER.labels(service=svc, status_code="200").inc(successes)
            if errors > 0:
                REQUEST_COUNTER.labels(service=svc, status_code="500").inc(errors)

            # Update p99 latency gauge
            p99 = profile["base_p99_s"] + random.gauss(0, profile["p99_jitter_s"])
            p99 = max(0.001, p99)
            P99_LATENCY.labels(service=svc, quantile="0.99").set(p99)

        time.sleep(1)


# --- Entry point -------------------------------------------------------

if __name__ == "__main__":
    print("Starting metrics server on :8080 ...")
    start_http_server(8080)

    thread = threading.Thread(target=simulate, daemon=True)
    thread.start()

    print("Metrics generator running. Ctrl-C to stop.")
    while True:
        time.sleep(60)
