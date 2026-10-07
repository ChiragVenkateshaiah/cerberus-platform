# Scale metrics (Phase 8)

_The metric set every step of the Phase 8 scale ladder records, where each
number comes from, and the baseline at today's volume. Defined in 8.3;
the collector is
[`observability/scale/collect_run_metrics.py`](../observability/scale/collect_run_metrics.py),
and its output for each run lands in
[`observability/scale/runs/`](../observability/scale/runs/)._

[plan.md](plan.md#phase-8--scale-validation) names six numbers to measure
at every step: run time, events per second, bytes read and written, cost
per million events, Prometheus series count, and the data-quality result.
This page pins each one to a source that already exists, so a step's
numbers come from one command after the run, not from memory or
screenshots.

## The metric set

| Metric | Definition | Source | Read as |
|---|---|---|---|
| **Run time** | Wall clock from execution start to stop, and per state (`InvokeIngestion`, `RunTransform`, `RunDbt`, `RunServingQuery`) | Step Functions execution history: `TaskStateEntered` → `TaskStateExited` timestamps | `cerberus-admin` |
| **Events processed** | Events the run had to process. The current full rebuild processes every silver event; from 8.5 (incremental) it is the new events only, passed with `--events-processed` | Athena `count(*)` on `payments_events` after the run | `cerberus-transform` (`cerberus-admin` can't start queries, 7.3) |
| **Events per second** | Events processed ÷ seconds, for the whole run and for each state | Derived | — |
| **Spark bytes read** | Sum over executors of each executor's peak `metrics_executor_totalInputBytes_bytes_total` inside the run window, per `spark_app` | AMP (Prometheus), SigV4 query API | `cerberus-admin` (`aps:QueryMetrics`) |
| **Spark shuffle bytes** | Same method with `metrics_executor_totalShuffleWrite_bytes_total` | AMP | `cerberus-admin` |
| **Bytes stored** | Object count and bytes under bronze `payments/`, bronze `payments_bulk/` (and one generator `run_id`), silver `payments/`, and gold | S3 `ListObjectsV2`, a snapshot at collection time | `cerberus-admin` |
| **Athena bytes** | Per state: query count, bytes scanned, and bytes billed (each query billed at least 10 MB, rounded up to the MB) | `GetQueryExecution` for each query in the `cerberus_platform` workgroup submitted inside the state's window | `cerberus-admin` |
| **Peak active series** | The highest count of series with a sample at any 15 s step during the run | AMP: `max_over_time(count({__name__=~".+"})[<run>:15s])` | `cerberus-admin` |
| **Cost per million events** | Run cost ÷ (events processed ÷ 1M), where run cost = the day's platform cost per EKS cluster-hour × run hours + the run's Athena billed cost | Cost Explorer, one request (see the cost method below) | `cerberus-admin` |
| **Data quality** | Pass/fail per check, including the bronze → silver count reconciliation ADR 0017 requires | The 8.4 suite. Until 8.4 lands, the record holds `null` | — |

The generator (`transform/spark/generate_bulk.sh`) is measured separately,
because it runs outside the state machine. Its driver prints a manifest of
`[generate]` lines (events per `dt`, total, write seconds, events per
second). `--generator-run-id` adds the size of that run's bronze prefix to
the record.

## Cost method

Cost Explorer has the only real numbers, and they have two limits: they
post about a day later, and they are daily. The method works with both.

- **Scope: the region, not the tag.** On 2026-10-06, usage tagged
  `Project=cerberus-platform` was $0.46, and untagged usage in us-east-1
  was $0.41. The largest untagged line was **EC2 compute ($0.33): the EKS
  node instances carry no `Project` tag**, because a managed node group
  does not pass the provider's `default_tags` to the instances it
  launches. The platform is the only workload in us-east-1, so the
  collector counts all us-east-1 and global usage (credits excluded,
  `RECORD_TYPE = Usage`) and leaves the tag out. The account's other
  regions are not the platform.
- **Cost Explorer's own charge is excluded.** Each API request costs
  $0.01, and that charge shows up as an `AWS Cost Explorer` service line.
  The collector makes exactly one request, and only with `--cost`.
- **Day → run.** The day's cost divided by that day's EKS cluster-hours
  (usage type `AmazonEKS-Hours:perCluster`) gives a platform cost per
  cluster-hour, which covers nodes, NAT, the EKS control plane, AMP and
  the rest together. Run cost is that rate × the run's hours, plus the
  run's Athena billed bytes at $5/TB. The day's total is recorded too, as
  the "all-in" exercise cost.
- **One exercise per UTC day** keeps the attribution clean. Two different
  ladder steps on one day would share one rate.
- **Collect `--cost` the day after** for the posted number. The record
  keeps Cost Explorer's `Estimated` flag either way.

## Baseline at today's volume

The current pipeline (full rebuild, Hive Parquet) at about 39k events.
The five successful orchestrated runs at this volume are all still in
Step Functions history. All five ran before #50 merged (2026-10-06
11:26 UTC; the last run ended 08:00 UTC). #50 changed two things the
pipeline runs, and both sit in the two shortest states:

- **`InvokeIngestion`:** the Lambda's `payments_lib` now builds tokens
  from 16 letters (`secrets`) instead of 16 hex characters. Same event
  count and size; the state takes about 3 s.
- **`RunServingQuery`:** the demo query now groups by currency as well
  (45 rows, not 15). It reads one more small column. At this volume it
  still scans well under 10 MB, so Athena bills the same 10 MB minimum.

`RunTransform` and `RunDbt`, about 84% of the run time and all of the
Spark and dbt bytes, ran exactly the code on `main` today. So these runs
stand as the baseline without a new exercise.

**Run time, seconds:**

| Execution | Total | InvokeIngestion | RunTransform | RunDbt | RunServingQuery |
|---|---|---|---|---|---|
| `demo-7-8-take1-20261006T075445` | 363 | 3.1 | 205.6 | 100.3 | 54.3 |
| `rehearsal-7-7-20261006T063937` | 400 | 3.4 | 233.1 | 106.3 | 57.3 |
| `phase7-exercise-run-3-20260929T050716Z` | 357 | 3.5 | 194.4 | 104.0 | 55.3 |
| `phase7-exercise-run-2-20260929T050053Z` | 355 | 3.4 | 191.3 | 102.1 | 58.3 |
| `phase7-exercise-run-1-20260929T045257Z` | 384 | 3.2 | 220.7 | 102.6 | 57.3 |
| **Median** | **363** | **3.4** | **205.6** | **102.6** | **57.3** |

**Full record for the latest run** (`demo-7-8-take1-20261006T075445`,
[JSON](../observability/scale/runs/demo-7-8-take1-20261006T075445.json)):

| Metric | Value |
|---|---|
| Events processed (full rebuild) | 39,222 events, 12,862 transactions |
| Events per second, whole run | 108 |
| Events per second, `RunTransform` | 191 |
| Spark bytes read | 54.6 MB (bronze `payments/` holds 18.2 MB) |
| Spark shuffle write | 6.2 KB |
| Silver / gold stored | 2.6 MB in 80 objects / 0.7 MB in 4 objects |
| Athena | 33 queries, 2.74 MB scanned, about 330 MB billed |
| Peak active series | 4,307 |
| Day cost, 2026-10-06 (estimated) | $0.84 for 2.10 cluster-hours = $0.40 per cluster-hour |
| Run cost | $0.042 |
| **Cost per million events** | **$1.07** |
| Data quality | The 14 manual checks on 2026-10-06 were clean after the #50 fixes. The suite becomes code in 8.4 |

## What the baseline already shows

- **The silver job reads bronze three times.**
  `promote_payments_spark.py` runs three Spark actions on the uncached
  bronze DataFrame: `count()`, `distinct().collect()` for the day list,
  and the write. Spark read 54.6 MB for 18.2 MB of bronze, exactly 3×.
  At 100M events (about 45 GB of bronze) that is about 135 GB read per
  run. 8.5 replaces this job; the replacement must read bronze once.
- **Fixed overhead dominates at this volume.** `RunTransform` takes about
  200 s for about 2 MB of Parquet output, so most of it is ECS task start,
  operator submission and pod scheduling, not data work. The ladder will
  show where data work overtakes that overhead.
- **Most of an exercise day's cost is the cluster waiting, not the
  runs.** On 2026-10-06 the cluster was up 2.10 hours ($0.84), and the
  two orchestrated runs used about 13 minutes of that ($0.084, 10%). The
  rest was bring-up, checks, the screen recording and teardown. At about
  $0.40 per cluster-hour, every idle 15 minutes costs about $0.10, more
  than two whole runs. The cheapest cost optimization at this volume is a
  shorter bracket (apply, run, collect, destroy without pauses), not a
  faster pipeline. This changes at 10M+ events, where the runs
  themselves get long.
- **`RunServingQuery` measures polling, not Athena.** The demo query
  executes in under 1 s, but the state takes 54–58 s in every run.
  Step Functions checks the `.sync` Athena integration's status on an
  interval it chooses, so this state has a floor of about a minute. Read
  Athena's own `TotalExecutionTimeInMillis` for query speed. A
  start-then-poll loop with a short `Wait` state would remove about 50 s
  per run. That is worth about $0.006 per run at $0.40 per cluster-hour,
  so it is a latency fix (SLO 3), not a cost fix.
- **Athena's 10 MB minimum dominates its bill at this volume.** 2.74 MB
  scanned is billed as about 330 MB. The ratio flips as the data grows.
- **Cost attribution needs node tags.** Until the node group tags its
  instances, the tag-filtered view misses about 40% of an exercise day.
  The region scope above works around it. The real fix (a launch template
  with `tag_specifications`) belongs with the node group changes in
  8.7/8.8.

## Running the collector

After a run, before the next one (the S3 sizes and the silver count are a
snapshot):

```bash
uv run --no-project --with boto3 python observability/scale/collect_run_metrics.py \
    --execution <execution-name> [--generator-run-id <run_id>] [--events-processed N]
```

The next day, once Cost Explorer has posted, add the cost to the same
record. `--cost-only` touches only the `cost` section, so the run-time
snapshot stays as collected (one Cost Explorer request, $0.01):

```bash
uv run --no-project --with boto3 python observability/scale/collect_run_metrics.py \
    --execution <execution-name> --cost-only
```
