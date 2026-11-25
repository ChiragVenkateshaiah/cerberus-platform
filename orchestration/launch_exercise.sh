#!/usr/bin/env bash
set -euo pipefail

# Cerberus 17.5 -- the downloads telemetry exercise (ADR 0030 Decisions 9, 11
# and 12): apply dev-compute -> generate downloads events -> promote to silver
# -> DESTROY -> dbt marts -> data quality, in one command. The cluster is the
# only part that costs money, so it is destroyed before dbt and the checks,
# which are Athena-only.
#
#   orchestration/launch_exercise.sh --generate EVENTS [--yes]
#                                    [--generator-executors N] [--executor-nodes N]
#                                    [--run-id ID] [--congestion two-pass|curve]
#                                    [--estimate-usd N]
#   orchestration/launch_exercise.sh --check
#
#   --check           preflight only: exercise.sh --check, the spend guard, the
#                     account lookup. Read-only; records nothing.
#   --generate EVENTS target event count (for example 1000000, then 10000000).
#   --yes             skip the one confirmation before the apply.
#   --generator-executors N   the generator's fixed executor count (default 2).
#   --executor-nodes N        Spot executor nodes (default 1; ADR 0020).
#   --run-id ID       default dl-<EVENTS>-<UTC stamp>; ^[a-z0-9-]{1,40}$.
#   --congestion MODE two-pass (default) or curve.
#   --estimate-usd N  the spend-guard estimate for this run (default 1.00;
#                     unverified: about $0.40/h x 1 h plus an allowance).
#
# Spend guard (ADR 0030 Decision 12). `python3 launch/ledger.py guard --next-usd
# N` must exit 0 before anything is applied, `record --kind exercise` is
# written before the apply and `correct` at exit. The script fails closed: no
# launch/ledger.py (17.4 builds it) or a non-zero guard means no apply. The
# teardown never calls the guard.
#
# Lifecycle, copied from exercise.sh: the destroy runs from an EXIT trap, so it
# also runs after a failed apply, a failed run, SIGINT, SIGTERM and SIGHUP. It
# runs under setsid (tfq) so a terminal Ctrl-C cannot reach terraform. A failed
# destroy, or any billable resource left in the account-wide check, exits
# non-zero. Bash runs a trap after the foreground command ends, so a SIGTERM
# takes effect when the running step returns.
#
# There is no flag to keep the cluster: a forgotten cluster costs money, and the
# destroy always runs.
#
# Bucket names are read at runtime from STS and never written to a file: the
# log is masked, and the run record has counts only.
#
# Claude Code's auto mode blocks `terraform apply`: run this from your own
# terminal. The owner reads `make compute-plan` first: the first run also
# applies the iam_spark downloads grant.

REGION="us-east-1"
ADMIN_PROFILE="cerberus-admin"
TRANSFORM_PROFILE="cerberus-transform"
# Terraform's S3 backend and providers, and kubectl's token helper, read
# these from the environment.
export AWS_PROFILE="$ADMIN_PROFILE" AWS_REGION="$REGION"
CLUSTER_NAME="cerberus-platform-eks"
NAMESPACE="spark-jobs"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPUTE_DIR="$REPO/terraform/envs/dev-compute"
SPARK_DIR="$REPO/transform/spark"
LEDGER="$REPO/launch/ledger.py"
TF="${TF_BIN:-terraform}"
# The all-in dev-compute rate (ADR 0030 Decision 12, about $0.40/h) and a flat
# allowance for Athena, S3 and CloudWatch. The allowance is unverified.
RATE_USD_PER_HOUR="0.40"
ALLOWANCE_USD="${ALLOWANCE_USD:-0.25}"
# A Spark app that runs longer than this is stopped and the run fails, so a
# stuck job cannot hold the cluster open. Unverified: the plan expects 20-40
# minutes at 100M events.
APP_TIMEOUT_SECONDS="${APP_TIMEOUT_SECONDS:-5400}"

YES=false CHECK=false GENERATE="" RUN_ID="" CONGESTION="two-pass"
EXECUTOR_NODES=1 GENERATOR_EXECUTORS=2 ESTIMATE_USD="1.00"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES=true ;;
    --check) CHECK=true ;;
    --generate) GENERATE="${2:?--generate needs a value}"; shift ;;
    --generator-executors) GENERATOR_EXECUTORS="${2:?}"; shift ;;
    --executor-nodes) EXECUTOR_NODES="${2:?}"; shift ;;
    --run-id) RUN_ID="${2:?}"; shift ;;
    --congestion) CONGESTION="${2:?}"; shift ;;
    --estimate-usd) ESTIMATE_USD="${2:?}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
