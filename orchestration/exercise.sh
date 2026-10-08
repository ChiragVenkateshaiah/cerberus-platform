#!/usr/bin/env bash
set -euo pipefail

# Cerberus 8.3 -- one-command compute exercise: apply -> run -> collect ->
# destroy, with no pauses between them. Covers steps 2-4 of the runbook in
# terraform/envs/dev-compute/main.tf -- the only steps where the cluster
# costs money.
#
#   orchestration/exercise.sh [--yes] [--generate EVENTS] [--name PREFIX] [--keep]
#   orchestration/exercise.sh --check
#
#   --check           preflight only: identity, empty dev-compute state, no
#                     cluster, schedule state. Read-only, costs nothing.
#   --yes             skip the one confirmation before the apply.
#   --generate EVENTS run generate_bulk.sh with EVENTS before the
#                     orchestrated run (8.3+: the scale ladder).
#   --name PREFIX     execution name prefix (default: exercise).
#   --keep            skip the destroy. For a debugging session only; the
#                     cluster costs about $0.40/hour until
#                     `make compute-destroy`.
#
# Why one command: on 2026-10-06 the cluster was up 2.10 hours ($0.84) and
# the two runs used about 13 minutes of it (docs/scale-metrics.md). Every
# idle 15 minutes costs about $0.10.
#
# The destroy runs from an EXIT trap, so it also runs after a failed apply,
# a failed run, or Ctrl-C. A failed destroy prints what to check and exits
# non-zero -- never assume the cluster is gone without the final check.
#
# Not covered here, and still manual (no cluster cost):
#   - runbook steps 1 and 5, the `pipeline_active` PRs. A manual
#     start-execution needs no ENABLED schedule; flip it only for a
#     multi-day exercise or to exercise the gated alarms.
#   - `--cost-only` for the collector, the day after (Cost Explorer posts
#     about a day late).
#
# Claude Code's auto mode blocks `terraform apply`: run this from your own
# terminal.

REGION="us-east-1"
PROFILE="cerberus-admin"
# Terraform's S3 backend and providers, and kubectl's token helper, read
# these from the environment -- set here so the script doesn't depend on
# the caller's shell.
export AWS_PROFILE="$PROFILE" AWS_REGION="$REGION"
STATE_MACHINE="arn:aws:states:${REGION}:131715059025:stateMachine:cerberus-platform-orchestration"
CLUSTER_NAME="cerberus-platform-eks"
SCHEDULE_NAME="cerberus-ingest-payments-daily"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPUTE_DIR="$REPO/terraform/envs/dev-compute"
TF="${TF_BIN:-terraform}"
# Prometheus agent's remote-write runs every few seconds; this lets the
# last Spark samples reach AMP before the agent is destroyed (2026-10-06
# checked pending samples = 0 before destroy by hand).
FLUSH_SECONDS="${FLUSH_SECONDS:-60}"

YES=false CHECK=false KEEP=false GENERATE="" PREFIX="exercise"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES=true ;;
    --check) CHECK=true ;;
    --keep) KEEP=true ;;
    --generate) GENERATE="$2"; shift ;;
    --name) PREFIX="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="$REPO/observability/scale/exercises"
LOG="$LOG_DIR/$PREFIX-$STAMP.log"
EXECUTION_NAME="$PREFIX-$STAMP"
CLUSTER_UP=""

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }
log() { echo "[$(date -u +%FT%TZ)] $*"; }
tf() { "$TF" -chdir="$COMPUTE_DIR" "$@"; }

preflight() {
  log "preflight"
  local who
  who="$(aws_ sts get-caller-identity --query Arn --output text)"
  log "  identity: $who"

  local clusters
  clusters="$(aws_ eks list-clusters --query 'length(clusters)' --output text)"
  if [[ "$clusters" != "0" ]]; then
    log "  STOP: $clusters EKS cluster(s) already exist -- tear down or investigate first"
    return 1
  fi
  log "  EKS clusters: 0"

  if ! tf init -input=false -no-color >/dev/null; then
    log "  STOP: terraform init failed for dev-compute (credentials? backend?)"
    return 1
  fi
  # Fail closed: an error reading state must not look like an empty state.
  local state resources
  if ! state="$(tf state list -no-color 2>&1)"; then
    log "  STOP: can't read dev-compute state:"
    echo "$state"
    return 1
  fi
  resources="$(grep -c '^[a-z]' <<<"$state" || true)"
  if [[ "$resources" != "0" ]]; then
    log "  STOP: dev-compute state holds $resources resource(s) -- a previous destroy did not finish"
    return 1
  fi
  log "  dev-compute state: empty"

  local schedule
  schedule="$(aws_ scheduler get-schedule --name "$SCHEDULE_NAME" --query State --output text)"
  log "  daily schedule: $schedule (a manual run doesn't need it ENABLED)"

  local running
  running="$(aws_ stepfunctions list-executions --state-machine-arn "$STATE_MACHINE" \
    --status-filter RUNNING --query 'length(executions)' --output text)"
  if [[ "$running" != "0" ]]; then
    log "  STOP: $running execution(s) already RUNNING"
    return 1
  fi
  log "  running executions: 0"
}

