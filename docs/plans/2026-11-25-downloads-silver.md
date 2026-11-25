# Plan: 17.5 downloads silver, dbt and data quality

Date: 2026-11-25. Planner: Sonnet (`cerberus-planner`).

## Binding corrections (main session; these win)

1. Branches: 17.5a (Terraform, steps 1-3) is `17.5a-downloads-grants`; 17.5b
   (steps 4-10) is `17.5-downloads-silver`. Glue names are fixed:
   `bronze_downloads_bulk_by_run`, `bronze_downloads_cdn`, `download_events`.
2. `bronze_downloads_cdn` declares all 12 columns as string, snake_case with
   SerDe mappings (`timestamp(ms)` becomes `timestamp_ms`,
   `time-to-first-byte` becomes `time_to_first_byte`, and so on); dbt casts
   with `try_cast`. `_manifest.json` sits in the same prefix and must not be
   read as data; check that Athena hides `_` files.
3. Collect contract: see section 4 of `2026-11-25-launch-session.md` (branch
   `17.4-launch-session`): uncompressed `part-*.json`, manifest last.
4. Spend guard: `python3 launch/ledger.py guard --next-usd N`, then `record`
   and `correct` with `--kind exercise`. `launch_exercise.sh` fails closed
   when the file is absent or exits non-zero. The teardown never calls guard.
5. DQ check 8 fails when a launch run record says logs were collected and
   rows are absent; it reports "skipped, telemetry only" when no such record
   exists. It is never a silent pass.
6. Open questions 1 and 3: yes to both.
7. The anti-join must be limited by touched days AND stay correct for a
   second `run_id` covering the same days.
8. `submit_job.sh` defaults render byte-identical to today.


## Plan

**PLAN 17.5 (Tier C, with a Tier S IAM/Glue slice).** No NEEDS DECISION: nothing contradicts ADR 0030. The plan was read against origin/main d8974fe. Worktree: /home/chirag/projects/cerberus/.claude/worktrees/17.5-downloads-silver.

**1. Goal.** Phases.md 17.5: the downloads silver job, `make launch-exercise`, dbt downloads marts and the downloads data-quality suite.

**2. Facts (V = read in the repo; U = unverified)**
- (V) `submit_job.sh` is `transform/spark/submit_job.sh`, not under dev-compute. It is hardwired to payments (script, app name, YAML, account-ID bucket constant).
- (V) `promote_payments_spark.py` has the pattern to copy: `CREATE TABLE IF NOT EXISTS` through GlueCatalog, a snapshot-property watermark, an anti-join plus append, touched-day pruning, and `rewrite_data_files` plus `expire_snapshots`.
- (V) The generator writes `downloads_bulk/run_id=<id>/dt=<day>/part-*.json`. `_manifest.json` is written last, and any old manifest is deleted before a rerun. The files carry no `run_id` or `dt` columns, so the path is the only source for them.
- (V) The generator envelope is `event_id, event_family, event_type, occurred_at, ingested_at, schema_version, payload{client_id, platform, region, isp, bytes, duration_ms, throughput_mbps, http_status}`.
- (V) The Glue grant of `cerberus-spark` covers one table, `payments_events`. Its bronze write grant covers `payments_bulk/*` only. The generator YAML therefore cannot write today.
- (V) The Fargate dbt role can build only `fct_*` and `dim_*`. The scheduled run is `dbt-ol build`, and source tests run inside `build`.
- (V) `cerberus-transform` can build `fct_*`, run Athena and read silver (`/*`). It cannot read `downloads_*` in bronze.
- (V) The existing `exercise.sh` runs the payments state machine, which includes Fargate dbt. It cannot be reused without change.
- (V) `verify_scan` flags 12-digit runs in added text files. New files take bucket names through placeholders or arguments.

**3. Steps**

*Recommended split: PR 17.5a (Terraform, Tier S), then PR 17.5b (code). Merge 17.5a before the Friday smoke run. 17.5b is safe to merge any time, because dbt is gated off.*

