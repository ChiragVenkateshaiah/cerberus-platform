"""Cerberus 2.1 — ingestion Lambda handler (ADR 0005).

Wraps payments_lib.py's shared generation core for the EventBridge
Scheduler-triggered path (2.2): a daily invocation, no meaningful event
payload. Replaces cerberus-payments.timer + run_payments_scheduled.sh's
trigger role, not the generator itself -- the generation logic
(build_roster, generate_events) carries over unchanged; only how it's
triggered and how it authenticates change.

Auth: runs as its own least-privilege execution role
(terraform/modules/iam -- cerberus-ingestion-lambda, same s3:PutObject
scope as cerberus-ingestion), via the default credential chain -- not a
CLI-profile chain, since Lambda has no ~/.aws/config equivalent.

Retirement: RETIRE_ON_OR_AFTER is the SAME window run_payments_scheduled.sh
already started (first systemd run 2026-08-07 -> 10-day cap), not a fresh
window from this Lambda's own deploy date, since both mechanisms write
into the same bronze dataset. Decided 2026-08-11 (see ADR 0005's
Consequences) to keep the cap for data-volume control, not cost -- at this
project's actual data rate, running the schedule longer costs fractions of
a cent either way. On/after that date this no-ops rather than disabling
the EventBridge schedule itself: doing that would need scheduler:*
permissions this role deliberately doesn't have. Same "soft retire, don't
delete" shape 1.3's wrapper already established -- disable/delete the
schedule by hand (`terraform/modules/lambda_ingestion`) to fully stop it.

Retry: the EventBridge schedule is configured with MaximumRetryAttempts=0
(terraform/modules/lambda_ingestion) -- an invocation-level retry would
regenerate a different, unseeded dataset and duplicate data into
append-only bronze (ADR 0005's Consequences). The only retry layer is
payments_lib.S3_CLIENT_CONFIG's client-level retry (botocore "standard"
mode: exponential backoff, genuinely-retryable errors only) on each
partition's put_object call -- not a hand-rolled loop.
"""

import os
import random
from datetime import UTC, datetime

import boto3
from payments_lib import (
    DEFAULT_TRANSACTION_COUNT,
    S3_CLIENT_CONFIG,
    build_roster,
    generate_events,
    iso,
    partition_by_day,
    upload_day,
)

BUCKET = os.environ["BRONZE_BUCKET"]
RETIRE_ON_OR_AFTER = os.environ.get("RETIRE_ON_OR_AFTER", "2026-08-17")
TRANSACTION_COUNT = int(os.environ.get("TRANSACTION_COUNT", DEFAULT_TRANSACTION_COUNT))

_s3 = boto3.client("s3", config=S3_CLIENT_CONFIG)


def handler(event, context):
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if today >= RETIRE_ON_OR_AFTER:
        msg = (
            f"retirement date reached ({RETIRE_ON_OR_AFTER}) -- skipping "
            "generation. Disable or delete the EventBridge schedule by "
            "hand to fully stop this Lambda."
        )
        print(f"[{iso(datetime.now(UTC))}] {msg}")
        return {"status": "retired"}

    now = datetime.now(UTC)
    run_ts = now.strftime("%Y%m%dT%H%M%SZ")
    print(f"[{iso(now)}] starting payments generation run ({TRANSACTION_COUNT} transactions)")

    merchants, customers = build_roster()
    rng = random.Random()  # unseeded: event content varies run to run

    events = generate_events(TRANSACTION_COUNT, merchants, customers, rng, now)
    ts = iso(datetime.now(UTC))
    print(f"[{ts}] generated {len(events)} events across {TRANSACTION_COUNT} transactions")

    by_day = partition_by_day(events)
    failed_days = [
        day for day in sorted(by_day) if not upload_day(_s3, BUCKET, day, by_day[day], run_ts)
    ]

    if failed_days:
        uploaded = len(by_day) - len(failed_days)
        msg = (
            f"done with errors — {uploaded}/{len(by_day)} partition(s) uploaded; "
            f"failed: {', '.join(failed_days)}"
        )
        print(f"[{iso(datetime.now(UTC))}] {msg}")
        # Raised only to surface the failure in CloudWatch -- the schedule
        # has no invocation-level retry configured, so this does not
        # trigger a re-run (see module docstring above).
        raise RuntimeError(msg)

    print(f"[{iso(datetime.now(UTC))}] done — {len(by_day)} partition(s) touched")
    return {"status": "ok", "partitions_touched": len(by_day)}
