#!/usr/bin/env bash
set -euo pipefail

# `make grafana-token` (ADR 0022 amendment): make the Grafana service account
# `cerberus-exercise` (Editor) if it is missing, give it one fresh token with a
# 30-day expiry, and store the token in observability/grafana/.env as
# GRAFANA_ANNOTATE_TOKEN. orchestration/exercise.sh posts run annotations with
# it. Safe to run again: the old tokens of the account are deleted first, and
# the key in .env is replaced.
#
# Needs the local Grafana up (make grafana-up). Uses the admin password from
# .env (read with grep, never sourced, never printed) over 127.0.0.1 only.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR/.env"
URL="http://127.0.0.1:3000"
SA_NAME="cerberus-exercise"
TTL_SECONDS=2592000 # 30 days

[[ -f "$ENV_FILE" ]] || { echo "create $ENV_FILE first (see .env.example)" >&2; exit 1; }
password="$(grep -m1 '^GF_SECURITY_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
[[ -n "$password" ]] || { echo "GF_SECURITY_ADMIN_PASSWORD is not set in .env" >&2; exit 1; }

# The password goes in through a config file descriptor, not on the command line.
api() { # METHOD PATH [JSON]
  local -a data=()
  if [[ -n "${3:-}" ]]; then data=(-H 'Content-Type: application/json' -d "$3"); fi
  curl -sS --fail-with-body --max-time 10 -X "$1" \
    --config <(printf 'user = "admin:%s"\n' "$password") \
    "${data[@]}" "$URL$2"
}

curl -sS --max-time 3 -o /dev/null "$URL/api/health" ||
  { echo "Grafana is not answering on $URL -- run make grafana-up" >&2; exit 1; }

id="$(api GET "/api/serviceaccounts/search?query=$SA_NAME" |
  jq -r --arg n "$SA_NAME" '[.serviceAccounts[] | select(.name == $n)][0].id // empty')"
if [[ -z "$id" ]]; then
  id="$(api POST /api/serviceaccounts "$(jq -n --arg n "$SA_NAME" '{name: $n, role: "Editor"}')" | jq -r .id)"
  echo "created service account $SA_NAME (Editor), id $id"
else
  echo "service account $SA_NAME exists, id $id"
fi

for old in $(api GET "/api/serviceaccounts/$id/tokens" | jq -r '.[].id'); do
  api DELETE "/api/serviceaccounts/$id/tokens/$old" >/dev/null
done
token="$(api POST "/api/serviceaccounts/$id/tokens" \
  "$(jq -n --arg n "exercise-$(date -u +%Y%m%dT%H%M%SZ)" --argjson t "$TTL_SECONDS" \
    '{name: $n, secondsToLive: $t}')" | jq -r .key)"
[[ -n "$token" && "$token" != null ]] || { echo "Grafana returned no token" >&2; exit 1; }

# Replace the key in .env, keeping every other line. Owner-only at every step.
umask 077
tmp="$(mktemp "$DIR/.env.XXXXXX")"
{ grep -v '^GRAFANA_ANNOTATE_TOKEN=' "$ENV_FILE" || true; printf 'GRAFANA_ANNOTATE_TOKEN=%s\n' "$token"; } >"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"
echo "wrote GRAFANA_ANNOTATE_TOKEN to observability/grafana/.env (mode 600, expires in 30 days)"
