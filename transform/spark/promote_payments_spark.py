"""Cerberus 8.5 -- bronze -> silver on Spark, incremental, into an Iceberg table.

Replaces 3.5's full rebuild (ADR 0017). Each run:

1. reads the bronze watermark from silver's newest snapshot that carries one
   (`cerberus.bronze_watermark`, epoch milliseconds);
2. lists bronze objects modified after it, under both prefixes -- the
   ingestion Lambda's JSON arrays in `payments/` and the bulk generator's
   JSON Lines in `payments_bulk/` (ADR 0018);
3. reads exactly those files, once, and keeps only the events whose
   (transaction_id, event_type) is not in silver yet;
4. appends them in one Iceberg commit whose snapshot carries the new
   watermark, so data and watermark commit together or not at all;
5. compacts small files and expires old snapshots.

With no watermark (the first run, or a rebuild into a new table) it reads
all of bronze, which keeps ADR 0002's rebuild-from-bronze recovery path.

Step 3+4 is ADR 0017's insert-only `MERGE INTO`, done as an anti-join plus a
DataFrame append: Spark 3.5 has no DataFrame MERGE, Iceberg ignores
snapshot properties set in the session for SQL writes, and wrapping the SQL
in CommitMetadata from PySpark deadlocks on the py4j callback (all three
tested locally on 2026-10-08). The append's `snapshot-property.*` write
option is what makes the watermark atomic with the data. Re-running a batch
adds nothing: every key is already there.

Silver is `glue.cerberus_platform.payments_events`: same name and 15 event
columns as the Hive table it replaces, plus `loaded_at` (when this job added
the row -- the input gold's incremental dbt model needs to find the events
added since its last run), partitioned by days(event_timestamp) (hidden
partitioning, so no `dt` column and no MSCK REPAIR), Iceberg format v2 (the
version Athena reads), Parquet + Snappy, under s3://<silver>/iceberg/.

Iceberg 1.10.2 is pinned in the SparkApplication: 1.11+ is built for Java
17, and apache/spark:3.5.9 runs Java 11 (tested 2026-10-08).

Runs as cerberus-spark via IRSA. S3A (bronze listing and reads) and
Iceberg's S3FileIO (silver) both pick up the web-identity credentials.

Every path and the catalog are arguments, so the same code runs locally in
the apache/spark image against a Hadoop catalog and local directories.
"""

import argparse
import re
import sys
import time
from datetime import date, timedelta

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

ACCOUNT_ID = "131715059025"
BRONZE_BUCKET = f"cerberus-platform-bronze-{ACCOUNT_ID}"
SILVER_BUCKET = f"cerberus-platform-silver-{ACCOUNT_ID}"

CATALOG = "glue"
NAMESPACE = "cerberus_platform"
TABLE_NAME = "payments_events"
WATERMARK = "cerberus.bronze_watermark"
KEY = ["transaction_id", "event_type"]

# Bronze prefix -> (glob under it, multiLine). The Lambda writes one JSON
# array per file (multiLine) and the generator JSON Lines; multiLine=true on
# JSON Lines silently keeps only the first object of each file (ADR 0018), so
# the two are never read together. The payments/ glob is the one 3.5's job
# read with under cerberus-spark's prefix-scoped grant: a glob lists by
# prefix, where exists()/listFiles() would first probe the bare `payments`
# key, which the grant doesn't cover (S3 answers 403).
BRONZE_PREFIXES = {
    "payments/": ("dt=*/*.json", True),
    "payments_bulk/": ("run_id=*/dt=*/*.json", False),
}

# The raw event schema in bronze -- nested merchant/customer/payment_method,
# per ADR 0003. Declared, not inferred, so a malformed file can't reshape it.
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

