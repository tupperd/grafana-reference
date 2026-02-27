# OCI Metrics Datasource Plugin — ERP Demo

Visualize custom business metrics from Oracle Cloud Infrastructure (OCI) Monitoring in Grafana Cloud. This example uses a synthetic ERP workload to demonstrate how to push custom metrics to OCI and build production-quality dashboards with the [OCI Metrics Datasource plugin](https://grafana.com/grafana/plugins/oci-metrics-datasource/).

## What this demo shows

- Publishing custom metrics to OCI Monitoring via the Telemetry Ingestion API
- Using the `groupBy()` MQL syntax to split time series by dimension
- Building a multi-section Grafana dashboard (Order Management, Inventory, Manufacturing, Finance) with mixed visualization types: time series, gauge, bar gauge, and stat panels
- The new Grafana `dashboard.grafana.app/v2beta1` schema (scenes-based)

**Metric streams published:** 83 streams across 4 resource groups
**Publish interval:** 60 seconds (OCI minimum aggregation granularity)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| OCI account | Free tier is sufficient |
| OCI CLI configured | `~/.oci/config` with a valid API key |
| Grafana Cloud account | Free tier works; stack must support plugin installation |
| Python 3.8+ | With `pip install oci` |

---

## Step 1 — Install the OCI Metrics Datasource Plugin

1. In Grafana Cloud, go to **Administration → Plugins**
2. Search for **OCI Metrics** and install [OCI Metrics Datasource](https://grafana.com/grafana/plugins/oci-metrics-datasource/)
3. After installation, go to **Connections → Data sources → Add data source → OCI Metrics**
4. Configure the datasource:
   - **Authentication:** OCI User Principals (uses `~/.oci/config`)
   - **Config file path:** `/etc/grafana/oci_config` (for hosted Grafana) or `~/.oci/config` (local)
   - **Tenancy mode:** Single tenancy
   - **Default region:** Your OCI home region (e.g. `us-ashburn-1`)
5. Click **Save & Test** — you should see a green success banner
6. Note the **datasource UID** shown in the URL (`/datasources/edit/<UID>`) — you'll need it when importing the dashboard

> **Note:** For Grafana Cloud (hosted), you need to provide your OCI credentials through the datasource configuration UI rather than a local config file. See the [plugin docs](https://grafana.com/grafana/plugins/oci-metrics-datasource/) for details on the hosted setup.

---

## Step 2 — Configure OCI Credentials

The simulator uses your local OCI CLI config. Verify it is working:

```bash
# Confirm OCI CLI can reach your tenancy
oci iam tenancy get --tenancy-id <YOUR_TENANCY_OCID>
```

You'll need your **compartment OCID** for the next step. To find it:

```bash
# List compartments in your tenancy (use tenancy OCID as compartment-id for root)
oci iam compartment list --compartment-id <YOUR_TENANCY_OCID>
```

---

## Step 3 — Run the Metrics Simulator

Install the Python dependency:

```bash
pip install oci
```

Run a dry run first to validate metric construction without publishing:

```bash
python simulate_erp_metrics.py \
  --compartment <YOUR_COMPARTMENT_OCID> \
  --region <YOUR_OCI_REGION> \
  --dry-run
```

If it prints `Built 83 metric streams`, you're ready to publish:

```bash
python simulate_erp_metrics.py \
  --compartment <YOUR_COMPARTMENT_OCID> \
  --region <YOUR_OCI_REGION>
```

Expected output every 60 seconds:
```
2024-01-15T10:00:00Z INFO Starting ERP metric simulation (namespace=erp_demo, interval=60s)
2024-01-15T10:00:01Z INFO Built 83 metric streams
2024-01-15T10:00:02Z INFO Published 83 streams (0 failed)
```

### Keeping the simulator running (macOS)

By default, macOS will suspend the process when the system sleeps. To prevent this:

```bash
# Run in foreground, preventing idle sleep + display sleep + lid-close sleep
caffeinate -dims python simulate_erp_metrics.py \
  --compartment <YOUR_COMPARTMENT_OCID> \
  --region <YOUR_OCI_REGION>
```

To run in the background and survive terminal close:

```bash
caffeinate -dims python simulate_erp_metrics.py \
  --compartment <YOUR_COMPARTMENT_OCID> \
  --region <YOUR_OCI_REGION> >> /tmp/erp-simulator.log 2>&1 &

# Monitor logs
tail -f /tmp/erp-simulator.log

# Stop it
pkill caffeinate
```

### Running on Linux (systemd)

For a persistent setup on a Linux VM:

```ini
# /etc/systemd/system/erp-simulator.service
[Unit]
Description=ERP Metrics Simulator
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/erp-simulator/simulate_erp_metrics.py \
  --compartment YOUR_COMPARTMENT_OCID \
  --region YOUR_OCI_REGION
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now erp-simulator
sudo journalctl -fu erp-simulator
```

---

## Step 4 — Verify Metrics Are Arriving in OCI

Allow 2–3 minutes after first publish, then verify via OCI Console:

**Observability → Monitoring → Metrics Explorer**
- Namespace: `erp_demo`
- Resource group: `order_mgmt`
- Metric: `orders_per_minute`
- Dimension: `channel`

Or via CLI:

```bash
oci monitoring metric-data summarize-metrics-data \
  --compartment-id <YOUR_COMPARTMENT_OCID> \
  --namespace erp_demo \
  --query-text 'orders_per_minute[1m].groupBy(channel).avg()'
```

---

## Step 5 — Import the Dashboard

The dashboard uses the Grafana `v2beta1` API format (scenes-based). Before importing, update the placeholder values in `dashboards/erp_overview.json`:

| Placeholder | Replace with |
|---|---|
| `YOUR_OCI_DATASOURCE_UID` | The UID from your OCI Metrics datasource (Step 1) |
| `YOUR_COMPARTMENT_OCID` | Your OCI compartment OCID |
| `YOUR_COMPARTMENT_NAME` | Display name for your compartment |
| `YOUR_OCI_REGION` | Your OCI region (e.g. `us-ashburn-1`) |

You can do this with a quick find-and-replace in your editor, then import via the Grafana API:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_GRAFANA_SERVICE_ACCOUNT_TOKEN>" \
  https://<YOUR_STACK>.grafana.net/apis/dashboard.grafana.app/v2beta1/namespaces/stacks-<STACK_ID>/dashboards \
  -d @dashboards/erp_overview.json
```

Alternatively, use the Grafana UI: **Dashboards → Import → Upload JSON file**.

> **Note:** The `v2beta1` format is the new scenes-based schema introduced in Grafana 11. If you are on an older Grafana version, you may need to convert panels to the legacy format manually.

---

## Metric Reference

### Namespace: `erp_demo`

#### Resource group: `order_mgmt`

| Metric | Dimensions | Unit |
|---|---|---|
| `orders_per_minute` | `channel` (distributor, direct, ecommerce) | count |
| `order_fulfillment_rate` | `warehouse` | percent |
| `average_order_value_usd` | `customer_tier` (platinum, gold, standard) | USD |
| `order_cycle_time_minutes` | `order_type` (standard, rush, scheduled) | minutes |
| `backorder_count` | `product_category` | count |

#### Resource group: `inventory`

| Metric | Dimensions | Unit |
|---|---|---|
| `inventory_fill_rate` | `warehouse`, `product_category` | percent |
| `days_of_supply` | `product_category` | days |
| `warehouse_utilization` | `warehouse` | percent |
| `inbound_shipments_on_time` | `supplier_tier` (strategic, preferred, standard) | percent |

#### Resource group: `manufacturing`

| Metric | Dimensions | Unit |
|---|---|---|
| `production_oee` | `plant`, `line` | percent |
| `units_produced_per_hour` | `plant`, `line` | count |
| `first_pass_yield` | `plant`, `line` | percent |
| `downtime_minutes` | `plant`, `line` | minutes |

#### Resource group: `finance`

| Metric | Dimensions | Unit |
|---|---|---|
| `revenue_per_hour_usd` | `business_unit` (foodservice, retail, industrial) | USD |
| `gross_margin_percent` | `product_category` | percent |
| `budget_vs_actual_variance_percent` | `department` | percent |

---

## OCI MQL Query Format

The OCI Metrics plugin uses MQL (Metrics Query Language). Key patterns:

```
# Average over 1-minute window, grouped by a dimension
metric_name[1m].groupBy(dimension).avg()

# Sum over 5-minute window
metric_name[5m].groupBy(dimension).sum()

# No groupBy — aggregate all streams
metric_name[5m].sum()
```

> **Important:** Always include the interval (`[1m]`, `[5m]`, etc.) before the aggregation function. The minimum interval is `1m`. Omitting it will cause a query error.

---

## Troubleshooting

**No data in Grafana after starting the simulator**
- Wait at least 2–3 minutes — OCI buffers metric data before it's queryable
- Verify the namespace and resource group match exactly (case-sensitive)
- Check the simulator log for `failed` counts in the publish output

**`ServiceError: 400` on publish**
- Confirm the compartment OCID is correct and the OCI user has `METRIC_SUBMISSION` permissions
- Required IAM policy: `Allow group <group> to use metrics in compartment <compartment>`

**Datasource test fails in Grafana**
- Ensure the OCI API key in your config has not expired
- For Grafana Cloud, confirm credentials are entered in the datasource UI (not just a local config file)

**`caffeinate` not preventing sleep on macOS**
- Use `-dims` (not just `-i`) to also block display sleep and lid-close sleep
- System-level sleep schedules (MDM policies) may override caffeinate
