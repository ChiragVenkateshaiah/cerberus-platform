#!/usr/bin/env bash
set -euo pipefail

# `make status-e2e` and the CI job status-e2e (plan 10.2, PR C): start a
# throwaway Prometheus with the remote-write receiver, bound to 127.0.0.1 only,
# wait until it is ready, run observability/status/test_e2e.py, and always
# remove the container. No AWS.
#
# PYTEST overrides the test command (CI uses plain `python -m pytest`).

# Pinned: tag and the index digest of prom/prometheus v3.15.0.
IMAGE="prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e"
NAME="cerberus-status-e2e"
PORT="9099"
PYTEST="${PYTEST:-uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest}"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.."

docker rm -f "$NAME" >/dev/null 2>&1 || true
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

docker run --rm -d --name "$NAME" -p "127.0.0.1:${PORT}:9090" "$IMAGE" \
  --config.file=/etc/prometheus/prometheus.yml --web.enable-remote-write-receiver >/dev/null

for _ in $(seq 60); do
  curl -sf "http://127.0.0.1:${PORT}/-/ready" >/dev/null && break
  sleep 1
done
curl -sf "http://127.0.0.1:${PORT}/-/ready" >/dev/null || {
  echo "Prometheus did not become ready" >&2
  docker logs "$NAME" >&2 || true
  exit 1
}

# shellcheck disable=SC2086  # PYTEST is a command line, split on purpose
CERBERUS_PROM_URL="http://127.0.0.1:${PORT}" $PYTEST -q observability/status/test_e2e.py
