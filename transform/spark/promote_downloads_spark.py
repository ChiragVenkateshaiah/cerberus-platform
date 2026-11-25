"""Cerberus 17.5 -- bronze -> silver for the `downloads` event family, on Spark.

The second silver job (ADR 0030 Decision 9: separate on purpose, accepted
debt that Phase 13.5 retires). It is promote_payments_spark.py's method
(ADR 0017) with the downloads differences:

1. a run is the unit, not a file. The generator writes
   `downloads_bulk/run_id=<id>/dt=<day>/part-*.json` and `_manifest.json`
   last, so a run with a manifest is complete and a run without one is still
   being written (or failed) and is skipped;
2. the watermark is the newest manifest LastModified of the runs taken
   (`cerberus.bronze_watermark`, epoch milliseconds, in the snapshot summary).
   A run is taken when its manifest is newer than the watermark, OR when its
   run_id is not in silver yet and its manifest is no more than LATE_OVERLAP
   older than the watermark. The second rule keeps a late manifest (a run that
   finished after a newer one was promoted, or in the same second as the
   watermark) from being lost; the anti-join makes reading it always safe. A
   re-run rewrites its manifest, so it is read again and adds 0 rows. A run
   whose events were all already in silver has no run_id in silver, so it is
   read again (adding 0 rows) until its manifest is older than the overlap.
   One writer is assumed: one job at a time promotes this table (see the plan);
3. the key is `event_id` alone (ADR 0030 Decision 7). The anti-join reads
   only the silver days the taken runs touch, so a second run_id on the same
   days is still compared with every earlier event of those days;
4. `run_id` is not in the files; it comes from the path.

Silver is `glue.cerberus_platform.download_events`, Iceberg v2, partitioned
by days(occurred_at), under `<warehouse>download_events`. No account ID is in
this file: `--bronze-root` and `--warehouse` are required, so the same code
runs in the apache/spark image against a Hadoop catalog and local directories.

The pure helpers (path parsing, run selection, touched days) import no Spark,
so the unit tests run without it.
"""

import argparse
import re
import time
from datetime import date, timedelta

CATALOG = "glue"
NAMESPACE = "cerberus_platform"
TABLE_NAME = "download_events"
WATERMARK = "cerberus.bronze_watermark"
KEY = ["event_id"]
BULK_PREFIX = "downloads_bulk/"
MANIFEST_NAME = "_manifest.json"

RUN_PATH_RE = re.compile(r"/run_id=([A-Za-z0-9][A-Za-z0-9_-]{0,63})(?:/|$)")
DT_PATH_RE = re.compile(r"/dt=(\d{4}-\d{2}-\d{2})/")

