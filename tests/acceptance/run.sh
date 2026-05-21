#!/usr/bin/env bash
# Acceptance test runner.
# Builds a fresh container, runs the full pipeline against fixture data,
# then runs pytest against the resulting AFTER xlsx.
# Exit code: 0 = pass, non-zero = fail.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURES="$SCRIPT_DIR/fixtures"

# ── API key ──────────────────────────────────────────────────────────────────
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    CONFIG_YAML="$REPO_ROOT/config.yaml"
    if [[ -f "$CONFIG_YAML" ]]; then
        ANTHROPIC_API_KEY=$(grep '^anthropic_api_key:' "$CONFIG_YAML" | sed 's/^anthropic_api_key:[[:space:]]*//' | tr -d '"'"'")
    fi
fi
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ERROR: ANTHROPIC_API_KEY not set and could not be read from config.yaml." >&2
    exit 1
fi

# ── Fresh container ───────────────────────────────────────────────────────────
echo "==> Building acceptance test container..."
docker build -t fibutool-acceptance "$REPO_ROOT" --quiet

# ── Temp workdir (cleaned up on exit) ────────────────────────────────────────
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# ── Populate workdir ──────────────────────────────────────────────────────────
cp -r "$FIXTURES/invoices"  "$WORKDIR/invoice_sources"
cp -r "$FIXTURES/payments"  "$WORKDIR/payments"
cp    "$FIXTURES/before.xlsx" "$WORKDIR/before.xlsx"
mkdir -p "$WORKDIR/permanent_merged"
mkdir -p "$WORKDIR/merged"
mkdir -p "$WORKDIR/payments-ordered"
mkdir -p "$WORKDIR/invoices"

# Substitute API key into config template
sed "s|\${ANTHROPIC_API_KEY}|${ANTHROPIC_API_KEY}|g" \
    "$FIXTURES/config.yaml.template" > "$WORKDIR/config.yaml"

# ── Run full pipeline in fresh container ──────────────────────────────────────
echo "==> Running pipeline..."
# On Windows/Git Bash convert the host path to Windows format for the -v mount;
# MSYS_NO_PATHCONV=1 stops Git Bash from mangling /workdir container arguments.
WORKDIR_DOCKER="$WORKDIR"
if [[ "$(uname -s)" == MINGW* ]] || [[ "$(uname -s)" == MSYS* ]]; then
    WORKDIR_DOCKER=$(cd "$WORKDIR" && pwd -W | tr '\\' '/')
fi
MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$WORKDIR_DOCKER:/workdir" \
    fibutool-acceptance \
    fibutool \
        --workdir /workdir \
        --config  /workdir/config.yaml \
        --non-interactive

# ── Run acceptance tests against AFTER xlsx ───────────────────────────────────
# journal_updater writes back to before.xlsx in place, making it the AFTER xlsx.
echo "==> Running acceptance tests..."
python -m pytest "$SCRIPT_DIR" -v --after-xlsx "$WORKDIR/before.xlsx"
