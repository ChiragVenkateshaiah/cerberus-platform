#!/usr/bin/env bash
set -uo pipefail

# Phase 17.4 -- destroy the launch edge and check (ADR 0030 Decision 2). It
# needs no shell state: run it from any terminal, any time, after a crash, or
# by the deadline that a PREWARM or HOLD session printed.
#
#   orchestration/launch_destroy.sh            stage 1 (leftover parameter), stage 2, check
#   orchestration/launch_destroy.sh --stage2   stage 2 and check only (launch_session.sh calls it)
#
# Stage 1 here terminates any launch instance directly (tag Stack=dev-launch; none is
# fine) and deletes a leftover cookie parameter. Stage 2 is `terraform
# destroy` with a -refresh=false retry; it removes any instance, the key group,
# the Function, the KVS and both buckets (force_destroy). Then launch_check.sh
# must report 0 for everything. A failure at any step exits non-zero and says so
# loudly. Ctrl-C is ignored while terraform runs. Never assume the edge is gone
# without the final check. Claude Code's auto mode blocks `terraform destroy`:
# run this from your own terminal.

REGION="us-east-1"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$REPO/terraform/envs/dev-launch"
TF="${TF_BIN:-terraform}"
COOKIE_PARAM="/cerberus/launch/session-cookies"

STAGE2_ONLY=false
case "${1:-}" in
  "") ;;
  --stage2) STAGE2_ONLY=true ;;
  *) echo "unknown argument: ${1:-}" >&2; exit 2 ;;
esac

log() { echo "[$(date -u +%FT%TZ)] $*"; }
loud() { printf '\a'; log "!!! $*"; }
aws_() { aws --region "$REGION" "$@"; }
tfq() { setsid -w "$TF" -chdir="$ENV_DIR" "$@"; }

# Same scope as terminate_instances in launch_session.sh: instances tagged Stack=dev-launch.
terminate_instances() {
  local ids
  ids="$(aws_ ec2 describe-instances --filters Name=tag:Stack,Values=dev-launch \
    Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].InstanceId' --output text)" || return 1
  [[ -z "$ids" || "$ids" == "None" ]] && return 0
  # shellcheck disable=SC2086  # a word per instance ID
  aws_ ec2 terminate-instances --instance-ids $ids >/dev/null
}

# A state-lock error leaves the lock behind: print the command, never run it.
lock_hint() {
  grep -q 'Error acquiring the state lock' "$1" 2>/dev/null || return 0
  loud "TERRAFORM STATE LOCK HELD. When no apply runs, free it by hand: terraform -chdir=terraform/envs/dev-launch force-unlock <LOCK_ID> (the ID is in the error above)"
}

# Nothing may stop the destroy half-way (see console_session.sh).
trap '' INT TERM PIPE HUP
RC=0

if ! $STAGE2_ONLY; then
  log "STAGE 1: terminate any launch instance, delete a leftover cookie parameter"
  terminate_instances || { loud "DIRECT TERMINATION FAILED: check EC2 by hand"; RC=1; }
  if out="$(aws_ ssm delete-parameter --name "$COOKIE_PARAM" 2>&1)"; then
    log "cookie parameter deleted"
  elif grep -q 'ParameterNotFound' <<<"$out"; then
    log "cookie parameter: none present"
  else
    loud "COOKIE PARAMETER DELETE FAILED: delete $COOKIE_PARAM by hand"
    RC=1
  fi
fi

log "STAGE 2: terraform destroy of dev-launch (allow 30 minutes; the delete duration is unverified)"
if ! setsid -w "$REPO/orchestration/launch_init.sh" -no-color >/dev/null; then
  loud "terraform init failed (credentials? backend?); the destroy could not run"
  RC=1
else
  # -lock-timeout: an interrupted apply can hold the state lock for a moment.
  dfile="$(mktemp)" || dfile=/dev/null
  tfq destroy -auto-approve -input=false -no-color -lock-timeout=120s 2>&1 | tee "$dfile"
  if [[ "${PIPESTATUS[0]}" != "0" ]]; then
    lock_hint "$dfile"
    log "destroy failed once, retrying with -refresh=false"
    tfq destroy -auto-approve -input=false -no-color -lock-timeout=120s -refresh=false 2>&1 | tee "$dfile"
    if [[ "${PIPESTATUS[0]}" != "0" ]]; then
      lock_hint "$dfile"
      loud "DESTROY FAILED TWICE"
      RC=1
    fi
  fi
  [[ "$dfile" == /dev/null ]] || rm -f "$dfile"
fi

log "final account check (launch_check.sh):"
setsid -w "$REPO/orchestration/launch_check.sh" | sed 's/^/    /'
# The pipe hides the check's status; ask again through PIPESTATUS.
[[ "${PIPESTATUS[0]}" == "0" ]] || RC=1

if ((RC != 0)); then
  loud "LAUNCH EDGE NOT CLEANLY DESTROYED. Something may still be running and billing."
  loud "Run: make launch-destroy && make launch-check"
fi
exit "$RC"