log() { echo "[$(date -u +%FT%TZ)] $*"; }
die() { log "$*"; exit 2; }
aws_() { aws --profile "$ADMIN_PROFILE" --region "$REGION" "$@"; }
tf() { "$TF" -chdir="$COMPUTE_DIR" "$@"; }
# setsid -w runs terraform in its own session, where the terminal's Ctrl-C never
# reaches it (Terraform re-enables SIGINT for itself). The teardown only.
tfq() { setsid -w "$TF" -chdir="$COMPUTE_DIR" "$@"; }

if ! $CHECK; then
  [[ "$GENERATE" =~ ^[1-9][0-9]*$ ]] || die "--generate EVENTS is required (a positive integer)"
  [[ "$GENERATOR_EXECUTORS" =~ ^[1-9][0-9]*$ ]] || die "--generator-executors must be a positive integer"
  [[ "$EXECUTOR_NODES" =~ ^[1-9][0-9]*$ ]] || die "--executor-nodes must be a positive integer"
fi
[[ "$CONGESTION" == "two-pass" || "$CONGESTION" == "curve" ]] || die "--congestion must be two-pass or curve"
[[ "$ESTIMATE_USD" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "--estimate-usd must be a number"
if [[ -z "$RUN_ID" ]]; then
  RUN_ID="dl-${GENERATE:-0}-$(printf '%s' "$STAMP" | tr '[:upper:]' '[:lower:]')"
fi
[[ "$RUN_ID" =~ ^[a-z0-9-]{1,40}$ ]] || die "--run-id must match ^[a-z0-9-]{1,40}\$"

# Fail closed: no ledger, no apply. 17.4 owns launch/ledger.py.
if [[ ! -f "$LEDGER" ]]; then
  die "REFUSED: launch/ledger.py is missing (17.4 builds the spend guard). Nothing was applied."
fi

CLUSTER_UP="" RECORDED=false FINAL_STATUS="" DQ_RC="" DBT_RC="" PROMOTE_LINE="" CDN="false"
LOG_DIR="$REPO/observability/launch/exercises"
RUN_DIR="$REPO/observability/launch/runs"
LOG="$LOG_DIR/launch-exercise-$STAMP.log"

preflight() {
  log "preflight"
  ACCOUNT="$(aws_ sts get-caller-identity --query Account --output text)"
  [[ "$ACCOUNT" =~ ^[0-9]{12}$ ]] || { log "  STOP: cannot read the account from STS"; return 1; }
  BRONZE="cerberus-platform-bronze-$ACCOUNT"
  SILVER="cerberus-platform-silver-$ACCOUNT"
  log "  identity: ok (account masked)"
  "$REPO/orchestration/exercise.sh" --check || { log "  STOP: exercise.sh --check failed"; return 1; }
  if ! python3 "$LEDGER" guard --next-usd "$ESTIMATE_USD"; then
    log "  REFUSED by the spend guard (estimate \$$ESTIMATE_USD). Nothing was applied."
    return 1
  fi
  log "  spend guard: allowed (estimate \$$ESTIMATE_USD)"
}

# The run record: counts and statuses only, no bucket names. Best-effort: the
# data-quality suite reads these files, and check 8 reads `cdn_logs_collected`.
write_record() {
  # runs/<run_id>/run.json is the layout 17.4 uses; the data-quality suite reads it.
  local file="$RUN_DIR/$RUN_ID/run.json"
  mkdir -p "$RUN_DIR/$RUN_ID"
  RUN_ID="$RUN_ID" STAGE="$1" EVENTS="${GENERATE:-0}" CLUSTER_SECONDS="$(cluster_seconds)" \
    PROMOTE_LINE="$PROMOTE_LINE" DBT_RC="$DBT_RC" DQ_RC="$DQ_RC" CDN="$CDN" STAMP="$STAMP" \
    python3 - "$file" <<'PY' || true
import json, os, sys
record = {
    "kind": "exercise",
    "run_id": os.environ["RUN_ID"],
    "started": os.environ["STAMP"],
    "stage": os.environ["STAGE"],
    "events_requested": int(os.environ["EVENTS"]),
    "cluster_seconds": int(os.environ["CLUSTER_SECONDS"]),
    "promote": os.environ["PROMOTE_LINE"],
    "dbt_exit": os.environ["DBT_RC"] or None,
    "data_quality_exit": os.environ["DQ_RC"] or None,
    "cdn_models_built": os.environ["CDN"] == "true",
    # The exercise never collects CloudFront logs (launch-collect does); a true
    # value written for this run_id by launch_collect.sh is kept.
    "cdn_logs_collected": False,
}
try:
    with open(sys.argv[1]) as handle:
        if json.load(handle).get("cdn_logs_collected") is True:
            record["cdn_logs_collected"] = True
except (OSError, ValueError, AttributeError):
    pass
with open(sys.argv[1], "w") as handle:
    json.dump(record, handle, indent=2)
    handle.write("\n")
PY
}

CLUSTER_STARTED=""
CLUSTER_TOTAL=0
cluster_seconds() {
  if [[ -n "$CLUSTER_STARTED" ]]; then
    echo $((CLUSTER_TOTAL + SECONDS - CLUSTER_STARTED))
  else
    echo "$CLUSTER_TOTAL"
  fi
}

# Destroys dev-compute and runs the account-wide check. Returns 0 only when
# nothing billable is left. Used by the normal path (before dbt) and by the EXIT
# trap; it never calls the spend guard.
destroy_cluster() {
  local destroy_start=$SECONDS
  log "destroying dev-compute -- let it finish; Ctrl-C is ignored from here"
  # -lock-timeout: an interrupted apply can hold the state lock for a moment.
  if ! tfq destroy -auto-approve -input=false -lock-timeout=120s; then
    log "destroy failed once, retrying"
    tfq destroy -auto-approve -input=false -lock-timeout=120s || {
      log "DESTROY FAILED. The cluster may still be running and billing."
      log "Check: make compute-destroy, then the AWS console (EKS, NAT gateways, EC2)."
      return 1
    }
  fi
  log "destroy took $((SECONDS - destroy_start))s"
  # Account-wide, not just this state: the check that matters for the bill.
  local eks nat eip ec2
  eks="$(aws_ eks list-clusters --query 'length(clusters)' --output text)" || return 1
  nat="$(aws_ ec2 describe-nat-gateways --filter Name=state,Values=pending,available \
    --query 'length(NatGateways)' --output text)" || return 1
  eip="$(aws_ ec2 describe-addresses --query 'length(Addresses)' --output text)" || return 1
  ec2="$(aws_ ec2 describe-instances --filters Name=instance-state-name,Values=pending,running \
    --query 'length(Reservations[].Instances[])' --output text)" || return 1
  log "after destroy: EKS $eks, NAT $nat, EIP $eip, running instances $ec2"
  if [[ "$eks$nat$eip$ec2" != "0000" ]]; then
    log "WARNING: something billable is still up -- check before you leave"
    return 1
  fi
}

on_exit() {
  local status=$?
  # Nothing may stop the destroy half-way: not a failing check (set +e), a second
  # Ctrl-C, a closed terminal, or a dead log pipe.
  trap - EXIT
  trap '' INT TERM PIPE HUP
  set +e
  if [[ -n "$CLUSTER_UP" ]]; then
    CLUSTER_TOTAL=$((CLUSTER_TOTAL + SECONDS - CLUSTER_STARTED))
    CLUSTER_STARTED=""
    if destroy_cluster; then
      CLUSTER_UP=""
    else
      status=1
    fi
  fi
  if $RECORDED; then
    local usd
    usd="$(awk -v s="$CLUSTER_TOTAL" -v r="$RATE_USD_PER_HOUR" -v a="$ALLOWANCE_USD" \
      'BEGIN { printf "%.2f", s / 3600 * r + a }')"
    if ! python3 "$LEDGER" correct --run-id "$RUN_ID" --usd "$usd"; then
      log "LEDGER CORRECTION FAILED for $RUN_ID (estimate was \$$ESTIMATE_USD): fix the ledger by hand"
      status=1
    fi
    write_record "${FINAL_STATUS:-failed}"
  fi
  exit "$status"
}

wait_for_app() { # wait_for_app NAME: poll the SparkApplication, give up after the timeout
  local name="$1" state="" deadline=$((SECONDS + APP_TIMEOUT_SECONDS))
  while [[ "$state" != "COMPLETED" && "$state" != "FAILED" ]]; do
    if ((SECONDS > deadline)); then
      log "$name: no result after ${APP_TIMEOUT_SECONDS}s -- giving up"
      return 1
    fi
    sleep 10
    state="$(kubectl get sparkapplication "$name" -n "$NAMESPACE" \
      -o jsonpath='{.status.applicationState.state}' 2>/dev/null || true)"
    log "$name state: ${state:-<not yet reported>}"
  done
  if [[ "$state" != "COMPLETED" ]]; then
    log "$name $state -- driver logs:"
    kubectl logs "${name}-driver" -n "$NAMESPACE" || true
    return 1
  fi
}

run_generator() {
  local now manifest
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "generator: $GENERATE events, run_id $RUN_ID, now $now"
  aws s3 cp "$SPARK_DIR/generate_bulk_downloads.py" \
    "s3://$SILVER/_spark_jobs/generate_bulk_downloads.py" \
    --profile "$TRANSFORM_PROFILE" --region "$REGION" >/dev/null
  kubectl delete sparkapplication cerberus-generate-bulk-downloads -n "$NAMESPACE" --ignore-not-found
  manifest="$(mktemp)"
  sed -e "s|__RUN_ID__|${RUN_ID}|" \
    -e "s|__EVENTS__|${GENERATE}|" \
    -e "s|__NOW__|${now}|" \
    -e "s|__EXECUTORS__|${GENERATOR_EXECUTORS}|" \
    -e "s|__CONGESTION__|${CONGESTION}|" \
    -e "s|__OUTPUT__|s3a://${BRONZE}/downloads_bulk/|" \
    -e "s|__SILVER_BUCKET__|${SILVER}|" \
    "$SPARK_DIR/spark-application-generate-downloads.yaml" >"$manifest"
  kubectl apply -f "$manifest"
  wait_for_app cerberus-generate-bulk-downloads
  kubectl logs cerberus-generate-bulk-downloads-driver -n "$NAMESPACE" | grep '^\[generate\]' || true
}

run_promote() {
  local out
  out="$(mktemp)"
  log "promote: downloads silver job"
  APP_NAME="cerberus-promote-downloads" \
    SCRIPT_NAME="promote_downloads_spark.py" \
    MANIFEST_YAML="spark-application-promote-downloads.yaml" \
    EXTRA_SED="s|__SILVER_BUCKET__|${SILVER}|g;s|__BRONZE_ROOT__|s3a://${BRONZE}/|g;s|__WAREHOUSE__|s3://${SILVER}/iceberg/|g" \
    timeout -k 30 "$APP_TIMEOUT_SECONDS" "$SPARK_DIR/submit_job.sh" | tee "$out"
  kubectl logs cerberus-promote-downloads-driver -n "$NAMESPACE" 2>/dev/null \
    | grep 'appended .* new events' >"$out.line" || true
  PROMOTE_LINE="$(head -1 "$out.line" 2>/dev/null || true)"
  log "promote: ${PROMOTE_LINE:-no 'appended' line in the driver log}"
}

if $CHECK; then
  preflight
  log "preflight passed"
  exit 0
fi

# The account lookup is silent; from here the log and the screen are masked.
ACCOUNT="$(aws_ sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT" =~ ^[0-9]{12}$ ]] || die "cannot read the account from STS"
mkdir -p "$LOG_DIR"
# tee ignores INT/TERM so the log pipe outlives a Ctrl-C and the teardown's
# output still reaches the screen and the log.
exec > >(
  trap '' INT TERM HUP
  sed -u "s/${ACCOUNT}/<ACCOUNT_ID>/g" | tee -a "$LOG"
) 2>&1
log "launch exercise $RUN_ID -- log: ${LOG#"$REPO"/}"
preflight

