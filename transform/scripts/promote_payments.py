#!/usr/bin/env python3
"""Cerberus 1.7 — minimal bronze -> silver -> gold transform.

Full-rebuild each run: reads every payments event currently in bronze,
writes the complete event history to silver as flattened, compacted
Parquet (one file per day partition, overwriting on rebuild -- silver is
derived and always reprocessable, unlike bronze's append-only log), and
resolves latest-event-wins per transaction_id into a gold current-state
table. Still denormalized (merchant/customer inline) -- ADR 0003 assigns
the fact/dimension split to 1.9's dbt models, not this script.

Runs as the cerberus-transform IAM role (1.6), assumed via STS, rather
than the default cerberus-admin credentials -- its first real use.

Also registers each day partition it writes to silver in the Glue Data
Catalog (1.8's payments_events table), via the Glue API directly --
partitions are data, not infrastructure, so Terraform doesn't manage
them; this script does, since it's the thing that knows which day
partitions it just wrote. PARQUET_COLUMNS below must stay in sync with
terraform/modules/glue_catalog/main.tf's column list by hand -- Terraform
and this script don't share a schema source today.
"""

import io
import json

import boto3
import pandas as pd

ACCOUNT_ID = "131715059025"
REGION = "us-east-1"
AWS_PROFILE = "cerberus-admin"
TRANSFORM_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/cerberus-transform"

BRONZE_BUCKET = f"cerberus-platform-bronze-{ACCOUNT_ID}"
SILVER_BUCKET = f"cerberus-platform-silver-{ACCOUNT_ID}"
GOLD_BUCKET = f"cerberus-platform-gold-{ACCOUNT_ID}"

BRONZE_PREFIX = "payments/"

GLUE_DATABASE = "cerberus_platform"
GLUE_SILVER_TABLE = "payments_events"
PARQUET_INPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
PARQUET_OUTPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
PARQUET_SERDE = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
PARQUET_COLUMNS = [
    {"Name": "transaction_id", "Type": "string"},
    {"Name": "event_type", "Type": "string"},
    {"Name": "event_timestamp", "Type": "timestamp"},
    {"Name": "amount", "Type": "double"},
    {"Name": "currency", "Type": "string"},
    {"Name": "merchant_id", "Type": "string"},
    {"Name": "merchant_name", "Type": "string"},
    {"Name": "merchant_category", "Type": "string"},
    {"Name": "customer_id", "Type": "string"},
    {"Name": "customer_name", "Type": "string"},
    {"Name": "customer_email", "Type": "string"},
    {"Name": "payment_method_type", "Type": "string"},
    {"Name": "payment_method_brand", "Type": "string"},
    {"Name": "payment_method_last4", "Type": "string"},
    {"Name": "payment_method_token", "Type": "string"},
]

# generate_payments.py clamps every event's timestamp to min(ts, now), so a
# transaction whose settle and refund events both land after "now" gets
# identical event_timestamp strings for the two -- sorting on timestamp
# alone is not enough to pick the true latest event. This fixed lifecycle
# order (created -> authorized -> settled/failed -> refunded) breaks that
# tie deterministically; settled/failed share a rank since a transaction
# only ever emits one of the two.
EVENT_TYPE_RANK = {
    "created": 0,
    "authorized": 1,
    "settled": 2,
    "failed": 2,
    "refunded": 3,
}


def assumed_session():
    base = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    sts = base.client("sts")
    creds = sts.assume_role(RoleArn=TRANSFORM_ROLE_ARN, RoleSessionName="promote-payments")[
        "Credentials"
    ]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=REGION,
    )


def list_bronze_keys(s3):
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BRONZE_BUCKET, Prefix=BRONZE_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                keys.append(obj["Key"])
    return keys


def read_events(s3, keys):
    events = []
    for key in keys:
        body = s3.get_object(Bucket=BRONZE_BUCKET, Key=key)["Body"].read()
        events.extend(json.loads(body))
    return events


def flatten(events):
    rows = []
    for e in events:
        merchant = e["merchant"]
        customer = e["customer"]
        pm = e["payment_method"]
        rows.append(
            {
                "transaction_id": e["transaction_id"],
                "event_type": e["event_type"],
                "event_timestamp": e["event_timestamp"],
                "amount": e["amount"],
                "currency": e["currency"],
                "merchant_id": merchant["merchant_id"],
                "merchant_name": merchant["name"],
                "merchant_category": merchant["category"],
                "customer_id": customer["customer_id"],
                "customer_name": customer["name"],
                "customer_email": customer["email"],
                "payment_method_type": pm["type"],
                "payment_method_brand": pm.get("brand"),
                "payment_method_last4": pm.get("last4"),
                "payment_method_token": pm["token"],
            }
        )
    df = pd.DataFrame(rows)
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True)
    return df


def write_parquet(s3, df, bucket, key):
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", compression="snappy", index=False)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    print(f"[transform] wrote s3://{bucket}/{key} ({len(df)} rows)")


def write_silver(s3, df):
    df = df.copy()
    df["dt"] = df["event_timestamp"].dt.strftime("%Y-%m-%d")
    days = sorted(df["dt"].unique())
    for day, day_df in df.groupby("dt"):
        key = f"payments/dt={day}/events.parquet"
        write_parquet(s3, day_df.drop(columns="dt"), SILVER_BUCKET, key)
    return days


def register_partitions(glue, days):
    partitions = [
        {
            "Values": [day],
            "StorageDescriptor": {
                "Location": f"s3://{SILVER_BUCKET}/payments/dt={day}/",
                "InputFormat": PARQUET_INPUT_FORMAT,
                "OutputFormat": PARQUET_OUTPUT_FORMAT,
                "SerdeInfo": {"SerializationLibrary": PARQUET_SERDE},
                "Columns": PARQUET_COLUMNS,
            },
        }
        for day in days
    ]
    resp = glue.batch_create_partition(
        DatabaseName=GLUE_DATABASE,
        TableName=GLUE_SILVER_TABLE,
        PartitionInputList=partitions,
    )
    errors = resp.get("Errors", [])
    for err in errors:
        if err["ErrorDetail"]["ErrorCode"] != "AlreadyExistsException":
            raise RuntimeError(
                f"Glue partition registration failed for {err['PartitionValues']}: "
                f"{err['ErrorDetail']}"
            )
    new = len(days) - len(errors)
    print(f"[transform] registered {new} new Glue partition(s), {len(errors)} already existed")


def write_gold(s3, df):
    ranked = df.assign(_rank=df["event_type"].map(EVENT_TYPE_RANK))
    latest = (
        ranked.sort_values(["event_timestamp", "_rank"])
        .groupby("transaction_id")
        .tail(1)
        .drop(columns="_rank")
    )
    write_parquet(s3, latest, GOLD_BUCKET, "payments_current/current_state.parquet")


def main():
    session = assumed_session()
    s3 = session.client("s3")
    glue = session.client("glue")

    keys = list_bronze_keys(s3)
    print(f"[transform] found {len(keys)} bronze objects under {BRONZE_PREFIX}")
    if not keys:
        print("[transform] nothing to do")
        return

    events = read_events(s3, keys)
    print(f"[transform] read {len(events)} events")

    df = flatten(events)
    days = write_silver(s3, df)
    register_partitions(glue, days)
    write_gold(s3, df)
    print(f"[transform] done — {df['transaction_id'].nunique()} distinct transactions")


if __name__ == "__main__":
    main()