teardown() {
  local status=$?
  # Nothing may stop the destroy half-way: not a failing check (set +e),
  # not a second Ctrl-C, and not a dead log pipe (PIPE) -- a Ctrl-C reaches
  # the whole process group, and a script killed by SIGPIPE on its next log
  # line would leave the cluster billing (found in testing, 2026-10-07).
  trap - EXIT
  trap '' INT TERM PIPE
  set +e
  if [[ -z "$CLUSTER_UP" ]]; then
    exit "$status"
  fi
  if $KEEP; then
    log "--keep: NOT destroying. The cluster costs about \$0.40/hour. Run: make compute-destroy"
    exit "$status"
  fi
  log "waiting ${FLUSH_SECONDS}s for the last metrics to reach AMP"
  sleep "$FLUSH_SECONDS"
  log "destroying dev-compute -- let it finish; Ctrl-C is ignored from here"
  local destroy_start=$SECONDS
  # -lock-timeout: an interrupted apply can hold the state lock for a moment.
  if ! tf destroy -auto-approve -input=false -lock-timeout=120s; then
    log "destroy failed once, retrying"
    tf destroy -auto-approve -input=false -lock-timeout=120s || {
      log "DESTROY FAILED. The cluster may still be running and billing."
      log "Check: make compute-destroy, then the AWS console (EKS, NAT gateways, EC2)."
      exit 1
    }
  fi
  log "destroy took $((SECONDS - destroy_start))s"

  # Account-wide, not just this state: the check that matters for the bill.
  local eks nat eip ec2
  eks="$(aws_ eks list-clusters --query 'length(clusters)' --output text)"
  nat="$(aws_ ec2 describe-nat-gateways --filter Name=state,Values=pending,available \
    --query 'length(NatGateways)' --output text)"
  eip="$(aws_ ec2 describe-addresses --query 'length(Addresses)' --output text)"
  ec2="$(aws_ ec2 describe-instances --filters Name=instance-state-name,Values=pending,running \
    --query 'length(Reservations[].Instances[])' --output text)"
  log "after destroy: EKS $eks, NAT $nat, EIP $eip, running instances $ec2"
  if [[ "$eks$nat$eip$ec2" != "0000" ]]; then
    log "WARNING: something billable is still up -- check before you leave"
    status=1
  fi
  log "cluster up for $((SECONDS - CLUSTER_UP))s in total"
  exit "$status"
}

