#!/usr/bin/env bash
set -euo pipefail

# `make status-render` and the CI job status-e2e (plan 10.3b): start a throwaway
# Prometheus (remote-write receiver) and a throwaway Grafana 13.2.3 on a private
# Docker network, both bound to 127.0.0.1 only. Grafana provisions the repo
# dashboards read-only and has anonymous Viewer access: this is a throwaway with
# no data worth protecting and no password. Run test_render.py, which publishes
# the fixture runs and checks every panel query through Grafana. Always remove
# both containers and the network. No AWS.
#
# PYTEST overrides the test command (CI uses plain `python -m pytest`).
# RENDER_CMD runs a command instead of the tests (screenshot.py, local only).
# PROM_PORT and GRAFANA_PORT override the loopback ports (not 9099, not 3000).

# Pinned: tag and the index digest. Prometheus is the image of observability/status/e2e.sh.
PROM_IMAGE="prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e"
GRAFANA_IMAGE="grafana/grafana:13.2.3@sha256:b28bae15e219c998fb0e0424ed724930cc61b1f61fb404d47c862f9a23f9e572"
NET="cb-render-net"
PROM="cb-render-prom"   # the name the test datasource URL uses
GRAF="cb-render-graf"
PROM_PORT="${PROM_PORT:-9098}"
GRAFANA_PORT="${GRAFANA_PORT:-3098}"
PYTEST="${PYTEST:-uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest}"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../.."
ROOT="$PWD"
PROV="$ROOT/observability/grafana/render_check/provisioning"

cleanup() {
  docker rm -f "$GRAF" "$PROM" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
cleanup
trap cleanup EXIT

docker network create "$NET" >/dev/null

docker run --rm -d --name "$PROM" --network "$NET" -p "127.0.0.1:${PROM_PORT}:9090" "$PROM_IMAGE" \
  --config.file=/etc/prometheus/prometheus.yml --web.enable-remote-write-receiver >/dev/null

docker run --rm -d --name "$GRAF" --network "$NET" -p "127.0.0.1:${GRAFANA_PORT}:3000" \
  -e GF_AUTH_ANONYMOUS_ENABLED=true \
  -e GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
  -e GF_AUTH_DISABLE_LOGIN_FORM=true \
  -e GF_PLUGINS_PREINSTALL_DISABLED=true \
  -v "$PROV/datasources:/etc/grafana/provisioning/datasources:ro" \
  -v "$PROV/dashboards:/etc/grafana/provisioning/dashboards:ro" \
  -v "$ROOT/observability/grafana/dashboards:/var/lib/grafana/dashboards/cerberus:ro" \
  "$GRAFANA_IMAGE" >/dev/null

wait_for() { # URL NAME
  for _ in $(seq 120); do
    curl -sf "$1" >/dev/null && return 0
    sleep 1
  done
  echo "$2 did not become ready" >&2
  docker logs "$3" >&2 || true
  return 1
}
wait_for "http://127.0.0.1:${PROM_PORT}/-/ready" Prometheus "$PROM"
wait_for "http://127.0.0.1:${GRAFANA_PORT}/api/health" Grafana "$GRAF"

# Grafana loads provisioned dashboards a moment after /api/health is ok.
for _ in $(seq 60); do
  curl -sf "http://127.0.0.1:${GRAFANA_PORT}/api/dashboards/uid/cerberus-pipeline-status" >/dev/null && break
  sleep 1
done

export CERBERUS_PROM_URL="http://127.0.0.1:${PROM_PORT}"
export CERBERUS_GRAFANA_URL="http://127.0.0.1:${GRAFANA_PORT}"
if [ -n "${RENDER_CMD:-}" ]; then
  # shellcheck disable=SC2086  # RENDER_CMD is a command line, split on purpose
  $RENDER_CMD
else
  # shellcheck disable=SC2086  # PYTEST is a command line, split on purpose
  $PYTEST -q observability/grafana/render_check/test_render.py
fi
