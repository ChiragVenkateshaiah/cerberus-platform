#!/usr/bin/env bash
set -euo pipefail

# `make alerts-test` and the CI job alert-rules (plan 10.4a): promtool checks and
# tests the rules, amtool checks the Alertmanager template rendered with a dummy
# ARN. Both run in throwaway containers with --network none and a read-only mount.
# No AWS, no secrets.
#
# PYTHON overrides the command that renders the template (CI uses plain `python`).

# Pinned by index digest. Prometheus v3.15.0 is the image `make status-e2e` uses.
PROM_IMAGE="prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e"
AM_IMAGE="prom/alertmanager:v0.35.0@sha256:e638797febd034838eca8b98cdbd46f951e9bf7f178777aa8669167406a9946c"
PYTHON="${PYTHON:-uv run --no-project --python 3.12 --with PyYAML==6.0.3 python}"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.."

promtool() {
  docker run --rm --network none --entrypoint promtool \
    -v "$PWD/observability/alerts:/alerts:ro" "$PROM_IMAGE" "$@"
}

promtool check rules /alerts/status.rules.yaml
promtool test rules /alerts/status.rules.test.yaml

out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
chmod 755 "$out"  # mktemp makes it 700; the container user is not the owner
# shellcheck disable=SC2086  # PYTHON is a command line, split on purpose
$PYTHON observability/alerts/render_alertmanager.py "$out"
# The rendered file names its template by this same path, so mount it there.
docker run --rm --network none --entrypoint amtool \
  -v "$out:$out:ro" "$AM_IMAGE" check-config "$out/alertmanager.yml"
