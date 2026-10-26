#!/usr/bin/env bash
# Cerberus 8.10 (ADR 0022 amendment) -- post run annotations to the local
# Grafana, so the story dashboard shows step times, the data-quality verdict
# and the account-wide teardown check.
#
# Sourced by orchestration/exercise.sh. Also a small CLI:
#   orchestration/annotate.sh --replay EXECUTION
#       post the annotations of a finished run from its committed exercise
#       log, its run record and its Step Functions history (read-only AWS).
#   orchestration/annotate.sh --delete-tag TAG [TAG...]
#       delete the annotations that carry all of these tags (test clean-up).
#
# Fail-open by design: every function returns 0, whatever happens. A missing
# token, a stopped Grafana or a non-2xx reply costs one warning line per run
# and nothing else. Callers still wrap each call in `{ ...; } || true`.
# The terminal and the run record stay the authoritative result.
#
# Only 127.0.0.1 / localhost is ever called. The token comes from
# observability/grafana/.env (key GRAFANA_ANNOTATE_TOKEN, read with grep --
# the file is never sourced, so the admin password stays out of the
# environment). `make grafana-token` writes it.

ANNOTATE_ENABLED="${ANNOTATE_ENABLED:-true}"
ANNOTATE_REPO="${ANNOTATE_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ANNOTATE_ENV_FILE="${ANNOTATE_ENV_FILE:-$ANNOTATE_REPO/observability/grafana/.env}"
ANNOTATE_URL="${ANNOTATE_URL:-http://127.0.0.1:3000}"
ANNOTATE_RUN=""      # execution name, for the run:<name> tag
ANNOTATE_EXTRA=()    # extra tags on every post (replay sets "replay")
ANNOTATE_WARNED=false
ANNOTATE_OK=false    # did the last call succeed?
ANNOTATE_BODY=""
ANNOTATE_TOKEN=""
ANNOTATE_TOKEN_LOADED=false
ANNOTATE_SEEN_FILE=""

annotate_now_ms() { date +%s%3N; }

annotate_init() { # RUN [EXTRA_TAG...]
  ANNOTATE_RUN="${1:-}"
  shift || true
  ANNOTATE_EXTRA=("$@")
  return 0
}

annotate_warn() {
  if ! $ANNOTATE_WARNED; then
    ANNOTATE_WARNED=true
    echo "[$(date -u +%FT%TZ)] annotation skipped ($1)" >&2
  fi
  return 0
}

annotate_load_token() {
  if ! $ANNOTATE_TOKEN_LOADED; then
    ANNOTATE_TOKEN_LOADED=true
    if [[ -r "$ANNOTATE_ENV_FILE" ]]; then
      ANNOTATE_TOKEN="$(grep -m1 '^GRAFANA_ANNOTATE_TOKEN=' "$ANNOTATE_ENV_FILE" | cut -d= -f2- || true)"
    fi
  fi
  return 0
}

# annotate_http METHOD PATH [JSON]: sets ANNOTATE_OK and ANNOTATE_BODY.
annotate_http() {
  ANNOTATE_OK=false
  ANNOTATE_BODY=""
  annotate_load_token
  if [[ -z "$ANNOTATE_TOKEN" ]]; then
    annotate_warn "no token -- run make grafana-token"
    return 0
  fi
  [[ "$ANNOTATE_URL" =~ ^http://(127\.0\.0\.1|localhost):[0-9]+$ ]] ||
    { annotate_warn "URL is not loopback"; return 0; }
  local out rc=0 code
  local -a data=()
  if [[ -n "${3:-}" ]]; then
    data=(-H 'Content-Type: application/json' -d "$3")
  fi
  # The token goes in through a config file descriptor, not on the command line.
  out="$(curl -sS --max-time 3 -w $'\n%{http_code}' -X "$1" \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$ANNOTATE_TOKEN") \
    "${data[@]}" "$ANNOTATE_URL$2" 2>/dev/null)" || rc=$?
  if ((rc != 0)); then
    annotate_warn "curl error $rc"
    # A timeout (28) means Grafana hangs: stop posting for the rest of the run.
    if ((rc == 28)); then ANNOTATE_ENABLED=false; fi
    return 0
  fi
  code="${out##*$'\n'}"
  ANNOTATE_BODY="${out%$'\n'*}"
  if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
    ANNOTATE_OK=true
  else
    annotate_warn "HTTP $code"
  fi
  return 0
}

