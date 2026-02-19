#!/usr/bin/env bash
# Remove contents of airgap-bundle so you can run prepare-bundle.sh from scratch.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/airgap-bundle"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "No airgap-bundle directory found. Nothing to clean."
  exit 0
fi

echo "==> Cleaning ${BUNDLE_DIR}"
rm -rf "${BUNDLE_DIR}/grafana-enterprise.tar"
rm -rf "${BUNDLE_DIR}/license.jwt"
rm -rf "${BUNDLE_DIR}/plugins"
rm -rf "./grafana-enterprise.tar"

# Reset so the next prepare-bundle.sh will include JIRA by default. When you source this script
# (e.g. source ./clean-bundle.sh), this persists in your shell; when you run it, it only affects this process.
export PREPARE_JIRA_PLUGIN=1

echo "==> Done. Run ./prepare-bundle.sh to rebuild the bundle."
