# 18. Bulk synthetic events land in bronze as JSON Lines under a sibling prefix

Date: 2026-10-07

## Status

Accepted

## Context

Phase 8 ([plan.md](../plan.md#phase-8--scale-validation)) climbs a scale
ladder of about 1M, 10M and 100M payment events. Subtask 8.3 needs a
generator that can produce that volume. The current producers cannot:

- The ingestion Lambda (2.1, ADR 0005) has a 15-minute limit and writes
  about 600 events a day.
- `payments_lib.py` builds events one at a time in Python and depends on
  Faker, which the stock `apache/spark:3.5.9` image does not ship.

So the generator is a PySpark job on the `dev-compute` cluster, built from
Spark functions plus the fixed 15-merchant / 75-customer roster. That part
is not in question. This ADR decides **what the generator writes into
bronze, and where**, because that changes two things earlier ADRs settled:
the bronze file shape (ADR 0003's events as written by `payments_lib`) and
bronze's write and delete boundaries (ADR 0002, 1.6).

**Bronze today.** Bronze holds 183 objects, 18.2 MB, about 40k events.
`payments_lib.upload_day` writes each day's events as **one JSON array per
file** at `payments/dt=YYYY-MM-DD/payments_<run_ts>.json`. The silver job
(`promote_payments_spark.py`, 3.5) reads `payments/dt=*/*.json` with
`multiLine=true`, which a root-level array requires.

**Forces, by pillar:**

- **Performance Efficiency (the driving pillar).** A `multiLine` JSON file
  cannot be split, so one task reads each whole file, and Spark's parser
  turns a root-level array into an in-memory row array before it returns
  any row. Peak memory therefore grows with file size. Today's files are
  about 100 KB, so this has never mattered. At about 450 bytes per event,
  100M events is about 45 GB of JSON. That data needs files large enough to
  avoid the small-file problem (about 128 MB) and small enough for a 1 GiB
  executor to read. JSON Lines (one object per line) can be split and
  streamed, so Spark reads it in parallel at bounded memory whatever the
  file size. Measured locally on 2026-10-07 with the cluster's own
  `apache/spark:3.5.9` image, `local[2]`, 512 MB heap, the events schema,
  and a forced full-row parse:

  | File | Read option | Partitions | Result |
  |---|---|---|---|
  | JSON Lines, 135 MB | `multiLine=false` | 2 | 291,777 rows |
  | JSON array, 135 MB | `multiLine=true` | 1 | 291,777 rows |
  | JSON array on one line, 135 MB | `multiLine=false` | — | `OutOfMemoryError` |
  | JSON Lines, 538 MB | `multiLine=false` | 5 | 1,167,108 rows |
  | JSON array, 539 MB | `multiLine=true` | 1 | `OutOfMemoryError` |
- **Reliability.** Bronze is append-only, so silver and gold can always be
  rebuilt from it (ADR 0002). A generator job can fail partway and be
  re-run, by a human or a retry. A re-run must not add a second copy of the
  same run's events. The ingestion Lambda avoids duplicates by not retrying
  at all (`MaximumRetryAttempts = 0`), because its random generator is
  unseeded. A batch job of 100M events needs a re-run that is safe instead.
- **Security.** `cerberus-spark` can read `bronze/payments/*` and has no
  write access to bronze at all (3.5). Any generator writing into bronze
  needs a new grant. Spark's file committer stages output and then renames
  it, and on S3 a rename is a copy plus a delete. So the grant includes
  `s3:DeleteObject`, which no role in bronze holds today.
- **Operational Excellence.** The scale data must be easy to tell apart
  from the daily Lambda feed: to count it, to reconcile it per run (8.4),
  and to measure each ladder step.
- **Cost Optimization.** 45 GB of bronze costs about $1.04/month in S3
  Standard and about $0.56/month after the 30-day move to Standard-IA (ADR
  0002's lifecycle rule applies bucket-wide). Writing it costs a few
  hundred `PUT`s. Neither is a deciding force, but both must stay inside
  Phase 8's $20/month.

**Options considered:**

| Option | Shape and place | Verdict |
|---|---|---|
| A. JSON arrays in `payments/` | Same files as the Lambda writes, so today's silver job reads them unchanged | Keeps the unsplittable, fully materialised read. Spark has no JSON-array writer, so this needs custom bracket logic per output file and a rename step to get a `.json` name. A rename on S3 is a full copy of 45 GB |
| B. JSON Lines in `payments/` | Spark's native JSON writer into the same partitions | Today's silver job reads these files with `multiLine=true` and **silently keeps only the first object of each file** (confirmed locally: a three-line file read with `multiLine=true` returns one row). That is a wrong-count failure, not an error. Ruled out |
| C. **JSON Lines in a sibling prefix** | `payments_bulk/run_id=<id>/dt=YYYY-MM-DD/part-*.json` | Splittable, native writer, no rename, invisible to today's silver job, separate from the daily feed |
| D. Parquet in bronze | Columnar from the start | Breaks ADR 0002's "raw JSON in bronze, Parquet from silver on" trade and makes the generator do silver's job. Ruled out |

## Decision

**Option C. The scale generator writes JSON Lines to a sibling prefix in
the bronze bucket:**

```
s3://cerberus-platform-bronze-<account>/payments_bulk/run_id=<run_id>/dt=YYYY-MM-DD/part-*.json
```

- **Same event schema, different file shape.** Each line is one event with
  exactly the fields and nesting of ADR 0003 (`merchant`, `customer` and
  `payment_method` as nested objects, `event_timestamp` as an ISO-8601 UTC
  string). Only the container changes: one object per line instead of one
  array per file. The Lambda keeps writing arrays to `payments/`. Bronze
  holds one dataset with two file shapes, one shape per prefix.
- **`run_id` in the path makes a re-run idempotent.** All randomness in an
  event comes from a hash of (`run_id`, row id), and "now" is a fixed run
  timestamp passed in as an argument, not the wall clock. So a run with the
  same arguments produces the same events. The job writes with dynamic
  partition overwrite, which replaces only that run's `dt=` directories.
  A re-run therefore replaces its own output and never doubles it, and no
  other run or the daily feed is touched. Transaction IDs are derived from
  the same hash, so they are unique across runs.
- **The ladder is cumulative.** Each step adds a new `run_id` (about 1M,
  then 9M, then 90M events) instead of deleting and regenerating. Bronze
  only grows, as ADR 0002 requires, and 8.5's incremental path gets
  genuinely new data at each step.
- **Files of about 128 MB.** The job sets the output partition count from
  the target event count, so each `dt=` directory gets files near 128 MB:
  about one per day at 1M events, about five at 10M, and about 44 at 100M
  (about 350 files in all).
- **Readers.** Today's silver job reads only `payments/dt=*/*.json`, so it
  never sees `payments_bulk/`. The 8.5 Iceberg silver job reads both
  prefixes and unions them before the `MERGE INTO` from ADR 0017:
  `payments_bulk/` with `multiLine=false`, and `payments/` with
  `multiLine=true`. (`payments_lib` writes each array on one line, so
  `multiLine=false` also reads today's daily files correctly. That would
  allow one reader for both prefixes, but it only works while each array
  file stays small: a 135 MB single-line array ran out of memory. So 8.5
  keeps the two options explicit.) Because a re-run produces
  identical events, a re-run that ADR 0017's watermark picks up again as
  newer objects merges as a no-op on `(transaction_id, event_type)`.
- **IAM.** `cerberus-spark` gains `s3:PutObject`, `s3:GetObject` and
  `s3:DeleteObject` on `bronze/payments_bulk/*`, and its `s3:ListBucket`
  prefix condition widens from `payments/*` to also allow `payments_bulk/*`.
  Nothing outside `payments_bulk/` gains write or delete. `payments/`, the
  daily feed, stays read-only for `cerberus-spark`.
- **How it runs.** A second SparkApplication manifest and a submit script
  next to the existing ones in `transform/spark/`, submitted by hand during
  a `dev-compute` exercise. The state machine does not change.

## Consequences

- **Bronze reads scale with cores, not with file size.** Splittable input
  is what lets the 10M and 100M steps use every executor, and it removes
  the materialised-array memory risk for bulk data. The daily feed keeps
  the old shape, which is harmless at about 100 KB per file.
- **Two file shapes in one bronze dataset.** Every bronze reader from 8.5
  on must read two globs with two options. That is a real cost in
  complexity. It is accepted because changing the Lambda to JSON Lines too
  would rewrite a working daily path for no gain at its volume, and
  `RETIRE_ON_OR_AFTER` (2026-10-30) may retire that path anyway.
- **The first delete permission in bronze.** ADR 0002 makes bronze
  append-only "in normal operation", with versioning as the backstop. The
  new `s3:DeleteObject` exists for the committer's staging and for a
  same-`run_id` re-run. It is limited to `payments_bulk/`, and a deleted or
  replaced object stays recoverable as a noncurrent version. Recorded as
  the security cost of an idempotent batch writer.
- **Re-runs leave noncurrent versions.** Bronze has no noncurrent-version
  expiration, so a re-run of a 100M step keeps the old 45 GB as noncurrent
  versions until they are removed by hand. Re-runs should be rare, and the
  run summary must report them.
- **The data-quality suite (8.4) reconciles per prefix.** Counts must
  match per `run_id` (events written = events the job reported) as well as
  bronze to silver overall.
- **The generator copies the lifecycle rules, not the code.** The roster
  and the probabilities in `payments_lib.py` are duplicated in the Spark
  job, because the image has no Faker and the job runs as a single file.
  A unit test checks the copied roster against `payments_lib.build_roster()`
  so the two cannot drift silently. This follows the existing hand-synced
  column lists noted in ADR 0017.
- **Not decided here:** the S3A committer (the default one copies each
  file once at commit time; the "magic" committer avoids that but needs the
  `spark-hadoop-cloud` package), executor sizing, and Spot. Those are 8.6
  and 8.7 decisions, made against measurements from this generator.

## Amendment (2026-10-09): each run ends with a `_manifest.json`

Every generator run now writes `payments_bulk/run_id=<id>/_manifest.json`
after its data: per dt, the event count and the data files' count and
total bytes, as listed right after the write. It is part of the bronze
format from here on.

- **Why:** the data-quality suite (8.4) re-read all of `payments_bulk/` on
  every run. At 10M events that was 49 GB per suite, and at 100M it would
  cost over $1 a run and pass the per-query cutoff. Since bronze is
  append-only (ADR 0002), the suite now checks each run once, in full,
  when it is new, and afterwards treats the manifests as a ledger: their
  sum is the bulk event total, and a free S3 listing compares every run's
  files and bytes with its manifest, so a deleted or rewritten old run
  still fails.
- **Written last:** a run without a manifest is unfinished; the suite
  reports it as such (`bulk_runs_without_manifest`).
- **Kept out of the data:** the leading underscore keeps the file out of
  Athena's tables and the silver job's `run_id=*/dt=*/*.json` glob, the
  same way Spark's `_SUCCESS` marker is.
- **Runs before this amendment:** `backfill_bulk_manifests.py` wrote their
  manifests from the run records whose per-run count check had passed.
- **Per-run reads:** `bronze_payments_bulk_by_run`, a partition-projected
  Glue table over the same files (`run_id` and `dt` both injected), lets
  the suite read one run's dt at a time; the unpartitioned
  `bronze_payments_bulk` stays for the suite's `--full` audit.
