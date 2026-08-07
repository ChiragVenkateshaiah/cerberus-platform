#!/usr/bin/env python3
"""Cerberus 1.3 — synthetic payments generator.

Generates a batch of synthetic payment-event lifecycles (per ADR 0003:
single denormalized event per transaction step, append-only, pre-masked
payment_method, no real PII) and lands them as raw JSON in the bronze
bucket under payments/dt=YYYY-MM-DD/, partitioned by the day each event
occurred.

Merchants and customers are drawn from a small, deterministically seeded
roster (reused across runs) so joins/aggregations in later phases are
meaningful instead of degenerate, per ADR 0003.
"""
import argparse
import json
import random
import subprocess
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

BUCKET = "cerberus-platform-bronze-131715059025"
AWS_PROFILE = "cerberus-admin"
AWS_REGION = "us-east-1"

ROSTER_SEED = 42
MERCHANT_COUNT = 15
CUSTOMER_COUNT = 75
DEFAULT_TRANSACTION_COUNT = 200

MERCHANT_CATEGORIES = [
    "retail", "grocery", "travel", "electronics", "dining",
    "subscription", "fuel", "utilities",
]
CARD_BRANDS = ["visa", "mastercard", "amex"]
CURRENCIES = ["USD", "USD", "USD", "EUR", "GBP"]

CREATED_WINDOW_DAYS = 7
AUTH_DELAY_SECONDS = (5, 120)
SETTLE_DELAY_HOURS = (1, 72)
DECLINE_PROBABILITY = 0.05
REFUND_PROBABILITY = 0.05
REFUND_DELAY_DAYS = (1, 14)


def build_roster():
    """Deterministic merchant/customer roster, stable across runs."""
    rng = random.Random(ROSTER_SEED)
    fake = Faker()
    fake.seed_instance(ROSTER_SEED)

    merchants = [
        {
            "merchant_id": f"mrc_{i:04d}",
            "name": fake.company(),
            "category": rng.choice(MERCHANT_CATEGORIES),
        }
        for i in range(1, MERCHANT_COUNT + 1)
    ]
    customers = []
    for i in range(1, CUSTOMER_COUNT + 1):
        first, last = fake.first_name(), fake.last_name()
        customers.append({
            "customer_id": f"cus_{i:04d}",
            "name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}{i:04d}@example.com",
        })
    return merchants, customers


def make_payment_method(rng):
    method_type = rng.choices(
        ["card", "bank_transfer", "wallet"], weights=[70, 20, 10]
    )[0]
    token = f"tok_{uuid.uuid4().hex[:16]}"
    if method_type == "card":
        return {
            "type": "card",
            "brand": rng.choice(CARD_BRANDS),
            "last4": f"{rng.randint(0, 9999):04d}",
            "token": token,
        }
    return {"type": method_type, "token": token}


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_events(count, merchants, customers, rng, now):
    events = []
    for _ in range(count):
        merchant = rng.choice(merchants)
        customer = rng.choice(customers)
        payment_method = make_payment_method(rng)
        amount = round(rng.uniform(1.00, 999.99), 2)
        currency = rng.choice(CURRENCIES)
        transaction_id = f"txn_{uuid.uuid4().hex}"

        created_ts = now - timedelta(
            seconds=rng.randint(0, CREATED_WINDOW_DAYS * 86400)
        )

        def event(event_type, ts):
            return {
                "transaction_id": transaction_id,
                "event_type": event_type,
                "event_timestamp": iso(min(ts, now)),
                "amount": amount,
                "currency": currency,
                "merchant": merchant,
                "customer": customer,
                "payment_method": payment_method,
            }

        events.append(event("created", created_ts))

        auth_ts = created_ts + timedelta(
            seconds=rng.randint(*AUTH_DELAY_SECONDS)
        )
        auth_ts = min(auth_ts, now)
        events.append(event("authorized", auth_ts))

        if rng.random() < DECLINE_PROBABILITY:
            events.append(event("failed", auth_ts + timedelta(seconds=rng.randint(1, 30))))
            continue

        settle_ts = auth_ts + timedelta(hours=rng.randint(*SETTLE_DELAY_HOURS))
        settle_ts = min(settle_ts, now)
        events.append(event("settled", settle_ts))

        if rng.random() < REFUND_PROBABILITY:
            refund_ts = settle_ts + timedelta(days=rng.randint(*REFUND_DELAY_DAYS))
            events.append(event("refunded", min(refund_ts, now)))

    return events


def partition_by_day(events):
    by_day = defaultdict(list)
    for event in events:
        day = event["event_timestamp"][:10]
        by_day[day].append(event)
    return by_day


def upload(day, day_events, run_ts):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(day_events, f)
        tmp_path = f.name
    try:
        s3_key = f"payments/dt={day}/payments_{run_ts}.json"
        subprocess.run(
            [
                "aws", "s3", "cp", tmp_path, f"s3://{BUCKET}/{s3_key}",
                "--profile", AWS_PROFILE,
                "--region", AWS_REGION,
                "--content-type", "application/json",
            ],
            check=True,
        )
        print(f"[{iso(datetime.now(timezone.utc))}] uploaded s3://{BUCKET}/{s3_key} ({len(day_events)} events)")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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

    by_day = partition_by_day(events)
    for day in sorted(by_day):
        upload(day, by_day[day], run_ts)

    print(f"[{iso(datetime.now(timezone.utc))}] done — {len(by_day)} partition(s) touched")


if __name__ == "__main__":
    main()
