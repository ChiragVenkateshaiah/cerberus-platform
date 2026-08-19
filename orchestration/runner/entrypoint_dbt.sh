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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

log "running dbt against gold"
dbt run --project-dir /opt/dbt --profiles-dir /opt/dbt
log "dbt run complete"
