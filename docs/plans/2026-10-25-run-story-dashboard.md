# Plan: a "story" layer for the recorded 100M run (rows filling up, pipeline journey, plain-English KPIs)

_Made by `cerberus-planner` (Opus) on 2026-10-25, Mode 1, and revised the same day after the user's answers (end of file). It is a task plan, carried out as an amendment to ADR 0022 (section 6)._

## 1. Question

How can the 100M video show live, real progress that everyone can read: payments counting from 0 to 100M, the pipeline steps lighting up, plain-English KPIs, and the data-quality and teardown results? It is needed now because it changes the runbook (ADR 0022 step 7) and the 1M rehearsal (step 8). Both must be built and rehearsed before the once-only 100M take.

## 2. Facts

**No row counter exists in AMP today.**
- A read-only `label/__name__/values` call over 2026-10-13 05:55–06:50Z returns 1,224 names, and none is a Spark records metric.
- The Spark series are the driver's PrometheusServlet sources (`metrics_cerberus_driver_DAGScheduler_*`, `ExecutorAllocationManager_*`, `CodeGenerator_*`, `LiveListenerBus_*`) and the executor summary (`metrics_executor_{activeTasks,completedTasks_total,totalInputBytes_bytes_total,totalShuffleRead/Write_bytes_total,...}`).
- Spark's executor-side source does have `recordsRead`/`recordsWritten`. Executors serve no HTTP endpoint, so it is never scraped. The PrometheusServlet runs only on the driver's 4040 (`transform/spark/spark-application.yaml` sparkConf).

**What the 2026-10-13 driver logs show** (`observability/scale/exercises/exercise-20261013T055859Z-spark/`):
- **Generator:**
  - ShuffleMapStage 0 had **8 tasks**, 06:13:40–06:16:42 (182.6 s).
  - ResultStage 2 (`json at …`, the write) had **328 tasks**, 06:16:43–06:19:55.
  - Then `FileFormatWriter: Write Job … committed. Elapsed time: 875397 ms`: **14.6 minutes with no Spark job running** (06:19:55–06:34:30).
  - Then a 17 s count pass.
  - AMP agrees: `activeJobs` 0 and executor `activeTasks` 0 from 06:21 to 06:34.
  - The cause (S3A rename under dynamic partition overwrite) is inferred, not verified.
- **Silver** (`cerberus-promote-payments-driver.log`):
  - Stages 2 and 3 (`append at …`, 367 + 19 tasks) read bronze and silver keys, 06:36:47–06:39:37.
  - Stage 6 (400 tasks) ran 06:39:37–06:40:48.
  - ResultStage 10 (63 tasks) wrote silver, 06:40:48–06:41:29. The log says `appended 100008511 new events`.
  - Compaction stages are named `save at SparkBinPackFileRewriteRunner.java:62` and ran 06:41:33–06:42:57.
- **Correction to the brief:** the generator wrote **100,002,421** events. 100,008,511 is what silver added. It includes 6,090 Lambda events from `payments/` (`observability/scale/runs/exercise-20261013T055859Z.json`, `generator.events` vs `events_processed`).

**The bytes proxy overshoots.**
- The silver job read 52,624,362,642 bytes (`prometheus.spark…spark_input_bytes`).
- The generator wrote 43,261,265,435 bytes (`storage_snapshot.generator_run`).
- Bytes read ÷ bronze bytes therefore ends near 122%. The extra bytes are the silver keys and compaction (inferred).
- AMP input bytes reach 44 GB at 06:40, stay flat, and reach 52 GB at 06:43.
- The generator reads 0 bytes, so no proxy exists for it.

**Changing the job code or the YAML means rebuilding the runner image.** RunTransform runs `/opt/spark/promote_payments_spark.py` and `/opt/spark/spark-application.yaml` from the runner image (`orchestration/runner/entrypoint_transform.sh` L51, L70–78). This is checkpoint's open "build_and_push landmine".

