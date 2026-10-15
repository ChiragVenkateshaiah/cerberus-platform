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
| **Events processed** | Events the run had to process. The old full rebuild processed every silver event; since 8.5 (incremental) it is the events the run added | Since 8.5: the sum of `added-records` over silver's Iceberg append snapshots committed during the run (`"payments_events$snapshots"`). Before: `count(*)` on `payments_events`. `--events-processed` overrides both | `cerberus-transform` (`cerberus-admin` can't start queries, 7.3) |
| **Events per second** | Events processed ÷ seconds, for the whole run and for each state | Derived | — |
| **Spark bytes read** | Sum over executors of each executor's peak `metrics_executor_totalInputBytes_bytes_total` inside the run window, per `spark_app` | AMP (Prometheus), SigV4 query API | `cerberus-admin` (`aps:QueryMetrics`) |
| **Spark shuffle bytes** | Same method with `metrics_executor_totalShuffleWrite_bytes_total` | AMP | `cerberus-admin` |
| **Bytes stored** | Object count and bytes under bronze `payments/`, bronze `payments_bulk/` (and one generator `run_id`), silver `payments/`, and gold | S3 `ListObjectsV2`, a snapshot at collection time | `cerberus-admin` |
| **Athena bytes** | Per state: query count, bytes scanned, and bytes billed (each query billed at least 10 MB, rounded up to the MB) | `GetQueryExecution` for each query in the `cerberus_platform` workgroup submitted inside the state's window | `cerberus-admin` |
| **Peak active series** | The highest count of series with a sample at any 15 s step during the run | AMP: `max_over_time(count({__name__=~".+"})[<run>:15s])` | `cerberus-admin` |
| **Cost per million events** | Run cost ÷ (events processed ÷ 1M), where run cost = the day's platform cost per EKS cluster-hour × run hours + the run's Athena billed cost | Cost Explorer, one request (see the cost method below) | `cerberus-admin` |
| **Data quality** | Pass/fail per check across bronze → silver → gold, including the bronze → silver reconciliation ADR 0017 requires (see [Data-quality suite](#data-quality-suite)) | [`data_quality.py`](../observability/scale/data_quality.py): one Athena query per check, run by the collector | `cerberus-transform` |

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
- **Collect `--cost-only` the day after** for the posted number. The
  record keeps Cost Explorer's `Estimated` flag either way, but that flag
  stays `true` until the month closes, so it can't show a partly posted
  day. The record's `complete` field does: a day with EKS hours but no EC2
  compute hasn't fully posted (on 2026-10-08, the day-old 2026-10-07
  exercise showed 0.26 of about 1.2 cluster-hours). Don't commit an
  incomplete cost; re-run `--cost-only` later.

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
| Data quality | The 14 manual checks on 2026-10-06 were clean after the #50 fixes. Since 8.4 the suite is code and runs with every collection |

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

## 8.6 at 10M: what the measurements show

Four timed exercises on 2026-10-08 and 2026-10-09, each changing one thing.
Driver logs, Spark stage timings and Iceberg metadata, not estimates.

### Fixed overhead first

| Change | Run | RunTransform | Effect |
|---|---|---|---|
| none (baseline, 1M silver, 6k new events) | `exercise-20261008T160759Z` | 178.3 s | -- |
| Spark image pre-pulled by a DaemonSet (#76) | `exercise-20261009T062108Z` | 159.0 s | **-19.3 s**; driver and executor log "already present on machine" |

The ECS Fargate wrapper around the job costs a fixed ~50 s per run (25 s to
start, 25 s to stop) in every run measured; ADR 0019 keeps it, with stated
triggers to replace it.

### The 10M pair: executor sizing

| | Before (`exercise-20261009T074853Z`) | After (`exercise-20261009T101830Z`) |
|---|---|---|
| Executors | 1 x 1 core x 1 GB | 2 x 1 core x 2 GB (#77) |
| New events | 9,005,590 | 9,005,875 |
| Silver read by the anti-join | ~1.1M rows | ~10.1M rows |
| **RunTransform** | 323.3 s | **241.6 s (-25%)** |
| Run cost | $0.137 | $0.175 |
| Cost per million events | $0.02 | $0.02 |

The "after" run was faster while its anti-join read a silver table twice as
large. Its RunDbt failed for an unrelated reason (below), so it has no clean
RunDbt number.

### Where the 10M "after" run's Spark time went

About 2 minutes of data work inside the 242 s step:

| Stage | Tasks | Wall time | Work |
|---|---|---|---|
| 2 | 34 | 58.7 s | read 4.4 GB of bronze JSON, flatten, de-duplicate (map side) |
| 3 | 20 | 71.9 s (in parallel with 2) | read silver's keys for the anti-join |
| 6 | 30 | 25.7 s | the shuffle: de-duplication and the anti-join |
| 10 | 8 | 14.8 s | the Iceberg write, one task per event day |

What that says about the four 8.6 levers:

- **Partition sizing:** the read splits 4.4 GB into 34 tasks (128 MB
  input splits) for 2 task slots, so slots, not splits, are the limit.
  Stage 2 is 117 s of task time on 2 cores: JSON parsing is CPU-bound.
- **AQE:** already on (Spark 3.5's default). The shuffle ran 30 tasks
  instead of the default 200 -- AQE coalescing small partitions. Nothing
  to switch on.
- **Skew:** mild, and from the data's shape rather than hot keys. Task
  times vary about 2x (event days hold 0.5M to 1.3M events); no task waits
  on a straggler, and the anti-join is not skew-bound.
- **Compaction:** not needed yet. Silver holds 19,087,262 rows in 54 files
  (1.23 GB) over 35 days; the busy days have 3 files of 50-60 MB, and the
  maintenance step correctly compacted nothing (`min-input-files` 5).

So 8.6 found no setting worth changing at 10M: the job is CPU-bound on two
cores. The next lever is more cores -- the autoscaler, Spot and dynamic
allocation in 8.7/8.8 -- not configuration. Day pruning for the anti-join
(written on 2026-10-08) ships with the next runner-image rebuild; with
every batch spanning the same 7-8 days it saves little until the
realistic time spread (Planned later work, docs/plan.md).

### What 10M broke outside Spark

- **Athena's 1 GiB per-query cutoff**, set as a guardrail in Phase 1,
  stopped two things in turn: five data-quality checks
  (`CANCELLED: Bytes scanned limit was exceeded`, run 1) and dbt's
  incremental `fct_transactions` merge (run 2, all three attempts; gold
  2,955,241 transactions behind until a manual `dbt build` caught it up
  exactly). The suite moved to its own workgroup (#81) and the shared
  cutoff went to 10 GiB (#83).
- **The data-quality suite's cost:** re-reading all of bronze cost 49 GB
  per run at 19M events. It now checks bronze as a manifest ledger (#85,
  ADR 0018 amendment): 8.1 GB per run, 12.5 GB with a new 10M run, with a
  `--full` audit (25.1 GB) before milestones.
- **A stale log line:** both 10M runs' "appended ... (silver now ...)" line
  printed the snapshot from before their own append (the Glue catalog's
  cached table); the data and the run records were right. A
  `REFRESH TABLE` before the read is the fix, confirmed on 2026-10-12
  (`exercise-20261012T111304Z` logged `silver now 28099699`, the record's
  exact count, and its watermark moved forward).

## 8.8 under load: autoscaler, Spot and dynamic allocation

Two exercises on 2026-10-12 on ADR 0020's node layout: an On-Demand system
node for the driver and the add-ons, and a tainted Spot executor group under
Cluster Autoscaler, sized at 1 node before each run (`--executor-nodes 1`).

| | First run (`exercise-20261012T075045Z`, #92) | Load test (`exercise-20261012T111304Z`, #94) |
|---|---|---|
| Executors | 2 fixed (1 core, 2 GB) | dynamic: 2 at start, 1-8 |
| New events | -- (no generator) | 9,006,333 |
| Silver before the run | -- | ~19.1M rows |
| RunTransform | 182 s | 295.7 s |
| RunDbt | 538.5 s (2 Glue `OperationTimeoutException` retries) | 143.5 s |
| Data quality | passed | passed (ledger, 16.4 GB, 25.9 s) |

The first run proved the layout: the driver on On-Demand, executors on Spot
(m7i.xlarge), the pre-pull DaemonSet on both node groups, the instances
tagged, and a clean teardown.

### The load test, from a 5-second watcher and the driver log

| Time (UTC) | Event |
|---|---|
| 11:34:14 | driver starts; 2 executors on the one Spot node |
| 11:34:55 | backlogged tasks: dynamic allocation asks for 3, then 4, 6, 8 executors |
| 11:35:01 | 4 executors Running, 4 Pending (the node holds four 1-core executors) |
| ~11:35:01 | Cluster Autoscaler: `triggered scale-up: executors 1->2 (max: 4)` |
| 11:35:46 | the new node Ready, the 4 executors creating |
| 11:36:01 | **8 executors Running** -- ~60 s after the scale-up |
| 11:37:23 | silver append committed |
| 11:37:35-52 | idle executors removed after 30 s, each `gracefully decommissioned` (0 unexpectedly exited) |
| 11:37:58 | driver ends |
| 11:40-11:41 | the idle second node drained and removed; the planned minimum of 1 kept |

The executor pods carry the `preStop` hook `/opt/decom.sh`, so a Spot node
that is reclaimed asks its executors to decommission before they stop.

### Why RunTransform was slower than the 10M "after" run

295.7 s against 241.6 s is not a regression; the job did more:

| | 10M "after" (2026-10-09) | Load test |
|---|---|---|
| Silver keys read by the anti-join | ~10.1M rows | ~19.1M rows |
| Watermark to append | 121 s | 150 s |
| Compaction (`min-input-files` 5) | 0 files | 25 files into 5, ~35 s |
| Spark time (driver start to end) | 167 s | 224 s |

And for ~60 s of the 150 s main stage only 4 executors ran, waiting on the
new node. So this run proves the scaling works (scale-up, scale-down,
graceful decommissioning); it does not measure a speed-up. A same-input
comparison belongs to 8.9 at 100M, where the extra executors matter most.

### Notes from the load test

- **Data-quality cost grows with silver:** 16.4 GB scanned against 12.5 GB
  on 2026-10-10. The silver checks read the whole table; 8.9 must allow
  for it.
- **A node swap before the job:** at 11:33, after the generator finished, a
  second Spot node came up and the first one drained, with no job running.
  Most likely an EKS managed node group Spot capacity rebalance; not
  confirmed.
- **Glue timeouts in RunDbt** did not recur (watch item from the first
  run).

### Spot interruption test (`exercise-20261012T133620Z`, #96)

`exercise.sh --interrupt-spot` started the AWS FIS experiment
`EXPqsCtFGsYV5mbxKc` (`aws:ec2:send-spot-instance-interruptions`, PT2M)
once the silver job had 2 executors running. It hit the planned Spot node,
`i-0b29379f1257004c9` (ip-10-0-18-248), which by then held 4 of the job's
executors.

| Time (UTC) | Event |
|---|---|
| 13:55:04 | silver job driver starts (On-Demand system node) |
| 13:55:36 | FIS experiment starts: rebalance recommendation + 2-minute notice |
| 13:56:01 | EKS cordons the node; the drain evicts executors 2, 4, 6, 8, each running `/opt/decom.sh` |
| 13:56:31 | all 4 `gracefully decommissioned` (after 13.5-29.9 s); 2 shuffle map tasks resubmitted |
| 13:56:42 | dynamic allocation re-requests executors; Cluster Autoscaler `executors 1->2 (max: 4)` |
| 13:57:18-23 | two new Spot nodes Ready (the Auto Scaling group's replacement and the scale-up) |
| 13:57:38 | the interrupted node removed |
| 13:58:51 | silver append committed: 9,005,730 events, `silver now 37105429` |
| 13:59:34-14:01:04 | Cluster Autoscaler removes the two empty extra nodes; 1 Spot node left |

Result: **the execution SUCCEEDED and data quality PASSED** -- silver
37,105,429 = bronze 37,105,429, every new-run key in silver, no duplicate
keys, gold matches silver. The driver's executor-removal statistics:
`gracefully decommissioned: 4, decommision unfinished: 0, driver killed: 0,
unexpectedly exited: 0`.

| | Load test (no interruption) | Interruption test |
|---|---|---|
| Silver before the run | ~19.1M rows | ~28.1M rows |
| Watermark to append | 150 s | 188 s |
| Compaction | 25 files into 5, ~35 s | 0 files |
| Spark time (driver start to end) | 224 s | 238 s |
| RunTransform | 295.7 s | 314.1 s |

The interruption cost the job tens of seconds, not a failure or a retry:
two map tasks re-ran, and the 4 lost executors were back in about a minute.
The two runs differ in silver size and compaction, so the exact cost is not
isolated.

What it shows for ADR 0020: executors on Spot are safe for this job. The
driver stays on On-Demand, EKS drains on the rebalance signal well inside
the 2-minute notice, Spark's decommissioning finishes before the 90 s
force-kill timeout, and the data comes out exact.

- **Data-quality scan keeps growing:** 20.5 GB this run (12.5 -> 16.4 ->
  20.5 GB as silver grew 19M -> 28M -> 37M rows). The silver checks read
  the whole table; at 100M rows a single check may pass the 10 GiB cutoff.
  8.9 must make the silver checks incremental or size the cutoff first.
- The one data-quality warning is the known `token_digit_runs` (97 legacy
  hex tokens from before #50).

## 8.9 at 100M: the full orchestrated run

One exercise on 2026-10-13 (`exercise-20261013T055859Z`, run record in
`observability/scale/runs/`), started with
`make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2"`
on the limits raised in #97. The generator landed 100,002,421 events in
bronze; the orchestrated run then promoted 100,008,511 new events (the
Lambda's few thousand included) on top of 37.1M, taking silver to
137,113,940 events and 44,991,746 transactions. Status SUCCEEDED, 742 s;
data quality passed. Teardown left EKS 0, NAT 0, EIP 0, running instances 0.
Cluster time was 3,773 s in total (63 min).

| Step | Seconds | Notes |
|---|---|---|
| Generator (outside the state machine) | 1,325 wall, 1,253 write | 8 executors, 79,810 events/s |
| InvokeIngestion | 4.2 | |
| RunTransform | 511.6 | 100M events, about 195k events/s |
| RunDbt | 167.9 | Athena $0.081 |
| RunServingQuery | 58.3 | |
| Data-quality suite | 28.8 | 26 checks, 105.9 GB scanned |

### Against the 10M step

| | 10M "after" (2026-10-09) | 100M |
|---|---|---|
| New events | ~9.0M | 100.0M |
| Silver before | ~10M | 37.1M |
| RunTransform | 241.6 s | 511.6 s |
| Events per second in RunTransform | ~37k | ~195k |

Eleven times the events took 2.1 times as long, so the per-event time fell
by more than five times. Dynamic allocation did that: the 10M run used two
2 GB executors, this run up to 16.

### Autoscaler and Spark at 100M

- Spark asked for 16 executors within seconds of the stage starting
  (`maxExecutors` 16, #97). The planned two Spot nodes held about 8; the
  autoscaler set the group to 4 nodes, its maximum, which is 16 vCPU of the
  32 vCPU Spot quota. Later stages asked again ("Requesting 15 new
  executors") as idle executors were released and work came back.
- Watermark to append: about 305 s (06:36:26 to 06:41:31). Compaction then
  merged 80 files into 22 (about 96 s) before the driver ended.
- Idle nodes were removed by `ScaleDown` after the job; two Spot nodes and
  the system node were left at the last snapshot.
- The speed-up from extra executors is not isolated here: silver was 3.7
  times larger and the executor count changed together, so this run shows
  the platform absorbing 100M, not the gain from any one setting.

### What to note

- **Generator slower than planned.** #97 expected about 8-10 min with 8
  executors; it took 22 min (1,325 s). The generator, not the pipeline, is
  now the longest step. The cause is not measured.
- **Data-quality scan grew faster than projected.** 105.9 GB against 20.5 GB
  at 37M rows, about 5.2 times for 3.7 times the silver rows; the
  projection was about 76 GB. At $5 per TB that is about $0.53 a run. Every
  check passed under the 10 GiB cutoff; per-check bytes are not recorded
  (the Athena records for that workgroup are readable only by
  `cerberus-transform`), so the largest check is unknown.
- **Prometheus peak:** 10,370 active series, just over ADR 0016's ~10k
  estimate.
- **No Glue timeouts** in RunDbt, and no retries.
- The one data-quality warning is the known `token_digit_runs`.

### Cost per million events

Cost Explorer posted 2026-10-13 on 2026-10-15 (`--cost-only`; the day is
`complete`, flagged `Estimated` until the month closes). The day cost
$1.78, all of it this exercise (EC2 other $0.74, Athena $0.57, EC2 compute
$0.24, S3 $0.13, EKS $0.09). At $2.0355 per cluster-hour, the cost per
step is the step's seconds × that rate, plus its Athena bytes at $5/TB.
Events are the 100,008,511 the run promoted.

| Step | Seconds | Cluster $ | Athena $ | Total $ | $ per M events |
|---|---|---|---|---|---|
| InvokeIngestion | 4.2 | 0.0024 | 0 | 0.0024 | 0.00002 |
| RunTransform | 511.6 | 0.2893 | 0 | 0.2893 | 0.0029 |
| RunDbt | 167.9 | 0.0949 | 0.0806 | 0.1755 | 0.0018 |
| RunServingQuery | 58.3 | 0.0330 | 0.0007 | 0.0337 | 0.0003 |
| **State machine** | 742 | 0.4195 | 0.0813 | **0.5008** | **0.0050** |
| Data-quality suite (outside the run) | 28.8 | 0 | about 0.53 | about 0.53 | 0.0053 |
| Generator (outside the run) | 1,325 | 0.7491 | 0 | 0.7491 | 0.0075 |
| **Whole exercise (day total)** | 3,773 cluster | | | **1.78** | **0.0178** |

- The orchestrated run costs half a cent per million events. The whole
  exercise costs 1.8 cents, because the generator (22 min of cluster time)
  and the data-quality scan cost more than the run itself. Neither is
  pipeline cost in production; both are cost of the test harness.
- The 10M step cost about $0.02 per million events for RunTransform alone
  (8.6). The 100M run is cheaper per event even with 16 executors, because
  the cluster-hour rate is fixed and the work per hour grew 5 times.
- RunTransform is 58% of the run's cost; RunDbt is 35%, and its Athena
  bytes (15.8 GB scanned, 33 queries) are 46% of that step.
- **Unexplained:** Cost Explorer shows 0.875 EKS cluster-hours, but the
  cluster was up 3,773 s (1.05 h). The per-hour rate is therefore about
  20% higher than the true rate if the 1.05 h is the right count. The
  total is the posted number and does not change.
- The three 2026-10-12 exercises also have cost now: $0.25 (the first Spot-layout run,
  almost no events), $0.16 (9M load test) and $0.17 (Spot interruption test).

### SLOs under load

[docs/slo.md](slo.md) targets against this run (a single run, so a
spot-check, not a budget statement):

| # | Objective | Result at 100M |
|---|---|---|
| 1 | Pipeline success | SUCCEEDED, no retries, no failed states |
| 2 | Gold freshness (< 24 h) | Met: gold was written by RunDbt during the run |
| 3 | Run latency (< 30 min) | **Met: 742 s (12.4 min), 41% of the limit.** The 45 min alarm would fire at 3.6 times this |
| 4 | Serving query (< 30 s) | The state took 58.3 s, over 30 s. Most of that is the ~55 s polling floor; the Athena query time is not in the record, so this is not shown met |
| 5 | Data quality (hard gate) | dbt build passed; the 26-check suite passed with one known warning |
| 6 | Observer freshness | Not load-related; not measured here |

Latency at 100M has headroom of 2.4 times. Objective 4 needs the query's
own `EngineExecutionTime` recorded to be judged under load: add it to the
collector (follow-up).

## Data-quality suite

Added in 8.4. [`observability/scale/data_quality.py`](../observability/scale/data_quality.py)
runs one Athena query per check, all at once, as `cerberus-transform`. Each
returns a violation count (0 = pass). `error` checks fail the suite and
`warn` checks are reported but accepted. A check that can't run (a missing
table, a permission gap) counts as a failure, never as a pass. The
collector runs the suite on every run and stores the result in the
record's `data_quality` field; it exits with code 3 when the suite fails,
and `make exercise` reports that separately from a collector error.

It complements the dbt tests in `transform/dbt/models/marts/schema.yml`,
which already test gold itself (unique, not null, accepted values, foreign
keys). The suite covers what no single dbt model can see:

| Group | Checks |
|---|---|
| Bronze → silver | `bronze_to_silver_count`, `bronze_to_silver_keys` (full outer join on `(transaction_id, event_type)`) |
| Silver → gold | `silver_to_gold_transactions`, `gold_status_matches_lifecycle` |
| Silver rules (ADR 0003) | `silver_duplicate_keys`, `lifecycle_created_authorized`, `lifecycle_one_terminal`, `lifecycle_refunds`, `lifecycle_order`, `silver_key_nulls`, `amount_range_and_stability`, `roster`, `masking`, `token_format` |
| Incremental silver (8.5) | `silver_caught_up`: no bronze object (`"$file_modified_time"`) is newer than the watermark in silver's Iceberg snapshots. It replaced `silver_partition_placement`, which checked the `dt` column that hidden partitioning removed |
| Accepted risk (`warn`) | `token_digit_runs`: 97 legacy hex tokens from before #50 hold a 13+ digit run. Bronze is append-only, so they stay |
| `payments_bulk/` (ADR 0018) | `bulk_duplicate_keys`; `bulk_run_counts` compares one generator run's per-`dt` counts in bronze with its own `[generate]` manifest (`--generator-log`) |

Bronze is read through two Glue tables added in 8.4, both unpartitioned:
Athena reads every object under the location, and the checks take `dt`
and `run_id` from `"$path"`, so nothing has to be registered after a run.
`bronze_payments_raw` reads each Lambda file as one text line (each is a
single-line JSON array) and the checks unpack it with `json_parse`;
`bronze_payments_bulk` reads the generator's JSON Lines. Neither is in
`cerberus-serving`'s catalog grant.

**Scope since 8.5:** silver is an incremental Iceberg table built from both
bronze prefixes, so the bronze → silver checks reconcile `payments/` and
`payments_bulk/` together (`SILVER_SOURCES`). Before the first Iceberg run,
the checks that read silver's snapshots fail, as a missing table should.

**Cost:** about 14 MB scanned for the silver and gold checks at today's
volume. The two bulk checks each scan the whole bulk JSON (433 MB at 1M
events; about 45 GB at 100M, so about $0.45 per suite run at $5/TB). That
is the one part of the suite whose cost grows with the ladder; a Parquet
copy or an Iceberg table (8.5) is the fix if it starts to matter.

**Tested on 2026-10-07:** all 14 silver/gold checks passed on live data
with the one expected warning, and a duplicated event injected into the
queries' input was caught by `silver_duplicate_keys` and
`lifecycle_created_authorized`, as it should be.

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
