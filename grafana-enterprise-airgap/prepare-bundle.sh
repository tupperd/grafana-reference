#!/usr/bin/env bash
# Phase 1: Prepare artifacts (run with network).
# Produces ./airgap-bundle/ with image tar, license, and optional plugins.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/airgap-bundle"
IMAGE_NAME="grafana/grafana-enterprise"
IMAGE_TAG="${GRAFANA_VERSION:-11.0.0}"
IMAGE_SPEC="${IMAGE_NAME}:${IMAGE_TAG}"
LICENSE_SRC="${SCRIPT_DIR}/license.jwt"

mkdir -p "$BUNDLE_DIR"

echo "==> Pulling ${IMAGE_SPEC}"
docker pull "$IMAGE_SPEC"

echo "==> Saving image to airgap-bundle/grafana-enterprise.tar"
docker save -o "${BUNDLE_DIR}/grafana-enterprise.tar" "$IMAGE_SPEC"

if [[ -f "$LICENSE_SRC" ]]; then
  echo "==> Copying license.jwt into bundle"
  cp "$LICENSE_SRC" "${BUNDLE_DIR}/license.jwt"
else
  echo "WARN: No license.jwt at ${LICENSE_SRC}; copy it into airgap-bundle/ before running airgapped."
fi

# Optional: JIRA Enterprise plugin (for airgapped testing). Use 2.3.3 for Grafana 11.0.x; 2.5.1 needs 11.6.7+.
# Use: PREPARE_JIRA_PLUGIN=0 ./prepare-bundle.sh  (prefix form so the var is passed to this script).
if [[ "${PREPARE_JIRA_PLUGIN:-1}" == "1" ]]; then
  JIRA_VERSION="${JIRA_PLUGIN_VERSION:-2.3.3}"
  PLUGINS_DIR="${BUNDLE_DIR}/plugins"
  mkdir -p "$PLUGINS_DIR"
  # Container is Linux; use amd64 (use linux-arm64 on ARM hosts if your image is arm64)
  JIRA_ZIP="${PLUGINS_DIR}/grafana-jira-datasource.zip"
  JIRA_URL="https://grafana.com/api/plugins/grafana-jira-datasource/versions/${JIRA_VERSION}/download?os=linux&arch=amd64"
  echo "==> Downloading JIRA datasource plugin ${JIRA_VERSION} (linux-amd64)"
  if curl -fsSL -o "$JIRA_ZIP" "$JIRA_URL"; then
    (cd "$PLUGINS_DIR" && unzip -o -q "$JIRA_ZIP" && rm -f "$JIRA_ZIP")
    echo "    Installed to airgap-bundle/plugins/grafana-jira-datasource/"
  else
    echo "WARN: JIRA plugin download failed (URL may require auth). Add plugin manually to airgap-bundle/plugins/grafana-jira-datasource/"
    rm -f "$JIRA_ZIP"
  fi
fi

echo "==> Bundle ready in ${BUNDLE_DIR}"
echo "    Next: disconnect network, then run ./run-airgapped.sh"