**Sources the journey can use** (`cerberus-admin` CloudWatch reads work, checked 2026-10-25):
- `AWS/States` has **per-integration** `ServiceIntegrationsStarted/Succeeded/Failed` keyed by `ServiceIntegrationResourceArn` = `…:lambda:invoke`, `…:ecs:runTask.sync`, `…:athena:startQueryExecution.sync`. On 2026-10-13 at 1-min resolution:
  - lambda started and succeeded at 06:35.
  - ECS started at 06:35 and 06:43 and succeeded at 06:43 and 06:46. RunTransform and RunDbt share the ARN: the first start is the transform, the second is dbt.
  - Athena started at 06:46 and succeeded at 06:47.
  - There are no metrics per state name.
- `AWS/Athena` per workgroup: `cerberus_platform_dq` shows 24 queries at 06:48. That proves queries ran and succeeded, not that the checks passed.
- `AWS/Usage` EC2 vCPU (OnDemand 2, Spot 8→16) has 5-min resolution and **no zero point after teardown**. The data just stops at 07:00Z.
- AMP `kube_pod_status_phase{namespace="spark-jobs"}`:
  - The generator driver was Running 06:14–06:34 and Succeeded from 06:35.
  - The silver driver was Running 06:36–06:43 and Succeeded from 06:44.
  - Succeeded pods stay until destroy (`generate_bulk.sh` L62 deletes only before an apply).
- `min(kube_node_created)` is 06:09:24Z. `count(kube_node_info)` is 5 at 06:41.
- **CloudWatch keeps 1-min data for 15 days.** The 2026-10-13 SFN 1-min data expires about **2026-10-28**. After that only 5-min data remains.

