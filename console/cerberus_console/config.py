"""Constants. Nothing here is read from visitor input (ADR 0024 rules 2 and 6)."""

import os
from pathlib import Path

REGION = "us-east-1"
STATE_MACHINE_NAME = "cerberus-platform-orchestration"
ROLE_NAME = "cerberus-console-cli"
WORKGROUP = "cerberus_platform_console"
DATABASE = "cerberus_platform"

# Must match `gold_table_names` in terraform/modules/console_roles/variables.tf
# (tests/test_tables_match_iam.py checks it): the IAM role can read only these.
GOLD_TABLES = ("fct_transactions", "dim_customers", "dim_merchants")

# The one query the console ever runs. A constant: no formatting, no input. It
# reads Iceberg metadata only. payments_current is left out because it has not
# been refreshed since 2026-08-10.
FRESHNESS_SQL = (
    "SELECT 'fct_transactions' AS table_name, max(committed_at) AS last_commit "
    'FROM "cerberus_platform"."fct_transactions$snapshots" '
    "UNION ALL SELECT 'dim_customers', max(committed_at) "
    'FROM "cerberus_platform"."dim_customers$snapshots" '
    "UNION ALL SELECT 'dim_merchants', max(committed_at) "
    'FROM "cerberus_platform"."dim_merchants$snapshots"'
)

# Input limits (ADR 0024 rule 1).
MAX_BODY_BYTES = 2048
MAX_TOKENS = 8
MAX_TOKEN_CHARS = 64

# Run records: where they are, and how much of them we will read.
RUNS_DIR = Path(
    os.environ.get(
        "CERBERUS_RUNS_DIR",
        str(Path(__file__).resolve().parents[2] / "observability" / "scale" / "runs"),
    )
)
MAX_RECORD_FILES = 200
MAX_RECORD_BYTES = 256 * 1024

# Output caps (ADR 0024 rule 4).
FIELD_CHARS = 200
TABLE_ROWS = 50
TEXT_BYTES = 16 * 1024
RESPONSE_BYTES = 64 * 1024
ERROR_CODE_CHARS = 64

# Cache lifetimes, in seconds. They bound the AWS calls (and the Athena bill)
# a visitor can cause.
LIST_EXECUTIONS_TTL = 30
FRESHNESS_TTL = 300

# Step Functions keeps a closed Standard execution's history this many days
# (service quotas page, read 2026-11-01).
SFN_HISTORY_DAYS = 90
SFN_LIST_PAGE = 100
SFN_LIST_PAGES = 2

# Athena: poll every 0.5 s (growing to 2 s) and give up after 12 s.
QUERY_POLL_SECONDS = 0.5
QUERY_DEADLINE_SECONDS = 12.0

# The SLO targets, from docs/slo.md.
SLO_WINDOW = 20
SLO1_TARGET_PCT = 95.0
SLO3_LIMIT_SECONDS = 1800
SLO3_TARGET_PCT = 90.0
SLO4_LIMIT_SECONDS = 30
SLO4_TARGET_PCT = 99.0