# 8.6: the Spark Operator's and drivers' logs, plus the SparkApplications and
# the spark-jobs events, for timing a run's fixed overhead (Ivy package
# resolution in the operator and again in each driver, pod scheduling and
# start-up). They exist only on the cluster, which the teardown destroys, so
# they are saved right after the run. Best-effort throughout: nothing here
# may stop the run from reaching the collector and the teardown.
capture_spark_logs() {
  local dir="$LOG_DIR/$EXECUTION_NAME-spark" pod
  mkdir -p "$dir"
  kubectl get sparkapplications -n spark-jobs -o yaml >"$dir/sparkapplications.yaml" 2>&1 || true
  kubectl get events -n spark-jobs --sort-by=.lastTimestamp -o wide >"$dir/events-spark-jobs.txt" 2>&1 || true
  for pod in $(kubectl get pods -n spark-operator -o name 2>/dev/null || true); do
    kubectl logs -n spark-operator "$pod" --all-containers --timestamps \
      >"$dir/operator-${pod#pod/}.log" 2>&1 || true
  done
  for pod in $(kubectl get pods -n spark-jobs -l spark-role=driver -o name 2>/dev/null || true); do
    kubectl logs -n spark-jobs "$pod" --timestamps >"$dir/${pod#pod/}.log" 2>&1 || true
  done
  log "Spark logs saved to ${dir#"$REPO"/}"
  # Ivy prints one ":: resolution report :: resolve Nms :: artifacts dl Nms"
  # line per resolution: the package-download cost, per operator and driver.
  grep -H -o 'resolve [0-9]*ms :: artifacts dl [0-9]*ms' "$dir"/*.log 2>/dev/null |
    sed "s|^$dir/|  |" || true
}

if $CHECK; then
  preflight
  log "preflight passed"
  exit 0
fi

mkdir -p "$LOG_DIR"
# tee ignores INT/TERM so the log pipe outlives a Ctrl-C and the teardown's
# output still reaches the screen and the log.
exec > >(
  trap '' INT TERM
  exec tee -a "$LOG"
) 2>&1
log "exercise $EXECUTION_NAME -- log: ${LOG#"$REPO"/}"
preflight

if ! $YES; then
  read -r -p "Apply dev-compute (about \$0.40/hour until the destroy at the end)? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { log "cancelled"; exit 0; }
fi

trap teardown EXIT
trap 'exit 130' INT TERM

# Plan and apply back to back: a saved dev-compute plan carries an EKS
# token that expires after about 15 minutes (checkpoint Notes, 2026-10-06).
PLAN="$(mktemp -d)/dev-compute.tfplan"
CLUSTER_UP=$SECONDS
apply_start=$SECONDS
tf plan -input=false -out="$PLAN" >/dev/null
tf apply -input=false "$PLAN"
log "apply took $((SECONDS - apply_start))s"

aws_ eks update-kubeconfig --name "$CLUSTER_NAME" >/dev/null
kubectl wait --for=condition=Ready nodes --all --timeout=300s
kubectl wait --for=condition=Available deployment --all -n spark-operator --timeout=300s

GENERATOR_ARGS=()
if [[ -n "$GENERATE" ]]; then
  log "generator: $GENERATE events"
  gen_start=$SECONDS
  gen_log="$(mktemp)"
  "$REPO/transform/spark/generate_bulk.sh" "$GENERATE" | tee "$gen_log"
  run_id="$(sed -n 's/.*RUN_ID=\([^ ]*\).*/\1/p' "$gen_log" | head -1)"
  # The log carries the generator's [generate] manifest, which the
  # collector records and the data-quality suite checks against bronze.
  GENERATOR_ARGS=(--generator-run-id "$run_id" --generator-log "$gen_log")
  log "generator took $((SECONDS - gen_start))s (run_id $run_id)"
fi

log "starting execution $EXECUTION_NAME"
run_start=$SECONDS
execution_arn="$(aws_ stepfunctions start-execution --state-machine-arn "$STATE_MACHINE" \
  --name "$EXECUTION_NAME" --query executionArn --output text)"
status="RUNNING"
while [[ "$status" == "RUNNING" ]]; do
  sleep 15
  status="$(aws_ stepfunctions describe-execution --execution-arn "$execution_arn" \
    --query status --output text)"
done
log "execution $status after $((SECONDS - run_start))s"
capture_spark_logs

log "collecting metrics"
# Collected while the cluster is still up but no longer needed for it --
# a collector failure is reported, not fatal: the run itself is recorded in
# Step Functions and AMP, and the collector can be re-run after the destroy
# (only the S3 sizes and silver count are moment-sensitive). Exit code 3 is
# different: the record is written, but the data-quality suite (8.4) failed.
collector_rc=0
uv run -q --no-project --with boto3 python "$REPO/observability/scale/collect_run_metrics.py" \
  --execution "$EXECUTION_NAME" "${GENERATOR_ARGS[@]}" || collector_rc=$?
case "$collector_rc" in
  0) ;;
  3) log "DATA QUALITY FAILED -- see data_quality in observability/scale/runs/$EXECUTION_NAME.json" ;;
  *) log "collector failed -- re-run it by hand: collect_run_metrics.py --execution $EXECUTION_NAME" ;;
esac

[[ "$status" == "SUCCEEDED" ]] || { log "execution did not succeed"; exit 1; }
[[ "$collector_rc" != 3 ]] || exit 3
log "exercise done -- the destroy follows. Tomorrow: collect_run_metrics.py --execution $EXECUTION_NAME --cost-only"