# annotate TEXT TIME_MS [TIME_END_MS] TAG...
annotate() {
  [[ "$ANNOTATE_ENABLED" == true ]] || return 0
  if (($# < 3)); then
    annotate_warn "bad arguments"
    return 0
  fi
  local text="$1" time="$2" end="" json
  shift 2
  if [[ "$1" =~ ^[0-9]+$ ]]; then
    end="$1"
    shift
  fi
  if ! json="$(jq -n --arg text "$text" --argjson time "$time" --arg end "$end" \
    '{text: $text, time: $time, tags: $ARGS.positional}
     + (if $end == "" then {} else {timeEnd: ($end | tonumber)} end)' --args "$@" 2>/dev/null)"; then
    annotate_warn "bad arguments"
    return 0
  fi
  annotate_http POST /api/annotations "$json"
  return 0
}

# Step annotation: tags cerberus, run:<execution>, step.
annotate_step() { # TEXT TIME_MS [TIME_END_MS]
  annotate "$@" cerberus "run:$ANNOTATE_RUN" step ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
  return 0
}

# Placeholders for the two result tiles. No `cerberus` tag, so the journey's
# step markers do not show them.
annotate_placeholders() { # [TIME_MS]
  local t="${1:-$(annotate_now_ms)}"
  annotate "Quality checks: not finished yet" "$t" cerberus-dq "run:$ANNOTATE_RUN" \
    ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
  annotate "Clean-up: not started yet" "$t" cerberus-teardown "run:$ANNOTATE_RUN" \
    ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
  return 0
}

# Verdict from the collector's exit code (0 passed, 3 failed, else not run);
# N, E and W come from the run record.
annotate_dq_verdict() { # COLLECTOR_RC TIME_MS
  local rc="$1" t="$2" rec="$ANNOTATE_REPO/observability/scale/runs/$ANNOTATE_RUN.json" text part=""
  case "$rc" in
    0)
      part="$(jq -r '.data_quality | def p(n; w): "\(n) \(w)\(if n == 1 then "" else "s" end)";
        "\(p(.checks | length; "check")), \(p(.errors; "error")), \(p(.warnings; "warning"))"' \
        "$rec" 2>/dev/null || true)"
      text="Quality checks: PASSED (${part:-see run record})"
      ;;
    3)
      part="$(jq -r '.data_quality.errors | "\(.) error\(if . == 1 then "" else "s" end)"' \
        "$rec" 2>/dev/null || true)"
      text="Quality checks: FAILED (${part:-? errors}) — see run record"
      ;;
    *) text="Quality checks: NOT RUN (collector failed)" ;;
  esac
  annotate "$text" "$t" cerberus "run:$ANNOTATE_RUN" dq cerberus-dq \
    ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
  return 0
}

# The account-wide check after the destroy. Counts are the check's own output.
annotate_teardown_check() { # EKS NAT EIP EC2 TIME_MS
  local text
  if [[ "$1$2$3$4" == "0000" ]]; then
    text="Cluster deleted: EKS 0, NAT 0, Elastic IP 0, running instances 0 (account-wide check)"
  else
    text="STILL RUNNING — check the console (EKS $1, NAT $2, Elastic IP $3, running instances $4)"
  fi
  annotate "$text" "$5" cerberus "run:$ANNOTATE_RUN" teardown cerberus-teardown \
    ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
  return 0
}

annotate_teardown_failed() { # TIME_MS
  annotate "Teardown FAILED — check the console" "$1" cerberus "run:$ANNOTATE_RUN" teardown \
    cerberus-teardown ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
  return 0
}

