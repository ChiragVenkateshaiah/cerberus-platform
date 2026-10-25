# Spark status REST capture (ADR 0022 amendment, step 6b)

Local run of the real scripts, unchanged, on 2026-10-25. $0, no AWS calls.
`capture.sh` polls the driver's `:4040` status API every 5 s. `trim_fixtures.sh`
cuts the committed fixtures in `fixtures/` from the raw snapshots, which stay in
the git-ignored `scratch/`.

## What ran

| Item | Value |
|---|---|
| Image | `apache/spark:3.5.9`, local mode `local[4]`, container limit 3 CPUs / 3 GiB, driver heap 2 GiB |
| Generator | `transform/spark/generate_bulk_payments.py`, `--events 8000000`, output a local dir (no jars: hadoop 3.3.4 ships in the image, no S3 used) |
| Silver | `transform/spark/promote_payments_spark.py --catalog-type hadoop`, `--packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.2` (same version as `spark-application.yaml`) |
| Jars left out | `hadoop-aws:3.3.4`, `iceberg-aws-bundle:1.10.2`, `openlineage-spark_2.12:1.53.0`: all paths are local, the catalog is Hadoop, no OpenLineage listener is configured |
| Scale | 8,000,000 requested (an earlier 2,000,000 run finished in 33 s + 66 s (console output, not kept; unverified), too fast for mid-stage polls) |
| Generator time | 60 s wall (write 41.1 s per the log) |
| Silver time | 122 s wall |
| Incremental rounds | 6 more rounds of 300,000 events (about 23 s generator + 45 s silver each), to get a silver-key scan and the compaction |
| Peak container use | 307% CPU (cap 300%), 2.28 GiB of 3 GiB (`docker stats`, every 10 s) |

Compaction needs 5 small files per partition, so it did not run in the first
silver run (`0 files compacted`). It ran in round 4 (`40 files compacted into 8`).

## Which fields grow mid-stage

All fields come from `/applications/<id>/stages`.

- **Granularity is per finished task.** `inputRecords`, `outputRecords`,
  `shuffleReadRecords` and `shuffleWriteRecords` do not move while a task runs.
  Evidence: the generator's map stage held 1, then 4 active tasks with
  `inputRecords=0` for three polls, then showed all `2,625,103` at the next poll
  (stage `COMPLETE`).
- **Active write stage grows.** Generator write stage (32 tasks):
  `outputRecords` 823,963 at 3/32, 3,262,330 at 11/32, 5,225,752 at 18/32,
  8,000,122 at 32/32.
- **Silver bronze scan** (30 tasks): `inputRecords` 1,132,180 at 4/30 up to
  8,000,122 at 30/30. It grows through the stage.
- **Silver append ResultStage** (6 tasks): `outputRecords` 0 at 0/6 before the
  first task ends, 902,388 at 1/6, 8,000,122 at 6/6. With few tasks the counter
  moves in big steps.
- **Few tasks means big steps.** The generator's map stage (4 tasks) goes 0 to
  100% in one step. Production has 8 map tasks and 328 write tasks (plan section 2), so the write stage is smooth and the map stage is not.
- **SQL node metrics are NOT live.** In `/sql?details=true`, every
  `nodes[].metrics` list is empty while the execution is `RUNNING`. Values
  (`number of output rows`, `written output`, ...) appear only when the execution
  is `COMPLETED`. The exporter must use stages only. The plan's "Scan json rows
  (SQL)" source does not work live.
- Stage `status` values seen: `ACTIVE`, `COMPLETE`, `PENDING`, `SKIPPED`.
  `SKIPPED` stages (reused shuffle output) carry zeros and must be ignored.
  Stage field names match the plan.

## Row definitions against the logs

| Row | Spark source | End value | Log line | Match |
|---|---|---|---|---|
| Payments created | generator write ResultStage (`json at ...`, the stage with `outputRecords > 0`) | 8,000,122 | `[generate] done ... events=8000122` | yes |
| Payments created (6 small rounds) | same | 299,939 / 300,072 / 300,083 / 300,023 / 299,968 / 300,022 | `events=` of each round | yes (checked on round 4: 300,023 in the stage, 300,023 in the log) |
| New payments read | silver bronze-scan stage `inputRecords` | 8,000,122 (first run), 300,023 (round 4) | no log line has this number. `[spark-transform] new bronze files {...}` counts files only | equals `appended N` here, because the generator output has no duplicates. In production the 6,090 Lambda events and any duplicates make it differ from `appended`, as in the plan |
| Added to the clean table | silver `append` ResultStage `outputRecords` | 8,000,122 (first run), 300,023 (round 4) | `appended 8000122 new events` | yes |
| Tidying files | stages named `save at SparkBinPackFileRewriteRunner.java:62` | in round 4: 8 stages, 1 task each, `inputRecords` = `outputRecords` (0.6 to 1.3 M each) | `maintenance: 40 files compacted into 8` | left out of the counts |