if ! $YES; then
  read -r -p "Apply dev-compute (about \$0.40/hour until the destroy)? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { log "cancelled"; exit 0; }
fi

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# The ledger entry comes before the apply. If it cannot be written, nothing is applied.
python3 "$LEDGER" record --run-id "$RUN_ID" --kind exercise --estimate-usd "$ESTIMATE_USD"
RECORDED=true

# Plan and apply back to back: a saved dev-compute plan carries an EKS token
# that expires after about 15 minutes (see exercise.sh).
PLAN="$(mktemp -d)/dev-compute.tfplan"
CLUSTER_UP=$SECONDS
CLUSTER_STARTED=$SECONDS
log "spot executor nodes: $EXECUTOR_NODES"
tf init -input=false -no-color >/dev/null
tf plan -input=false -var "executor_nodes=$EXECUTOR_NODES" -out="$PLAN" >/dev/null
tf apply -input=false "$PLAN"
log "apply took $((SECONDS - CLUSTER_STARTED))s"

aws_ eks update-kubeconfig --name "$CLUSTER_NAME" >/dev/null
kubectl wait --for=condition=Ready nodes --all --timeout=300s
kubectl wait --for=condition=Available deployment --all -n spark-operator --timeout=300s

run_generator
run_promote

# The cluster has done its work: destroy it before the Athena-only steps, so
# they cost no cluster minutes. A failure here ends the run (non-zero).
CLUSTER_TOTAL=$((CLUSTER_TOTAL + SECONDS - CLUSTER_STARTED))
CLUSTER_STARTED=""
if ! destroy_cluster; then
  CLUSTER_STARTED=$SECONDS
  exit 1