**PR 17.5a (Tier S)**
1. `terraform/modules/iam_spark`: make the table variable a list `["payments_events","download_events"]`, with no `DeleteTable`. Add a `WriteBronzeDownloadsBulk` statement, and add `downloads_bulk` and `downloads_bulk/*` to the ListBucket prefix condition. Exact actions:
   - `glue:GetDatabase`, `GetTable`, `CreateTable`, `UpdateTable` on the catalog, the database and `table/cerberus_platform/download_events`.
   - `s3:GetObject`, `PutObject`, `DeleteObject`, `AbortMultipartUpload` on `<bronze>/downloads_bulk` and `/downloads_bulk/*`.

   `launch_exercise.sh` applies this as part of `dev-compute`. The owner should read `make compute-plan` first.
2. `terraform/modules/glue_catalog` (applied by CI on `dev-standing`):
   - `bronze_downloads_bulk_by_run`: JSON, partition-projected with injected `run_id` and `dt`, copied from the payments table.
   - `bronze_downloads_cdn`: an unpartitioned JsonSerDe table over `downloads_cdn/`. `run_id` comes from `"$path"` in dbt, so there are no partitions to repair. Hyphenated field names are mapped with SerDe `mapping.*` properties.
3. `terraform/modules/iam`:
   - `cerberus-transform` gains `s3:GetObject` on `downloads_bulk/*` and `downloads_cdn/*`, matching ListBucket prefixes, and `glue:GetTable` and `GetPartitions` on `download_events` and the two new bronze tables.
   - `cerberus-orchestration-dbt` gains the ADR D11 grants: `iceberg/download_events/*`, `downloads_cdn/*`, and `glue:GetTable` on `download_events` and `bronze_downloads_cdn`.
   - The CI role is not touched. The plan job confirms `cerberus-ci-apply` is enough.
   - Test: `terraform fmt`, `terraform validate` and the CI plan. Review with `escalate: opus-security` as ADR 0030 requires.

**PR 17.5b (code)**
4. `transform/spark/promote_downloads_spark.py`:
   - No account ID. `--bronze-root` and `--warehouse` are required arguments.
   - Table `glue.cerberus_platform.download_events`, Iceberg v2, partitioned by `days(occurred_at)`, location `iceberg/download_events`.
   - Columns: `event_id, event_family, event_type, occurred_at, ingested_at (timestamps), schema_version, client_id, platform, region, isp, bytes, duration_ms, throughput_mbps, http_status, run_id, loaded_at`.
   - Select runs by `_manifest.json`. Take a run if its manifest `LastModified` is above the watermark, or if its `run_id` is not in silver and its manifest is at most `LATE_OVERLAP_MS` (24 h, a design choice, unverified) older than the watermark. Then read that run's `dt=*/part-*.json` with `multiLine=false`. The watermark is the maximum manifest time. The second rule means a late manifest, even one in the same second as the watermark, is never lost; the anti-join on `event_id` makes the extra read safe, and a rerun adds 0 rows. The set of promoted runs comes from `select distinct run_id` on silver, so no ADR 0017 change is needed. Cost: a run whose events were all already in silver has no `run_id` in silver, so it is re-read (0 rows added) until its manifest is older than the overlap.
   - Before the append the job raises if any `event_id`, `occurred_at` or `ingested_at` is null (an unparseable timestamp becomes null in the flatten step), so nothing is committed and the watermark does not move.
   - **One-writer assumption.** One promote job at a time writes `download_events`. `launch_exercise.sh` is the only caller, it runs once at a time and is owner-run, and Iceberg's commit check would reject a concurrent writer's second commit rather than corrupt the table. Two parallel runs are unsupported: both could read the same watermark and select the same runs.
   - This skips runs still being written. A rerun (the manifest is rewritten) is re-read and appends 0 rows.
   - Take `run_id` from `input_file_name()`.
   - Dedup: `dropDuplicates(["event_id"])`, then an anti-join on `event_id` limited to touched days. Append with `snapshot-property.cerberus.bronze_watermark`. Maintenance and `REFRESH TABLE` logging as in payments.
   - Pure helpers (run selection, path parsing) are testable without Spark.
