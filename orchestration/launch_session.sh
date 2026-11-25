#!/usr/bin/env bash
# shellcheck disable=SC2329  # the functions run from the EXIT trap, which shellcheck cannot follow
set -uo pipefail

# Phase 17.4 -- one command for a launch session: preflight -> apply the edge
# -> sign cookies -> run the load generator -> stage 1 -> stage 2 -> check
# (ADR 0030 Decisions 2, 4, 6, 12; plan docs/plans/2026-11-25-launch-session.md).
# Copied in shape from console_session.sh.
#
#   SCENARIO=bcd MINUTES=90 orchestration/launch_session.sh [--yes] [--dry-run]
#   SCENARIO=a PREWARM=1 orchestration/launch_session.sh        edge only, no key, no instance
#   SCENARIO=bcd HOLD=1  orchestration/launch_session.sh        keep the edge up to 24 h
#
#   env SCENARIO  a, b, c, d, bcd or p (default a)
#   env MINUTES   session length, also the cookie lifetime (cookies expire at mint +
#                 MINUTES, ADR 0030 Decision 4) and the deadline of the run, which is
#                 measured from the mint. The minimum, the default (= the minimum) and the
#                 maximum are derived from the scenario files by launch/scenario.py
#                 (runs, ramp, licence rate, bytes over the link: unverified estimates, Run A
#                 measures them). A smaller MINUTES is refused before any call.
#   env RELEASE_OFFSET_MINUTES  T0 (release_at) in minutes after the instance apply starts.
#                 The default is derived: after the runs that come before the first run that
#                 needs the release (B ends, plus a margin). A smaller value is refused.
#   env PREWARM   1: build the edge with the default (discarded) key and no instance
#   env HOLD      1: stop after stage 1; the owner runs `make launch-destroy` by the deadline
#   --yes         skip the y/N question
#   --dry-run     print the commands, the bytes and the ledger estimate. No aws,
#                 terraform, openssl, k6 or curl call is made.
#
# The apply order keeps ADR 0030 Decision 4: apply the public PEM (default release_at, no
# instance) -> wait for Deployed -> mint the cookies -> put the parameter -> apply the
# instance with an explicit release_at. T0 is fixed after Deployed, so the wait for the
# distribution does not eat the schedule. Both applies pass the same PEM.
#
# Stage 1 (private key, instance, cookie parameter) always runs from the EXIT
# trap, after a failed apply, Ctrl-C or SIGTERM. Its steps are independent: each
# runs even if another failed, and any failure ends the script non-zero with a
# loud message. The instance is always terminated directly (tag Stack=dev-launch),
# then the stage 1 apply (default PEM, so no valid signer remains) runs, with one
# retry. If that apply fails twice, or a byte-budget stop ended the run, stage 2
# runs even with HOLD. Stage 2 (orchestration/launch_destroy.sh --stage2) runs
# from the trap too, unless PREWARM or HOLD asks the owner to run it. A failed
# PREWARM apply runs both stages. A trap does not survive SIGKILL or power
# loss: the instance shuts itself down at MINUTES plus a margin.
#
# The private key lives only in a 0700 directory under $XDG_RUNTIME_DIR (tmpfs).
# Cookies are never printed: they go from a tmpfs file to SSM (file://) and to
# k6 (a cookie file). Never run this with `set -x`.
# Claude Code's auto mode blocks `terraform apply`: run this from your terminal.

REGION="us-east-1"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_DIR="$REPO/launch"
ENV_DIR="$REPO/terraform/envs/dev-launch"
TF="${TF_BIN:-terraform}"
K6="${K6_BIN:-k6}"
RUNS_DIR="${LAUNCH_RUNS_DIR:-$REPO/observability/launch/runs}"
POLL_SECONDS="${LAUNCH_POLL_SECONDS:-60}"
COLLECT_TIMEOUT="${LAUNCH_COLLECT_TIMEOUT:-300}"
COOKIE_PARAM="/cerberus/launch/session-cookies"
HOLD_HOURS=24

SCENARIO="${SCENARIO:-a}"
MINUTES="${MINUTES:-}"
PREWARM="${PREWARM:-0}"
HOLD="${HOLD:-0}"
YES=false DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES=true ;;
    --dry-run) DRY_RUN=true ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

log() { echo "[$(date -u +%FT%TZ)] $*"; }
die() { log "STOP: $*"; exit 1; }
loud() { printf '\a'; log "!!! $*"; }
mask() { sed -E 's/[0-9]{12}/<account>/g'; }
aws_() { aws --region "$REGION" "$@"; }
tf() { "$TF" -chdir="$ENV_DIR" "$@"; }
py() { python3 "$LAUNCH_DIR/$1" "${@:2}"; }
now_ms() { date -u +%s%3N; }
is_on() { [[ "$1" == "1" || "$1" == "true" ]]; }

