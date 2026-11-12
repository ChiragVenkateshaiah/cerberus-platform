#!/usr/bin/env bash
set -euo pipefail

# Cerberus step 10 -- one command for a live Grafana session: preflight ->
# apply -> countdown -> destroy -> check (ADR 0024; plan
# docs/plans/2026-11-12-console-session.md sections 5 and 6 PR E).
#
#   orchestration/console_session.sh [--yes] [--minutes N]
#   orchestration/console_session.sh --destroy
#
#   --minutes N  session length, 1 to 120 (default 90). Terraform's own
#                validation uses the same bounds.
#   --yes        skip the one y/N confirmation before the apply.
#   --destroy    no session: destroy dev-console and run the check. For a
#                session whose trap died (laptop sleep, crash). `make
#                console-destroy` calls this.
#
# The apply runs with -auto-approve after the y/N: the plan is shown first and
# the preflight proved the state empty, so nothing else can change.
# The destroy runs from an EXIT trap, so it also runs after a failed apply or
# Ctrl-C (which ends the session early). A failed destroy prints what to run
# next and exits non-zero. The destroy runs under setsid so Ctrl-C cannot reach
# terraform; press it once only while the apply runs. Never assume the session is gone without the final
# console_check.sh.
#
# The session URL goes to this terminal only. Nothing here writes it, or any
# secret, to a file. Claude Code's auto mode blocks `terraform apply`: run
# this from your own terminal.

REGION="us-east-1"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONSOLE_DIR="$REPO/terraform/envs/dev-console"
STANDING_DIR="$REPO/terraform/envs/dev-standing"
ARTIFACTS="$REPO/observability/grafana/console/artifacts.json"
TF="${TF_BIN:-terraform}"
# Hourly list prices from the plan (section 8): t4g.small, NAT, its IPv4, gp3.
HOURLY="0.068"
ENI_WAIT_SECONDS="${ENI_WAIT_SECONDS:-1800}"

YES=false DESTROY_ONLY=false MINUTES=90
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES=true ;;
    --destroy) DESTROY_ONLY=true ;;
    --minutes) MINUTES="${2:-}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

aws_() { aws --region "$REGION" "$@"; }
log() { echo "[$(date -u +%FT%TZ)] $*"; }
tf() { "$TF" -chdir="$CONSOLE_DIR" "$@"; }
# Terraform re-enables SIGINT for itself (Go signal handling), so `trap ''` in
# this shell does not protect a destroy. setsid -w runs it in its own session,
# where the terminal's Ctrl-C never reaches it.
tfq() { setsid -w "$TF" -chdir="$CONSOLE_DIR" "$@"; }
# Hide anything that looks like an account ID in text we echo.
mask() { sed -E 's/[0-9]{12}/<account>/g'; }

SUBNET=""
BUCKET=""
STARTED=""

# Reads the standing outputs this script needs. Fails if any is missing.
read_standing() {
  local outputs
  outputs="$("$TF" -chdir="$STANDING_DIR" output -json 2>/dev/null)" || return 1
  BUCKET="$(jq -r '.console_site_bucket_name.value // empty' <<<"$outputs")"
  SUBNET="$(jq -r '.console_subnet_id.value // empty' <<<"$outputs")"
  [[ -n "$BUCKET" && -n "$SUBNET" ]]
}