# Post each Step Functions state once: StateEntered as a point, StateExited as
# a region from the entry to the exit. Event ids already posted are kept in a
# temp file, so the 15 s poll can call this every time. Read-only AWS.
annotate_sfn_history() { # EXECUTION_ARN RUN_TAG
  [[ "$ANNOTATE_ENABLED" == true ]] || return 0
  local events id kind name start end
  if [[ -z "$ANNOTATE_SEEN_FILE" ]]; then
    ANNOTATE_SEEN_FILE="$(mktemp)" || return 0
  fi
  events="$(aws stepfunctions get-execution-history --execution-arn "$1" --output json 2>/dev/null)" ||
    return 0
  # The CLI prints ISO timestamps with a local offset (v2) or epoch seconds
  # (v1); both become epoch ms.
  while IFS=$'\t' read -r id kind name start end; do
    if grep -qx "$id" "$ANNOTATE_SEEN_FILE" 2>/dev/null; then
      continue
    fi
    if [[ "$kind" == region && "$start" == "$end" ]]; then
      echo "$id" >>"$ANNOTATE_SEEN_FILE" # a zero-length state (Succeed): the point is enough
      continue
    fi
    if [[ "$kind" == point ]]; then
      annotate "$name started" "$start" cerberus "$2" step ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
    else
      annotate "$name" "$start" "$end" cerberus "$2" step ${ANNOTATE_EXTRA[@]+"${ANNOTATE_EXTRA[@]}"}
    fi
    $ANNOTATE_OK || break
    echo "$id" >>"$ANNOTATE_SEEN_FILE"
  done < <(jq -r '
    def ms: if type == "number" then (. * 1000 | floor)
      else capture("^(?<a>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\\.(?<f>[0-9]+))?(?<z>Z|[+-][0-9]{2}:[0-9]{2})$")
        | ((.a + "Z" | fromdateiso8601) * 1000) + (((.f // "0") + "000")[0:3] | tonumber)
          - (if .z == "Z" then 0
             else ((.z[0:1] + "1" | tonumber) * ((.z[1:3] | tonumber) * 3600 + (.z[4:6] | tonumber) * 60) * 1000) end)
      end;
    .events as $e
    | ([$e[] | select(.type | endswith("StateEntered"))
        | {key: .stateEnteredEventDetails.name, value: (.timestamp | ms)}] | from_entries) as $in
    | $e[]
    | if (.type | endswith("StateEntered")) then
        [(.id | tostring), "point", .stateEnteredEventDetails.name, (.timestamp | ms), 0]
      elif (.type | endswith("StateExited")) then
        [(.id | tostring), "region", .stateExitedEventDetails.name,
         ($in[.stateExitedEventDetails.name] // (.timestamp | ms)), (.timestamp | ms)]
      else empty end
    | @tsv' <<<"$events" 2>/dev/null)
  return 0
}

# Test clean-up: delete every annotation that carries all of the tags.
annotate_delete_tags() { # TAG...
  local qs="" t id n=0
  local -a ids=()
  for t in "$@"; do
    qs+="&tags=$(jq -rn --arg t "$t" '$t | @uri')"
  done
  annotate_http GET "/api/annotations?limit=5000$qs"
  $ANNOTATE_OK || return 0
  mapfile -t ids < <(jq -r '.[].id' <<<"$ANNOTATE_BODY" 2>/dev/null)
  for id in ${ids[@]+"${ids[@]}"}; do
    annotate_http DELETE "/api/annotations/$id"
    if $ANNOTATE_OK; then n=$((n + 1)); fi
  done
  echo "deleted $n annotation(s) tagged: $*"
  return 0
}

# --- replay -----------------------------------------------------------------

# Epoch ms of a log timestamp such as 2026-10-13T06:12:36Z.
annotate_ts_ms() { echo "$(($(date -u -d "$1" +%s) * 1000))"; }

# The timestamp of the first log line that starts with the given text.
annotate_log_ts() { # LOG TEXT
  sed -n "s/^\[\([^]]*\)\] $2.*/\1/p" "$1" | head -1
}

annotate_replay() { # EXECUTION
  local run="$1" log="$ANNOTATE_REPO/observability/scale/exercises/$1.log" arn line ts n s e rc
  if [[ ! -r "$log" ]]; then
    echo "no exercise log: $log" >&2
    return 1
  fi
  arn="arn:aws:states:us-east-1:131715059025:execution:cerberus-platform-orchestration:$run"
  export AWS_PROFILE="${AWS_PROFILE:-cerberus-admin}" AWS_REGION="${AWS_REGION:-us-east-1}"
  annotate_init "$run" replay
  annotate_delete_tags replay "run:$run"

  # apply took Ns: ends at the line's time.
  line="$(sed -n 's/^\[\([^]]*\)\] apply took \([0-9]*\)s.*/\1 \2/p' "$log" | head -1)"
  if [[ -n "$line" ]]; then
    read -r ts n <<<"$line"
    e="$(annotate_ts_ms "$ts")"
    s=$((e - n * 1000))
    annotate_placeholders "$s"
    annotate_step "Start servers started" "$s"
    annotate_step "Start servers" "$s" "$e"
  fi
  line="$(sed -n 's/^\[\([^]]*\)\] generator took \([0-9]*\)s.*/\1 \2/p' "$log" | head -1)"
  if [[ -n "$line" ]]; then
    read -r ts n <<<"$line"
    e="$(annotate_ts_ms "$ts")"
    s=$((e - n * 1000))
    annotate_step "Generate started" "$s"
    annotate_step "Generate" "$s" "$e"
  fi
  ts="$(annotate_log_ts "$log" "starting execution ")"
  if [[ -n "$ts" ]]; then annotate_step "Pipeline run started" "$(annotate_ts_ms "$ts")"; fi
  line="$(sed -n 's/^\[\([^]]*\)\] execution \([A-Z_]*\) after.*/\1 \2/p' "$log" | head -1)"
  if [[ -n "$line" ]]; then
    read -r ts n <<<"$line"
    annotate_step "Pipeline run $n" "$(annotate_ts_ms "$ts")"
  fi
  annotate_sfn_history "$arn" "run:$run"

  # The verdict time is the first log line after the collector's case.
  rc=""
  for line in "DATA QUALITY FAILED:3" "collector failed:1" "exercise done:0"; do
    ts="$(annotate_log_ts "$log" "${line%:*}")"
    if [[ -n "$ts" ]]; then
      rc="${line##*:}"
      break
    fi
  done
  if [[ -n "$rc" ]]; then annotate_dq_verdict "$rc" "$(annotate_ts_ms "$ts")"; fi

  line="$(sed -n 's/^\[\([^]]*\)\] destroy took \([0-9]*\)s.*/\1 \2/p' "$log" | head -1)"
  if [[ -n "$line" ]]; then
    read -r ts n <<<"$line"
    e="$(annotate_ts_ms "$ts")"
    s=$((e - n * 1000))
    annotate_step "Delete servers started" "$s"
    annotate_step "Delete servers" "$s" "$e"
  fi
  line="$(sed -n 's/^\[\([^]]*\)\] after destroy: EKS \([0-9]*\), NAT \([0-9]*\), EIP \([0-9]*\), running instances \([0-9]*\).*/\1 \2 \3 \4 \5/p' "$log" | head -1)"
  if [[ -n "$line" ]]; then
    local c1 c2 c3 c4
    read -r ts c1 c2 c3 c4 <<<"$line"
    annotate_teardown_check "$c1" "$c2" "$c3" "$c4" "$(annotate_ts_ms "$ts")"
  elif grep -q 'DESTROY FAILED' "$log"; then
    ts="$(annotate_log_ts "$log" "DESTROY FAILED")"
    annotate_teardown_failed "$(annotate_ts_ms "$ts")"
  fi
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -uo pipefail
  case "${1:-}" in
    --replay)
      [[ -n "${2:-}" ]] || { echo "usage: annotate.sh --replay EXECUTION" >&2; exit 2; }
      annotate_replay "$2"
      ;;
    --delete-tag)
      shift
      [[ $# -gt 0 ]] || { echo "usage: annotate.sh --delete-tag TAG [TAG...]" >&2; exit 2; }
      annotate_delete_tags "$@"
      ;;
    *) echo "usage: annotate.sh --replay EXECUTION | --delete-tag TAG [TAG...]" >&2; exit 2 ;;
  esac
fi