fi
CLUSTER_UP=""
write_record "silver_done"

# dbt runs locally as cerberus-transform. The CDN models need real log files in
# bronze (launch-collect); an unreadable listing leaves them off, and data-quality
# check 8 then warns (and check 9 fails to query) if a run record says logs were collected.
# The backticks below are JMESPath literals, not shell.
# shellcheck disable=SC2016
CDN_KEYS="$(aws --profile "$TRANSFORM_PROFILE" --region "$REGION" s3api list-objects-v2 \
  --bucket "$BRONZE" --prefix downloads_cdn/ --max-keys 1 \
  --query 'length(Contents || `[]`)' --output text 2>/dev/null || echo "error")"
case "$CDN_KEYS" in
  0) CDN="false"; log "no downloads_cdn/ objects: CDN models stay off" ;;
  error) CDN="false"; log "WARNING: cannot list downloads_cdn/: CDN models stay off" ;;
  *) CDN="true" ;;
esac
# The k6 request counts of the run records label fct_cdn_run (logs_status). A
# record without an integer count is left out: that run reads "unknown".
K6="$(python3 - "$RUN_DIR" <<'PY' || echo "{}"
import glob, json, os, re, sys
counts = {}
for path in sorted(glob.glob(os.path.join(sys.argv[1], "*", "run.json"))):
    try:
        with open(path) as handle:
            record = json.load(handle)
        run_id, k6 = record.get("run_id"), record.get("k6_requests")
        if (isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id)
                and isinstance(k6, int) and not isinstance(k6, bool) and k6 > 0):
            counts[run_id] = k6
    except (OSError, ValueError, AttributeError):
        pass
