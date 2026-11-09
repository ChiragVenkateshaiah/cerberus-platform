#!/usr/bin/env bash
set -euo pipefail

# `make grafana-up` (ADR 0024): start the local Grafana on short-lived,
# read-only credentials. The script looks up the AMP query endpoint, assumes
# the role cerberus-grafana-read, and starts Compose with the session keys in
# the environment of that one process. The keys are never written to a file
# and never printed. Run it again to renew them: a changed environment makes
# Compose recreate the container, and the data volume stays.
#
# GRAFANA_SESSION_HOURS sets the session length (default 12, maximum 12).
# AMP_URL overrides the endpoint lookup. Needs the cerberus-admin profile
# (AWS_PROFILE overrides it) and observability/grafana/.env.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR/.env"
REGION="us-east-1"
ROLE_NAME="cerberus-grafana-read"
HOURS="${GRAFANA_SESSION_HOURS:-12}"

[[ -f "$ENV_FILE" ]] || { echo "create $ENV_FILE first (see .env.example)" >&2; exit 1; }
if ! [[ "$HOURS" =~ ^[0-9]+$ ]] || ((HOURS < 1 || HOURS > 12)); then
  echo "GRAFANA_SESSION_HOURS must be a whole number from 1 to 12 (got '$HOURS')" >&2
  exit 1
fi

export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"

amp_url="${AMP_URL:-}"
if [[ -z "$amp_url" ]]; then
  id="$(aws amp list-workspaces --query "workspaces[?alias=='cerberus-platform'].workspaceId | [0]" --output text)"
  case "$id" in
    ws-*) ;;
    *) echo "AMP workspace cerberus-platform not found (got '$id')" >&2; exit 1 ;;
  esac
  amp_url="https://aps-workspaces.$REGION.amazonaws.com/workspaces/$id/"
fi

role_arn="$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)"
session="grafana-$(date -u +%Y%m%dT%H%M%SZ)"
creds="$(aws sts assume-role --role-arn "$role_arn" --role-session-name "$session" \
  --duration-seconds $((HOURS * 3600)) --query Credentials --output json)"

key_id="$(jq -r .AccessKeyId <<<"$creds")"
secret="$(jq -r .SecretAccessKey <<<"$creds")"
token="$(jq -r .SessionToken <<<"$creds")"
expiry="$(jq -r .Expiration <<<"$creds")"
for v in "$key_id" "$secret" "$token" "$expiry"; do
  [[ -n "$v" && "$v" != null ]] || { echo "assume-role returned incomplete credentials" >&2; exit 1; }
done

echo "role:    $ROLE_NAME"
echo "session: $session"
echo "expires: $expiry"
echo "renew:   run make grafana-up again"

# The session keys replace the profile for this process only, so Compose
# passes the keys, not the profile, to the container.
unset AWS_PROFILE
AMP_URL="$amp_url" GRAFANA_UID="$(id -u)" GRAFANA_GID="$(id -g)" \
  AWS_ACCESS_KEY_ID="$key_id" AWS_SECRET_ACCESS_KEY="$secret" AWS_SESSION_TOKEN="$token" \
  docker compose -f "$DIR/compose.yaml" --env-file "$ENV_FILE" up -d
