#!/usr/bin/env bash
set -uo pipefail

# Phase 17.4 -- copy the CloudFront standard logs of one run from the launch
# log bucket to bronze (ADR 0030 Decisions 10 and 13). It is never refused by
# the cost ledger, and it can repeat: it skips keys that exist.
#
#   orchestration/launch_collect.sh RUN_ID        (or RUN_ID=... in the environment)
#
# Reads the run record observability/launch/runs/<RUN_ID>/run.json (written by
# launch_session.sh) for the session window. When the manifest is in bronze it
# sets "cdn_logs_collected": true in that record (the contract with 17.5). Logs exist only for a HOLD run,
# because stage 2 deletes the log bucket; with no bucket this exits 0 and says
# so. The k6 output is the evidence for every other run.
#
# Target: s3://cerberus-platform-bronze-<acct>/downloads_cdn/run_id=<id>/
#         part-<16 hex of sha256(source key)>.json, then _manifest.json last.
# Everything is checked by launch/cdn_filter.py BEFORE the first copy: every
# field must be in launch/cdn_fields.json, and no path or value (except
# x-edge-request-id and timestamp(ms)) may hold a 12-digit run. One violation
# copies nothing. Messages never print a key, a value or a bucket name.

REGION="us-east-1"
export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="$REGION"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="${LAUNCH_RUNS_DIR:-$REPO/observability/launch/runs}"
RUN_ID="${1:-${RUN_ID:-}}"

log() { echo "[$(date -u +%FT%TZ)] $*"; }
fail() { log "STOP: $*"; exit "${2:-1}"; }
aws_() { aws --region "$REGION" "$@"; }
# A non-digit-bounded 12-digit run: a 13-digit timestamp must not match.
has_twelve() { grep -Eq '(^|[^0-9])[0-9]{12}([^0-9]|$)'; }

[[ "$RUN_ID" =~ ^[a-z0-9-]{1,40}$ ]] || fail "give a run id matching ^[a-z0-9-]{1,40}$" 2
command -v jq >/dev/null || fail "jq is not installed"
RECORD="$RUNS_DIR/$RUN_ID/run.json"
[[ -f "$RECORD" ]] || fail "no run record for this run id (run.json is written by launch-session)"
START_MS="$(jq -r '.window_start_ms // empty' "$RECORD")"
END_MS="$(jq -r '.window_end_ms // empty' "$RECORD")"
[[ "$START_MS" =~ ^[0-9]+$ && "$END_MS" =~ ^[0-9]+$ ]] || fail "the run record has no usable window"

acct="$(aws_ sts get-caller-identity --query Account --output text)" || fail "no AWS identity"
LOG_BUCKET="cerberus-platform-launch-logs-$acct"
BRONZE="cerberus-platform-bronze-$acct"

if ! aws_ s3api head-bucket --bucket "$LOG_BUCKET" >/dev/null 2>&1; then
  err="$(aws_ s3api head-bucket --bucket "$LOG_BUCKET" 2>&1)"
  if grep -Eq '404|Not Found|NoSuchBucket' <<<"$err"; then
    log "no log bucket: logs exist only for a HOLD run. The k6 output is the evidence. Nothing collected."
    exit 0
  fi
  fail "the log bucket could not be read"
fi

keys_json="$(aws_ s3api list-objects-v2 --bucket "$LOG_BUCKET" --prefix cdn/ --query 'Contents[].Key' --output json)" \
  || fail "could not list the log bucket"
mapfile -t KEYS < <(jq -r '.[]?' <<<"$keys_json")
if ((${#KEYS[@]} == 0)); then
  log "no log files yet (delivery can lag up to hours). Run this again later."
  exit 0
fi
log "${#KEYS[@]} log file(s) listed"

# Check every path first: one violation copies nothing.
for key in "${KEYS[@]}"; do
  if has_twelve <<<"$key"; then
    fail "a log path holds a 12-digit run (a possible account ID). Nothing was copied." 2
  fi
done

WORK="$(mktemp -d)" || fail "no temp directory"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/in" "$WORK/out"
for key in "${KEYS[@]}"; do
  hex="$(printf '%s' "$key" | sha256sum | cut -c1-16)"
  aws_ s3 cp "s3://$LOG_BUCKET/$key" "$WORK/in/$hex" --only-show-errors || fail "a log file could not be downloaded"
done

python3 "$REPO/launch/cdn_filter.py" --run-id "$RUN_ID" --start-ms "$START_MS" --end-ms "$END_MS" \
  --in-dir "$WORK/in" --out-dir "$WORK/out" || fail "the logs were refused. Nothing was copied." 2

PREFIX="downloads_cdn/run_id=$RUN_ID"
copied=0 skipped=0
for part in "$WORK"/out/part-*.json; do
  [[ -e "$part" ]] || continue
  dest="$PREFIX/$(basename "$part")"
  if aws_ s3api head-object --bucket "$BRONZE" --key "$dest" >/dev/null 2>&1; then
    skipped=$((skipped + 1))
    continue
  fi
  err="$(aws_ s3api head-object --bucket "$BRONZE" --key "$dest" 2>&1)"
  grep -Eq '404|Not Found|NoSuchKey' <<<"$err" || fail "could not tell whether a part exists"
  aws_ s3 cp "$part" "s3://$BRONZE/$dest" --only-show-errors || fail "a part could not be copied"
  copied=$((copied + 1))
done

# The manifest is the completeness marker: it goes last, and only when something
# is new or it is missing.
if ((copied > 0)) || ! aws_ s3api head-object --bucket "$BRONZE" --key "$PREFIX/_manifest.json" >/dev/null 2>&1; then
  aws_ s3 cp "$WORK/out/_manifest.json" "s3://$BRONZE/$PREFIX/_manifest.json" --only-show-errors || fail "the manifest could not be copied"
  log "manifest written"
fi
log "collected: $copied part(s) copied, $skipped already there"

# Run-record contract with 17.5: only now, with the manifest in bronze, the run
# record says "cdn_logs_collected": true. Atomic: write a temp file in the same
# directory, then rename. launch_session.sh starts the record with false.
tmp_record="$(mktemp "$RECORD.XXXXXX")" || fail "could not create a temp file next to the run record"
if jq '.cdn_logs_collected = true' "$RECORD" >"$tmp_record" && mv -f "$tmp_record" "$RECORD"; then
  log "run record: cdn_logs_collected = true"
else
  rm -f "$tmp_record"
  fail "could not update the run record"
fi