PREWARM_ON=false HOLD_ON=false
is_on "$PREWARM" && PREWARM_ON=true
is_on "$HOLD" && HOLD_ON=true

# --- input checks (no AWS) ---------------------------------------------------
# The layer 4 poll: a whole number of seconds from 10 to 120 (a smaller one hammers
# CloudWatch, a larger one is blind). LAUNCH_ALLOW_FAST_POLL=1 is the tests' override.
if [[ "${LAUNCH_ALLOW_FAST_POLL:-0}" != "1" ]]; then
  [[ "$POLL_SECONDS" =~ ^[0-9]+$ ]] && ((10#$POLL_SECONDS >= 10 && 10#$POLL_SECONDS <= 120)) \
    || die "LAUNCH_POLL_SECONDS must be a whole number from 10 to 120 (got: $POLL_SECONDS)"
  POLL_SECONDS=$((10#$POLL_SECONDS))
fi
case "$SCENARIO" in a | b | c | d | bcd | p) ;; *) die "SCENARIO must be a, b, c, d, bcd or p (got: $SCENARIO)" ;; esac

# The timeline comes from the scenario files (launch/scenario.py): the seed list,
# T0 (release_at), the minimum MINUTES (also the default) and the maximum. All are
# planning estimates (unverified); Run A measures them.
RELEASE_OFFSET_MINUTES="${RELEASE_OFFSET_MINUTES:-}"
sched_args=(scenario.py schedule "$SCENARIO")
if [[ -n "$RELEASE_OFFSET_MINUTES" ]]; then
  [[ "$RELEASE_OFFSET_MINUTES" =~ ^[0-9]+$ ]] || die "RELEASE_OFFSET_MINUTES must be a whole number (got: $RELEASE_OFFSET_MINUTES)"
  RELEASE_OFFSET_MINUTES=$((10#$RELEASE_OFFSET_MINUTES))
  sched_args+=(--release-offset "$RELEASE_OFFSET_MINUTES")
fi
sched="$(py "${sched_args[@]}" 2>&1)" || die "the schedule could not be derived: $(tail -n 1 <<<"$sched")"
sget() { sed -n "s/^$1=//p" <<<"$sched"; }
RELEASE_OFFSET_MINUTES="$(sget release_offset_minutes)"
MIN_MINUTES="$(sget min_minutes)"
MAX_MINUTES="$(sget max_minutes)"
ORDER="$(sget order)"
SEED="$(sget seed_sets)"
RUN_FILES="$(sget run_files)"
[[ "$RELEASE_OFFSET_MINUTES" =~ ^[0-9]+$ && "$MIN_MINUTES" =~ ^[0-9]+$ && "$MAX_MINUTES" =~ ^[0-9]+$ && -n "$ORDER" && -n "$SEED" ]] \
  || die "the schedule output is not usable"
MINUTES="${MINUTES:-$MIN_MINUTES}"
if ! [[ "$MINUTES" =~ ^[0-9]+$ ]] || ((10#$MINUTES < 1 || 10#$MINUTES > MAX_MINUTES)); then
  die "MINUTES must be a whole number from 1 to $MAX_MINUTES (got: $MINUTES)"
fi
MINUTES=$((10#$MINUTES))
if ! $PREWARM_ON && ((MINUTES < MIN_MINUTES)); then
  die "MINUTES=$MINUTES is below the planned timeline of scenario $SCENARIO: $MIN_MINUTES minutes (release at +$RELEASE_OFFSET_MINUTES min, runs end at +$(sget end_minutes) min, from the instance apply, plus the prepare and slack minutes). The cookies would expire mid-run."
fi
RUN_ID="${LAUNCH_RUN_ID:-s$(date -u +%m%d%H%M%S)-$SCENARIO}"
[[ "$RUN_ID" =~ ^[a-z0-9-]{1,40}$ ]] || die "run id must match ^[a-z0-9-]{1,40}$"

# Planned GB and the instance budget come from the one source: plan_bytes.py.
# --offline: ledger only, no AWS call.
BUDGET=0 TOTAL_GB=0 PROBE_BYTES=0 EST_MINUTES=0 PLAN_RC=0 plan_out=""
if ! $PREWARM_ON; then
  plan_out="$(py plan_bytes.py "$SCENARIO" --offline 2>&1)" || PLAN_RC=$?
  BUDGET="$(sed -n 's/^budget_bytes=//p' <<<"$plan_out")"
  TOTAL_GB="$(sed -n 's/^total_gb=//p' <<<"$plan_out")"
  PROBE_BYTES="$(sed -n 's/^probe_bytes=//p' <<<"$plan_out")"
  EST_MINUTES=$MINUTES
fi

# Layer 4 limit: the instance budget plus the probe P bytes x 1.10 (exact bytes
# from plan_bytes.py). The probe uses the same distribution, so CloudWatch counts both.
layer4_limit() {
  python3 - "${BUDGET:-0}" "${PROBE_BYTES:-0}" <<'PY'
import sys
from decimal import Decimal as D
print(int(D(sys.argv[1]) + D(sys.argv[2]) * D("1.10")))
PY
}

# --- dry run: print and stop -------------------------------------------------
if $DRY_RUN; then
  ((PLAN_RC == 0)) || die "plan_bytes.py refused (exit $PLAN_RC): $(tail -n 1 <<<"$plan_out")"
  est="$(py ledger.py estimate --minutes "$EST_MINUTES" --gb "$TOTAL_GB")" || die "ledger estimate failed"
  log "DRY RUN: nothing is called. Run id $RUN_ID, scenario $SCENARIO, $MINUTES minutes."
  log "planned GB (probe included): $TOTAL_GB; instance budget_bytes: $BUDGET"
  log "timeline: release at +${RELEASE_OFFSET_MINUTES} min (from the instance apply); minimum MINUTES $MIN_MINUTES, maximum $MAX_MINUTES (cookies and the run deadline count from the mint)"
  log "runs: $RUN_FILES; seed sets: $SEED"
  log "layer 4 stop limit (budget + probe bytes x 1.10): $(layer4_limit) bytes"
  log "ledger estimate for this run: \$$est (guard and record run only for a live session)"
  if $PREWARM_ON; then
    log "would run: launch_init.sh; terraform apply -var create_load_gen=false (default key, sentinel release_at)"
  else
    log "would run: launch_init.sh; openssl genrsa/rsa in a tmpfs dir under \$XDG_RUNTIME_DIR"
    log "would run: terraform apply -var public_key_pem=<public> -var create_load_gen=false (default release_at)"
    log "would run: aws cloudfront wait distribution-deployed; sign cookies; aws ssm delete-parameter, put-parameter (SecureString)"
    log "would run: aws s3 cp scenarios; terraform apply -var public_key_pem=<public> -var release_at_epoch=<now+${RELEASE_OFFSET_MINUTES}m> -var create_load_gen=true -var budget_bytes=$BUDGET"
    log "would run: curl /license (expect 403 before T0)"
    log "would run: poll CloudWatch BytesDownloaded each ${POLL_SECONDS}s; stop at budget"
    log "would run: stage 1: terraform apply -var create_load_gen=false; ssm delete-parameter; shred the key"
  fi
  if $PREWARM_ON || $HOLD_ON; then
    log "would end after stage 1/apply with a ${HOLD_HOURS} h deadline; the owner runs: make launch-destroy"
  else
    log "would run: stage 2: launch_destroy.sh --stage2 (destroy, check)"
  fi
  exit 0
fi

# --- state -------------------------------------------------------------------
KEYDIR=""
RUN_DIR="$RUNS_DIR/$RUN_ID"
APPLY_PID=""
LIVE_STARTED=false BUDGET_STOP=false
DOMAIN="" DIST="" KEYID="" BUCKET=""
START_MS="" START_ISO="" RELEASE_AT="" RUN_START=$SECONDS
LEDGER_RECORDED=false
PROBE_PID="" MINT_SECONDS=$SECONDS UNREADABLE=0 LIMIT=0 CURL_REQUESTS=0
PUB_PEM=""
FAILED=0

# Runs terraform in the background in its own process group (set -m), so a
# terminal Ctrl-C cannot reach it a second time, and so a signal to this script
# runs the EXIT trap at once instead of after terraform. (A plain `&` in a
# script ignores SIGINT in the job.) teardown() forwards one INT and waits.
run_apply() {
  set -m
  "$TF" -chdir="$ENV_DIR" apply -auto-approve -input=false -no-color -lock-timeout=120s "$@" &
  APPLY_PID=$!
  set +m
  wait "$APPLY_PID"
  local rc=$?
  APPLY_PID=""
  return "$rc"
}

# Both live applies pass the same PEM and minutes; only the second one passes release_at.
live_vars() {
  LIVE_VARS=(-var "public_key_pem=$PUB_PEM" -var "minutes=$MINUTES")
}

# CloudFront URL-safe base64: + -> -, = -> _, / -> ~.
cf_b64() { base64 -w0 | tr '+=/' '-_~'; }

# --- preflight ---------------------------------------------------------------
preflight() {
  log "preflight"
  local tool
  for tool in jq python3 curl setsid shred base64 timeout; do
    command -v "$tool" >/dev/null || { log "  STOP: $tool is not installed"; return 1; }
  done
  if ! $PREWARM_ON; then
    command -v openssl >/dev/null || { log "  STOP: openssl is not installed"; return 1; }
    command -v "$K6" >/dev/null || { log "  STOP: k6 is not installed (the probe P runs from this machine)"; return 1; }
    # Fail closed: the private key must never reach a disk.
    if [[ -z "${XDG_RUNTIME_DIR:-}" || ! -d "$XDG_RUNTIME_DIR" ]]; then
      log "  STOP: XDG_RUNTIME_DIR is unset or not a directory; the key needs tmpfs"
      return 1
    fi
    if [[ "$(stat -f -c %T "$XDG_RUNTIME_DIR" 2>/dev/null)" != "tmpfs" ]]; then
      log "  STOP: XDG_RUNTIME_DIR is not tmpfs; the private key must not reach a disk"
      return 1
    fi
  fi
  local who
  who="$(aws_ sts get-caller-identity --query Arn --output text)" || {
    log "  STOP: no AWS identity (credentials? AWS_PROFILE=$AWS_PROFILE)"
    return 1
  }
  log "  identity: $(mask <<<"$who")"
  "$REPO/orchestration/launch_init.sh" -no-color >/dev/null || { log "  STOP: terraform init failed (credentials? backend?)"; return 1; }
  log "  terraform init: ok"

  local n
  n="$(aws_ ec2 describe-instances \
    --filters Name=tag:Stack,Values=dev-launch \
    Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down \
    --query 'length(Reservations[].Instances[])' --output text)" || n="?"
  if [[ "$n" != "0" ]]; then
    log "  STOP: $n launch instance(s) exist or could not be read. Run: make launch-destroy"
    return 1
  fi
  log "  no launch instance: ok"

  # Layer 1 of the byte control, then the $25 rule.
  if ! $PREWARM_ON; then
    local dist out
    dist="$(tf output -json 2>/dev/null | jq -r '.distribution_id.value // empty' 2>/dev/null)" || dist=""
    local pb=(plan_bytes.py "$SCENARIO")
    [[ -n "$dist" ]] && pb+=(--distribution-id "$dist")
    out="$(py "${pb[@]}")" || { log "  STOP: plan_bytes refused: $(tail -n 1 <<<"$out")"; return 1; }
    log "  bytes: $(tr '\n' ' ' <<<"$out")"
    # On a first live run the distribution does not exist yet, so plan_bytes
    # cannot read CloudWatch: month-to-date is then the ledger only.
    [[ -n "$dist" ]] || log "  note: no distribution yet, so month-to-date (mtd_gb) comes from the ledger only, not from CloudWatch"
    BUDGET="$(sed -n 's/^budget_bytes=//p' <<<"$out")"
    TOTAL_GB="$(sed -n 's/^total_gb=//p' <<<"$out")"
    PROBE_BYTES="$(sed -n 's/^probe_bytes=//p' <<<"$out")"
    MTD_GB="$(sed -n 's/^mtd_gb=//p' <<<"$out")"
  fi
  EST="$(py ledger.py estimate --minutes "$EST_MINUTES" --gb "$TOTAL_GB" --mtd-gb "${MTD_GB:-0}")" || { log "  STOP: ledger estimate failed"; return 1; }
  if ! py ledger.py guard --next-usd "$EST" 2>&1 | sed 's/^/  /'; then
    log "  STOP: the cost rule refused this run (or could not be checked)"
    return 1
  fi
  log "  ledger estimate for this run: \$$EST"
}

# --- stage 1 -----------------------------------------------------------------
remove_key() {
  [[ -n "$KEYDIR" ]] || return 0
  local rc=0
  if [[ -d "$KEYDIR" ]]; then
    find "$KEYDIR" -type f -exec shred -u {} + 2>/dev/null || { loud "SHRED FAILED: the files are removed without it"; rc=1; }
    rm -rf "$KEYDIR"
  fi
  if [[ -e "$KEYDIR" ]]; then
    loud "KEY DIRECTORY STILL EXISTS: remove it by hand"
    return 1
  fi
  log "private key directory removed"
  return "$rc"
}

delete_parameter() {
  local out
  if out="$(aws_ ssm delete-parameter --name "$COOKIE_PARAM" 2>&1)"; then
    log "cookie parameter deleted"
  elif grep -q 'ParameterNotFound' <<<"$out"; then
    log "cookie parameter: none present"
  else
    return 1
  fi
}

# Terminates any launch instance directly when the Terraform apply failed.
terminate_instances() {
  local ids
  ids="$(aws_ ec2 describe-instances --filters Name=tag:Stack,Values=dev-launch \
    Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].InstanceId' --output text)" || return 1
  [[ -z "$ids" || "$ids" == "None" ]] && return 0
  # shellcheck disable=SC2086  # a word per instance ID
  aws_ ec2 terminate-instances --instance-ids $ids >/dev/null
}

STAGE1_APPLY_FAILED=false

# A state-lock error leaves the lock behind: print the command, never run it.
lock_hint() {
  grep -q 'Error acquiring the state lock' "$1" 2>/dev/null || return 0
  loud "TERRAFORM STATE LOCK HELD. When no apply runs, free it by hand: terraform -chdir=terraform/envs/dev-launch force-unlock <LOCK_ID> (the ID is in the error above)"
}

stage1() {
  local rc=0 out
  log "STAGE 1: remove the key, terminate the instance, delete the cookie parameter"
  # The key first: it is the one secret, and it needs no network.
  remove_key || rc=1
  # Always terminate directly: this does not wait on a Terraform lock or a failed apply.
  terminate_instances || { loud "DIRECT TERMINATION FAILED: check EC2 by hand"; rc=1; }
  if $LIVE_STARTED; then
    # The default key and sentinel release_at are the variable defaults: no
    # valid signer remains after this apply. No -target. One retry.
    out="$(mktemp)" || out=/dev/null
    local try ok=false
    for try in 1 2; do
      if setsid -w "$TF" -chdir="$ENV_DIR" apply -auto-approve -input=false -no-color \
        -lock-timeout=120s -var create_load_gen=false -var "minutes=$MINUTES" >"$out" 2>&1; then
        cat "$out"
        ok=true
        break
      fi
      cat "$out"
      lock_hint "$out"
      ((try == 1)) && log "stage 1 apply failed; trying once more"
    done
    [[ "$out" == /dev/null ]] || rm -f "$out"
    if ! $ok; then
      loud "STAGE 1 APPLY FAILED TWICE: the instance was terminated directly; stage 2 will run"
      STAGE1_APPLY_FAILED=true
      rc=1
    fi
  fi
  delete_parameter || { loud "COOKIE PARAMETER DELETE FAILED: run: make launch-destroy"; rc=1; }
  return "$rc"
}

# Copies k6 results and the run record out of the build bucket, before stage 2.
# A failure here is logged and never delays or skips the destroy. run.json holds
# the k6 request counts (k6_requests, an integer: the sum of http_reqs over every
# run summary and probe P) so cdn_logs_complete can compare them with the log
# lines; it is null (17.5 reads "unknown") and k6_complete is false when a summary is
# missing. curl_requests counts the session's own checks: they reach the edge too, so
# a small run (A) can read a few lines high; 17.7 must say so.
collect_results() {
  [[ -n "$BUCKET" ]] || { log "no build bucket known; nothing to copy out"; return 0; }
  mkdir -p "$RUN_DIR/results" || return 1
  # One bounded step: a slow or hung copy must never delay stage 2.
  # The subshell resets TERM and INT: teardown ignores them, and an ignored
  # signal would stop timeout from ending the copy.
  # shellcheck disable=SC2016  # $1..$3 expand in the inner bash, not here
  (trap - TERM INT; timeout -k 5 "$COLLECT_TIMEOUT" bash -c '
    aws --region "$1" s3 cp "s3://$2/results/" "$3" --recursive --only-show-errors
  ' _ "$REGION" "$BUCKET" "$RUN_DIR/results/") || log "collection failed: the results copy failed or timed out (the destroy goes on)"
  local counts probe=()
  [[ "$SCENARIO" == "p" ]] || probe=(--probe "$RUN_DIR/probe-p.json")
  counts="$(py k6_counts.py --dir "$RUN_DIR/results" --names "${RUN_FILES// /,}" "${probe[@]}")" || return 1
  jq -n --arg run_id "$RUN_ID" --arg scenario "$SCENARIO" --arg planned_gb "$TOTAL_GB" \
    --argjson minutes "$MINUTES" --argjson hold "$HOLD_ON" --argjson start "${START_MS:-0}" \
    --argjson end "$(now_ms)" --argjson budget "$BUDGET" --argjson release "${RELEASE_AT:-0}" \
    --argjson curl "$CURL_REQUESTS" --argjson counts "$counts" \
    '{run_id: $run_id, scenario: $scenario, minutes: $minutes, hold: $hold, window_start_ms: $start,
      window_end_ms: $end, planned_gb: $planned_gb, budget_bytes: $budget, release_at_epoch: $release,
      k6_requests: (if $counts.complete then $counts.k6_requests else null end), k6_requests_by_type: $counts.by_type, k6_complete: $counts.complete,
      curl_requests: $curl, cdn_logs_collected: false}' >"$RUN_DIR/run.json"
}

# Waits for the probe P job (it counts bytes on the same distribution as the
# instance). Called before stage 1 on every path.
wait_probe() {
  [[ -n "$PROBE_PID" ]] || return 0
  local rc=0
  wait "$PROBE_PID" || rc=$?
  PROBE_PID=""
  ((rc == 0)) || { loud "probe P failed or timed out (exit $rc)"; FAILED=1; }
  return 0
}

teardown() {
  local status=$?
  # Nothing may stop the teardown half-way: not a failing step (set +e), a
  # second Ctrl-C, or a dead pipe (see console_session.sh).
  trap - EXIT
  trap '' INT TERM PIPE HUP
  set +e
  if [[ -n "$APPLY_PID" ]] && kill -0 "$APPLY_PID" 2>/dev/null; then
    log "stopping the running apply (one INT; terraform saves its state)"
    kill -INT "$APPLY_PID" 2>/dev/null
    wait "$APPLY_PID" 2>/dev/null
  fi
  APPLY_PID=""
  $BUDGET_STOP && loud "BYTE BUDGET EXCEEDED: the session was stopped"
  # Probe P first: on a failed or stopped run end it, then wait, so no byte
  # is still flowing when stage 1 starts.
  if [[ -n "$PROBE_PID" ]] && kill -0 "$PROBE_PID" 2>/dev/null && ((status != 0)); then
    kill -TERM "$PROBE_PID" 2>/dev/null
  fi
  wait_probe

  local rc=0 run_stage2=true
  if $PREWARM_ON && ((status == 0)); then
    log "PREWARM: no instance and no usable key; nothing to stop"
    run_stage2=false
  else
    stage1 || rc=1
    collect_results || log "collection failed (the destroy goes on)"
    if $PREWARM_ON && ((status != 0)); then
      run_stage2=true # a failed PREWARM apply runs both stages
    elif $HOLD_ON; then
      run_stage2=false
      # HOLD keeps the edge only when nothing is wrong: a failed stage 1 apply or a
      # byte-budget stop must not leave the edge up for 24 h.
      if $STAGE1_APPLY_FAILED || $BUDGET_STOP; then
        loud "HOLD is ignored: running stage 2 now"
        run_stage2=true
      fi
    fi
  fi

  if $run_stage2; then
    log "STAGE 2: destroy the rest and check (let it finish; Ctrl-C is ignored)"
    setsid -w "$REPO/orchestration/launch_destroy.sh" --stage2 || {
      loud "STAGE 2 FAILED: run: make launch-destroy && make launch-check"
      rc=1
    }
  elif $PREWARM_ON || $HOLD_ON; then
    local deadline
    deadline="$(date -u -d "+${HOLD_HOURS} hours" +%FT%TZ)"
    log "THE EDGE IS STILL UP. Run by $deadline: make launch-destroy"
    ((status != 0)) && loud "this run FAILED (exit $status); the edge is still up"
  fi

  # Correct the ledger estimate with what actually ran.
  if $LEDGER_RECORDED; then
    local minutes usd
    minutes=$(((SECONDS - RUN_START + 59) / 60))
    if usd="$(py ledger.py estimate --minutes "$minutes" --gb "${TOTAL_GB:-0}" --mtd-gb "${MTD_GB:-0}")"; then
      py ledger.py correct --run-id "$RUN_ID" --usd "$usd" || usd=""
    fi
    [[ -n "$usd" ]] || { loud "LEDGER CORRECTION FAILED for $RUN_ID: the estimate stands"; rc=1; }
  fi

  if ((rc != 0)); then
    loud "SESSION NOT CLEANLY ENDED. Something may still be running and billing."
    loud "Run: make launch-destroy && make launch-check"
    ((status == 0)) && status=1
  fi
  log "session ran for $((SECONDS - RUN_START))s in total"
  exit "$status"
}

# --- main --------------------------------------------------------------------
preflight || exit 1

log "plan: scenario $SCENARIO ($ORDER), $MINUTES minutes, run $RUN_ID, planned $TOTAL_GB GB, budget_bytes $BUDGET"
if ! $YES; then
  read -r -p "Start the launch session (about \$$EST by the ledger)? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { log "cancelled"; exit 0; }
fi

# Set before anything is created, so a failed apply, Ctrl-C or SIGTERM still
# stops the instance, deletes the parameter and removes the key.
trap teardown EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

START_MS="$(now_ms)"
START_ISO="$(date -u +%FT%TZ)"
py ledger.py record --run-id "$RUN_ID" --kind session --estimate-usd "$EST" --gb "$TOTAL_GB" \
  || die "the ledger could not record this run"
LEDGER_RECORDED=true

if $PREWARM_ON; then
  log "PREWARM: applying the edge with the default key and no instance"
  run_apply -var create_load_gen=false || die "the PREWARM apply failed"
  exit 0
fi

# --- live: key, apply 1, wait, cookies, parameter, apply 2 -------------------
KEYDIR="$(mktemp -d "$XDG_RUNTIME_DIR/launch-XXXXXX")" || die "could not create the key directory"
chmod 0700 "$KEYDIR"
openssl genrsa -out "$KEYDIR/key.pem" 2048 >/dev/null 2>&1 || die "openssl could not generate the key"
openssl rsa -in "$KEYDIR/key.pem" -pubout -out "$KEYDIR/pub.pem" >/dev/null 2>&1 || die "openssl could not derive the public key"
PUB_PEM="$(cat "$KEYDIR/pub.pem")" # the trailing newline is lost here; the module adds one back
live_vars

# Apply 1: the public key and the edge, no instance, the default (far-future)
# release_at. T0 is fixed only after Deployed (apply 2), so the wait for the
# distribution does not shorten the schedule.
log "applying the edge with the session's public key (no instance yet)"
LIVE_STARTED=true
run_apply "${LIVE_VARS[@]}" -var create_load_gen=false || die "the edge apply failed"

OUT="$(tf output -json)" || die "could not read the terraform outputs"
DOMAIN="$(jq -r '.domain_name.value // empty' <<<"$OUT")"
DIST="$(jq -r '.distribution_id.value // empty' <<<"$OUT")"
KEYID="$(jq -r '.public_key_id.value // empty' <<<"$OUT")"
BUCKET="$(jq -r '.build_bucket.value // empty' <<<"$OUT")"
[[ -n "$DOMAIN" && -n "$DIST" && -n "$KEYID" && -n "$BUCKET" ]] || die "a terraform output is missing (domain, distribution, key id, bucket)"

log "waiting for the distribution to reach Deployed"
aws_ cloudfront wait distribution-deployed --id "$DIST" || die "the distribution did not reach Deployed"

# Cookies: one custom-policy set for https://<domain>/*, expiring MINUTES from now.
MINT_SECONDS=$SECONDS
EXPIRES=$(($(date -u +%s) + MINUTES * 60))
POLICY="$(printf '{"Statement":[{"Resource":"https://%s/*","Condition":{"DateLessThan":{"AWS:EpochTime":%s}}}]}' "$DOMAIN" "$EXPIRES")"
POLICY_B64="$(printf '%s' "$POLICY" | cf_b64)"
SIG_B64="$(printf '%s' "$POLICY" | openssl dgst -sha1 -sign "$KEYDIR/key.pem" | cf_b64)"
[[ -n "$POLICY_B64" && -n "$SIG_B64" ]] || die "could not sign the cookies"
printf 'CloudFront-Policy=%s; CloudFront-Signature=%s; CloudFront-Key-Pair-Id=%s' \
  "$POLICY_B64" "$SIG_B64" "$KEYID" >"$KEYDIR/cookies.txt"
size="$(wc -c <"$KEYDIR/cookies.txt")"
((size <= 4096)) || die "the cookie value is $size bytes; the SSM Standard limit is 4096"
printf 'Cookie: %s' "$(cat "$KEYDIR/cookies.txt")" >"$KEYDIR/cookie-header.txt"
log "cookies signed ($size bytes); not printed"

# --tags conflicts with --overwrite, so delete first.
delete_parameter || die "could not clear the old cookie parameter"
aws_ ssm put-parameter --name "$COOKIE_PARAM" --type SecureString --tier Standard \
  --value "file://$KEYDIR/cookies.txt" --tags Key=Project,Value=cerberus-platform >/dev/null \
  || die "put-parameter failed"
log "cookie parameter written"

# Before the instance exists: with the default release_at, /license must say 403.
CURL_REQUESTS=$((CURL_REQUESTS + 1))
code="$(curl -s -o /dev/null -w '%{http_code}' -H "@$KEYDIR/cookie-header.txt" "https://$DOMAIN/license")" || code="curl-failed"
[[ "$code" == "403" ]] || die "/license answered $code before T0; expected 403"

# Scenarios, sets, the k6 script and the run order go to the build bucket
# (private scenarios/ prefix); the instance reads them. T0 is now + the offset
# from the schedule; it is set by the second apply (explicit variable).
RELEASE_AT=$(($(date -u +%s) + RELEASE_OFFSET_MINUTES * 60))
for name in $ORDER; do
  aws_ s3 cp "$LAUNCH_DIR/scenarios/$name.json" "s3://$BUCKET/scenarios/$name.json" --only-show-errors || die "scenario upload failed"
done
aws_ s3 cp "$LAUNCH_DIR/scenarios/sets.json" "s3://$BUCKET/scenarios/sets.json" --only-show-errors || die "sets upload failed"
aws_ s3 cp "$LAUNCH_DIR/seed.py" "s3://$BUCKET/scenarios/seed.py" --only-show-errors || die "seed script upload failed"
aws_ s3 cp "$LAUNCH_DIR/k6/download.js" "s3://$BUCKET/scenarios/download.js" --only-show-errors || die "k6 script upload failed"
aws_ s3 cp "$LAUNCH_DIR/k6/wait.js" "s3://$BUCKET/scenarios/wait.js" --only-show-errors || die "k6 helper upload failed"
printf '%s\n' "$RELEASE_AT" | aws_ s3 cp - "s3://$BUCKET/scenarios/release_at" --only-show-errors || die "release_at upload failed"
tr ' ' '\n' <<<"$ORDER" | aws_ s3 cp - "s3://$BUCKET/scenarios/order" --only-show-errors || die "order upload failed"
tr ' ' '\n' <<<"$SEED" | aws_ s3 cp - "s3://$BUCKET/scenarios/seed" --only-show-errors || die "seed upload failed"
mkdir -p "$RUN_DIR"

# Old results (a done marker from an earlier run) must not end this run at once.
aws_ s3 rm "s3://$BUCKET/results/" --recursive --only-show-errors || die "could not clear old results"

log "creating the load generator (the budget is $BUDGET bytes)"
# Apply 2: the same PEM, the explicit release_at, and the instance.
run_apply "${LIVE_VARS[@]}" -var "release_at_epoch=$RELEASE_AT" -var create_load_gen=true -var "budget_bytes=$BUDGET" \
  || die "the instance apply failed"

# The signing key must be the one the cookies name: a replaced key would void them.
[[ "$(tf output -raw public_key_id)" == "$KEYID" ]] || die "the signing key changed after the cookies were minted"

# T0 is set and has not come: /license must still say 403.
CURL_REQUESTS=$((CURL_REQUESTS + 1))
code="$(curl -s -o /dev/null -w '%{http_code}' -H "@$KEYDIR/cookie-header.txt" "https://$DOMAIN/license")" || code="curl-failed"
[[ "$code" == "403" ]] || die "/license answered $code before T0; expected 403"
log "probe: /license is 403 before T0. This alone does not prove the signature: the Function also answers 403 before release_at. The checks after seeding do."

# --- wait: edge checks, probe P, layer 4 poll, until done or the deadline ----
probe_done=false checked=false
[[ "$SCENARIO" == "p" ]] && probe_done=true
finished=false
# The cookies expire at mint + MINUTES, so the deadline counts from the mint.
deadline=$((MINT_SECONDS + MINUTES * 60))
LIMIT="$(layer4_limit)" || die "could not compute the layer 4 limit"
first_obj="/build/manifest.json" # the build manifest: the laptop checks and probe P read it through the signed edge
log "running; the instance writes results/done when it ends (at most until $MINUTES minutes after the cookie mint); layer 4 stops above $LIMIT bytes"
while ((SECONDS < deadline)); do
  if ! $checked && aws_ s3api head-object --bucket "$BUCKET" --key results/seeded >/dev/null 2>&1; then
    checked=true
    # The pre-T0 403 does not prove the signature. After seeding: no cookie
    # must be 403, and a signed cookie on a build object must be 200.
    CURL_REQUESTS=$((CURL_REQUESTS + 2))
    nc="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN$first_obj")" || nc="curl-failed"
    [[ "$nc" == "403" ]] || die "a request without a cookie answered $nc; expected 403"
    wc="$(curl -s -I -o /dev/null -w '%{http_code}' -H "@$KEYDIR/cookie-header.txt" "https://$DOMAIN$first_obj")" || wc="curl-failed"
    [[ "$wc" == "200" ]] || die "a signed request on the build object answered $wc; expected 200 (the signature is not proven)"
    log "checks: no cookie is 403, a signed cookie on a build object is 200"
  fi
  if $checked && ! $probe_done; then
    probe_done=true
    log "probe P: running from this machine, in the background"
    timeout -k 5 "$((deadline - SECONDS))s" "$K6" run --quiet --summary-export "$RUN_DIR/probe-p.json" \
      -e "SCENARIO_FILE=$LAUNCH_DIR/scenarios/p.json" -e "SETS_FILE=$LAUNCH_DIR/scenarios/sets.json" \
      -e "COOKIE_FILE=$KEYDIR/cookies.txt" -e "EDGE_DOMAIN=$DOMAIN" -e "MINUTES=$MINUTES" \
      "$LAUNCH_DIR/k6/download.js" &
    PROBE_PID=$!
  fi
  if aws_ s3api head-object --bucket "$BUCKET" --key results/done >/dev/null 2>&1; then
    finished=true
    break
  fi
  # Layer 4: BytesDownloaded since the start. CloudWatch lags by minutes.
  sum="$(aws_ cloudwatch get-metric-statistics --namespace AWS/CloudFront --metric-name BytesDownloaded \
    --dimensions "Name=DistributionId,Value=$DIST" Name=Region,Value=Global \
    --start-time "$START_ISO" --end-time "$(date -u +%FT%TZ)" --period 60 --statistics Sum --output json 2>/dev/null \
    | jq -r '[.Datapoints[].Sum] | add // 0 | floor' 2>/dev/null)" || sum=""
  if [[ "$sum" =~ ^[0-9]+$ ]]; then
    UNREADABLE=0
    log "BytesDownloaded since the start: $sum (stop above $LIMIT)"
    if ((sum > LIMIT)); then
      BUDGET_STOP=true
      exit 3
    fi
  else
    UNREADABLE=$((UNREADABLE + 1))
    log "BytesDownloaded could not be read this minute ($UNREADABLE of 5 in a row; the nftables quota still applies)"
    if ((UNREADABLE >= 5)); then
      loud "BytesDownloaded was unreadable 5 minutes in a row: layer 4 is blind, so the session is stopped"
      exit 4
    fi
  fi
  sleep "$POLL_SECONDS"
done

wait_probe
$finished || { loud "the run did not finish within $MINUTES minutes of the mint"; FAILED=1; }
((FAILED == 0)) || exit 1
log "the run finished"
exit 0
