#!/usr/bin/env bash
# Readiness probe: poll https://<distribution>/api/health until it answers
# 200, at most MAX_SECONDS. Grafana opens port 3000 only after the annotations
# are loaded and basic auth is off, so a 200 through CloudFront means the
# session is really ready. Run by terraform_data.probe in session.tf, which
# sets URL and MAX_SECONDS. It runs on the owner's machine and needs curl.
# No AWS calls, no credentials, nothing printed except status codes.
set -euo pipefail

: "${URL:?URL is not set}"
: "${MAX_SECONDS:=1200}"

deadline=$((SECONDS + MAX_SECONDS))
while true; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL" || true)"
  if [ "$code" = "200" ]; then
    echo "ready: $code after ${SECONDS}s"
    exit 0
  fi
  echo "waiting: HTTP ${code:-none} at ${SECONDS}s"
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "not ready within ${MAX_SECONDS}s" >&2
    exit 1
  fi
  sleep 15
done
