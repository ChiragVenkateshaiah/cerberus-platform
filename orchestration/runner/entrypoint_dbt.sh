#!/usr/bin/env bash
set -euo pipefail

# Runs dbt's gold fact/dimension models (1.9) inside the "dbt" ECS Fargate
# task Step Functions invokes via RunDbt (4.2). /opt/dbt/profiles.yml is
# the committed transform/dbt/profiles.yml with its aws_profile_name line
# stripped at image build time (Dockerfile) -- that line names a CLI
# profile this container doesn't have; the task role
# (cerberus-orchestration-dbt) supplies credentials directly instead. The
# dbt project itself is baked into /opt/dbt at image build time (no CI/CD
# pipeline yet to fetch it fresh at run time -- Phase 5).
#
# 6.3: `dbt build`, not `dbt run` -- builds the marts and then runs the
# schema tests in models/sources.yml and models/marts/schema.yml against
# them in the same pass. A test failure exits this script non-zero, which
# fails this ECS task, which fails the RunDbt state, which fails the whole
# orchestrated execution -- tripping 6.2's cerberus-pipeline-run-unsuccessful
# alarm. That's the mechanism behind plan.md's Phase 6 "done when": bad
# data fails the pipeline loudly instead of landing silently in gold.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

# 6.4c: `dbt-ol build`, not `dbt build` -- the openlineage-dbt wrapper runs
# dbt normally, then emits OpenLineage events (dataset + column-level
# lineage for each mart) from target/manifest.json + run_results.json to
# the collector at $OPENLINEAGE_URL (6.4b, set on this task definition).
# Verified 2026-09-06: dbt-ol emits AFTER dbt finishes and returns dbt's
# own exit code -- a collector outage logs a ConnectionError and emits 0
# events, it never fails this task. With OPENLINEAGE_URL unset the wrapper
# falls back to a console transport (harmless), so this is unconditional.
export OPENLINEAGE_NAMESPACE="${OPENLINEAGE_NAMESPACE:-cerberus-platform}"
if [ -n "${OPENLINEAGE_URL:-}" ]; then
  log "running dbt-ol build (models + tests) against gold -- lineage -> $OPENLINEAGE_URL"
else
  log "running dbt-ol build (models + tests) against gold -- OPENLINEAGE_URL unset, events to console only"
fi
dbt-ol build --project-dir /opt/dbt --profiles-dir /opt/dbt
log "dbt-ol build complete"