print(json.dumps(counts))
PY
)"
log "dbt build (downloads marts, enable_downloads_cdn=$CDN)"
DBT_RC=0
(
  cd "$REPO/transform/dbt"
  env -u AWS_PROFILE uv run --no-project --python 3.12 --with-requirements requirements.txt \
    dbt build --select path:models/marts/downloads source:cerberus_downloads \
    --vars "{enable_downloads: true, enable_downloads_cdn: $CDN, k6_requests_by_run: $K6}"
) || DBT_RC=$?

log "data quality (downloads)"
DQ_RC=0
DQ_JSON="$(mktemp)"
env -u AWS_PROFILE uv run --no-project --with boto3 python \
  "$REPO/observability/launch/data_quality_downloads.py" \
  --run-id "$RUN_ID" --bronze-bucket "$BRONZE" --json-out "$DQ_JSON" || DQ_RC=$?

FINAL_STATUS="done"
[[ "$DBT_RC" == 0 && "$DQ_RC" == 0 ]] || FINAL_STATUS="failed"
write_record "$FINAL_STATUS"

[[ "$DBT_RC" == 0 ]] || { log "dbt build FAILED (exit $DBT_RC)"; }
if [[ "$DQ_RC" == 3 ]]; then
  log "DATA QUALITY FAILED"
  exit 3
fi
[[ "$DQ_RC" == 0 ]] || { log "data-quality suite did not run (exit $DQ_RC)"; exit 1; }
[[ "$DBT_RC" == 0 ]] || exit 1
log "launch exercise done: cluster destroyed, silver and gold built, data quality passed"