# Silver's columns: the envelope (ADR 0030 Decision 7) with the payload
# flattened, plus `run_id` (from the path) and `loaded_at` (when this job added
# the row; the input a later incremental gold model needs).
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    event_id string,
    event_family string,
    event_type string,
    occurred_at timestamp,
    ingested_at timestamp,
    schema_version int,
    client_id string,
    platform string,
    region string,
    isp string,
    bytes bigint,
    duration_ms bigint,
    throughput_mbps double,
    http_status int,
    run_id string,
    loaded_at timestamp
)
USING iceberg
PARTITIONED BY (days(occurred_at))
{location}
TBLPROPERTIES (
    'format-version' = '2',
    'write.parquet.compression-codec' = 'snappy',
    'write.metadata.delete-after-commit.enabled' = 'true',
    'write.metadata.previous-versions-max' = '20'
)
"""

# A manifest older than the watermark is still taken when its run is not in
# silver, up to this age behind the watermark. A design choice, not a measured
# number: runs are minutes long, so a day is far wider than any real lateness.
LATE_OVERLAP_MS = 24 * 3600 * 1000

RETAIN_SNAPSHOTS = 5
SNAPSHOT_MAX_AGE_DAYS = 7


def log(message):
    print(f"[spark-transform] {message}", flush=True)


# --- Pure helpers (no Spark) -------------------------------------------------
def run_id_of(path):
    """The run_id= segment of a bronze path, or None."""
    match = RUN_PATH_RE.search(path)
    return match.group(1) if match else None


def select_runs(manifests, watermark, promoted=frozenset(), overlap_ms=LATE_OVERLAP_MS):
    """Pick the runs to read and the watermark to commit.

    `manifests` is [(run_id, manifest_modified_ms), ...]; `promoted` is the set
    of run_ids already in silver. A run is taken when its manifest is newer than
    `watermark`, or when it is not in `promoted` and its manifest is not older
    than `watermark - overlap_ms` (a late manifest, including one in the same
    second as the watermark). The new watermark is the newest taken manifest, or
    the old one when nothing is taken (it never moves back).
    """
    taken = sorted(
        (
            (run_id, ms)
            for run_id, ms in manifests
            if ms > watermark or (run_id not in promoted and ms >= watermark - overlap_ms)
        ),
        key=lambda r: (r[1], r[0]),
    )
    new_watermark = max([watermark] + [ms for _, ms in taken])
    return [run_id for run_id, _ in taken], new_watermark


def null_key_message(counts):
    """An error text when event_id, occurred_at or ingested_at has nulls, else None.

    `counts` is {column: null rows}. These columns are the key and the time the
    silver partition and the gold models rely on; a null must stop the job.
    """
    bad = {column: n for column, n in counts.items() if n}
    if not bad:
        return None
    return "refusing to append: null " + ", ".join(
        f"{c} in {n} rows" for c, n in sorted(bad.items())
    )


def touched_days(paths):
    """The UTC event days the data files hold, from their `dt=` directories.

    The generator writes each event under dt = the first 10 characters of its
    occurred_at, so the directory day is the event day. None if any path lacks
    a `dt=` segment, so the caller compares against all of silver.
    """
    days = set()
    for path in paths:
        match = DT_PATH_RE.search(path)
        if match is None:
            return None
        days.add(match.group(1))
    return sorted(days)


def day_bounds(day):
    """[start, end) of a UTC day, as 'YYYY-MM-DD HH:MM:SS' strings."""
    start = date.fromisoformat(day)
    return f"{start} 00:00:00", f"{start + timedelta(days=1)} 00:00:00"


# --- Spark -------------------------------------------------------------------
def bronze_schema():
    from pyspark.sql.types import (
        DoubleType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    return StructType(
        [
            StructField("event_id", StringType()),
            StructField("event_family", StringType()),
            StructField("event_type", StringType()),
            StructField("occurred_at", StringType()),
            StructField("ingested_at", StringType()),
            StructField("schema_version", IntegerType()),
            StructField(
                "payload",
                StructType(
                    [
                        StructField("client_id", StringType()),
                        StructField("platform", StringType()),
                        StructField("region", StringType()),
                        StructField("isp", StringType()),
                        StructField("bytes", LongType()),
                        StructField("duration_ms", LongType()),
                        StructField("throughput_mbps", DoubleType()),
                        StructField("http_status", IntegerType()),
                    ]
                ),
            ),
        ]
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bronze-root", required=True, help="e.g. s3a://<bronze>/")
    parser.add_argument("--warehouse", required=True, help="e.g. s3://<silver>/iceberg/")
    parser.add_argument(
        "--catalog-type",
        choices=["glue", "hadoop"],
        default="glue",
        help="hadoop is for local tests only",
    )
    parser.add_argument(
        "--skip-maintenance", action="store_true", help="no compaction or snapshot expiry"
    )
    args = parser.parse_args()
    for name in ("bronze_root", "warehouse"):
        if not getattr(args, name).endswith("/"):
            setattr(args, name, getattr(args, name) + "/")
    return args


def build_session(args):
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName("cerberus-promote-downloads")
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
    """The newest committed watermark, or 0 when the table has none yet."""
    rows = spark.sql(
        f"SELECT summary['{WATERMARK}'] AS watermark FROM {table}.snapshots "
        f"WHERE summary['{WATERMARK}'] IS NOT NULL ORDER BY committed_at DESC LIMIT 1"
    ).collect()
    return int(rows[0]["watermark"]) if rows else 0


def _glob(spark, pattern):
    jvm = spark.sparkContext._jvm
    path = jvm.org.apache.hadoop.fs.Path(pattern)
    fs = path.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    return fs.globStatus(path) or []


def run_manifests(spark, root):
    """[(run_id, manifest LastModified ms)] for every run that has a manifest.

    A glob lists by prefix, where exists()/listFiles() would first probe the bare
    `downloads_bulk` key, which cerberus-spark's prefix-scoped grant does not
    cover (same reason as promote_payments_spark.py).
    """
    found = []
    for status in _glob(spark, f"{root}{BULK_PREFIX}run_id=*/{MANIFEST_NAME}"):
        run_id = run_id_of(status.getPath().toString())
        if run_id is not None and status.isFile():
            found.append((run_id, status.getModificationTime()))
    return found


def run_files(spark, root, run_id):
    return [
        status.getPath().toString()
        for status in _glob(spark, f"{root}{BULK_PREFIX}run_id={run_id}/dt=*/part-*.json")
        if status.isFile()
    ]


def flatten(df, loaded_at):
    from pyspark.sql import functions as F

    return df.select(
        F.col("event_id"),
        F.col("event_family"),
        F.col("event_type"),
        F.to_timestamp("occurred_at").alias("occurred_at"),
        F.to_timestamp("ingested_at").alias("ingested_at"),
        F.col("schema_version"),
        F.col("payload.client_id").alias("client_id"),
        F.col("payload.platform").alias("platform"),
        F.col("payload.region").alias("region"),
        F.col("payload.isp").alias("isp"),
        F.col("payload.bytes").alias("bytes"),
        F.col("payload.duration_ms").alias("duration_ms"),
        F.col("payload.throughput_mbps").alias("throughput_mbps"),
        F.col("payload.http_status").alias("http_status"),
        F.regexp_extract(F.input_file_name(), RUN_PATH_RE.pattern, 1).alias("run_id"),
        F.lit(loaded_at).cast("timestamp").alias("loaded_at"),
    )


def existing_keys(spark, table, days):
    """Silver's event_ids, limited to the event days the taken runs fall on.

    A new event can only repeat a silver event with the same event_id, which has
    the same occurred_at and so the same UTC day. The filter is plain timestamp
    ranges on the partition source column, which Iceberg turns into partition
    pruning. The filter covers every earlier run of those days, not only the
    taken runs, so a second run_id over the same days is compared correctly.
    """
    from pyspark.sql import functions as F

    keys = spark.table(table)
    if days is not None:
        condition = None
        for day in days:
            lo, hi = day_bounds(day)
            in_day = (F.col("occurred_at") >= F.lit(lo).cast("timestamp")) & (
                F.col("occurred_at") < F.lit(hi).cast("timestamp")
            )
            condition = in_day if condition is None else condition | in_day
        keys = keys.where(condition)
    return keys.select(*KEY)


def promoted_run_ids(spark, table):
    """The run_ids already in silver (a distinct, column-pruned read of run_id)."""
    return {row["run_id"] for row in spark.table(table).select("run_id").distinct().collect()}


def null_key_counts(events):
    from pyspark.sql import functions as F

    row = events.agg(
        *[
            F.count(F.when(F.col(c).isNull(), 1)).alias(c)
            for c in ("event_id", "occurred_at", "ingested_at")
        ]
    ).collect()[0]
    return row.asDict()


def latest_snapshot(spark, table):
    # REFRESH TABLE: the Glue catalog's cached table can be stale after the
    # append (see promote_payments_spark.py). Logging only.
    spark.sql(f"REFRESH TABLE {table}")
    return spark.sql(
        f"SELECT snapshot_id, summary['added-records'] AS added, "
        f"summary['total-records'] AS total, summary['{WATERMARK}'] AS watermark "
        f"FROM {table}.snapshots ORDER BY committed_at DESC LIMIT 1"
    ).collect()[0]


def maintain(spark):
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
    manifests = run_manifests(spark, args.bronze_root)
    runs, new_watermark = select_runs(manifests, watermark, promoted_run_ids(spark, table))
    log(f"watermark {watermark}; runs with a manifest {len(manifests)}; new runs {runs}")
    if not runs:
        log("nothing new in bronze -- silver unchanged")
        spark.stop()
        return

    files = [path for run_id in runs for path in run_files(spark, args.bronze_root, run_id)]
    if not files:
        # A manifest with no data files is a broken run: fail, never commit a watermark.
        raise SystemExit(f"runs {runs} have a manifest but no part-*.json files")
    # One timestamp for the whole run, so every row this run adds shares it.
    loaded_at = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    # FAILFAST: a corrupt line fails the job instead of loading a row of nulls.
    raw = (
        spark.read.schema(bronze_schema())
        .option("multiLine", "false")
        .option("mode", "FAILFAST")
        .json(files)
    )
    events = flatten(raw, loaded_at).dropDuplicates(KEY)
    days = touched_days(files)
    # An unparseable timestamp becomes null in flatten(); stop before the append.
    message = null_key_message(null_key_counts(events))
    if message:
        raise SystemExit(message)
    log(f"anti-join limited to {'all of silver' if days is None else f'{len(days)} event days'}")
    new_events = events.join(existing_keys(spark, table, days), KEY, "left_anti")

    # One append: the watermark commits with the data in the same snapshot.
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
        maintain(spark)
    spark.stop()


if __name__ == "__main__":
    main()
