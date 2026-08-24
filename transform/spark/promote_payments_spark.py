"""Cerberus 3.5 — bronze -> silver on Spark, replacing 1.7's promote_payments.py
for this one step only.

Reads every payments event currently in bronze (same full-rebuild-every-run
design as 1.7 -- no watermark/incremental tracking, trivially idempotent)
and writes the same flattened, Snappy-compressed Parquet silver layout
1.7 already writes: same bucket, same `payments/dt=YYYY-MM-DD/` partitions,
same 15-column schema. Gold's latest-event-wins rollup is deliberately left
to 1.7's script -- this job replaces only the "heavy" flatten/parse step
plan.md's Phase 3 goal calls out, not the whole pipeline.

Runs as the cerberus-spark IAM role (terraform/modules/iam), assumed via
IRSA -- the driver/executor pods' service account (terraform/modules/spark_job)
is annotated with the role ARN, and EKS's Pod Identity webhook injects the
credentials Spark's own S3A client picks up automatically via
WebIdentityTokenCredentialsProvider.

Deliberately does NOT register the new partitions with Glue itself, unlike
1.7's script: that would need boto3 in the driver's Python environment, and
the off-the-shelf apache/spark image (no custom build, per this phase's own
cost/complexity discipline) doesn't ship it. transform/spark/submit_job.sh
runs `MSCK REPAIR TABLE payments_events` via Athena after the job completes
instead -- the standard Glue/Athena mechanism for exactly this "new
partition directories appeared in S3" case, and it reuses cerberus-transform's
existing Glue/Athena permissions rather than granting cerberus-spark any.

The 15-column output schema mirrors 1.7's PARQUET_COLUMNS constant -- kept
in sync by hand, same caveat 1.7 already documents (no shared schema source
between this script, promote_payments.py, and terraform/modules/glue_catalog).
"""

import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

ACCOUNT_ID = "131715059025"

BRONZE_BUCKET = f"cerberus-platform-bronze-{ACCOUNT_ID}"
SILVER_BUCKET = f"cerberus-platform-silver-{ACCOUNT_ID}"
BRONZE_PREFIX = "payments/"
SILVER_PREFIX = "payments/"

# The raw event schema as it exists in bronze -- nested merchant/customer/
# payment_method objects, per ADR 0003. Declared explicitly (not inferred)
# so a partially-written or empty bronze file can't silently produce a
# differently-shaped DataFrame across runs.
BRONZE_EVENT_SCHEMA = StructType(
    [
        StructField("transaction_id", StringType()),
        StructField("event_type", StringType()),
        StructField("event_timestamp", StringType()),
        StructField("amount", DoubleType()),
        StructField("currency", StringType()),
        StructField(
            "merchant",
            StructType(
                [
                    StructField("merchant_id", StringType()),
                    StructField("name", StringType()),
                    StructField("category", StringType()),
                ]
            ),
        ),
        StructField(
            "customer",
            StructType(
                [
                    StructField("customer_id", StringType()),
                    StructField("name", StringType()),
                    StructField("email", StringType()),
                ]
            ),
        ),
        StructField(
            "payment_method",
            StructType(
                [
                    StructField("type", StringType()),
                    StructField("brand", StringType()),
                    StructField("last4", StringType()),
                    StructField("token", StringType()),
                ]
            ),
        ),
    ]
)


def read_bronze(spark):
    path = f"s3a://{BRONZE_BUCKET}/{BRONZE_PREFIX}dt=*/*.json"
    # Each bronze file is a JSON array of events (payments_lib.upload_day),
    # not one-object-per-line -- multiLine is required to parse it at all.
    return spark.read.schema(BRONZE_EVENT_SCHEMA).option("multiLine", "true").json(path)


def flatten(df):
    return df.select(
        F.col("transaction_id"),
        F.col("event_type"),
        F.to_timestamp("event_timestamp").alias("event_timestamp"),
        F.col("amount"),
        F.col("currency"),
        F.col("merchant.merchant_id").alias("merchant_id"),
        F.col("merchant.name").alias("merchant_name"),
        F.col("merchant.category").alias("merchant_category"),
        F.col("customer.customer_id").alias("customer_id"),
        F.col("customer.name").alias("customer_name"),
        F.col("customer.email").alias("customer_email"),
        F.col("payment_method.type").alias("payment_method_type"),
        F.col("payment_method.brand").alias("payment_method_brand"),
        F.col("payment_method.last4").alias("payment_method_last4"),
        F.col("payment_method.token").alias("payment_method_token"),
        F.date_format("event_timestamp", "yyyy-MM-dd").alias("dt"),
    )


def write_silver(df):
    # Spark's partitioned writer names output files part-NNNNN-<uuid>.snappy.parquet
    # inside each dt=.../ directory, not the single events.parquet 1.7's
    # script writes -- a deliberate divergence, not a bug: both Glue and
    # Athena read a partition by its directory, not by exact filename, so
    # this stays queryable through the same payments_events table either
    # way. mode("overwrite") wipes the whole prefix before writing, which
    # matches 1.7's own full-rebuild-every-run semantics -- both scripts
    # reprocess all of bronze on every run, not just new partitions.
    path = f"s3a://{SILVER_BUCKET}/{SILVER_PREFIX}"
    days = [row["dt"] for row in df.select("dt").distinct().collect()]
    (df.write.mode("overwrite").partitionBy("dt").option("compression", "snappy").parquet(path))
    return sorted(days)


def main():
    credentials_provider = "com.amazonaws.auth.WebIdentityTokenCredentialsProvider"
    spark = (
        SparkSession.builder.appName("cerberus-promote-payments")
        .config("spark.hadoop.fs.s3a.aws.credentials.provider", credentials_provider)
        .getOrCreate()
    )

    raw = read_bronze(spark)
    count = raw.count()
    print(f"[spark-transform] read {count} events from bronze")
    if count == 0:
        print("[spark-transform] nothing to do")
        spark.stop()
        return

    flat = flatten(raw)
    days = write_silver(flat)
    print(f"[spark-transform] done — wrote {len(days)} day partition(s) to silver: {days}")
    print(
        "[spark-transform] run submit_job.sh's MSCK REPAIR TABLE step next to register them in Glue"
    )

    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
