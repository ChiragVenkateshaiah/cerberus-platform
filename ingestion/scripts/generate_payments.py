#!/usr/bin/env python3
"""Cerberus 1.3 — synthetic payments generator (CLI).

Generates a batch of synthetic payment-event lifecycles (per ADR 0003:
single denormalized event per transaction step, append-only, pre-masked
payment_method, no real PII) and lands them as raw JSON in the bronze
bucket under payments/dt=YYYY-MM-DD/, partitioned by the day each event
occurred.

Merchants and customers are drawn from a small, deterministically seeded
roster (reused across runs) so joins/aggregations in later phases are
meaningful instead of degenerate, per ADR 0003.

Thin CLI wrapper around payments_lib.py's shared generation core -- the
same core the Lambda handler (../lambda/handler.py, 2.1/ADR 0005) uses for
the EventBridge-scheduled path. This script stays a plain, always-runnable
entry point for manual runs, per ADR 0003/checkpoint history.
"""
import argparse
import random
from datetime import datetime, timezone

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

BUCKET = "cerberus-platform-bronze-131715059025"
# Assumes the least-privilege cerberus-ingestion role (1.6), scoped to
# s3:PutObject on bronze/payments/* only -- chained via role_arn +
# source_profile in ~/.aws/config, same pattern as cerberus-transform/
# cerberus-serving. Not the default cerberus-admin credentials.
AWS_PROFILE = "cerberus-ingestion"
AWS_REGION = "us-east-1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count", type=int, default=DEFAULT_TRANSACTION_COUNT,
        help="number of transaction lifecycles to generate this run",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    run_ts = now.strftime("%Y%m%dT%H%M%SZ")
    print(f"[{iso(now)}] starting payments generation run ({args.count} transactions)")

    merchants, customers = build_roster()
    rng = random.Random()  # unseeded: event content varies run to run

    events = generate_events(args.count, merchants, customers, rng, now)
    print(f"[{iso(datetime.now(timezone.utc))}] generated {len(events)} events across {args.count} transactions")

    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    s3 = session.client("s3", config=S3_CLIENT_CONFIG)

    by_day = partition_by_day(events)
    failed_days = [
        day for day in sorted(by_day) if not upload_day(s3, BUCKET, day, by_day[day], run_ts)
    ]

    if failed_days:
        print(f"[{iso(datetime.now(timezone.utc))}] done with errors — {len(by_day) - len(failed_days)}/{len(by_day)} partition(s) uploaded; failed: {', '.join(failed_days)}")
        raise SystemExit(1)

    print(f"[{iso(datetime.now(timezone.utc))}] done — {len(by_day)} partition(s) touched")


if __name__ == "__main__":
    main()
