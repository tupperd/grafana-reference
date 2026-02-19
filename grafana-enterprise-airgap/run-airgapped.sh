#!/usr/bin/env bash
# Phase 2 (Option B): Load and run Grafana Enterprise from airgap-bundle only.
# Run this AFTER disconnecting Wi‑Fi or blocking outbound (firewall) to simulate airgap.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/airgap-bundle"
IMAGE_TAG="${GRAFANA_VERSION:-11.0.0}"
CONTAINER_NAME="${GRAFANA_CONTAINER_NAME:-grafana-airgap}"
TAR_PATH="${BUNDLE_DIR}/grafana-enterprise.tar"
LICENSE_PATH="${BUNDLE_DIR}/license.jwt"

if [[ ! -f "$TAR_PATH" ]]; then
  echo "Missing ${TAR_PATH}. Run ./prepare-bundle.sh (with network) first."
  exit 1
fi

# if [[ ! -f "$LICENSE_PATH" ]]; then
#   echo "Missing ${LICENSE_PATH}. Add license.jwt to airgap-bundle/ (or run prepare-bundle.sh with license.jwt in this directory)."
#   exit 1
# fi

# Remove existing container if present
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "==> Loading image from bundle (no network)"
docker load -i "$TAR_PATH"

# Use default bridge so -p 3000:3000 works (with --network none, port publishing doesn't work on Docker Desktop).
# For airgap simulation: disconnect Wi‑Fi before running; the container then has no outbound internet.
RUN_OPTS=(
  -d
  --name "$CONTAINER_NAME"
  -p 3000:3000
  -v "${LICENSE_PATH}:/etc/grafana/license.jwt:ro"
  -e GF_ENTERPRISE_LICENSE_PATH=/etc/grafana/license.jwt
  -e GF_SERVER_ROOT_URL=http://localhost:3000/
  -e GF_ENTERPRISE_AUTO_REFRESH_LICENSE=false
)
if [[ -d "${BUNDLE_DIR}/plugins" ]] && [[ -n "$(ls -A "${BUNDLE_DIR}/plugins" 2>/dev/null)" ]]; then
  RUN_OPTS+=( -v "${BUNDLE_DIR}/plugins:/var/lib/grafana/plugins:ro" )
  echo "==> Starting Grafana Enterprise (with plugins from bundle)"
else
  echo "==> Starting Grafana Enterprise"
fi
docker run "${RUN_OPTS[@]}" "grafana/grafana-enterprise:${IMAGE_TAG}"

echo "==> Grafana running at http://localhost:3000 (admin/admin)"
echo "    Check license: Administration → General → Stats and license"
echo "    Add JIRA datasource: Connections → Data sources → Add data source → Jira"
