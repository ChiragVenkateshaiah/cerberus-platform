# Plan: 10.2 pipeline status exporter (publisher, per-execution series, named query set and CI check)

Date: 2026-11-20. Planner: Opus. Mode: plan for Phases.md 10.2. It also proposes a small amendment to ADR 0021 for the result of the transport check and the series names (section 6). It reads `origin/main` at `c9bfd08`.

## 1. Question

How does each run get its status, failed step, step durations, events, data-quality result and timestamps into AMP? It must also write the per-execution start and finish series that the 10.4 alerts join on, and one named query set that 10.3, 10.4, 10.5 and Phase 14 all read. Most of this should be buildable and checkable with no live session.

Why now: Phase 10 is next after 9.7, and checkpoint "Next up" item 3 says to start with 10.2a (the query set). The alerts (10.4), the dashboard (10.3), `make status` (10.5) and the 14.x agents all read these series and this file.

## 2. Facts (V = verified, U = unverified)

**ADR 0021 and its amendments**
- V. AMP is the store and the alert evaluator. A run-end publisher writes by remote-write. There is no scrape and no Pushgateway. Every read uses `last_over_time(...[30d])` (ADR 0021, Decision Q1 and Q2).
- V. The latest-run series have no `execution` label. Drill-down uses `cerberus_run_info{execution}`. ADR 0021 Q2 lists these series:
  - Latest-run: `cerberus_run_status`, `cerberus_run_failed_step_info{step}`, `cerberus_last_success_timestamp_seconds`, `cerberus_run_started_timestamp_seconds`, `cerberus_run_finished_timestamp_seconds`, `cerberus_dq_passed`, `cerberus_dq_errors`, `cerberus_dq_warnings`.
  - Detail: `cerberus_run_duration_seconds`, `cerberus_step_duration_seconds{step}`, `cerberus_run_events_processed`.
  - "10.2 fixes the exact names after the spike."
- V. Samples are stamped at publish time. "AMP refuses samples older than one hour" is quoted from ADR 0021 and was not re-checked (U).
- V. The ADR says to use OpenTelemetry "as the API, with the transport left to 10.2's first spike". If the exporter cannot both remote-write and sign for `aps`, the publisher writes the protobuf itself (snappy, SigV4 from `collect_run_metrics.py`) "and keeps the OpenTelemetry API for naming".
- V. Amendment 2026-11-12, D1: one named query set. Each entry has a name, PromQL and a one-line meaning. Consumers:
  - panels: the `expr` equals an entry;
  - rules: the `expr` contains an entry verbatim;
  - `make status` / `cerberus status`;
  - ADR 0025's tool, which takes names only.
  A CI test in `code-ci.yml` fails on any Phase 10 panel or rule that is not built from an entry, after whitespace is normalised. The file in the ADR is "for example `observability/queries/status.yaml`".
- V. Amendment D2:
  - The per-execution start series is written at run start. The finish series is written at run end, in the same remote-write request as the status.
  - `topk(1, last_over_time(<finish>[30d]))` returns the newest run.
  - "10.2 fixes the names."
- V. ADR 0021 Q3 (lineage through the console transport): "10.2 checks this first". Phases.md 10.2 does not mention lineage.
- V. ADR 0021 says the workspace keeps 90 days. That text is out of date: `aws amp describe-workspace-configuration` returned `retentionPeriodInDays: 400`, `ACTIVE` (read 2026-11-20). `terraform/modules/prometheus_workspace/variables.tf` sets the default to 400 per ADR 0024. The 95-day query-range limit is quoted from ADR 0021 (U).

**OpenTelemetry remote-write exporter (the transport check)**
- V. Read from PyPI and from the source on contrib `main`, 2026-11-20:
  - Latest release `opentelemetry-exporter-prometheus-remote-write` 0.66b2, classified "4 - Beta".
  - The constructor takes `endpoint, basic_auth, headers, timeout, tls_config, proxies, resources_as_labels, ...`. It sends with `requests.post(auth=<basic tuple or None>)`.
  - There is no SigV4 hook. SigV4 signs the body, so static headers cannot carry it. Signing would mean overriding the private `_send_message`.
  - It needs native `snappy` (python-snappy).
  - Unit suffix is `name_unit` (so unit `s` gives `_s`, not `_seconds`). No `_total`, no `job`/`instance`, no `target_info`. Resource attributes become labels by default.
  - Result: the exporter cannot do both, so the ADR's fallback applies.

