#!/usr/bin/env bash
set -euo pipefail

# ADR 0022 amendment, step 6b ($0, local only): run the REAL generator and
# silver job unchanged in apache/spark:3.5.9 (local mode), and save Spark's
# live status REST API every POLL_SECONDS while each job runs. The raw JSON
# shows which fields grow mid-stage; trimmed copies become the exporter's
# test fixtures (see CAPTURE.md). No AWS calls: the data is local.
#
#   ./capture.sh [EVENTS]        EVENTS defaults to 2000000
#
# Env: INCREMENTAL_RUNS (0) adds that many small generator + silver rounds
#        after the main pair, so silver has old keys to read and enough small
#        files for the compaction to run (it needs 5 per partition);
#      EXTRA_EVENTS (300000) is the size of each round;
#      SKIP_BASE (unset) =1 keeps the scratch data and skips the main pair;
#      SCRATCH_DIR (default observability/spark_progress/scratch, git-ignored),
#      CPUS (3), MEM (3g), DRIVER_MEMORY (2g), POLL_SECONDS (5).
#
# Jars: the silver job gets iceberg-spark-runtime 1.10.2, the version in
# transform/spark/spark-application.yaml. hadoop-aws, iceberg-aws-bundle and
# openlineage are left out on purpose: every path is local, the catalog is
# Hadoop, and no OpenLineage listener is configured here.

EVENTS="${1:-2000000}"
IMAGE="apache/spark:3.5.9"
ICEBERG="org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.2"
CPUS="${CPUS:-3}"
MEM="${MEM:-3g}"
DRIVER_MEMORY="${DRIVER_MEMORY:-2g}"
POLL_SECONDS="${POLL_SECONDS:-5}"
RUN_ID="local-e${EVENTS}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPARK_DIR="$(cd "$HERE/../../transform/spark" && pwd)"
SCRATCH_DIR="${SCRATCH_DIR:-$HERE/scratch}"
mkdir -p "$SCRATCH_DIR/data" "$SCRATCH_DIR/ivy" "$SCRATCH_DIR/snapshots"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

# Leave no container behind on Ctrl-C or an error.
CURRENT=""
cleanup() {
  [[ -n "$CURRENT" ]] && docker rm -f "$CURRENT" >/dev/null 2>&1
  # shellcheck disable=SC2046
  kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT

# Two preflight checks: Grafana must be down (the laptop is small), and
# port 4040 must be free (the status API is read from there).
if docker ps -q --filter label=com.docker.compose.service=grafana | grep -q .; then
  log "Grafana is running; run make grafana-down first" >&2
  exit 1
fi
if curl -s --max-time 1 http://127.0.0.1:4040 >/dev/null; then
  log "port 4040 is in use; stop what listens there first" >&2
  exit 1
fi

# Poll the status API of one job until its container exits.
poll() {
  local phase="$1" container="$2" n=0 app dir
  dir="$SCRATCH_DIR/snapshots/$phase"
  rm -rf "$dir"
  mkdir -p "$dir"
  while [[ -n "$(docker ps -q -f "name=^${container}$")" ]]; do
    n=$((n + 1))
    local stamp base=http://127.0.0.1:4040/api/v1/applications
    stamp="$(printf '%04d' "$n")"
    if curl -sS --max-time 4 "$base" -o "$dir/$stamp-applications.json" 2>/dev/null; then
      date -u +%FT%T.%3NZ >"$dir/$stamp-time.txt"
      app="$(jq -r '.[0].id // empty' "$dir/$stamp-applications.json" 2>/dev/null || true)"
      if [[ -n "$app" ]]; then
        curl -sS --max-time 4 "$base/$app/jobs" -o "$dir/$stamp-jobs.json" || true
        curl -sS --max-time 4 "$base/$app/stages" -o "$dir/$stamp-stages.json" || true
        curl -sS --max-time 4 "$base/$app/sql?details=true" -o "$dir/$stamp-sql.json" || true
      fi
    else
      rm -f "$dir/$stamp-applications.json"
      n=$((n - 1))
    fi
    sleep "$POLL_SECONDS"
  done
}

# Run one spark-submit in a container; poll while it runs.
run_job() {
  local phase="$1"
  shift
  local container="cerberus-capture-$phase"
  log "$phase: starting"
  CURRENT="$container"
  docker run -d --name "$container" \
    --cpus "$CPUS" --memory "$MEM" \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -v /etc/passwd:/etc/passwd:ro \
    -p 127.0.0.1:4040:4040 \
    -v "$SPARK_DIR:/opt/jobs:ro" \
    -v "$SCRATCH_DIR/data:/data" \
    -v "$SCRATCH_DIR/ivy:/ivy" \
    "$IMAGE" /opt/spark/bin/spark-submit \
    --master 'local[4]' --driver-memory "$DRIVER_MEMORY" \
    --conf spark.jars.ivy=/ivy "$@" >/dev/null
  # Driver log: follow it until the container exits.
  docker logs -f "$container" >"$SCRATCH_DIR/$phase-driver.log" 2>&1 &
  local logs_pid=$!
  # Sample container CPU and memory every 10 s.
  (while [[ -n "$(docker ps -q -f "name=^${container}$")" ]]; do
    docker stats --no-stream --format '{{.CPUPerc}} {{.MemUsage}}' "$container" 2>/dev/null |
      sed "s/^/$(date -u +%T) /" >>"$SCRATCH_DIR/$phase-stats.txt" || true
    sleep 10
  done) &
  local stats_pid=$!
  local started
  started="$(date +%s)"
  poll "$phase" "$container"
  wait "$logs_pid" "$stats_pid" || true
  local rc
  rc="$(docker wait "$container")"
  docker rm "$container" >/dev/null
  CURRENT=""
  if [[ "$rc" != 0 ]]; then
    log "$phase: FAILED (exit $rc), see $SCRATCH_DIR/$phase-driver.log" >&2
    exit 1
  fi
  log "$phase: done in $(($(date +%s) - started))s"
}

INCREMENTAL_RUNS="${INCREMENTAL_RUNS:-0}"
EXTRA_EVENTS="${EXTRA_EVENTS:-300000}"
generate() { # phase run-id events
  run_job "$1" /opt/jobs/generate_bulk_payments.py \
    --run-id "$2" --events "$3" --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --output /data/bronze/payments_bulk/
}
promote() { # phase
  run_job "$1" --packages "$ICEBERG" /opt/jobs/promote_payments_spark.py \
    --catalog-type hadoop --bronze-root /data/bronze/ --warehouse /data/warehouse/
}

if [[ "${SKIP_BASE:-}" != 1 ]]; then
  rm -rf "$SCRATCH_DIR/data/bronze" "$SCRATCH_DIR/data/warehouse" "$SCRATCH_DIR"/*-stats.txt
  log "events=$EVENTS run_id=$RUN_ID scratch=$SCRATCH_DIR"
  # The silver job globs <bronze-root>/payments_bulk/run_id=*/dt=*/*.json.
  generate generator "$RUN_ID" "$EVENTS"
  promote silver
fi

for i in $(seq 1 "$INCREMENTAL_RUNS"); do
  generate "gen-inc$i" "inc$i-e${EXTRA_EVENTS}" "$EXTRA_EVENTS"
  promote "silver-inc$i"
done

log "log lines to compare with the final snapshots:"
grep -h '^\[generate\] done\|\[spark-transform\]' "$SCRATCH_DIR"/*-driver.log || true