preflight() {
  log "preflight"
  command -v jq >/dev/null || { log "  STOP: jq is not installed"; return 1; }

  if ! [[ "$MINUTES" =~ ^[0-9]+$ ]] || ((10#$MINUTES < 1 || 10#$MINUTES > 120)); then
    log "  STOP: --minutes must be a whole number from 1 to 120 (got: $MINUTES)"
    return 1
  fi
  MINUTES=$((10#$MINUTES))
  log "  minutes: $MINUTES"

  local who
  who="$(aws_ sts get-caller-identity --query Arn --output text)" || {
    log "  STOP: no AWS identity (credentials? AWS_PROFILE=$AWS_PROFILE)"
    return 1
  }
  log "  identity: $(mask <<<"$who")"

  if ! read_standing; then
    log "  STOP: can't read the dev-standing outputs (run: make standing-init)"
    return 1
  fi
  log "  dev-standing outputs: readable"

  # The check covers instances, distributions, VPC origins, the Cognito
  # client, IAM, the SG, the route table, live.json, session artifacts and
  # the dev-console state.
  log "  account check (console_check.sh):"
  if ! "$REPO/orchestration/console_check.sh" | sed 's/^/    /'; then
    log "  STOP: the account is not clean -- see above. Do not start a session."
    log "  If dev_console_state or a session count is not 0 after an interrupted session, run: make console-destroy"
    return 1
  fi

  # Both pinned artifacts must be staged with the pinned sha256 in metadata
  # (make console-artifacts); user-data checks the hash again at boot.
  local key sha have want checked=0
  while IFS=$'\t' read -r key sha; do
    have="$(aws_ s3api head-object --bucket "$BUCKET" --key "$key" \
      --query 'Metadata.sha256' --output text 2>/dev/null)" || have=""
    if [[ "$have" != "$sha" ]]; then
      log "  STOP: $key is missing or its sha256 differs from artifacts.json -- run: make console-artifacts"
      return 1
    fi
    log "  artifact staged: ${key##*/}"
    checked=$((checked + 1))
  done < <(jq -r '.artifacts[] | [.key, .sha256] | @tsv' "$ARTIFACTS")
  want="$(jq '.artifacts | length' "$ARTIFACTS")" || want=""
  if [[ -z "$want" || "$want" == "0" || "$checked" != "$want" ]]; then
    log "  STOP: checked $checked artifact(s), artifacts.json lists ${want:-?}"
    return 1
  fi
}

# Waits for the console subnet's network interfaces (the VPC origin's) to go.
# They block the subnet and the service SG, and clear about a minute after
# the origin is deleted (spike F6).
wait_enis() {
  [[ -n "$SUBNET" ]] || { log "no subnet ID known; skipping the ENI wait"; return 0; }
  local deadline=$((SECONDS + ENI_WAIT_SECONDS)) n
  while :; do
    n="$(aws_ ec2 describe-network-interfaces --filters "Name=subnet-id,Values=$SUBNET" \
      --query 'length(NetworkInterfaces)' --output text 2>/dev/null)" || n="?"
    if [[ "$n" == "0" ]]; then
      log "console subnet network interfaces: 0"
      return 0
    fi
    if ((SECONDS > deadline)); then
      log "console subnet network interfaces still $n after $((ENI_WAIT_SECONDS / 60)) minutes"
      return 1
    fi
    sleep 15
  done
}

# Destroy, wait, check. Returns 0 only when console_check.sh is clean.
destroy_and_check() {
  local rc=0
  log "destroying dev-console -- let it finish; Ctrl-C is ignored from here"
  if ! setsid -w "$REPO/orchestration/console_init.sh" -no-color >/dev/null; then
    log "terraform init failed (credentials? backend?); the destroy could not run"
    rc=1
  else
    # -lock-timeout: an interrupted apply can hold the state lock for a moment.
    if ! tfq destroy -auto-approve -input=false -lock-timeout=120s; then
      # Once the VPC origin is gone the service-SG data source no longer
      # matches, so the refresh fails; retry without it (PR D review).
      log "destroy failed once, retrying with -refresh=false"
      tfq destroy -auto-approve -input=false -lock-timeout=120s -refresh=false || rc=1
    fi
  fi
  [[ -n "$SUBNET" ]] || read_standing || true
  # Waiting for ENIs only makes sense once the destroy has succeeded.
  ((rc == 0)) && { wait_enis || rc=1; }
  log "final account check (console_check.sh):"
  setsid -w "$REPO/orchestration/console_check.sh" | sed 's/^/    /' || rc=1
  if ((rc != 0)); then
    log "SESSION NOT CLEANLY ENDED. Something may still be running and billing"
    log "(the NAT gateway and its IP cost about \$1.20/day)."
    log "Run: make console-destroy && make console-check"
  fi
  return "$rc"
}

teardown() {
  local status=$?
  # Nothing may stop the destroy half-way: not a failing check (set +e), not
  # a second Ctrl-C, and not a dead pipe (PIPE) -- see exercise.sh.
  trap - EXIT
  trap '' INT TERM PIPE HUP
  set +e
  destroy_and_check || status=1
  if [[ -n "$STARTED" ]]; then
    log "session ran for $((SECONDS - STARTED))s in total"
  fi
  exit "$status"
}

if $DESTROY_ONLY; then
  trap '' INT TERM PIPE HUP
  set +e
  read_standing || log "dev-standing outputs unreadable; the ENI wait is skipped"
  destroy_and_check
  exit $?
fi

preflight

# Init and plan before the question, so the prompt comes after you have seen
# "N to add". The plan reads AWS but changes nothing.
log "initialising dev-console"
"$REPO/orchestration/console_init.sh" -no-color >/dev/null || { log "STOP: terraform init failed (credentials? backend?)"; exit 1; }
log "plan (nothing is changed yet):"
tf plan -input=false -no-color -var "minutes=$MINUTES"

cost="$(awk -v m="$MINUTES" -v h="$HOURLY" 'BEGIN { printf "%.2f", (m + 30) / 60 * h }')"
if ! $YES; then
  read -r -p "Apply dev-console: a $MINUTES-minute session, about \$$HOURLY/hour, about \$$cost in total (wake and destroy included)? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { log "cancelled"; exit 0; }
fi

# Set before the apply, so a failed apply or Ctrl-C still destroys.
trap teardown EXIT
trap 'exit 130' INT TERM
trap 'exit 129' HUP

STARTED=$SECONDS
log "Press Ctrl-C once only: a second one stops terraform without saving state."
log "applying dev-console -- the wake takes about 15 minutes"
tf apply -auto-approve -input=false -no-color -var "minutes=$MINUTES"

url="$(tf output -raw session_url)"
ends="$(tf output -raw ends)"
ends_epoch="$(date -u -d "$ends" +%s)"
log "session is live (this URL is for your terminal only; it is not saved):"
echo "  $url"
log "ends at $ends. Ctrl-C ends it early."
while :; do
  left=$((ends_epoch - $(date -u +%s)))
  ((left > 0)) || break
  printf '\r  time left: %02d:%02d ' $((left / 60)) $((left % 60))
  sleep 10
done
printf '\n'
log "time is up"