# Silver's columns: the Hive table's 15, minus its `dt` partition column
# (hidden partitioning on event_timestamp), plus `loaded_at`.
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    transaction_id string,
    event_type string,
    event_timestamp timestamp,
    amount double,
    currency string,
    merchant_id string,
    merchant_name string,
    merchant_category string,
    customer_id string,
    customer_name string,
    customer_email string,
    payment_method_type string,
    payment_method_brand string,
    payment_method_last4 string,
    payment_method_token string,
    loaded_at timestamp
)
USING iceberg
PARTITIONED BY (days(event_timestamp))
{location}
TBLPROPERTIES (
    'format-version' = '2',
    'write.parquet.compression-codec' = 'snappy',
    'write.metadata.delete-after-commit.enabled' = 'true',
    'write.metadata.previous-versions-max' = '20'
)
"""

# expire_snapshots keeps at least this many snapshots. A run commits at most
# two (the append, then a compaction), so the newest append -- the one that
# carries the watermark -- always survives.
RETAIN_SNAPSHOTS = 5
SNAPSHOT_MAX_AGE_DAYS = 7


def log(message):
    print(f"[spark-transform] {message}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bronze-root", default=f"s3a://{BRONZE_BUCKET}/")
    parser.add_argument("--warehouse", default=f"s3://{SILVER_BUCKET}/iceberg/")
    parser.add_argument(
        "--catalog-type",
        choices=["glue", "hadoop"],
        default="glue",
        help="hadoop is for local tests only",
    )
    parser.add_argument(
        "--skip-maintenance", action="store_true", help="no compaction or snapshot expiry"
    )
    return parser.parse_args()


def build_session(args):
    builder = (
        SparkSession.builder.appName("cerberus-promote-payments")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{CATALOG}.warehouse", args.warehouse)
        # Event timestamps are UTC; days() partitions on the UTC day.
        .config("spark.sql.session.timeZone", "UTC")
    )
    if args.catalog_type == "glue":
        builder = (
            builder.config(
                f"spark.sql.catalog.{CATALOG}.catalog-impl",
                "org.apache.iceberg.aws.glue.GlueCatalog",
            )
            .config(f"spark.sql.catalog.{CATALOG}.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
            .config(
                "spark.hadoop.fs.s3a.aws.credentials.provider",
                "com.amazonaws.auth.WebIdentityTokenCredentialsProvider",
            )
        )
    else:
        builder = builder.config(f"spark.sql.catalog.{CATALOG}.type", "hadoop")
    return builder.getOrCreate()


def current_watermark(spark, table):
    """The newest committed watermark, or 0 when the table has none yet.

    Read from the newest snapshot that carries it, not simply the newest
    snapshot: compaction commits a snapshot of its own without the property.
    """
    rows = spark.sql(
        f"SELECT summary['{WATERMARK}'] AS watermark FROM {table}.snapshots "
        f"WHERE summary['{WATERMARK}'] IS NOT NULL ORDER BY committed_at DESC LIMIT 1"
    ).collect()
    return int(rows[0]["watermark"]) if rows else 0


def new_bronze_files(spark, root, prefix, after_millis):
    """Bronze objects under `prefix` modified after the watermark.

    Globbed through Hadoop's FileSystem API (S3A on the cluster), which gives
    each object's LastModified without boto3 -- the stock image has none.
    The globs match only data files: Spark's _SUCCESS, .spark-staging and
    local .crc files don't end in a matching name.
    """
    pattern, _ = BRONZE_PREFIXES[prefix]
    jvm = spark.sparkContext._jvm
    path = jvm.org.apache.hadoop.fs.Path(root + prefix + pattern)
    fs = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    statuses = fs.globStatus(path) or []
    return [
        (status.getPath().toString(), status.getModificationTime())
        for status in statuses
        if status.isFile() and status.getModificationTime() > after_millis
    ]


def read_bronze(spark, files_by_prefix):
    frames = []
    for prefix, files in files_by_prefix.items():
        if files:
            reader = spark.read.schema(BRONZE_EVENT_SCHEMA)
            reader = reader.option("multiLine", str(BRONZE_PREFIXES[prefix][1]).lower())
            frames.append(reader.json([path for path, _ in files]))
    raw = frames[0]
    for frame in frames[1:]:
        raw = raw.unionByName(frame)
    return raw


def touched_days(files_by_prefix):
    """The UTC event days the new bronze files hold, from their `dt=` paths.

    Both bronze layouts put each event in the `dt=` directory of its own
    event_timestamp's UTC day (payments_lib.upload_day; the generator's
    partitionBy("dt")). None if any path lacks a `dt=` segment, so the
    caller falls back to comparing against all of silver.
    """
    days = set()
    for files in files_by_prefix.values():
        for path, _ in files:
            match = re.search(r"/dt=(\d{4}-\d{2}-\d{2})/", path)
            if match is None:
                return None
            days.add(match.group(1))
    return sorted(days)


def existing_keys(spark, table, days):
    """Silver's keys, limited to the event days the new events fall on (8.6).

    A new event can only duplicate a silver event with the same
    (transaction_id, event_type) -- the same event, delivered again, with
    the same event_timestamp and therefore the same UTC day. So the
    anti-join needs only those days' partitions. The filter is plain
    timestamp ranges on the partition source column, which Iceberg turns
    into partition pruning: the files of all other days are never opened.
    Before 8.6 this read every silver key (30.5 MB read and 41.5 MB
    shuffled for ~2-3 MB of new bronze at 1M events, 2026-10-08).
    """
    keys = spark.table(table)
    if days is not None:
        condition = None
        for day in days:
            start = date.fromisoformat(day)
            in_day = (F.col("event_timestamp") >= F.lit(f"{start} 00:00:00").cast("timestamp")) & (
                F.col("event_timestamp")
                < F.lit(f"{start + timedelta(days=1)} 00:00:00").cast("timestamp")
            )
            condition = in_day if condition is None else condition | in_day
        keys = keys.where(condition)
    return keys.select(*KEY)


def flatten(df, loaded_at):
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
        F.lit(loaded_at).cast("timestamp").alias("loaded_at"),
    )


def latest_snapshot(spark, table):
    return spark.sql(
        f"SELECT snapshot_id, summary['added-records'] AS added, "
        f"summary['total-records'] AS total, summary['{WATERMARK}'] AS watermark "
        f"FROM {table}.snapshots ORDER BY committed_at DESC LIMIT 1"
    ).collect()[0]


def maintain(spark, table):
    """Compact small files and expire old snapshots (ADR 0017)."""
    identifier = f"{NAMESPACE}.{TABLE_NAME}"
    rewritten = spark.sql(
        f"CALL {CATALOG}.system.rewrite_data_files(table => '{identifier}', "
        "options => map('min-input-files', '5'))"
    ).collect()[0]
    older_than = time.strftime(
        "%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - SNAPSHOT_MAX_AGE_DAYS * 86400)
    )
    expired = spark.sql(
        f"CALL {CATALOG}.system.expire_snapshots(table => '{identifier}', "
        f"older_than => TIMESTAMP '{older_than}', retain_last => {RETAIN_SNAPSHOTS})"
    ).collect()[0]
    log(
        f"maintenance: {rewritten['rewritten_data_files_count']} files compacted into "
        f"{rewritten['added_data_files_count']}, "
        f"{expired['deleted_data_files_count']} expired data files deleted"
    )


def main():
    args = parse_args()
    spark = build_session(args)
    table = f"{CATALOG}.{NAMESPACE}.{TABLE_NAME}"

    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{NAMESPACE}")
    # A Hadoop catalog (local tests) fixes each table's path itself and
    # rejects a LOCATION clause.
    location = f"LOCATION '{args.warehouse}{TABLE_NAME}'" if args.catalog_type == "glue" else ""
    spark.sql(CREATE_TABLE.format(table=table, location=location))

    watermark = current_watermark(spark, table)
    files_by_prefix = {
        prefix: new_bronze_files(spark, args.bronze_root, prefix, watermark)
        for prefix in BRONZE_PREFIXES
    }
    counts = {prefix: len(files) for prefix, files in files_by_prefix.items()}
    log(f"watermark {watermark}; new bronze files {counts}")
    if not any(counts.values()):
        log("nothing new in bronze -- silver unchanged")
        spark.stop()
        return

    new_watermark = max(m for files in files_by_prefix.values() for _, m in files)
    # One timestamp for the whole run, so every row this run adds shares it.
    loaded_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    events = flatten(read_bronze(spark, files_by_prefix), loaded_at).dropDuplicates(KEY)
    days = touched_days(files_by_prefix)
    log(f"anti-join limited to {'all of silver' if days is None else f'{len(days)} event days'}")
    new_events = events.join(existing_keys(spark, table, days), KEY, "left_anti")

    # One action: bronze is read once, here, and the watermark commits with
    # the data in the same snapshot.
    (
        new_events.writeTo(table)
        .option(f"snapshot-property.{WATERMARK}", str(new_watermark))
        .append()
    )
    snapshot = latest_snapshot(spark, table)
    log(
        f"appended {snapshot['added'] or 0} new events "
        f"(silver now {snapshot['total']}); watermark {watermark} -> {snapshot['watermark']}"
    )

    if not args.skip_maintenance:
        maintain(spark, table)
    spark.stop()


if __name__ == "__main__":
    sys.exit(main())
