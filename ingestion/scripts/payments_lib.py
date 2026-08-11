"""Cerberus 1.3/2.1 — shared synthetic payments generation core.

Pure generation logic (roster, event lifecycle, day-partitioning) plus a
boto3-based upload-with-retry helper, shared between the CLI script
(generate_payments.py, for manual/systemd-triggered runs) and the Lambda
handler (../lambda/handler.py, for the EventBridge-scheduled path — 2.1,
ADR 0005). Kept free of argparse/Lambda specifics so both callers can
import it unchanged; each caller supplies its own boto3 S3 client, since
the two run under different credentials (a chained CLI profile vs. a
Lambda execution role).
"""
import json
import random
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError
from faker import Faker

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

UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_DELAY_SECONDS = 5


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


def upload_day(s3_client, bucket, day, day_events, run_ts,
                max_attempts=UPLOAD_MAX_ATTEMPTS,
                retry_delay=UPLOAD_RETRY_DELAY_SECONDS, log=print):
    """Uploads one day's events via S3 PutObject, retrying transient
    failures. Returns True on success, False if every attempt failed --
    callers must not let one day's failure stop the rest of the run from
    being attempted, since a failed day's events can't be regenerated
    identically (callers use an unseeded rng for event content).
    """
    body = json.dumps(day_events).encode("utf-8")
    s3_key = f"payments/dt={day}/payments_{run_ts}.json"
    for attempt in range(1, max_attempts + 1):
        try:
            s3_client.put_object(
                Bucket=bucket, Key=s3_key, Body=body,
                ContentType="application/json",
            )
            log(f"[{iso(datetime.now(timezone.utc))}] uploaded s3://{bucket}/{s3_key} ({len(day_events)} events)")
            return True
        except ClientError as exc:
            if attempt < max_attempts:
                log(f"[{iso(datetime.now(timezone.utc))}] upload attempt {attempt}/{max_attempts} for {day} failed ({exc}), retrying in {retry_delay}s")
                time.sleep(retry_delay)
            else:
                log(f"[{iso(datetime.now(timezone.utc))}] upload for {day} failed after {max_attempts} attempts ({exc}) -- {len(day_events)} events for this partition were NOT saved")
    return False
