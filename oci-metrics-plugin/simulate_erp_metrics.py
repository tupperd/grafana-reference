#!/usr/bin/env python3
"""
ERP Metrics Simulator for Grafana Cloud + OCI Monitoring
Publishes synthetic ERP metrics to OCI Monitoring, which are then
visualized in Grafana Cloud via the OCI Metrics datasource plugin.

Namespace : erp_demo
Resource groups: order_mgmt, inventory, manufacturing, finance

Usage:
    python simulate_erp_metrics.py [--config ~/.oci/config] [--profile DEFAULT]
    python simulate_erp_metrics.py --instance-principal   # when running on OCI compute

Requirements:
    pip install oci
"""

import argparse
import datetime
import logging
import math
import random
import time
import sys

import oci
from oci.monitoring.models import (
    MetricDataDetails,
    Datapoint,
    PostMetricDataDetails,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("erp-simulator")

# ── Configuration ──────────────────────────────────────────────────────────────
NAMESPACE = "erp_demo"
PUBLISH_INTERVAL_SECONDS = 60  # OCI minimum aggregation granularity is 1 minute

# Set this to your OCI compartment OCID.
# You can override via the --compartment flag or OCI_COMPARTMENT_ID env var.
DEFAULT_COMPARTMENT_ID = ""  # e.g. "ocid1.compartment.oc1..aaaaaaaaxxx"

# Telemetry ingestion endpoint — update region to match your OCI home region.
# Common: us-ashburn-1, us-phoenix-1, eu-frankfurt-1, ap-sydney-1, uk-london-1
DEFAULT_REGION = "us-ashburn-1"


# ── Simulation helpers ─────────────────────────────────────────────────────────

def wave(t: float, base: float, amplitude: float, period_hours: float,
         noise_stddev: float, min_val: float = 0, max_val: float = float("inf")) -> float:
    """Sinusoidal wave with Gaussian noise, clamped to [min_val, max_val]."""
    period_s = period_hours * 3600
    value = base + amplitude * math.sin(2 * math.pi * t / period_s)
    value += random.gauss(0, noise_stddev)
    return max(min_val, min(max_val, value))


def incident_modifier(t: float, metric: str) -> float:
    """
    Inject occasional 'incidents' to make the demo interesting.
    Returns a multiplier (1.0 = no incident, <1.0 = degradation).
    Uses a deterministic seed so incidents persist for several minutes.
    """
    window = int(t / 300)  # 5-minute windows
    rng = random.Random(f"{metric}-{window}")
    if rng.random() < 0.03:  # ~3% of windows ≈ 1 incident per ~2.7 hours
        severity = rng.uniform(0.6, 0.85)  # 15–40% degradation
        return severity
    return 1.0


def now_ts() -> str:
    """Return current UTC time in OCI-compatible ISO-8601 format."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ── Metric builders ────────────────────────────────────────────────────────────

def build_order_metrics(t: float, compartment_id: str) -> list:
    """Order Management module metrics."""
    metrics = []

    # Orders per minute by channel
    for channel, base, amp in [
        ("distributor", 85, 25),
        ("direct",      35, 15),
        ("ecommerce",   20, 10),
    ]:
        opm = wave(t, base, amp, period_hours=8, noise_stddev=6, min_val=0)
        opm *= incident_modifier(t, f"opm_{channel}")
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="order_mgmt",
            name="orders_per_minute",
            dimensions={"channel": channel},
            metadata={"unit": "count", "displayName": "Orders Per Minute"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(opm, 2))],
        ))

    # Order fulfillment rate by warehouse
    for warehouse in ["west_dc", "southwest_dc", "northwest_dc"]:
        rate = wave(t, 97.2, 2.5, period_hours=12, noise_stddev=0.8,
                    min_val=85, max_val=100)
        rate *= incident_modifier(t, f"fulfillment_{warehouse}")
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="order_mgmt",
            name="order_fulfillment_rate",
            dimensions={"warehouse": warehouse},
            metadata={"unit": "percent", "displayName": "Order Fulfillment Rate"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(rate, 2))],
        ))

    # Average order value by customer tier
    for tier, base, amp in [
        ("platinum", 4800, 600),
        ("gold",     2200, 350),
        ("standard",  850, 150),
    ]:
        aov = wave(t, base, amp, period_hours=24, noise_stddev=80, min_val=100)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="order_mgmt",
            name="average_order_value_usd",
            dimensions={"customer_tier": tier},
            metadata={"unit": "USD", "displayName": "Average Order Value"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(aov, 2))],
        ))

    # Order cycle time (minutes from receipt to ship-confirmation)
    for order_type, base, amp in [
        ("standard",  48, 12),
        ("rush",      18,  4),
        ("scheduled", 72,  8),
    ]:
        cycle = wave(t, base, amp, period_hours=8, noise_stddev=3, min_val=1)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="order_mgmt",
            name="order_cycle_time_minutes",
            dimensions={"order_type": order_type},
            metadata={"unit": "minutes", "displayName": "Order Cycle Time"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(cycle, 1))],
        ))

    # Backorder count by product category
    for category in ["dressings", "sauces", "condiments", "oils", "specialty"]:
        backorders = wave(t, 12, 8, period_hours=24, noise_stddev=3, min_val=0)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="order_mgmt",
            name="backorder_count",
            dimensions={"product_category": category},
            metadata={"unit": "count", "displayName": "Backorder Count"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(backorders))],
        ))

    return metrics


def build_inventory_metrics(t: float, compartment_id: str) -> list:
    """Inventory & Supply Chain metrics."""
    metrics = []

    categories = ["dressings", "sauces", "condiments", "oils", "specialty"]
    warehouses = ["west_dc", "southwest_dc", "northwest_dc"]

    # Inventory fill rate by warehouse × category
    for warehouse in warehouses:
        for category in categories:
            fill = wave(t, 76, 14, period_hours=24, noise_stddev=3,
                        min_val=20, max_val=100)
            fill *= incident_modifier(t, f"inventory_{warehouse}_{category}")
            metrics.append(MetricDataDetails(
                namespace=NAMESPACE,
                compartment_id=compartment_id,
                resource_group="inventory",
                name="inventory_fill_rate",
                dimensions={"warehouse": warehouse, "product_category": category},
                metadata={"unit": "percent", "displayName": "Inventory Fill Rate"},
                datapoints=[Datapoint(timestamp=now_ts(), value=round(fill, 1))],
            ))

    # Days of supply by category
    for category, base in [
        ("dressings", 18), ("sauces", 22), ("condiments", 15),
        ("oils", 30), ("specialty", 12),
    ]:
        dos = wave(t, base, base * 0.25, period_hours=48, noise_stddev=1.5, min_val=1)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="inventory",
            name="days_of_supply",
            dimensions={"product_category": category},
            metadata={"unit": "days", "displayName": "Days of Supply"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(dos, 1))],
        ))

    # Warehouse utilization
    for warehouse, base in [
        ("west_dc", 82), ("southwest_dc", 71), ("northwest_dc", 88),
    ]:
        util = wave(t, base, 6, period_hours=12, noise_stddev=2, min_val=40, max_val=100)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="inventory",
            name="warehouse_utilization",
            dimensions={"warehouse": warehouse},
            metadata={"unit": "percent", "displayName": "Warehouse Utilization"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(util, 1))],
        ))

    # Inbound shipments on-time by supplier tier
    for supplier_tier in ["strategic", "preferred", "standard"]:
        ont = wave(t, 94, 4, period_hours=24, noise_stddev=1.5, min_val=70, max_val=100)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="inventory",
            name="inbound_shipments_on_time",
            dimensions={"supplier_tier": supplier_tier},
            metadata={"unit": "percent", "displayName": "Inbound Shipments On-Time"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(ont, 1))],
        ))

    return metrics


def build_manufacturing_metrics(t: float, compartment_id: str) -> list:
    """Manufacturing / Production metrics."""
    metrics = []

    plants = {
        "west_plant":    ["line_1", "line_2", "line_3"],
        "south_plant":   ["line_1", "line_2"],
        "midwest_plant": ["line_1", "line_2"],
    }

    for plant, lines in plants.items():
        for line in lines:
            key = f"{plant}_{line}"

            # Overall Equipment Effectiveness (OEE) — headline manufacturing KPI
            oee = wave(t, 82, 7, period_hours=8, noise_stddev=1.8, min_val=40, max_val=100)
            oee *= incident_modifier(t, f"oee_{key}")
            metrics.append(MetricDataDetails(
                namespace=NAMESPACE,
                compartment_id=compartment_id,
                resource_group="manufacturing",
                name="production_oee",
                dimensions={"plant": plant, "line": line},
                metadata={"unit": "percent", "displayName": "Production OEE"},
                datapoints=[Datapoint(timestamp=now_ts(), value=round(oee, 1))],
            ))

            # Units produced per hour (correlated with OEE)
            uph = wave(t, 2400, 400, period_hours=8, noise_stddev=120, min_val=0)
            uph *= (oee / 82)
            metrics.append(MetricDataDetails(
                namespace=NAMESPACE,
                compartment_id=compartment_id,
                resource_group="manufacturing",
                name="units_produced_per_hour",
                dimensions={"plant": plant, "line": line},
                metadata={"unit": "count", "displayName": "Units Produced Per Hour"},
                datapoints=[Datapoint(timestamp=now_ts(), value=round(uph))],
            ))

            # First pass yield
            fpy = wave(t, 98.2, 1.5, period_hours=8, noise_stddev=0.4,
                       min_val=85, max_val=100)
            metrics.append(MetricDataDetails(
                namespace=NAMESPACE,
                compartment_id=compartment_id,
                resource_group="manufacturing",
                name="first_pass_yield",
                dimensions={"plant": plant, "line": line},
                metadata={"unit": "percent", "displayName": "First Pass Yield"},
                datapoints=[Datapoint(timestamp=now_ts(), value=round(fpy, 2))],
            ))

            # Downtime minutes (spikes during incidents)
            downtime = 0.0
            if incident_modifier(t, f"oee_{key}") < 1.0:
                downtime = random.uniform(5, PUBLISH_INTERVAL_SECONDS / 60 * 0.4)
            metrics.append(MetricDataDetails(
                namespace=NAMESPACE,
                compartment_id=compartment_id,
                resource_group="manufacturing",
                name="downtime_minutes",
                dimensions={"plant": plant, "line": line},
                metadata={"unit": "minutes", "displayName": "Downtime (last interval)"},
                datapoints=[Datapoint(timestamp=now_ts(), value=round(downtime, 1))],
            ))

    return metrics


def build_finance_metrics(t: float, compartment_id: str) -> list:
    """Finance module metrics."""
    metrics = []

    # Revenue per hour by business unit
    for bu, base, amp in [
        ("foodservice", 92000, 22000),
        ("retail",      55000, 18000),
        ("industrial",  28000,  8000),
    ]:
        rev = wave(t, base, amp, period_hours=8, noise_stddev=3000, min_val=0)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="finance",
            name="revenue_per_hour_usd",
            dimensions={"business_unit": bu},
            metadata={"unit": "USD", "displayName": "Revenue Per Hour"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(rev, 2))],
        ))

    # Gross margin % by product category
    for category, base, amp in [
        ("dressings",  38, 4),
        ("sauces",     42, 5),
        ("condiments", 35, 3),
        ("oils",       28, 6),
        ("specialty",  45, 3),
    ]:
        margin = wave(t, base, amp, period_hours=24, noise_stddev=1.0,
                      min_val=10, max_val=75)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="finance",
            name="gross_margin_percent",
            dimensions={"product_category": category},
            metadata={"unit": "percent", "displayName": "Gross Margin %"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(margin, 2))],
        ))

    # Budget vs actual variance % (negative = under budget)
    for dept in ["operations", "logistics", "manufacturing", "sales"]:
        variance = wave(t, 2.5, 3.5, period_hours=24, noise_stddev=1.0,
                        min_val=-10, max_val=20)
        metrics.append(MetricDataDetails(
            namespace=NAMESPACE,
            compartment_id=compartment_id,
            resource_group="finance",
            name="budget_vs_actual_variance_percent",
            dimensions={"department": dept},
            metadata={"unit": "percent", "displayName": "Budget vs Actual Variance"},
            datapoints=[Datapoint(timestamp=now_ts(), value=round(variance, 2))],
        ))

    return metrics


# ── Main publish loop ──────────────────────────────────────────────────────────

def build_monitoring_client(args) -> oci.monitoring.MonitoringClient:
    region = args.region or DEFAULT_REGION
    endpoint = f"https://telemetry-ingestion.{region}.oraclecloud.com"

    if args.instance_principal:
        log.info("Using instance principal authentication")
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        return oci.monitoring.MonitoringClient(
            config={}, signer=signer, service_endpoint=endpoint
        )

    log.info("Using OCI config file: %s [profile: %s]", args.config, args.profile)
    config = oci.config.from_file(args.config, args.profile)
    if args.region:
        config["region"] = args.region
    return oci.monitoring.MonitoringClient(config=config, service_endpoint=endpoint)


def publish(client: oci.monitoring.MonitoringClient,
            metrics: list,
            dry_run: bool = False):
    if dry_run:
        log.info("[DRY RUN] Would publish %d metric streams", len(metrics))
        return

    # OCI allows max 50 metric streams per API call — batch accordingly
    batch_size = 50
    failed_total = 0
    for i in range(0, len(metrics), batch_size):
        batch = metrics[i:i + batch_size]
        resp = client.post_metric_data(
            post_metric_data_details=PostMetricDataDetails(metric_data=batch)
        )
        failed = resp.data.failed_metrics_count or 0
        failed_total += failed
        if failed:
            log.warning("Batch %d: %d metric(s) failed", i // batch_size, failed)

    log.info("Published %d streams (%d failed)", len(metrics), failed_total)


def main():
    parser = argparse.ArgumentParser(description="ERP Metric Simulator for OCI + Grafana")
    parser.add_argument("--config",    default="~/.oci/config", help="OCI config file path")
    parser.add_argument("--profile",   default="DEFAULT",       help="OCI config profile name")
    parser.add_argument("--region",    default=None,            help="OCI region (e.g. us-ashburn-1)")
    parser.add_argument("--compartment", default=None,          help="OCI compartment OCID")
    parser.add_argument("--instance-principal", action="store_true",
                        help="Use instance principal auth (for OCI compute instances)")
    parser.add_argument("--interval", type=int, default=PUBLISH_INTERVAL_SECONDS,
                        help=f"Publish interval in seconds (default: {PUBLISH_INTERVAL_SECONDS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build metrics but do not publish them")
    parser.add_argument("--once", action="store_true",
                        help="Publish once and exit (useful for cron)")
    args = parser.parse_args()

    compartment_id = args.compartment or DEFAULT_COMPARTMENT_ID
    if not compartment_id:
        log.error(
            "Compartment OCID required. Set DEFAULT_COMPARTMENT_ID in the script "
            "or pass --compartment ocid1.compartment.oc1..xxx"
        )
        sys.exit(1)

    client = None
    if not args.dry_run:
        client = build_monitoring_client(args)

    log.info("Starting ERP metric simulation (namespace=%s, interval=%ds)",
             NAMESPACE, args.interval)

    while True:
        t = time.time()
        try:
            metrics = (
                build_order_metrics(t, compartment_id)
                + build_inventory_metrics(t, compartment_id)
                + build_manufacturing_metrics(t, compartment_id)
                + build_finance_metrics(t, compartment_id)
            )
            log.info("Built %d metric streams", len(metrics))
            publish(client, metrics, dry_run=args.dry_run)

        except oci.exceptions.ServiceError as e:
            log.error("OCI API error: %s %s", e.status, e.message)
        except Exception as e:
            log.exception("Unexpected error: %s", e)

        if args.once:
            break

        elapsed = time.time() - t
        sleep_for = max(0, args.interval - elapsed)
        log.debug("Sleeping %.1fs until next publish", sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
