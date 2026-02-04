#!/usr/bin/env python3
import argparse
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import boto3


@dataclass
class SeriesState:
    value: float
    drift: float
    spike_remaining: int
    spike_target: float
    drain_rate: float


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def make_keys(brokers: int, queues: int, vhosts: int):
    broker_names = [f"rmq-broker-{i+1}" for i in range(brokers)]
    queue_names = [f"queue-{i+1:02d}" for i in range(queues)]
    vhost_names = ["/", "/payments", "/core"][:vhosts]
    keys = []
    for b in broker_names:
        for q in queue_names:
            for v in vhost_names:
                keys.append((b, q, v))
    return keys


def init_state(seed: int) -> SeriesState:
    rng = random.Random(seed)
    baseline = rng.uniform(20, 120)  # typical steady queue depth
    drift = rng.uniform(-0.8, 0.8)   # slow trend
    return SeriesState(
        value=baseline,
        drift=drift,
        spike_remaining=0,
        spike_target=0.0,
        drain_rate=rng.uniform(8, 25),
    )


def step_state(
    st: SeriesState,
    minute_of_day: int,
    rng: random.Random,
) -> SeriesState:
    # Daily cycle: busier mid-day than overnight (simple sinusoid)
    # peak ~ mid-day, trough ~ early morning
    daily = 18.0 * math.sin((2 * math.pi) * (minute_of_day / 1440.0) - 1.2)

    # Random walk-ish drift (slowly varying)
    st.drift += rng.uniform(-0.15, 0.15)
    st.drift = clamp(st.drift, -2.0, 2.0)

    # Noise
    noise = rng.gauss(0, 6.0)

    # Spike logic:
    # - Small chance to start a spike if not already in one
    # - Once spike starts, jump toward a target then drain for a while
    if st.spike_remaining <= 0:
        # ~1.5% chance per minute per series -> expect occasional spikes across 60 series
        if rng.random() < 0.015:
            st.spike_remaining = rng.randint(8, 25)  # minutes
            st.spike_target = rng.uniform(250, 1200)  # spike magnitude
    else:
        st.spike_remaining -= 1

    # If in spike window, move up toward spike_target
    if st.spike_remaining > 0:
        # ease upward quickly
        st.value += (st.spike_target - st.value) * rng.uniform(0.25, 0.55)
    else:
        # drain behavior: trend down a bit faster than normal after spike
        st.value -= st.drain_rate + rng.uniform(0, 6.0)

    # Normal evolution: baseline + daily + drift + noise
    st.value += daily + st.drift + noise

    # Keep non-negative and reasonable
    st.value = clamp(st.value, 0.0, 5000.0)
    return st


def publish_batch(cw, namespace: str, metric_name: str, unit: str, items):
    # CloudWatch PutMetricData supports up to 20 MetricData per call
    for i in range(0, len(items), 20):
        cw.put_metric_data(Namespace=namespace, MetricData=items[i:i+20])


def main():
    ap = argparse.ArgumentParser(description="Simulate RabbitMQ-like queue depth metrics in CloudWatch.")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--namespace", default="Demo/AmazonMQ")
    ap.add_argument("--metric", default="MessageCount")
    ap.add_argument("--unit", default="Count")
    ap.add_argument("--brokers", type=int, default=2)
    ap.add_argument("--queues", type=int, default=10)
    ap.add_argument("--vhosts", type=int, default=3)
    ap.add_argument("--interval-seconds", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cw = boto3.client("cloudwatch", region_name=args.region)

    keys = make_keys(args.brokers, args.queues, args.vhosts)
    states = {}
    for idx, key in enumerate(keys):
        # per-series deterministic seed for repeatability
        states[key] = init_state(args.seed * 10_000 + idx)

    print(f"Publishing {len(keys)} time series to CloudWatch:")
    print(f"  Namespace: {args.namespace}")
    print(f"  Metric:    {args.metric}")
    print(f"  Region:    {args.region}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            now = datetime.now(timezone.utc)
            minute_of_day = now.hour * 60 + now.minute

            metric_data = []
            for (broker, queue, vhost), st in states.items():
                rng = random.Random(hash((broker, queue, vhost, now.minute, now.hour, args.seed)))
                st = step_state(st, minute_of_day, rng)
                states[(broker, queue, vhost)] = st

                metric_data.append({
                    "MetricName": args.metric,
                    "Dimensions": [
                        {"Name": "Broker", "Value": broker},
                        {"Name": "Queue", "Value": queue},
                        {"Name": "VirtualHost", "Value": vhost},
                    ],
                    "Timestamp": now,
                    "Unit": args.unit,
                    "Value": float(int(st.value)),  # make it look like a count
                })

            publish_batch(cw, args.namespace, args.metric, args.unit, metric_data)

            # Basic heartbeat
            sample = keys[0]
            print(f"{now.isoformat()}Z published {len(metric_data)} series. sample={sample} value={int(states[sample].value)}")

            time.sleep(args.interval_seconds)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