**Run records, Step Functions and the collector**
- V. `observability/scale/collect_run_metrics.py` writes one record per run to `observability/scale/runs/<execution>.json` with:
  - `execution`, `status`, `start`, `end` (UTC ISO), `run_seconds`, `events_processed`;
  - `states[] {state, seconds, events_per_second, athena}`;
  - `data_quality {passed, errors, warnings, ...}` or `null`.
  It hard-codes `ACCOUNT_ID` (L52). The repo has 17 records, two of them FAILED (`exercise-20261008T085728Z` with DQ errors 2; `exercise-20261009T101830Z` with DQ passed). `demo-7-8-take1` has `data_quality: null`.
- V. `state_timings` (L112-124) keeps only states that have a `TaskStateExited`.
- V. The real failed-run history (`get-execution-history` for `exercise-20261008T085728Z`, read-only) runs: `TaskStateEntered RunDbt` → 3×`TaskFailed` → `TaskStateExited RunDbt` → `FailStateEntered PipelineFailed` → `ExecutionFailed CerberusPipelineFailed`.
  - Every Task in `orchestration/state_machine.asl.json.tftpl` has a `Catch` to `PipelineFailed`. So for FAILED runs the last `states[]` entry is the failed step.
  - For ABORTED or TIMED_OUT, the step that was running never exits, so it is missing from `states[]` (U for a real abort; it follows from the code).
- V. The Task states are `InvokeIngestion`, `RunTransform`, `RunDbt` and `RunServingQuery`. The Fail state is `PipelineFailed` (ASL tftpl).
- V. **Bug in shipped code.** `console/cerberus_console/aws.py` L150-158 sets `last_state` from any `stateEnteredEventDetails`, including `FailStateEntered`. On a real failed history, `failed_state` therefore becomes `PipelineFailed`. The test fixture `console/tests/fixtures/sfn/history_failed.json` is synthetic: `RunDbt` never exits and there is no Fail state, so CI does not catch it. `cmd_status` uses `stages[-1]` from the record, which is correct.

**`exercise.sh`**
- V. `orchestration/exercise.sh` order: preflight → apply → optional generator → `start-execution` (L341) → poll → `capture_spark_logs` → collector via `uv run -q --no-project --with boto3` (L368) → exit, which runs the teardown from the EXIT trap.
- V. Annotation calls are fail-open: `{ ...; } || true`. `--no-annotate` exists. The file hard-codes the account in `STATE_MACHINE` (L68).

**Console (9.3)**
- V. `console/cerberus_console/sources.py` says "Phase 10 adds an AMP reader here without touching the grammar".
- V. `records.py` uses plain `json.loads` only.
- V. `console/ruff.toml` adds bandit (S) and bans `subprocess`, `pickle` and similar under `console/`.
- V. The Lambda zip takes only `console/cerberus_console/*.py` and `observability/scale/runs/*.json` (`terraform/modules/console_edge/main.tf` L39-40, L431-450). The runtime is `python3.12` and provides boto3 only, so PyYAML is not available (U: from the AWS runtime list, not re-read).
- V. The `cerberus-console-cli` role has no `aps:*` grant. Only `grafana_read` has `aps:QueryMetrics...` (`terraform/modules/console_roles/main.tf` L60-63). This matters for 10.5, not 10.2.

**IAM (`cerberus-admin`)**
- V. `iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`, statement `AmpQuery` (L224-232): `aps:QueryMetrics/GetSeries/GetLabels/GetMetricMetadata` on `workspace/*`. `aps:ListWorkspaces` is in L194-195.
- V. `iam simulate-principal-policy` for `cerberus-admin`: `aps:RemoteWrite` gives `implicitDeny`; `aps:QueryMetrics` gives `allowed`.
- V. `aps:ListRuleGroupsNamespaces` and `aps:DescribeAlertManagerDefinition` are denied to `cerberus-admin`. That is 10.4's concern.
- V. Policy sizes (minified): iam-and-governance 4,069 characters, which leaves room under the 6,144 managed-policy limit.