**Cost basis for an estimate** (from the run record's `cost` block):
- The day total was $1.781607, of which Athena was $0.574015. The cluster was observed up for 3,773 s.
- Non-Athena cost per observed hour: ($1.781607 − $0.574015) ÷ 1.048 h = **$1.15/h**. This is derived here; the repo does not contain it.
- The record's `usd_per_cluster_hour` 1.3801 uses EKS cluster-hours, which checkpoint flags as 17–29% low.

**Where `exercise.sh` knows each result** (`orchestration/exercise.sh`):
- The collector exit code: 0 = DQ passed, 3 = DQ failed (record written), anything else = collector failed. See the `case "$collector_rc"`, about L343.
- The account-wide check `after destroy: EKS $eks, NAT $nat, EIP $eip, running instances $ec2` in `teardown()`, about L186. It runs under `set +e` with INT, TERM and PIPE ignored. A destroy that fails twice exits 1 before the check.
- The execution poll is `describe-execution` every 15 s (about L321–325). The collector already reads the same execution history for `state_timings` (`collect_run_metrics.py` L112).
- `jq` and `curl` are installed. `observability/grafana/.env` is git-ignored (`.gitignore` L66) and holds only `GF_SECURITY_ADMIN_PASSWORD` today (`.env.example`).

**Grafana annotations (docs, added 2026-10-25):**
- Grafana 13.2's HTTP API documents `POST /api/annotations`. Only `text` is required, and `time`, `timeEnd` (epoch ms) and `tags` are optional.
- Without `dashboardUID` it creates an **organization annotation**, which any dashboard can query through the built-in Grafana annotations source and filter by tags.
- The permission is `annotations:create`.
- `/api` routes are "being deprecated in favor of `/apis`" but "remain fully accessible and operative" ([v13.2 docs](https://grafana.com/docs/grafana/v13.2/developer-resources/api-reference/http-api/api-legacy/annotations.md)).
- The **Annotations list** visualization exists. It filters by dashboard or org, by time range and by tags, has a limit (default 10), and can show time and tags ([docs](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/annotations/)).
- Annotations render on Time series, **State timeline** and Candlestick panels ([docs](https://grafana.com/docs/grafana/latest/dashboards/annotations/)).
- Annotations live in Grafana's database, which is the `grafana-data` volume. That volume survives `make grafana-down` and is lost on `down -v` (`observability/grafana/README.md`).
- **Unverified:**
  - that the Viewer basic role is refused `annotations:create` in OSS, which would make Editor the least role allowed (OSS has no fixed roles);
  - the exact panel type ids in the 13.2.3 container.

**Other facts:**
- ADR 0021 (Accepted) says status goes to AMP **at the end of a run** through a publisher (10.2, not built), with no Pushgateway. `aps:RemoteWrite` is not in `cerberus-admin`'s policies (Sid `AmpQuery` only, ADR 0022 Context).
- Grafana `grafana/grafana:13.2.3` measured 346–364 MiB with no datasources (ADR 0022). The brief's 250 MiB is not sourced.
- The in-cluster Grafana loads every JSON in `observability/grafana/dashboards/` through a ConfigMap (`eks_observability/main.tf` L310).
- PR #114 (open) adds the Running-only driver relabel (`spark_driver_relabel`, main.tf L157).

## 3. Constraints

- $0 idle. Anything new in `dev-compute` dies with the cluster. Nothing new goes into `dev-standing`.
- No change to the job code or the transform YAML before the take. A change there needs a runner image rebuild and puts the once-only run at risk.
- ADR 0016: AMP is the single metrics store. ADR 0021: no Pushgateway; the status publisher stays in Phase 10. ADR 0022: real metrics only.
- ADR 0022's Consequences say "No live events-processed counter exists". This plan changes that, so it is an **amendment**.
- Every number on screen is live and sourced. Estimates say "estimate" in their title.
- The laptop has 4 cores and 7.1 GiB, shared by OBS, Firefox and Grafana.

## 4. Options

### 4a. Live row counter

- **R1. Spark status REST → small in-cluster exporter → agent → AMP. Recommended.**
  - A stdlib-Python exporter (about 150 lines) runs as a Deployment in `monitoring` on the `apache/spark:3.5.9` image, which already has python3 3.10.
  - It uses the Prometheus multi-target pattern. A new scrape job reuses `spark_driver_relabel`, sets `__param_target=<driver-pod-ip>:4040` and points `__address__` at the exporter service.
  - The exporter reads `/api/v1/applications` → `…/<id>/stages`, plus `…/sql?details=true` if step 6b shows it is live. It serves a few `cerberus_spark_*` series.
  - The numbers are Spark's own live status, the same ones the Spark UI shows. They update per finished task.
  - Cost: $0 idle. AMP ingestion is under a cent.
  - Effort: 3 PRs.
  - What it gives up:
    - One new component.
    - No 2026-10-13 history, so it is first proven in the 1M rehearsal.
    - The generator's first stage has only 8 tasks, so counts jump in chunks. SQL node metrics may be smoother (step 6b).
    - No counter during the generator's 14.6-min commit.
  - Pillars: Reliability (no job or image change; a failure empties one panel only) and Operational Excellence (fixture tests in `code-ci`).
- **R2. Grafana Infinity plugin on the port-forwarded `:4040`.** Not a core plugin. The container cannot reach a host-loopback port-forward. The data is live only, and it bypasses AMP. Rejected.
- **R3. Executor `recordsRead`/`recordsWritten` through the JMX sink and an exporter agent.** Changes both YAMLs and the runner image, and adds 16 more scrape targets. Rejected.
- **R4. A labelled proxy (fallback).** "Data read so far (GB)" and "Spark tasks finished". No build. These are not rows, and no percent is possible (122%; the generator reads 0 bytes).

### 4b. Pipeline journey, DQ verdict and teardown result

- **J1. Existing metrics only.**
  - Sources:
    - Generate and Transform: AMP `kube_pod_status_phase` (15 s).
    - The "saving files" sub-row: generator driver Running and `DAGScheduler_job_activeJobs` = 0.
    - Ingest, Transform, Model (dbt) and Serve: CloudWatch metric math (`RUNNING_SUM`) on the three integration ARNs.
    - Quality: `AWS/Athena` query count for `cerberus_platform_dq`.
  - Cost: $0 build. CloudWatch `GetMetricData` is about $0.02 per viewing hour at a 15 s refresh (estimate).
  - It can be checked on history now.
  - What it gives up:
    - A 1–3 min CloudWatch delay (unverified).
    - No apply or destroy step.
    - **No DQ verdict and no teardown result.**
- **J2. `exercise.sh` pushes to Grafana Live (`/api/live/push`).** Exact, but held only in memory: no replay after a restart and no history check. The API is unverified in 13.2.3. Rejected in favour of J5.
- **J3. ADR 0021's publisher built early, writing during the run.** Needs an `aps:RemoteWrite` paste, 10.2's open protobuf, snappy and SigV4 spike, and an amendment to ADR 0021. Rejected for now.
- **J4. Step Functions console Graph view.** Native and exact, but covers only 4 steps. It stays as a supporting tab.
- **J5. `exercise.sh` posts Grafana annotations to the local Grafana. Recommended, together with J1 and J4.**
  - **Verdict annotations (the user's question 2):**
    - After the collector:
      - "Quality checks: PASSED (N checks, E errors, W warnings)" when rc 0;
      - "Quality checks: FAILED (E errors) — see run record" when rc 3;
      - "Quality checks: NOT RUN (collector failed)" otherwise.
      - N, E and W come from `jq` on `observability/scale/runs/$EXECUTION_NAME.json` (`data_quality.checks | length`, `.errors`, `.warnings`).
    - After the account-wide check: "Cluster deleted: EKS 0, NAT 0, Elastic IP 0, running instances 0 (account-wide check)". If a count is non-zero, the text says "STILL RUNNING — check the console".
    - If the destroy fails twice, the text is "Teardown FAILED — check the console".
    - The wording is the check's own result. It does not claim a "$0 bill"; the bill comes from Cost Explorer a day later.
  - **Step annotations.** Each step is a point at its start and a region (`time` to `timeEnd`) at its end:
    - apply;
    - generator;
    - each Step Functions state (InvokeIngestion, RunTransform, RunDbt, RunServingQuery). These come from `get-execution-history` read inside the existing 15 s poll and use the history's own `StateEntered`/`StateExited` timestamps, the source `state_timings` uses;
    - the execution end;
    - DQ;
    - destroy.
  - **Does it improve accuracy over CloudWatch? Yes.**
    - The Step Functions steps get exact times, appearing within the 15 s poll instead of after 1–3 min.
    - Apply and destroy get any time at all, since no metric covers them.
    - The generator gains nothing: AMP pod phase is already 15 s, so its annotation is only a label.
  - **Tags:** `cerberus`, `run:<execution>`, plus one of `step`, `dq` or `teardown`. Test annotations use `cerberus-test` and never match the story dashboard's filter.
  - **Storage and replay:** organization annotations in the `grafana-data` volume. They survive `grafana-down` and replay over any time range. The run record in git stays the authoritative copy.
  - **Credentials (least privilege):**
    - A Grafana **service account** `cerberus-exercise` with the **Editor** basic role (Viewer is expected to be refused; step 6e checks) and a token with a 30-day expiry.
    - It is created by a one-off `make grafana-token`, which uses the admin password through `127.0.0.1:3000` and writes `GRAFANA_ANNOTATE_TOKEN` into the git-ignored `.env` with umask 077.
    - `exercise.sh` reads only that key, with `grep`, and never sources the file, so the admin password stays out of the run's environment.
    - An Editor token is preferred to the admin password because it is narrower, expires and can be revoked. Editor can still create dashboards; this is accepted for a localhost-only Grafana. Provisioned dashboards stay `editable: false`.
  - **Fail-open rules:**
    - One helper, `annotate()`, in `orchestration/annotate.sh`, sourced by `exercise.sh`. It builds JSON with `jq -n --arg` (no string splicing) and calls `curl -sS --max-time 3` to `http://127.0.0.1:3000/api/annotations` only.
    - With no token, or on any non-2xx reply, it logs one `annotation skipped (…)` warning per run, and nothing more.
    - It always returns 0 and runs inside `{ …; } || true`, so `set -e`, the teardown's `status` and every exit code are unchanged.
    - The history read for step annotations is in a function with `|| true`, inside the existing loop. It never touches `status`.
    - `--no-annotate` turns all of it off.
  - Cost: $0. SFN `GetExecutionHistory` calls are not billed per call.
  - What it gives up:
    - A small change to the script that runs the once-only take (mitigated by the fail-open rules and the $0 tests in 6e).
    - Annotations are not in git.
    - An Editor-scoped token sits on disk (git-ignored, mode 600, 30-day expiry).
    - If the run dies before a step, that step gets no annotation, so its row stays empty.

**Panel types:**
- The journey is a **state timeline**: one row per step, coloured grey = waiting, blue = running, green = done, red = failed. J1 metrics drive the live colours, and J5 step annotations draw exact start and end markers on it.
- An **Annotations list** panel, titled "Run log", shows the verdict and step lines with times. Its filter is tags `cerberus` and the dashboard time range, limit 20.
- Canvas is optional polish after the rehearsal.

## 5. Recommendation

**R1, with R4 as the fallback; J1 + J5 + J4; a new non-engineer dashboard `cerberus-run-story.json`. `cerberus-run-live.json` stays the engineers' view.**

Why:
- R1 is the only option that gives real row counts for both phases without touching the job, the YAML or the image. Its data lands in AMP and survives teardown.
- J1 gives live colours and can be checked now against the 2026-10-13 history.
- J5 adds the two results the metrics cannot show (the DQ verdict and the account-wide teardown check) plus exact step times, in the words of the authoritative check itself.
- J5 cannot change the run's outcome, and the terminal stays the authoritative record.

**Row definitions** (fixed in exporter code and checked against fixtures in 6b):

| Phase | Plain title | Source | Must equal at the end |
|---|---|---|---|
| Generator | "Payments created" | write ResultStage `outputRecords` (or the SQL write node, if live) | `[generate] done events=` |
| Generator, commit | "Saving files into bronze — no counter for this part" | driver Running and active jobs 0 | — |
| Silver | "New payments read" | `Scan json` rows (SQL) or the bronze-scan stage `inputRecords` | bronze new events |
| Silver | "Added to the clean table" | `append` ResultStage `outputRecords` | `appended N` and the collector's `events_processed` |
| Silver | "Tidying files" | stages `save at SparkBinPackFileRewriteRunner…`, left out of the counts | — |

**Erratum (6b, 2026-10-25)**, evidence in `observability/spark_progress/CAPTURE.md`:
- (a) The source is stages only. SQL node metrics are empty while the execution is RUNNING.
- (b) "New payments read" is the lowest-stageId stage with `inputRecords` > 0 in the first `append at` job. No log line has this number, so the end check is that it is at least `appended N`. It is equal when bronze has no duplicates or Lambda events.
- (c) Pick the write stage by `outputRecords`, since all stages in a job share one name.

**Story dashboard layout** (4:5, kiosk, about 864×1080 or 1080×1350; 15 s refresh; an absolute `from=<take start>&to=now` in the URL, because `RUNNING_SUM` needs the run start inside the range):

1. A full-width bar gauge, "Payments processed: 63.4 M of 100 M". The max is a constant variable labelled "requested". Under it, a stat "Now: Reading new payments" from the exporter.
2. The journey state timeline with J5 markers. Rows:
   - Start servers
   - Generate, with a "saving files" sub-row
   - Ingest
   - Transform
   - Model (dbt)
   - Serve
   - Quality checks
   - Teardown
3. Two result tiles, both from J5 annotations shown in the "Run log" list:
   - "Data quality", showing the PASSED/FAILED line;
   - "Clean-up", showing the account-check line.
   They stay empty ("waiting") until the run posts them.
4. KPI tiles, each with one plain sentence:
   - "Payments per second".
   - "Time running (since the first server)", from `time() - min(kube_node_created)`.
   - "Servers working now: X regular, Y spare-capacity (Spot)".
   - "Cost so far — estimate", elapsed × $1.15/h, with the note "2026-10-13 rate; Athena and the real bill come a day later".
   - "Data read so far (GB)".
5. Links "For engineers →" to `cerberus-run-live` and back. In the video, switch with browser tabs, not a playlist.

**Colour rule** (both dashboards): green = done, blue = running, grey = waiting, red = failed. Use units like "M" and "GB", and no small text, so it stays readable at 15–20×.

**Note, outside this plan:** the generator's 14.6-min commit is about two thirds of its time. The runbook speeds that segment up about 30×, and the screen labels it. Fixing the commit is the existing "slow generator" follow-up.

## 6. ADR change: amend ADR 0022 (no new ADR)

Add an "Amendment (2026-10-25)" section. Status stays Accepted. The amendment is marked Proposed until the user accepts it.

- **Context:**
  - The audience now includes non-engineers (finance, product, leadership).
  - No records metric exists in AMP. The Spark status REST API is live.
  - The bytes proxy overshoots to 122%. The generator's 14.6-min commit has no progress.
  - SFN per-integration metrics exist but lag 1–3 min.
  - The DQ verdict and the teardown result live only in `exercise.sh`.
  - Grafana 13.2 offers organization annotations through `POST /api/annotations`, an Annotations list panel, and annotation display on state timelines.
- **Decision:**
  - The R1 exporter in `dev-compute`. R4 is the named fallback.
  - `cerberus-run-story.json` with J1 for the live colours.
  - J5: `exercise.sh` posts annotations to the local Grafana for:
    - the DQ verdict (from the collector exit code and the run record);
    - the account-wide teardown check;
    - step start and end times (apply, generator, Step Functions states from the execution history, destroy).
  - J5 is fail-open: localhost only, a 3 s timeout, one warning line, always returns 0, and `--no-annotate` turns it off. It does not change the run's success logic.
  - Credentials: a Grafana service account with the Editor role and a 30-day token, made by `make grafana-token`, stored in the git-ignored `.env`. `exercise.sh` reads only that key, and the admin password is not used.
  - Rejected: J2 (memory only) and J3 (Phase 10; would need an ADR 0021 change).
  - Build steps 6a–6f are inserted after step 6. Steps 7–10 keep their numbers.
- **Consequences:**
  - Replace "No live events-processed counter exists" with: "a live counter from Spark's status API, updated per finished task; none during the generator commit; first proven in the 1M rehearsal."
  - The DQ verdict and the clean-up check now appear on Grafana as annotations. The terminal and the run record stay authoritative.
  - Step Functions steps get exact times without waiting for CloudWatch.
  - Given up:
    - one more in-cluster component;
    - a small fail-open change to `exercise.sh`;
    - annotations live in the Grafana volume, not in git;
    - an Editor-scoped token on disk;
    - the cost tile is an estimate.
  - The "extra dashboards are decoration" line is answered: this is a front page for another audience, and every number on it is sourced.
  - Phase 10.2's publisher may later replace the verdict annotation with `cerberus_dq_passed` in AMP, and 10.3 may move the journey to `cerberus_step_duration_seconds`.
  - With Phase 10's two dashboards, the local stack reaches about five dashboards, which is ADR 0021's revisit point.

## 7. Build steps

All steps are under **Phases.md 8.10**. Add to its text: "story dashboard, Spark progress exporter and run annotations (ADR 0022 amendment)". They go **between ADR 0022 steps 6 and 7**, and #114 merges first.

**6a. Amendment, this plan, Phases.md and the checkpoint note.** One PR.
- Verify: the user accepts the amendment, and its status is flipped.

**6b. Local Spark capture ($0).**
- Add `observability/spark_progress/capture.sh`. It runs `apache/spark:3.5.9` in local mode with the real scripts: the generator at about 2M events to a local dir, then `promote_payments_spark.py --catalog-type hadoop`.
- It polls `:4040` `/stages`, `/jobs` and `/sql?details=true` every 5 s, and the trimmed JSON fixtures are committed.
- Run it with Grafana down.
- Verify:
  - which fields grow mid-stage;
  - each end value in the table in section 5 matches its log line;
  - the compaction stage names;
  - the commit shows as active jobs 0.

**6c. Exporter and Terraform.**
- `observability/spark_progress/exporter.py` (stdlib, Python 3.10), with pytest against the 6b fixtures in `code-ci`.
- In `eks_observability/main.tf`: a ConfigMap, a Deployment (10m CPU / 32Mi), a Service, and a `spark-progress` scrape job that reuses `spark_driver_relabel` with a target rewrite. A small, fixed series set.
- Verify:
  - pytest passes;
  - `terraform fmt` and `validate` pass;
  - a read-only `dev-compute` plan shows only the additions.

**6d. Story dashboard.**
- `observability/grafana/dashboards/cerberus-run-story.json`, plus the colour rule and links in `cerberus-run-live.json`. It includes the "Run log" Annotations list panel, the two result tiles, and an annotation query on the journey filtered by tag `cerberus`.
- Verify **before 2026-10-28**, on 2026-10-13 06:05–06:55Z:
  - Generate is Running 06:14–06:34, with the "saving files" sub-row 06:20–06:34.
  - Ingest is at 06:35, Transform 06:35–06:43, dbt 06:43–06:46, Serve 06:46–06:47, Quality queries at 06:48.
  - Servers peak at 5.
  - The cost estimate is about $1.15/h × elapsed.
  - The exporter panels show "No data" with no error, and the R4 panel shows 52.6 GB.
  - `GET /api/plugins?type=panel` lists the state timeline, bar gauge and annotations list types.
  - A kiosk screenshot at 864×1080 is readable.

**6e. Run annotations (J5) and their $0 test.**
- Add `orchestration/annotate.sh`: `annotate()`, plus a history reader that posts each Step Functions state once, using a temp file of the event ids already posted.
- In `orchestration/exercise.sh`, add calls:
  - after the apply;
  - around the generator;
  - after `start-execution`;
  - inside the poll loop (history);
  - after the execution ends;
  - after the collector `case`;
  - in `teardown()` after the account-check line and on the destroy-failed path;
  - plus the `--no-annotate` flag.
- Add a `make grafana-token` target, and add `GRAFANA_ANNOTATE_TOKEN=` to `.env.example`.
- Add a replay mode, `orchestration/annotate.sh --replay <execution>`. It reads the committed exercise log lines (`apply took`, `generator took`, `starting execution`, `execution …`, `DATA QUALITY …`, `after destroy: …`), the run record's `data_quality`, and the execution history (a read-only `get-execution-history`).
- Verify at $0 against the local Grafana:
  1. `shellcheck` passes on both scripts.
  2. `make grafana-token` creates the service account and writes the key with mode 600. Then:
     - a Viewer-role test token gets 403 on `POST /api/annotations` (this settles Editor as the least role; if Viewer is allowed, use Viewer);
     - the Editor token gets 200.
  3. Fail-open, in a stub harness that sources `annotate.sh` under `set -euo pipefail`. The exit code is unchanged and exactly one warning appears in each case:
     - Grafana stopped;
     - no token;
     - a wrong token (401);
     - an unreachable port.
  4. `annotate` with tag `cerberus-test` appears in `GET /api/annotations?tags=cerberus-test`. Delete it afterwards.
  5. Replay `exercise-20261013T055859Z` with tags `cerberus` and `replay`. On 06:05–07:05Z the story dashboard must show:
     - the RunTransform region 06:35:06–06:43:38;
     - "Quality checks: PASSED (17 checks …)", with the count taken from the record;
     - the account-check line from the committed log.
     - The step markers must line up with the J1 rows, and the delay of J1's CloudWatch rows behind the markers is measured.
     - Do this before 2026-10-28, while CloudWatch still has the 1-min data.
  6. `bash -n orchestration/exercise.sh` passes, and `make exercise-check` (preflight, $0) is unaffected.

**6f. Runbook input** (folded into step 7):
- The story dashboard is tab 2, with the absolute `from=` URL. `cerberus-run-live` is tab 3.
- Story screen first in each phase. The commit segment is sped up about 30×.
- Run `make grafana-up` and check the token before `make exercise`.

**Step 8 (the 1M rehearsal) gains these checks:**
- The generator bar ends at the exact `[generate] done events=`.
- "Added to the clean table" equals `events_processed`.
- The J5 step regions match `state_timings` within 15 s.
- The DQ and Clean-up tiles show the collector's result and the account-check line.
- The J1 CloudWatch delay is measured.
- The exporter pod is Running and the driver is not Pending.
- Fewer than about 200 `cerberus_spark_*` series.
- A planned fail-open check: stop Grafana for one minute mid-run. The run carries on and one warning line appears.
- **Decision point:** if the exporter fails, switch to the R4 panel (prepared in 6d) and check it again before step 9.

**Checks at $0 against the 2026-10-13 history:**
- the J1 journey;
- servers, elapsed time, the cost estimate, data read, executors;
- the replayed J5 annotations;
- panel availability.

**Checks only in the 1M rehearsal:**
- the row counter and the "Now" text;
- the live J5 posts;
- the CloudWatch delay;
- exporter scheduling;
- kiosk under OBS.

## 8. Open questions for the user

None.

## User answers (2026-10-25)

1. **Plan:** approved. R1 exporter, J1 journey, R4 fallback and the story dashboard, as an ADR 0022 amendment with steps 6a–6e (now 6a–6f, after J5 was added).
2. **DQ verdict and "$0 after teardown" on Grafana:** "If we can show this on Grafana, that is fine too." This is done as J5 annotations. The terminal stays authoritative.
3. **Cost tile:** a live labelled estimate, approved.