5. `spark-application-promote-downloads.yaml`:
   - A copy of the payments YAML, with name `cerberus-promote-downloads`.
   - The same pinned packages and the same dynamic-allocation and shuffle settings. Ivy path `/tmp`.
   - Placeholders `__SILVER_BUCKET__`, `__BRONZE_ROOT__`, `__WAREHOUSE__`, `__OPENLINEAGE_URL__`.
6. `submit_job.sh`: add env overrides `APP_NAME`, `SCRIPT_NAME`, `MANIFEST_YAML` and `EXTRA_SED`, with defaults equal to today's values, so payments is unchanged. Test: `bash -n`, shellcheck, and a rendered-manifest diff for the default case.
7. `orchestration/launch_exercise.sh` (flags: `--generate N`, `--yes`, `--check`, `--generator-executors`, `--executor-nodes`, `--run-id`, `--congestion`):
   - Preflight: `exercise.sh --check`, a spend-guard call, and bucket names read at runtime from STS.
   - Then apply dev-compute, run the generator (it fills `__RUN_ID__`, `__EVENTS__`, `__NOW__`, `__EXECUTORS__`, `__CONGESTION__`, `__OUTPUT__` and `__SILVER_BUCKET__`), then call `submit_job.sh` for the promote job.
   - The teardown is a copy of the `exercise.sh` trap, with the same final account-wide check.
   - The cluster is destroyed before dbt and DQ. Both are Athena-only, so they cost no cluster minutes.
   - dbt runs locally as `cerberus-transform`: `dbt build --select path:models/marts/downloads --vars '{enable_downloads: true, enable_downloads_cdn: <true only if downloads_cdn/ has objects>}'`. Then DQ runs, and a record is written to `observability/launch/runs/<run_id>/run.json` (the layout 17.4's `launch_session.sh` uses; `launch_collect.sh` sets `"cdn_logs_collected": true` in it after its manifest upload). The script has no `--keep` flag: the destroy always runs, because a forgotten cluster costs money.
   - **What is committed.** `observability/launch/runs/<run_id>/run.json` records (counts and statuses, no bucket names) are committable. The raw logs in `observability/launch/exercises/` are gitignored and stay local; check 9 of the data-quality suite scans both directories for account numbers and ARNs.
   - Makefile: add only the `launch-exercise` target. 17.4 owns every other `launch-*` target. Expect a trivial merge conflict.
8. dbt, under `models/marts/downloads/`:
   - **Names:** the dbt role is allowed only `fct_*`, so use `fct_download_sessions`, `fct_isp_minute`, `fct_release_window`, `fct_cdn_requests` and `fct_cdn_run`. This replaces the `agg_*` names in the task text, per ADR 0030.
   - **Models:**
     - `fct_download_sessions`: one row per (`run_id`, `client_id`), with milestone times, bytes, stalls, retries and status.
     - `fct_isp_minute`: per (isp, minute), with active clients, modelled Gbps and stall rate.
     - `fct_release_window`: per (region, minute) from T-60 to T+6h, using the offset `region_nn - 12` from a Jinja `range(1,25)` CTE.
     - `fct_cdn_requests`: allowlist columns only, deduplicated on `x-edge-request-id`, with the POP taken as the first 3 characters of the edge location.
     - `fct_cdn_run`: `grouping sets` for run and for (run, POP), with hit ratio, origin misses and TTFB p50/p99. Never mix this with k6 TTFB.
   - **Gating:** `dbt_project.yml` gets `vars: {enable_downloads: false, enable_downloads_cdn: false}`. `+enabled` for the `marts/downloads` models and for the downloads sources reads these vars.
   - **Sources:** a new `models/downloads_sources.yml`, not the existing `sources.yml`, so disabled sources run no tests in the scheduled build.
   - **Tests:** schema tests on `event_id`, `event_type` accepted values, `non_negative` bytes, and unique `(run_id, client_id)`.
9. `observability/launch/data_quality_downloads.py` (9 checks; run as `cerberus-transform`, workgroup `cerberus_platform_dq`):
   1. bronze to silver count per run (manifest events versus silver count by `run_id`)
   2. `event_id` unique
   3. lifecycle valid
   4. `bytes` between 0 and `212 * 10**9`
   5. timestamps inside the window, and `occurred_at` ≤ `ingested_at`
   6. no `license_granted` before local release
   7. gold session count equals silver distinct (`run_id`, `client_id`)
   8. CDN logs present for every run record with `"cdn_logs_collected": true` (reads `runs/*/run.json`; fails on zero rows, missing CDN models, an unreadable record or a non-boolean value; skipped, telemetry only, when no record says collected)
   9. no account ID or ARN in published outputs

   An Athena failure, an unreadable manifest, zero runs found, or a missing table counts as a fail. Exit 3 means failure, as in payments.
10. Tests:
    - `transform/spark/tests/test_promote_downloads.py` (pure helpers, py3.10, run by the existing verify step and CI step).
    - `observability/launch/tests/` with fake boto3 clients: fail-closed paths, SQL parses with sqlglot (Trino dialect), and the exit codes.
    - A Docker integration test, gated on `RUN_SPARK_DOCKER=1` and added to `verify.sh --full`, on `apache/spark:3.5.9` with a Hadoop catalog and the 10k sample. Assert: load = 10,000 rows, a rerun adds 0, and a new run adds only its own rows.
    - CI: add `pytest observability/launch` to the py3.10 job. In `dbt-validate`, run `dbt parse` twice (default, and with both vars true) and assert from `manifest.json` that the default has zero downloads nodes and the vars run has all 5 models.

**4. Verify.** `make verify`, and `make verify-full` for the Docker test. Also `dbt parse` in both modes, sqlfluff, shellcheck on the new scripts, `terraform fmt` and `validate` for 17.5a.

**5. Owner steps (agents never apply)**
- 17.5a merge: CI applies `dev-standing`, which creates the Glue tables and updates IAM.
- `make compute-plan`, then read it. The `iam_spark` change is applied by the first `launch-exercise`.
- Friday smoke: `make launch-exercise ARGS="--generate 1000000"`, then 10M.
- No Grafana or Databricks writes.

**6. Cost and scale for 100M events**
- Bronze is about 45 to 60 GB. Silver is about 8 GB Parquet (U).
- Cluster: generator plus silver about 20 to 40 minutes at $0.40/h, so about $0.15 to $0.30 (U).
- The `existing_keys` anti-join is cheap on a first load.
- Athena: DQ and dbt scans are narrow columns, about 3 to 5 GB, roughly $0.02 each.
- Risks:
  - Hash write distribution with 12 day-partitions could make 12 slow writer tasks. Measure on the 10M smoke run; fall back to `write.distribution-mode=none`.
  - The compaction step could be slow.
  - The Python worker memory in the generator is U.
  - Iceberg 1.10.2 on Java 11 is unchanged.
  - The `+enabled: "{{ var() }}"` behaviour is U; the dual `dbt parse` test proves it.

**7. The bronze/downloads_cdn/run_id=<id>/ contract I assume from 17.4's `collect.sh`**
- JSON Lines, one request per line, optionally `.gz`. No manifest is needed, though one is welcome.
- Keys are exactly the allowlisted AWS names: `timestamp(ms)`, `x-edge-request-id`, `x-edge-location`, `x-edge-result-type`, `x-edge-response-result-type`, `sc-status`, `sc-bytes`, `cs-method`, `cs-uri-stem`, `time-taken`, `time-to-first-byte`, `cs-protocol`.
- Types (U): the timestamp is an ISO-8601 UTC string or an epoch-ms number (dbt handles both, and a null timestamp fails a test); `sc-status` is an int; `sc-bytes` is a long; `time-taken` and `time-to-first-byte` are doubles in seconds.
- No `c-ip`, cookie, referer or user agent, and no account ID in the key or the content.
- A repeated collection may duplicate lines; gold deduplicates.

**8. Open questions**
1. Does the Fargate dbt role also get the D11 grants even though the downloads marts are gated off in the scheduled run? Recommend yes (ADR 0030 conformance), and note it is not exercised.
2. What is the spend-guard command from 17.4's ledger? Recommend `launch-exercise` fails closed, refusing unless the guard exists; agree the name with 17.4.
3. Does `launch-exercise` run dbt and DQ locally after the destroy? Recommend yes.