**Grafana**
- V. AMP datasource uid `amp` (`observability/grafana/provisioning/datasources/amp.yaml`).
- V. The dashboards today use only the `cerberus_spark_*`, `cerberus_driver_*` and `cerberus_platform*` names. None use a 10.2 name.

**CI and conventions**
- V. `code-ci.yml` path filter includes `observability/**` and `console/**`.
- V. Jobs:
  - `python-lint` (3.12, `ruff check .` and `ruff format --check .`);
  - `exporter-tests` (3.10, `pytest observability/spark_progress`);
  - `grafana-console-tests` (3.9);
  - `console-tests` (3.12, `pytest console`, plus node).
- V. `pyproject.toml`: ruff line-length 100, target py312, select E/F/I/B/UP. `requirements-dev.txt`: ruff 0.16.4, sqlfluff 4.3.0, pytest 9.1.1. No PyYAML.
- V. Test style (`observability/spark_progress/test_exporter.py`): module beside its tests, `import exporter`, fixtures in `fixtures/`, stdlib only.
- V. Makefile convention: `uv run --no-project --python 3.12 --with <pin> python -m <pkg>` (`cerberus` target).

**Lineage (ADR Q3)**
- V. No OpenLineage events in the saved driver logs. `grep -c '"eventType"'` on `observability/scale/exercises/exercise-20261015T145812Z-spark/*.log` (local, git-ignored) returns 0.
- V. `submit_job.sh` L63 and `entrypoint_transform.sh` L76 already know how to switch to `console`.
- V. `spark_progress/CAPTURE.md` shows a local Spark run of the real scripts at $0 with no AWS.

## 3. Constraints

- **Cost:** $0 idle. No new standing resource. AMP bills per sample (ADR 0016 prices: $0.90 per 10M ingested). This design writes about 23 samples per run, so 30 runs a month is about 700 samples, or about $0.0001.
- **Fail-open:** status can never fail a run (ADR 0013, 0016, 0021). Every `exercise.sh` call is `timeout 60 ... || log`.
- **Ownership:** CI applies `dev-standing` only. 10.2 has no Terraform. The `cerberus-admin` grant is a root paste by the owner, as in 7.3 (ADR 0021, "IAM work comes with this").
- **Nothing in `dev-compute`:** the destroy contract is untouched.
- **Claude never applies, never pastes IAM and never writes to AMP.** Every `--send` is owner-run.
- **No new account IDs or domains in repo files.** New code resolves the workspace by alias (`amp:ListWorkspaces`) and the account by STS. The IAM edit adds an action to an existing statement and no new ARN line.
- **Must not contradict:**
  - ADR 0021 and its amendment: no `execution` label on latest-run series; `last_over_time(...[30d])`; one request for status and finish; no recording rules.
  - ADR 0024: the console never runs a program; JSON only.
  - ADR 0025: names only, never free text.
- **Must amend:** ADR 0021 Q2, "Instrumentation API" and the names. See section 6.

## 4. Options

Two open choices remain. The rest is fixed by ADR 0021.

**Transport and API (the transport check)**
- **T1. OpenTelemetry SDK plus its PRW exporter.**
  - Ruled out by the check: no SigV4 without overriding a private method, plus a native snappy dependency on a beta package.
  - Names would need `unit=""` to avoid `_s`.
- **T2. Hand-written PRW, keep the OpenTelemetry SDK as the instrumentation API.**
  - This is the ADR's own fallback, so no amendment is needed.
  - Cost: `opentelemetry-sdk` and `-api` pinned, an in-memory reader, and a translation layer from OpenTelemetry data points to PRW. We would write and test that layer.
  - Gain: an "uses OpenTelemetry" line. It gives no function for about 20 gauges written once.
