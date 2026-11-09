#!/usr/bin/env bash
set -euo pipefail

# Trim chosen capture.sh snapshots into small, commit-ready fixtures under
# fixtures/. Each fixture is one JSON file holding only the fields the 6c
# exporter reads: the application id and state, jobs, stages, and the SQL
# executions (node names and metrics only). Needs jq.
#
#   ./trim_fixtures.sh [SNAPSHOT_DIR]     (default: scratch/snapshots)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$HERE/scratch/snapshots}"
OUT="$HERE/fixtures"
mkdir -p "$OUT"

# fixture name = phase/snapshot number. The comment says what it shows.
# The generator/* and silver/* picks match the 8,000,000-event run of
# 2026-10-25 (see CAPTURE.md, Fixtures). Re-run `./capture.sh 8000000`
# with INCREMENTAL_RUNS=6 before re-trimming, or the picks point at
# different moments.
PICKS=(
  "generator-early-map-stage=generator/0003"      # ShuffleMapStage running: 4 tasks active, no records yet
  "generator-map-done=generator/0005"             # map stage done (input and shuffle write counted), write stage 0/32
  "generator-write-mid=generator/0007"            # write ResultStage 11/32: outputRecords growing per finished task
  "generator-end-idle=generator/0009"             # write job done, no job running (commit / between jobs)
  "generator-count-pass=gen-inc4/0003"            # the count pass after the write (small run)
  "silver-early-bronze-scan=silver/0003"          # bronze scan stage 0/30, nothing counted yet
  "silver-bronze-scan-mid=silver/0010"            # bronze scan stage 19/30: inputRecords growing
  "silver-anti-join-mid=silver/0015"              # shuffle stage 10/23
  "silver-append-mid=silver/0018"                 # append ResultStage 1/6: outputRecords growing
  "silver-end-commit=silver/0019"                 # append stage done, no job running, SQL still RUNNING (Iceberg commit)
  "silver-incr-two-scans=silver-inc4/0002"        # later run: bronze scan and silver-key scan both active
  "silver-incr-append-mid=silver-inc4/0005"       # later run: append stage 5/7
  "silver-compaction-active=silver-inc4/0006"     # compaction: five save-at-SparkBinPack jobs running at once
  "silver-compaction-end=silver-inc4/0010"        # everything done, compaction stages complete
)

# Check every source first, so a partial capture cannot change some fixtures
# and then fail.
for pick in "${PICKS[@]}"; do
  rest="${pick#*=}"
  rest="${rest%%[[:space:]]*}"
  dir="$SRC/${rest%/*}"
  num="${rest#*/}"
  for part in time applications jobs stages sql; do
    [[ -f "$dir/$num-$part.json" || ( "$part" == time && -f "$dir/$num-time.txt" ) ]] ||
      { echo "missing $dir/$num ($part)" >&2; exit 1; }
  done
done

for pick in "${PICKS[@]}"; do
  name="${pick%%=*}"
  rest="${pick#*=}"
  rest="${rest%%[[:space:]]*}"
  dir="$SRC/${rest%/*}"
  num="${rest#*/}"
  jq -n \
    --arg at "$(cat "$dir/$num-time.txt")" \
    --slurpfile apps "$dir/$num-applications.json" \
    --slurpfile jobs "$dir/$num-jobs.json" \
    --slurpfile stages "$dir/$num-stages.json" \
    --slurpfile sql "$dir/$num-sql.json" \
    '{
      capturedAt: $at,
      applications: ($apps[0] | map({id, name, completed: .attempts[0].completed})),
      jobs: ($jobs[0] | map({jobId, name, status, numTasks, numActiveTasks, numCompletedTasks, stageIds})),
      stages: ($stages[0] | map({stageId, attemptId, name, status, numTasks, numActiveTasks,
        numCompleteTasks, inputRecords, outputRecords, shuffleReadRecords, shuffleWriteRecords,
        inputBytes, outputBytes, submissionTime, completionTime})),
      sql: ($sql[0] | map({id, status, description, runningJobIds, successJobIds,
        nodes: (.nodes | map({nodeName, metrics: (.metrics | map({name, value}))}))}))
    }' >"$OUT/$name.json"
done
du -sh "$OUT"
