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

log "running dbt build (models + tests) against gold"
dbt build --project-dir /opt/dbt --profiles-dir /opt/dbt
log "dbt build complete"