- **T3. Hand-written PRW, no OpenTelemetry.** Recommended.
  - Stdlib protobuf encoding (about 40 lines) and a literal-only snappy block (valid snappy, about 15 lines).
  - Signed with botocore `SigV4Auth(..., "aps", ...)`, as `collect_run_metrics.py` already does.
  - The series carry exactly the labels listed, so the ADR's `max without (instance, job)` wrapper is not needed.
  - Gives up the OpenTelemetry API line. Needs the amendment.
- Pillars:
  - Operational Excellence favours T3: one dependency (boto3, already used), and everything is testable offline.
  - Reliability is equal.
  - Security is equal: same SigV4 and IAM.
  - Cost: $0 for all.
  - Sustainability: smallest footprint with T3.

**Query-set file format**
- **F1. YAML** (`observability/queries/status.yaml`, the ADR's example).
  - Easiest to read.
  - Needs PyYAML in CI and in the 10.5 Lambda zip, vendored, against the console's "plain json only" rule (`records.py`).
- **F2. JSON** (`observability/queries/status.json`). Recommended.
  - Stdlib everywhere: the Lambda, the console, the publisher, the 3.9 Grafana host, and Phase 12 Go.
  - Cost: `"` inside PromQL must be escaped (`{step=\"RunDbt\"}`). No comments, so a README explains the rules.
- **F3. TOML.** `tomllib` exists only on 3.11+, and the Grafana host runs 3.9. Go needs a library.

## 5. Recommendation and design

T3 and F2, with an ADR 0021 amendment.

### 5.1 Series (names fixed here, recorded in the amendment)

No series has `job` or `instance`. Every value is a float64 gauge.

| Series | Labels | Written | Value |
|---|---|---|---|
| `cerberus_run_status` | none | end | 1 if `SUCCEEDED`, else 0 (FAILED, TIMED_OUT, ABORTED) |
| `cerberus_run_step_failed` | `step` | end, all 4 steps | 1 on the failed step, 0 on the others; all 0 on success |
| `cerberus_last_success_timestamp_seconds` | none | end, success only | run end, Unix s |
| `cerberus_run_started_timestamp_seconds` | none | start; repeated at end | run start, Unix s |
| `cerberus_run_finished_timestamp_seconds` | none | end | run end, Unix s |
| `cerberus_dq_passed` | none | end | 1/0; NaN if the suite did not run |
| `cerberus_dq_errors`, `cerberus_dq_warnings` | none | end | counts; NaN if not run |
| `cerberus_run_duration_seconds` | none | end | `run_seconds` |
| `cerberus_step_duration_seconds` | `step` | end, all 4 | seconds; NaN for a step not reached |
| `cerberus_run_events_processed` | none | end | `events_processed`; NaN if unknown |
| `cerberus_run_info` | `execution` | end | 1 |
| `cerberus_execution_started_timestamp_seconds` | `execution` | start; repeated at end | run start, Unix s |
| `cerberus_execution_finished_timestamp_seconds` | `execution` | end | run end, Unix s |

Notes on the table:
- **Rename.** `cerberus_run_failed_step_info` becomes `cerberus_run_step_failed`. An `_info` series always has value 1. This one must carry 0 on the steps that did not fail, or `last_over_time` would keep showing an old failed step for 30 days.
- **Why NaN.** A NaN marks a value as unknown. Without it, `last_over_time` would show the previous run's value, for example a DQ result from an earlier run. `NaN > 0` is false, so a DQ rule cannot fire on an unknown value. NaN is a normal NaN, not the Prometheus stale marker.
- **Steps.** Taken from the ASL Task states. A test parses the tftpl so the list cannot drift.
- **Failed step.** If the run did not succeed, it is the record's new `failed_state` field: the last `TaskStateEntered` before the end (PR D). That is right for both the Catch path and an abort. Older records fall back to the last `states[]` entry. If neither exists, every step is 0 and the terminal shows "unknown".
- **Cardinality:** 18 fixed series plus 3 per run. After 100 runs that is 318 series, far under the "few thousand" revisit trigger.
- **Samples per run:** 2 at start and 20–21 at end.

### 5.2 Where it runs and how it writes

- **Code:** `observability/status/publish.py`, run on the laptop as `cerberus-admin`. It is called by `exercise.sh`:
  - `start`, right after `start-execution`;
  - `end`, right after the collector.
  It can also be run by hand.
- **Input for `end`:** the run record, `observability/scale/runs/<execution>.json`. If the collector failed and there is no record, it reads `describe_execution` and `get_execution_history` instead. The DQ and events series are then NaN.
- **Request:** one WriteRequest per call. Labels are sorted, including `__name__`. All samples share one publish timestamp in ms; `--at` overrides it for tests. Body: snappy (literal blocks). Headers: `Content-Encoding: snappy`, `Content-Type: application/x-protobuf`, `X-Prometheus-Remote-Write-Version: 0.1.0`.
- **Endpoint:** `ListWorkspaces(alias="cerberus-platform")` → `prometheusEndpoint` + `api/v1/remote_write`. Signed with SigV4 for service `aps`. 5 s timeout, 2 attempts.
- **Default is a dry run.** It prints the series in Prometheus text format. `--send` writes to AMP. `--url http://127.0.0.1:...` sends unsigned to a local receiver; any host other than loopback is refused.
- **Newest-run guard (`end --send`):** it reads `max(last_over_time(cerberus_execution_finished_timestamp_seconds[30d]))` with `aps:QueryMetrics`. It refuses when that value is newer than this run's end, unless `--force`. This stops a hand re-publish of an old run from overwriting the latest status. If the guard query fails, it warns and continues.
- **`smoke`** writes one `cerberus_publisher_smoke` sample and reads it back. It touches no 10.2 series.

### 5.3 Named query set: `observability/queries/status.json`

```json
{"version": 1,
 "metrics": [{"name": "cerberus_run_status", "labels": [], "scope": "latest", "meaning": "..."}, ...],
 "queries": [{"name": "latest_status", "expr": "last_over_time(cerberus_run_status[30d])", "meaning": "1 if the newest run succeeded, 0 if not"}, ...]}
```

10.2 entries (10.3 to 10.5 add more; 10.4 adds the error-budget entries):

| Entry | PromQL |
|---|---|
| `latest_status` | `last_over_time(cerberus_run_status[30d])` |
| `latest_failed_step` | `last_over_time(cerberus_run_step_failed[30d]) == 1` |
| `latest_started` | `last_over_time(cerberus_run_started_timestamp_seconds[30d])` |
| `latest_finished` | `last_over_time(cerberus_run_finished_timestamp_seconds[30d])` |
| `last_success` | `last_over_time(cerberus_last_success_timestamp_seconds[30d])` |
| `latest_run_seconds` | `last_over_time(cerberus_run_duration_seconds[30d])` |
| `latest_step_seconds` | `last_over_time(cerberus_step_duration_seconds[30d])` |
| `latest_events` | `last_over_time(cerberus_run_events_processed[30d])` |
| `latest_dq_passed` | `last_over_time(cerberus_dq_passed[30d])` |
| `latest_dq_errors` | `last_over_time(cerberus_dq_errors[30d])` |
| `latest_dq_warnings` | `last_over_time(cerberus_dq_warnings[30d])` |
| `newest_finished_execution` | `topk(1, last_over_time(cerberus_execution_finished_timestamp_seconds[30d]))` |
| `newest_started_execution` | `topk(1, last_over_time(cerberus_execution_started_timestamp_seconds[30d]))` |

**Lint (CI) on the file:**
- Names match `^[a-z][a-z0-9_]{2,63}$` and are unique.
- `meaning` is one line of 120 characters or less.
- No `$` and no `{{` (no templating; ADR 0025 takes names only).
- Every `cerberus_*` name in an `expr` is in `metrics`.
- Every catalogue selector sits inside `last_over_time(<sel>[30d])`. The only exception is `avg_over_time` or `count_over_time` with `[90d]`, kept for 10.4's error budget. The ADR's "always `last_over_time[30d]`" does not fit the error budget's 90-day average, so the amendment states this exception.

**Consistency check (CI):**
- `normalise(expr)` removes whitespace outside quoted strings.
- **Panels:** every target `expr` in every `observability/grafana/dashboards/*.json`, including panels nested in rows, that mentions a catalogue metric must equal an entry. No tag is needed, so an untagged panel cannot escape the check. Today's dashboards are not affected (fact above).
- **Rules:** `check_rule_expr(expr)` removes every entry it contains. The rule fails if any catalogue metric is left. 10.4 calls it on its rule files. 10.2 tests it on string fixtures.
- **Publisher:** a test in `observability/status` checks that the names it emits equal the `metrics` catalogue in both directions.

**Location:** a stdlib loader in `console/cerberus_console/queries.py`, with `config.QUERIES_FILE` from the env var `CERBERUS_QUERIES_FILE` (default: the repo path, like `RUNS_DIR`). 10.5 adds the zip `source` block and the console role's `aps:Query*` grant.

## 6. ADR outline (amendment to ADR 0021, Proposed)

Title: "Amendment (2026-11-20): 10.2 transport, series names and query-set format". Status: Proposed.

**Context**
- The transport check result (section 2).
- The OpenTelemetry API gives nothing without its exporter.
- The `_info` naming problem.
- The out-of-date 90-day retention text.
- YAML would need PyYAML in the Lambda.

**Decision**
- T3: hand-written PRW, snappy and SigV4. No OpenTelemetry, so no `max without (instance, job)`.
- The series table in 5.1, including the NaN rule and `cerberus_run_step_failed`.
- The start/end write points and the newest-run guard.
- F2: JSON at `observability/queries/status.json`.
- The 90-day exception (`avg_over_time`/`count_over_time [90d]`) to "always `last_over_time[30d]`".
- Retention text corrected to 400 days (ADR 0024).

**Consequences**
- Good: zero new dependencies, so the whole path is testable offline, including against a real Prometheus receiver.
- Given up: the OpenTelemetry line; PRW encoding code to maintain (small, and pinned by the e2e test); escaped quotes in the JSON.
- To confirm in 10.6: AMP accepts literal-only snappy and NaN samples.

## 7. Build steps (one PR each; Phases.md 10.2 notes)

**PR 0: decision (docs only).** This plan, the ADR 0021 amendment (Proposed), Phases.md 10.2 note, checkpoint. The owner accepts, then `cerberus-git` flips the status.
- Verify: `git diff main --stat` shows only these files.
- Verify: `grep -nE '\b[0-9]{12}\b'` on the added lines returns nothing.

**PR A (10.2a): query set and CI check. Offline.**
- Files:
  - `observability/queries/status.json`
  - `observability/queries/README.md` (format, lint rules, how to add an entry)
  - `console/cerberus_console/queries.py` (`load`, `normalise`, `lint`, `check_dashboard`, `check_rule_expr`; stdlib, `json.loads` only)
  - `console/cerberus_console/config.py` (`QUERIES_FILE`)
  - `console/tests/test_queries.py`
  - fixtures in `console/tests/fixtures/queries/`: `dashboard_ok.json`, `dashboard_hand_edited.json`, `dashboard_nested_row.json`, `dashboard_untagged_uses_status_metric.json`, `status_bad_window.json`
- Tests:
  - the real file passes the lint;
  - every repo dashboard passes;
  - the hand-edited and bad-window fixtures fail with named messages;
  - `normalise` keeps spaces inside quotes;
  - `check_rule_expr` passes `<entry> == 0` and `<entry> * on() group_left(execution) <entry>`, and fails `<entry> and cerberus_run_status`.
- Note: `queries.py` enters the Lambda zip at the next CI `dev-standing` apply, because the zip takes every `*.py` file. Nothing imports it yet, so behaviour does not change.
- Verify:
  - `cd console && uv run --no-project --python 3.12 --with pytest==9.1.1 pytest tests/test_queries.py`
  - `ruff check . && ruff format --check .`
  - CI `console-tests` and `python-lint` are green.

**PR B (10.2b): publisher core, dry run only. Offline.**
- Files:
  - `observability/status/series.py` (`STEPS` from the ASL, `end_series(record)`, `start_series(execution, started)`, `failed_step(record)`)
  - `observability/status/remote_write.py` (`encode(series, ts_ms)`, `snappy_block(data)`, `HEADERS`)
  - `observability/status/publish.py` (argparse: `start | end --execution N [--record P] [--at ISO]`; dry run prints Prometheus text)
  - `observability/status/test_series.py`, `test_remote_write.py` (a test-only protobuf and snappy-literal decoder), `test_publish.py`
  - `.github/workflows/code-ci.yml`: new job `status-tests` (3.12, requirements-dev, `pytest observability/status`)
- Tests:
  - Every one of the 17 committed records converts.
  - `exercise-20261008T085728Z` gives status 0, `step_failed{RunDbt}`=1, `RunServingQuery` duration NaN and `dq_errors` 2.
  - `demo-7-8-take1` gives NaN DQ values.
  - A success writes `last_success`; a failure does not.
  - Emitted names equal `status.json` `metrics`.
  - `STEPS` equals the ASL Task states.
  - The encoding round-trips; labels are sorted; a 70 KB payload spans literal blocks.
  - No `boto3` import in this PR.
- Verify:
  - `uv run --no-project --python 3.12 --with pytest==9.1.1 pytest observability/status`
  - `uv run --no-project --python 3.12 python observability/status/publish.py end --execution exercise-20261008T085728Z` prints the series and makes no network call.

**PR C (10.2c): local end-to-end test against a throwaway Prometheus. Offline: Docker, no AWS.**
- Files:
  - `publish.py --url` (loopback only, unsigned)
  - `observability/status/test_e2e.py` (skipped unless `CERBERUS_PROM_URL` is set)
  - Makefile target `status-e2e`: `docker run --rm -d -p 127.0.0.1:9099:9090 prom/prometheus:<pinned v3 tag> --web.enable-remote-write-receiver`, then pytest, then `docker rm -f`
  - `code-ci.yml` job `status-e2e` with the same steps
- Test steps:
  1. Push the FAILED record at now−60 s, then the start of the next run, then the SUCCEEDED record `exercise-20261015T145812Z` at now−30 s.
  2. Evaluate every query-set entry through `/api/v1/query` after each push.
  3. After the failed push, expect `latest_failed_step` = `{step="RunDbt"}` and `newest_finished_execution` labelled with the failed execution.
  4. After the success push, expect `latest_status` 1, `latest_failed_step` empty, and `last_success` equal to the success end.
- This proves the protobuf field numbers, real snappy decoding, NaN acceptance by Prometheus and that every entry parses.
- Verify: `make status-e2e`; CI `status-e2e` is green.

**PR D (10.2d): AWS transport and exercise hooks. Offline with fakes; the first real write is the owner smoke.**
- Files:
  - `publish.py`: `--send` (SigV4 `aps`, workspace by alias, newest-run guard, `--force`), the Step Functions fallback (account from STS), and `smoke`.
  - `observability/scale/collect_run_metrics.py`: add `failed_state` (last `TaskStateEntered` when status is not `SUCCEEDED`). About 4 lines.
  - `orchestration/exercise.sh`:
    - a `--no-status` flag;
    - `status_publish start` after L341 and `status_publish end` after the collector, each `timeout 60 ... --send || log "status publish failed (fail-open)"`;
    - a warn-only `simulate-principal-policy aps:RemoteWrite` line in `preflight`.
  - Makefile: `status-publish` (AWS WRITE, owner-run; `EXECUTION=`; dry run unless `ARGS=--send`) and `status-smoke`.
  - `iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`: add `aps:RemoteWrite` to `AmpQuery` and rename the Sid to `AmpQueryAndStatusWrite`. Add no new ARN line.
  - `iam/cerberus-admin/README.md`: a dated entry, "paste pending".
  - Tests:
    - fake AMP and STS clients;
    - the signed request has `Authorization` with `/us-east-1/aps/aws4_request`, the right URL and the headers;
    - the guard refuses an older run and `--force` passes;
    - the fallback uses a new fixture `observability/status/fixtures/history_failed_catch.json`, copied from the real event order above, and gives `RunDbt`;
    - a dry run makes no AWS call.
- Verify:
  - pytest;
  - `bash -n orchestration/exercise.sh`;
  - `shellcheck orchestration/exercise.sh` (U: not checked whether it is installed);
  - `make exercise-check`, which is read-only and should print the RemoteWrite warning until the paste;
  - `make status-publish EXECUTION=demo-100m-20261108T135119Z` (dry run).

**PR E (side fix, small, offline):** in `console/cerberus_console/aws.py` L150-158, only `TaskStateEntered` sets `last_state`. Add `console/tests/fixtures/sfn/history_failed_catch.json` in the real event order, and a test that expects `RunDbt`.

**Owner step (not a PR, $0, no cluster):**
1. Root-paste the policy.
2. Check that `aws iam simulate-principal-policy ... --action-names aps:RemoteWrite` returns `allowed`.
3. Run `make status-smoke ARGS=--send`; it reads the sample back.
4. Record the result in Phases.md 10.2 and in the IAM README.

**Lineage track (ADR 0021 Q3), separate PRs:**
- **L1 (offline):** an extractor for OpenLineage console lines in the saved driver logs and dbt CloudWatch text. Keys are built with the collector's `_object_key` and the result is a dry run. Spark half: verify with a local Spark run of `promote_payments_spark.py` with `openlineage-spark_2.12:1.53.0` and the console transport (the CAPTURE.md method, $0, no AWS).
- **L2 (live, 10.6):** the dbt-ol console output in ECS logs, and the upload as `cerberus-admin`.

**Can be built and verified offline or in CI now:** PR 0, A, B, C, D (code and fakes), E, and L1 Spark half.

**Waits for AWS or a live run:**
- Owner smoke: the IAM paste, AMP accepting SigV4, literal-only snappy and NaN.
- 10.6:
  - the real `exercise.sh` hooks;
  - the start/end gap under the AMP ruler (with 10.4);
  - dbt lineage;
  - the AMP bill.

## 8. Unverified items

- AMP accepts literal-only snappy, NaN samples and a v0.1.0 PRW request signed by botocore. Owner smoke, then 10.6.
- "AMP refuses samples older than 1 hour" and the 95-day query range (ADR 0021 text).
- The behaviour of `failed_state` for ABORTED and TIMED_OUT runs (derived from the code, never seen live).
- The Prometheus v3 tag to pin, and that `--web.enable-remote-write-receiver` is still the flag in that tag.
- The protobuf field numbers for `WriteRequest`, `TimeSeries`, `Label` and `Sample` (from memory). PR C proves them against a real receiver.
- That the Lambda `python3.12` runtime has no PyYAML (AWS runtime list, not re-read).
- That `shellcheck` is installed locally.
- The OpenLineage console-line format for Spark 1.53.0 and dbt-ol (L1 and L2).

## 9. Owner answers (2026-11-20)

1. **T3, recorded as an amendment to ADR 0021 (not a new ADR).** The exporter check failed on SigV4 and snappy, so OpenTelemetry would only add a dependency and a translation layer.
2. **JSON at `observability/queries/status.json`.** It is stdlib in the Lambda, on the 3.9 Grafana host and in Go, and it keeps the console's JSON-only rule.
3. **No backfill.** All samples would be stamped "now", and 2 FAILED of 17 (11.8% against the 5% SLO) would fire the 10.4 error-budget alert on day one.
4. **Yes, the owner smoke before 10.6.** It proves SigV4, snappy and NaN on AMP without a cluster, so 10.6 tests only the pipeline.
5. **Yes, lineage stays under 10.2** (PRs A-E, the smoke and L1). The live lineage check moves to 10.6's list. The ADR assigns lineage's first check to 10.2.

Sources:
- https://pypi.org/project/opentelemetry-exporter-prometheus-remote-write/
- https://raw.githubusercontent.com/open-telemetry/opentelemetry-python-contrib/main/exporter/opentelemetry-exporter-prometheus-remote-write/src/opentelemetry/exporter/prometheus_remote_write/__init__.py