Findings that change the exporter:

1. **The bronze scan and the silver-key scan have the same stage name**
   (`append at NativeMethodAccessorImpl.java:0`) in a later run. Round 4: stage 1
   read 300,023 bronze rows (5 tasks), stage 2 read 8,900,216 silver keys (14
   tasks). In the first run only the bronze scan exists (silver is empty).
   Nothing in the stage list names the source (`description` is null; `details`
   is the same call stack). In every run seen, the bronze scan has the lower
   `stageId`. Round 4: bronze (5 tasks) is stage 1 and silver (14 tasks) is
   stage 2. The 2026-10-13 log has stage 2 (367 tasks) first and stage 3 (19
   tasks) second, which fits the same rule. Rule for 6c: take the lowest
   `stageId` with `inputRecords > 0` among the stages of the first `append` job.
   Verify it in the 1M rehearsal. Production also runs a `json at ...`
   file-listing job (job 1, 515 tasks;
   `observability/scale/exercises/exercise-20261013T055859Z-spark/cerberus-promote-payments-driver.log`
   L443-452, L1583) before the scans; the local run does not show it. The rule
   must filter on job name `append at`, not stage order. Production stages 2 and
   3 are separate map-stage jobs (L1627, L1640), matching the local one stage
   per job.
2. **Stage names are all `append at NativeMethodAccessorImpl.java:0`**, not
   `json at ...`, for every silver stage (scan, shuffle, write). The ResultStage
   that writes is the one with `outputRecords > 0`. Other silver stages seen:
   `collect at /opt/jobs/promote_payments_spark.py:216` (watermark read) and
   `...:333` (maintenance), and `collectAsList at ExpireSnapshotsSparkAction.java:227`
   (snapshot expiry, round 1).
3. **Compaction runs as separate parallel jobs**: one job and one stage per
   file group, up to 5 active at the same time (`silver-compaction-active.json`).
   Job and stage ids keep rising.

## Commit and idle

- **Generator:** locally the write job ends and the count pass starts within
  one poll, so one snapshot (`generator-end-idle.json`) shows 0 running jobs with
  the write job `SUCCEEDED`. The local commit is fast (under one 5 s poll, local disk), so this
  does not show the 14.6-minute S3A commit. The shape holds: the
  application is alive, active jobs 0, active stages 0. The count pass
  (`generator-count-pass.json`) comes after.
- **Silver:** `silver-end-commit.json` shows the append stages all `COMPLETE`, 0
  running jobs, and the SQL execution still `RUNNING`. This is the Iceberg
  commit. It lasted one poll (under 5 s).
- Not proven locally: whether the executor-less idle in production reads the
  same. The exporter should treat "driver Running, 0 active jobs" as the commit,
  which the plan already says.

## Fixtures

The fixtures came from the pre-fix `capture.sh`. Its polling and trim logic is
unchanged: only the failure detection, the exit trap and the preflight checks
changed afterwards. A re-run of the fixed script at 2,000,000 events (base pair
only, no incremental rounds) validated it end to end with Grafana down and no
X noise: generator write 19.1 s per its log (poll window 08:47:22 to 08:47:44),
silver poll window 08:47:56 to 08:48:33, `events=1999793` equal to
`appended 1999793`. That re-run overwrote the raw `generator` and `silver`
snapshots in `scratch/`, so `trim_fixtures.sh` can no longer rebuild those
fixtures from scratch; the committed files are the record.

14 files in `fixtures/`, 216 KB in total. Each holds `capturedAt`, `applications`,
`jobs`, `stages` and `sql` (trimmed). Names say the phase and moment. The picks
and their meaning are listed in `trim_fixtures.sh`. Round 4 fixtures are the
only ones with the silver-key scan and the compaction; they come from a
300,000-event round, so their counts are small and the stage ids differ from the
first-run fixtures.

## Differences from the plan's assumptions

- SQL node metrics are not live (plan: "if step 6b shows it is live"). Use
  stages.
- "Bronze new events" has no log line. The comparison is with `appended N` or
  the collector's `events_processed`.
- Silver stage names are not distinguishable. The scan and the write stage need
  the rules above.
- No compaction in the first run; it needs 5 files per partition (here, after 4
  rounds).

## Known limits

- Rows can undercount after a stage retry. Spark re-runs only the missing
  partitions, and the exporter keeps the newest attempt of each stage. Unverified:
  check for `attemptId > 0` in the 1M rehearsal.
