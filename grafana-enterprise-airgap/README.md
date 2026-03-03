# Deploy Grafana Enterprise in a Simulated Airgapped Environment

Two-phase workflow: **prepare** all artifacts on a connected machine, then **deploy** from the bundle with no network (Option B from the practice plan).

NOTE: This demo uses specific versions of Grafana Enterprise and the JIRA plugin to avoid version / dependency conflicts. When implementing this in practice, it is advisable to use the latest compatible version of GE and the JIRA plugin. 

## Prerequisites

- Docker
- A Grafana Enterprise license file (`license.jwt`) in this directory (or in `airgap-bundle/` before running airgapped)
- For plugins: `curl`, `unzip` (used by `prepare-bundle.sh`)

---

## Deploy **without** plugins

Use this when you only need Grafana Enterprise with no extra plugins.

### 1. Prepare the bundle (with network)

Skip plugin download by setting `PREPARE_JIRA_PLUGIN=0` (use the **prefix** form so the variable is passed into the script; `PREPARE_JIRA_PLUGIN=0 && ./prepare-bundle.sh` does not):

```bash
PREPARE_JIRA_PLUGIN=0 ./prepare-bundle.sh
```

This will:

- Pull and save `grafana/grafana-enterprise:12.4.0` to `airgap-bundle/grafana-enterprise.tar`
- Copy `license.jwt` into `airgap-bundle/`
- **Not** download the JIRA plugin

### 2. Run airgapped

```bash
./run-airgapped.sh
```

Grafana will start with no extra plugins. Open http://localhost:3000 (admin/admin).

---

## Deploy **with** plugins

Use this to include the JIRA datasource (or other plugins) in the bundle.

### 1. Prepare the bundle (with network)

Run the prepare script with its default (JIRA plugin included):

```bash
./prepare-bundle.sh
```

This will:

- Pull and save the Grafana Enterprise image to `airgap-bundle/grafana-enterprise.tar`
- Copy `license.jwt` into `airgap-bundle/`
- Download the **JIRA datasource** plugin (v2.5.1) into `airgap-bundle/plugins/grafana-jira-datasource/`

### 2. Run airgapped

```bash
./run-airgapped.sh
```

The script detects `airgap-bundle/plugins` and mounts it into the container. Grafana will load the JIRA plugin. Open http://localhost:3000, then add the datasource: **Connections → Data sources → Add data source → Jira**.

### Adding other plugins (or a different JIRA version)

- **Other plugins:** On a connected machine, download the plugin ZIP from [Grafana plugin catalog](https://grafana.com/grafana/plugins/) (use the download link for the Linux build). Unzip it so the plugin directory lives under the bundle, e.g.:

  ```text
  airgap-bundle/plugins/
  ├── grafana-jira-datasource/   # already added by prepare-bundle.sh
  └── my-other-plugin/            # unzip your plugin here
  ```

  Then run `./run-airgapped.sh` as usual; all contents of `airgap-bundle/plugins/` are mounted.

- **Different JIRA version:** Override with `JIRA_PLUGIN_VERSION`:

  ```bash
  JIRA_PLUGIN_VERSION=2.3.3 ./prepare-bundle.sh
  ```

  Use with a matching Grafana version, e.g. `GRAFANA_VERSION=11.0.0 ./prepare-bundle.sh` (and the same when running).

---

## Environment variables

| Variable | Used by | Default | Description |
|----------|---------|---------|-------------|
| `GRAFANA_VERSION` | both | `12.4.0` | Grafana Enterprise image tag and plugin compatibility. |
| `PREPARE_JIRA_PLUGIN` | prepare-bundle.sh | `1` | Set to `0` to skip downloading the JIRA plugin. |
| `JIRA_PLUGIN_VERSION` | prepare-bundle.sh | `2.5.1` | JIRA datasource plugin version. |
| `GRAFANA_CONTAINER_NAME` | run-airgapped.sh | `grafana-airgap` | Docker container name. |

---

## Simulating an airgapped environment

To practice a true “no network” run:

1. Run `./prepare-bundle.sh` while connected.
2. Disconnect Wi‑Fi or block outbound traffic (e.g. firewall).
3. Run `./run-airgapped.sh` from this directory.

The container uses only the image and files in `airgap-bundle/` (no `docker pull` or plugin download at runtime).

---

## Clean the bundle and start over

To remove all bundle artifacts so you can run `prepare-bundle.sh` again from scratch:

```bash
./clean-bundle.sh
```

Cleaning deletes `airgap-bundle/grafana-enterprise.tar`, `airgap-bundle/license.jwt`, and `airgap-bundle/plugins/`. The `airgap-bundle/` directory is left in place.

---

## Restart and stop

- **Restart** the existing container:  
  `docker restart grafana-airgap`  
  (use your `GRAFANA_CONTAINER_NAME` value if you overrode it)

- **Recreate** (e.g. after changing the bundle or script):  
  `./run-airgapped.sh`  
  (removes the old container and starts a new one)

- **Stop and remove:**  
  `docker stop grafana-airgap && docker rm grafana-airgap`

---

## Bundle layout

After a full prepare (with plugins), the bundle looks like:

```text
airgap-bundle/
├── grafana-enterprise.tar      # Docker image (required)
├── license.jwt                  # Enterprise license (required)
├── plugins/                     # Optional; mounted if present
│   └── grafana-jira-datasource/
└── README.md                    # Short description of the bundle (in-repo)
```

For deploy **without** plugins, `plugins/` is omitted or empty; `run-airgapped.sh` still runs and only mounts plugins when the directory exists and is non-empty.
