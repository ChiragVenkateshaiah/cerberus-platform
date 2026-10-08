# 17. Apache Iceberg tables and incremental processing for the scale ladder

Date: 2026-10-06

## Status

Accepted

## Context

Phase 8 ([plan.md](../plan.md#phase-8--scale-validation)) takes the
platform from today's volume to 100M payment events in three 10x steps
(about 1M, 10M, 100M) and measures run time and cost per million events at
each step. On 2026-10-06 silver held 39,222 events and 12,862 transactions
in 32 daily partitions. The design that carries that volume does not carry
100M events.

**How silver and gold are built today:**

- **Silver** (`transform/spark/promote_payments_spark.py`, 3.5) reads
  *all* of bronze on every run and writes Hive-style Parquet with
  `mode("overwrite").partitionBy("dt")`. That wipes the whole `payments/`
  prefix and rewrites it. `submit_job.sh` then runs `MSCK REPAIR TABLE`
  through Athena to register partitions, because the stock `apache/spark`
  image has no boto3 and `cerberus-spark` holds no Glue permissions.
- **Gold** is three dbt models with `+materialized: table`
  (`dbt_project.yml`), rebuilt from all of silver on every `dbt build`.
  `fct_transactions` resolves latest-event-wins over every event.
- **Bronze** is raw JSON and append-only (ADR 0002). That stays.

The full rebuild was the right call at Phase 1 volume: trivially
idempotent, no watermark to get wrong (1.7). At 100M events every run
rereads and rewrites everything, so run time and cost grow with the total
history, not with the new data. A 10x step in history would cost 10x per
run even when one day of new data arrives.

**Forces, by pillar:**

- **Cost Optimization (the driving pillar).** Phase 8 has a $20/month
  budget on a pay-as-you-go account. EKS node hours dominate exercise cost
  ([cost-security-summary.md](../cost-security-summary.md): `dev-compute`
  was 56% of spend). Work that scales with *new* data instead of *all*
  data is the largest lever on node hours. Athena bills per byte scanned,
  so file layout and pruning matter for dbt and the serving query.
- **Performance Efficiency.** A partitioned overwrite also produces many
  small files per partition. At 100M events, small files slow both Spark
  and Athena. Any option must have a compaction story.
- **Reliability.** Today a failed run leaves silver half-wiped until the
  next run: `overwrite` deletes before it writes, and readers between
  those two moments see partial data. Incremental writes must be atomic
  and safe to re-run, because Step Functions retries and a human re-runs
  exercises.
- **Operational Excellence.** Schema changes today mean editing three
  hand-synced column lists (the Spark script, `promote_payments.py`, and
  `glue_catalog`). Recovery from a bad run means re-running everything.
- **Security.** Writing table metadata from Spark needs Glue write access
  for `cerberus-spark`, which 3.5 deliberately avoided.

**Options considered:**

| Option | Silver | Gold | Verdict |
|---|---|---|---|
| A. Keep the full rebuild | Hive Parquet, overwrite all | dbt `table` | Fails the cost force at 10M+ |
| B. Incremental on Hive Parquet | Dynamic partition overwrite of the touched `dt=` partitions | dbt `insert_overwrite` by partition | Works, but no atomic commit, no row-level upsert, compaction is manual, and late events force whole-partition rewrites |
| C. **Apache Iceberg** in the Glue catalog | Spark `MERGE INTO` on the event key | dbt-athena incremental `merge` on `transaction_id` | Atomic commits, row-level upserts, hidden partitioning, built-in compaction (`rewrite_data_files`), native in Glue and Athena |
| D. Delta Lake | Spark `MERGE` | — | Athena reads Delta but cannot write it, so dbt-athena cannot merge into gold. Ruled out |

## Decision

**Option C, Apache Iceberg tables in the existing Glue Data Catalog for
silver and gold, with incremental processing at both steps.** Bronze stays
raw, append-only JSON.

- **Silver: `payments_events` becomes an Iceberg table**, partitioned by
  `days(event_timestamp)` (hidden partitioning, so the `dt` string column
  and `MSCK REPAIR` go away). Spark loads Iceberg the same way it loads
  `hadoop-aws` and `openlineage-spark` today: through `deps.packages`
  (the Iceberg Spark runtime for Spark 3.5 / Scala 2.12, plus the
  `iceberg-aws-bundle`), with exact versions pinned and verified against
  Maven Central at implementation, as 3.5 did for `hadoop-aws`. No custom
  image.
- **Silver writes are `MERGE INTO` on `(transaction_id, event_type)`**,
  inserting only events not already present. That key is unique today
  (0 duplicate groups in the 2026-10-06 data-quality pass), and the
  lifecycle allows each event type at most once per transaction. Re-running
  the same input is a no-op, so retries are safe.
- **The watermark lives in the silver commit itself.** Each run reads only
  bronze objects whose `LastModified` is newer than the watermark, and
  records the new watermark as an Iceberg snapshot property
  (`snapshot-property.cerberus.bronze_watermark`). Data and watermark
  commit together or not at all. Without a watermark (first run, or a
  rebuild), the job reads all of bronze, which keeps today's
  rebuild-from-bronze recovery path (ADR 0002).
- **Gold: the three dbt models become Iceberg** (`table_type='iceberg'`).
  `fct_transactions` becomes `incremental` with
  `incremental_strategy='merge'` and `unique_key='transaction_id'`. Each
  run recomputes latest-event-wins only for transactions that received a
  new event, over *all* of that transaction's events, because a refund can
  land days after settlement. The dimensions stay full rebuilds (15 and
  75 rows).
- **Compaction and snapshot expiry run as a step** after the silver
  write (`rewrite_data_files`, `expire_snapshots` with a retention set in
  code), so file counts and metadata stay bounded as the ladder climbs.
- **IAM:** `cerberus-spark` gains Glue table read/write scoped to the
  `cerberus_platform` database and its tables, which Iceberg's Glue catalog
  needs for commits. `cerberus-transform` and `cerberus-serving` keep their
  current read paths. The 7.3 path applies to any `cerberus-admin` gap
  found on the way.

## Consequences

- **Run cost tracks new data instead of total history**, which is what
  makes the 10M and 100M steps affordable inside $20/month. The scale
  ladder measures this directly: per-run bytes read and written, alongside
  run time and cost per million events.
- **Writes become atomic.** A failed run leaves the previous snapshot
  intact, and readers never see a half-written silver. This removes
  today's overwrite window.
- **Iceberg time travel becomes a recovery tool** within the snapshot
  retention window. The full rebuild from bronze remains the deeper
  recovery path.
- **Complexity moves into state.** A wrong watermark silently skips data,
  where the full rebuild could not. The data-quality suite (Phase 8)
  must reconcile bronze to silver by count on every exercise, not only
  silver to gold.
- **Small migrations, once.** The existing Hive Parquet tables are
  migrated by one full rebuild into the new Iceberg tables, then dropped.
  `MSCK REPAIR` and the `dt` column go away, so the 2026-10-06
  `partition_correct` check is replaced by an Iceberg partition check.
  `promote_payments.py` (1.7's local script) is retired, not ported.
- **`cerberus-spark` gets Glue write access**, a deliberate reversal of
  3.5's choice, scoped to one database. Recorded as the security cost of
  atomic commits.
- **New moving parts to observe:** commit conflicts, snapshot counts, and
  file counts per partition. Grafana and the run summary gain those
  numbers in the 10M step.
- **Not decided here:** Spark tuning (partition sizing, AQE, skew), node
  autoscaling and Spot. Those are measured decisions for the 10M step and
  a separate ADR.

## Implementation notes (2026-10-08, 8.5)

Recorded while building the silver job, after local tests in the
`apache/spark:3.5.9` image. The decision above stands; these are the
mechanics it needed.

- **Iceberg 1.10.2, not the latest.** 1.11.0 and 1.12.0 are built for Java
  17 (class file 61); the image runs Java 11, and both failed with
  `UnsupportedClassVersionError`. 1.10.2 passed every test. Moving the
  Spark image to `3.5.9-java17` (which exists) is a recorded follow-up,
  not part of this phase's critical path.
- **The insert-only MERGE is an anti-join plus an append.** The watermark
  must commit with the data. Iceberg ignores
  `spark.sql.iceberg.snapshot-property.*` for SQL writes (the snapshot
  carried no property), and wrapping the SQL `MERGE INTO` in
  `CommitMetadata.withCommitProperties` from PySpark deadlocked on the
  py4j callback. A DataFrame append accepts the
  `snapshot-property.cerberus.bronze_watermark` write option, so the job
  keeps only events whose `(transaction_id, event_type)` is not in silver
  yet (left anti-join) and appends them. That is the same operation as an
  insert-only `MERGE INTO`; tested: a re-run of an already-loaded batch
  adds 0 rows.
- **The watermark is read from the newest snapshot that carries it**, not
  the newest snapshot: compaction commits snapshots of its own without the
  property. `expire_snapshots` keeps at least 5, and a run commits at most
  2, so the newest watermark always survives.
- **Silver gained a `loaded_at` column** (one value per job run), so gold's
  incremental dbt model can find the events added since its last run.
- **Bronze is listed with globs** (`payments/dt=*/*.json`,
  `payments_bulk/run_id=*/dt=*/*.json`), as 3.5's job read it: a plain
  `exists()`/`listFiles()` probes the bare `payments` key first, which
  `cerberus-spark`'s prefix-scoped grant answers with 403. Each run reads
  only the bronze files modified after the watermark, once (tested: 73.4 MB
  read for 73.3 MB of bronze on a full load).
- **The Hive table is retired by Terraform.** `glue_catalog` no longer
  declares `payments_events`; the apply that removes it deletes the Glue
  entry only (the Hive Parquet under `silver/payments/` stays until a
  cleanup), and the first Iceberg run recreates the name under
  `silver/iceberg/` by a full rebuild from bronze. `cerberus-spark` gets
  Glue read/create/update on that one table and no `DeleteTable`.
