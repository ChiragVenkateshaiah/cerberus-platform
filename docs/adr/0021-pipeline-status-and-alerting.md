# 21. Pipeline status and alerting: AMP as the store and the alert evaluator, run-end remote-write, local Grafana

Date: 2026-10-13 (amended 2026-10-15)

## Status

Accepted, with changes from a design review on 2026-10-15. The first
draft (2026-10-13, merged as Proposed in #99) had three blocking faults,
all fixed below: lineage files written inside tasks that exit, a
stale-data alert that cannot work for hand-started exercises, and a
"revisit if" trigger that Phase 9 had already fired.

Amended by [ADR 0024](0024-demo-console.md) (2026-10-27): the shared Grafana is settled (one file set, two hosts) and the datasource file is split by datasource.

Amended 2026-11-12 (Accepted 2026-11-12): hooks for the Phase 14 agents — one named query set, an `execution` label on alerts, a reserved AI review panel, and 14.2–14.4 moved to directly after Phase 10 (see Amendment below).

Amendment 2026-11-20 (Accepted 2026-11-20): 10.2 transport (hand-written remote write, no OpenTelemetry), series names, JSON query set (see Amendment below).

Amendment 2026-11-28 (Accepted 2026-11-28): 30-day windows in AMP, SLO 1 from the run records (see Amendment below).

## Context

Phase 10 ([plan.md](../plan.md#phase-10--pipeline-status--alerting)) exists
to answer one question at any time: did the last run pass, and if not,
which step failed? Today the answer is spread over the Step Functions
console, CloudWatch, an exercise log and a JSON run record in
`observability/scale/runs/`. The Prometheus agent and Grafana from ADR 0016
see only the EKS and Spark layer, and only while `dev-compute` is up.

**What the workload looks like.** This is a batch pipeline run by hand, a
few times a month, each run lasting minutes. No process is alive between
runs. That differs from the case Prometheus was built for, a long-lived
service scraped continuously. The Prometheus documentation's answer for
batch jobs is a *last success timestamp* and a *last status* per job, kept
somewhere that outlives the job.

**The rules this ADR works inside.**

- No new idle cost. The platform's standing infrastructure has cost cents
  a month since ADR 0005.
- Metrics stay out of the critical path (ADR 0013, ADR 0016): a status
  failure can never fail a run.
- `dev-standing` is applied by CI; `dev-compute` and `make exercise` are
  human-run (ADR 0011).

**What alerts exist today.** The seven CloudWatch alarms from 6.2 notify
SNS topic `cerberus-pipeline-alerts`, but five of them (including the
failed-run and freshness alarms) exist only while `pipeline_active =
true`. Hand-started exercises leave it `false`, so **an exercise today has
no failed-run alert at all.** This ADR adds one; the ownership split is
under Decision.

**Phase 9 changed the viewer question.** The demo console (Phase 9,
inserted 2026-10-15) will host Grafana and Prometheus views on a
start/stop instance. The first draft of this ADR assumed a Grafana that
only runs on the laptop. This ADR now fixes what must be portable and
leaves the host to Phase 9's ADR.

**What already stands.** ADR 0016 put an Amazon Managed Service for
Prometheus (AMP) workspace in `dev-standing`. It has no workspace fee;
AMP bills for samples ingested, stored and queried (list prices in ADR
0016: $0.90 per 10M samples ingested, $0.03 per GB-month, $0.10 per billion
query samples). `collect_run_metrics.py` already signs and runs PromQL
against it (SigV4, service `aps`).

**Three questions this ADR has to answer.**

1. Where do status series live, and what evaluates alerts, when nothing
   is running?
2. How does a batch run get its status into Prometheus format, given that
   its process has exited by the time anyone scrapes it?
3. How does a hand-started exercise's lineage reach the collector? Since
   2026-10-07 the collector's route is open only while `pipeline_active =
   true`, and `make exercise` leaves it `false`: dbt-ol logged 348 `403`s
   and the runs finished with no lineage. Run status and lineage answer the
   same question, so they are decided together.

## Options for question 1

| Option | Series live in | Alerts evaluated by | Idle cost | History |
|---|---|---|---|---|
| **A. Local Docker Compose** (Prometheus, Alertmanager, Grafana) reading AWS on demand | The laptop | The laptop | $0 | Lost when the stack is rebuilt; none while it is off |
| **B. AMP** (the 7.7 workspace) with AMP's ruler and managed Alertmanager; Grafana local | AMP | AMP, always on (no idle fee) | $0 plus cents per month for a few hundred series | Kept: the workspace sets 90 days (`retention_days`; the AWS default is 150) |
| **C. Grafana Cloud free tier** | Grafana Cloud | Grafana Cloud | $0 | Free tier: 10,000 active series, 14 days of metrics (checked against Grafana's pricing page, 2026-10-15) |
| **D. Amazon Managed Grafana** as the viewer | n/a | n/a | $9 a month fixed | n/a |

D is out for the reason ADR 0016 gave: one editor license is the
platform's first fixed monthly cost.

Why B, in plain terms. Three things count; the rest are close to ties.

- **Operational Excellence decides.** B reuses the store, the IAM pattern
  and the PromQL client the project already has, and keeps the rules and
  the Alertmanager config as Terraform (`aws_prometheus_rule_group_namespace`,
  `aws_prometheus_alert_manager_definition`), tested with `promtool` in CI.
  Rules as code is the point of Phase 10 (plan.md). C adds a second metrics
  store and a vendor account. A has nothing to apply and nothing to lose,
  which is its appeal; but it is off when the laptop is off.
- **Reliability helps, but less than the first draft said.** A failed-run
  alert does not need a rule engine: an always-on, $0 EventBridge rule on
  Step Functions `FAILED`, `TIMED_OUT` and `ABORTED` could send it to SNS.
  What needs a standing evaluator is "a run started and never reported",
  and alerts on data-quality results and the run history. C's 14-day
  retention is shorter than the 30-day window the queries use.
- **Cost is a tie.** All three are about $0. B's cost is samples: a few
  hundred series written once per run is a few thousand samples a month,
  far under the free-tier allowance in ADR 0016. AMP bills alerting rules
  as query samples processed; the estimate is about $0.01 a month, inside
  the free tier (AWS pricing page, read 2026-10-15), and still to be
  confirmed from the first bill. How recording rules are billed is not
  stated on that page, so this ADR writes no recording rules.
- **Security:** B keeps writes and reads SigV4-signed with IAM, no new
  ingress and no new credential. C needs an API key stored somewhere.

An EventBridge rule is not adopted, but stays open as cheap belt and
braces: it covers only the Step Functions outcome, not data quality or
"never reported".

**The tension worth naming: Prometheus assumes something is always
running; this platform deliberately has nothing running.** B resolves it by
splitting roles, as ADR 0016 and ADR 0013 did: the *producers* are
ephemeral (the exercise's own end-of-run step), while *storage and rule
evaluation* are managed and pay-per-use, standing at zero idle cost. The
price is the AMP dependency, and one limit: AMP's Alertmanager can notify
only through SNS. That is acceptable. The alerts already go to SNS topic
`cerberus-pipeline-alerts` from 6.2, so there is one place alerts arrive.

## Decision

**Question 1: option B.** Status series are written to the existing AMP
workspace. Alerting and recording rules and the Alertmanager config are
Terraform in `dev-standing` (`aws_prometheus_rule_group_namespace`,
`aws_prometheus_alert_manager_definition`), receiving through the existing
SNS topic. `promtool test rules` runs in `code-ci.yml` over the same rule
files. What is decided about Grafana is only that its **provisioning is
portable**: the datasource (AMP, SigV4) and the dashboards are provisioned
files in the repository, so any Grafana can load them. Local Docker Compose
stays as the development loop. **Where the shared Grafana runs is Phase 9's
decision (9.1)**, and the two ADRs should end with one Grafana, not two. The
Phase 10 terminal view, `make status`, must be the same code as Phase 9's
`cerberus status` (9.3), not a second implementation, so both show the same
numbers. Nothing runs when nobody is looking.

**Question 2: write at the end of a run, with `remote_write`; no scrape
and no Pushgateway.** A small publisher, called by `exercise.sh` after the
collector and also available by hand, writes the run's series straight to
AMP with the Prometheus remote-write protocol, then exits.

Alerts must read *the latest run*, so the series that alerts use carry
**no `execution` label**: each run writes a new sample to the same series,
and `last_over_time` returns the newest. (With an `execution` label,
`cerberus_run_status == 0` would keep firing for 30 days after a later
passing run.) Names follow Prometheus conventions (`_info` for info series,
the unit as suffix):

- Latest-run series: `cerberus_run_status` (1 succeeded, 0 failed),
  `cerberus_run_failed_step_info{step}` (1 on the failed step),
  `cerberus_last_success_timestamp_seconds`,
  `cerberus_run_started_timestamp_seconds`,
  `cerberus_run_finished_timestamp_seconds`, `cerberus_dq_passed`,
  `cerberus_dq_errors`, `cerberus_dq_warnings`. Their history is a normal
  time series; a dashboard reads it with a range query.
- Detail series: `cerberus_run_duration_seconds`,
  `cerberus_step_duration_seconds{step}`, `cerberus_run_events_processed`.
- One info series, `cerberus_run_info{execution}`, for drill-down.

Cardinality is a few dozen series. A sample written once looks stale to
PromQL after five minutes, so every query and rule reads the latest-run
series with `last_over_time(...[30d])`. The workspace keeps 90 days and AMP
accepts a query range of up to 95 days, so 30 days is safe. This is the
cost of having no process to re-serve the last value, which a Pushgateway
would do. A Pushgateway would also have to stand somewhere: in
`dev-compute` it would die with the cluster.

*Timestamps.* AMP refuses samples older than one hour. The publisher
therefore stamps samples with the time it runs, not the run's own time. A
late rerun by hand is fine for the latest-run series; the run's real times
live in the `…_timestamp_seconds` values.

*Instrumentation API.* The plan asked this ADR to decide whether the
exporter uses the OpenTelemetry metrics SDK. **Yes as the API, with the
transport left to 10.2's first spike.** OpenTelemetry is the vendor-neutral
instrumentation standard, and Prometheus remote write is one of its
supported outputs. The maturity of the Python remote-write exporter, and
whether it signs for AMP (service `aps`), was **not verified** in writing
this ADR. If it cannot do both, the publisher writes the remote-write
protobuf itself (snappy-compressed, signed with the SigV4 code
`collect_run_metrics.py` already has) and keeps the OpenTelemetry API
for naming. The OpenTelemetry route changes the plan's stack line
(`prometheus_client` cannot remote-write; plan.md is updated) and its
Prometheus translation adds unit and `_total` suffixes, `job` and
`instance` labels and a `target_info` series. Queries therefore aggregate
(`max without (instance, job)`), and 10.2 fixes the exact names after the
spike. The decision (the series meanings and the `last_over_time` reading)
does not change.

**Question 3: lineage events are collected after the run, not posted
during it.** Hand-started exercises will not use the HTTP route at all. The
producers do not run on the laptop: dbt runs in an ECS Fargate task and the
Spark job on EKS, and a file written inside a task is lost when the task
exits. So the first draft's "file transport" is replaced by the **console
transport**, which `submit_job.sh` already uses as its fallback. The events
then leave through logs that the exercise already keeps:

- Spark: the driver log that `capture_spark_logs` saves;
- dbt: the task's CloudWatch Logs.

After the run, `exercise.sh` extracts the OpenLineage events from those two
sources, splits them into one object per event, keyed the way the
collector keys its objects (`_object_key` in `lineage/collector/handler.py`),
and uploads them to the lineage bucket as `cerberus-admin`, an
authenticated `PutObject`. The renderer already reads that bucket. This keeps the
7.5 narrowing (the route stays closed outside `pipeline_active`), needs no
SigV4 in producers that cannot sign, and puts a run's lineage next to its
status record. **Not yet verified:** that both listeners (OpenLineage
1.53.0 in the runner image) print complete events to the console, and that
the extracted objects parse with the collector's handling. 10.2 checks this
first. If it fails, the fallback is to open the route for the exercise
window with a `dev-standing` variable CI does not own, which is a bigger
change and would need its own amendment.

**Dashboards: provisioned JSON, as in 7.7.** Two dashboards at most (run
status; SLO and burn rate). Grafonnet or Jsonnet would add a toolchain
for a file count that does not justify it. Revisit if the dashboards grow
past about five.

**Alerts, as code, and who owns them.** Two systems raise alerts, so
the split is explicit:

- **AMP owns (all runs, including hand-started exercises):** failed run
  (`last_over_time(cerberus_run_status[30d]) == 0`, which clears on the next
  passing run); data-quality errors above zero; a run that never reported
  (`cerberus_run_started_timestamp_seconds` newer than
  `cerberus_run_finished_timestamp_seconds`, for over an hour); and an
  error-budget alert, below.
- **CloudWatch (6.2) keeps** its alarms for the `pipeline_active` windows,
  including stale gold data and the slow-run alarm. When both are active, one
  failure raises two alerts. That is accepted; SNS is the one place they
  arrive.
- **Dropped: a stale-data alert in AMP.** The first draft offered to scope
  it to `pipeline_active` periods, but exercises never set it. And after 30
  days with no success, `time() - last_over_time(...[30d])` returns no
  result, so the alert goes quiet exactly when the data is stalest. For a
  pipeline that runs only in exercise windows, "no success lately" is the
  normal state, not a fault. If a scheduled path returns, it comes back
  (see Revisit).
- **Error budget over runs, not multi-window burn rate.** SLOs 1–5 in
  docs/slo.md use the trailing 20 runs. With a few runs a month, a 1-hour or
  6-hour window holds zero or one run, so multi-window burn rate means
  nothing. Each run writes one status sample, so the average of
  `cerberus_run_status` over a 90-day window (the query range limit is 95)
  is the failed-run share. The alert fires when that share exceeds the SLO's
  5% and the window holds at least five runs. 10.4 fixes the exact
  expressions. The SLO definitions stay in docs/slo.md, as ADR 0016 said.

## Consequences

**Good**

- One store for metrics (AMP), one place alerts arrive (SNS), one query
  client. Phase 10 adds no resource with an idle fee (AMP's ruler runs
  always, but bills only for samples evaluated).
- An exercise gets a failed-run alert for the first time.
- Rules are evaluated while the laptop is off, and history survives
  teardown and rebuilds.
- Status, lineage and the run record are written by the same step, so they
  describe the same run.

**Given up**

- **Grafana's host is open.** Local Compose reaches only the machine
  running it. Phase 9's console is the planned shared viewer; until it
  lands, the README video and `make status` output stand in for it.
- **A run that dies before the end-of-run step publishes nothing.** The
  "never reported" alert (execution started, no series) is the safety net;
  it needs the start to be recorded too, which 10.2 must settle (publish a
  `cerberus_run_started_timestamp_seconds` at the start).
- **`last_over_time(...[30d])` in every query.** Easy to forget in a new
  panel; the dashboard and `make status` share the query set to limit that.
- **AMP's Alertmanager supports SNS only.** Fine today; a Slack or
  PagerDuty route would go through an SNS subscription.
- **No stale-data alert in AMP** for hand-started exercises (reasons
  above). Stale gold data is still caught by CloudWatch while
  `pipeline_active = true`.
- **IAM work comes with this.** `cerberus-admin` needs `aps:RemoteWrite`
  (a root-pasted policy change, as in 7.3). `cerberus-ci-apply` needs the
  rule-group-namespace and Alertmanager actions. The SNS topic policy must
  allow `aps.amazonaws.com` to publish.

**To confirm from real runs (10.2, 10.6), not from this document**

- The Python OpenTelemetry remote-write exporter versus a hand-written
  one (above).
- That dbt-ol and the Spark listener print full lineage events to the
  console, and that the extracted objects parse.
- That the Python remote-write exporter can sign for `aps`
  (`opentelemetry-exporter-prometheus-remote-write` 0.66b1 is beta; its
  page does not mention SigV4).
- AMP's bill for rule evaluation and the first month's ingest.
- That `promtool test rules` can run over the AMP rule files unchanged
  (AMP rule files use the standard Prometheus rule format).

**Revisit if**

- The pipeline gets a standing, scheduled path again (then a stale-data
  alert is real, and a heartbeat series may be wanted).
- Phase 9's ADR chooses a Grafana host that cannot read the provisioned
  files as they are.
- Series counts grow past a few thousand (AMP cost stops being noise).

## Amendment (2026-11-12): designed for the Phase 14 agents

Status: Accepted (2026-11-12). The user chose option C on 2026-11-12 and accepted defaults (a)–(c) of the plan the same day. The plan is [2026-11-12-phase-10-agent-hooks.md](../plans/2026-11-12-phase-10-agent-hooks.md). It adds to Question 2's series list, the Dashboards point and the AMP-owned alerts, and settles the "recording rules" wording in Question 1. The original text stays as written.

### Context

- [ADR 0025](0025-ai-operations-agents.md) decision 4 needs a fixed, named PromQL query set for the agents. This ADR already wants one query set shared by the dashboard and `make status` (Consequences, "`last_over_time(...[30d])` in every query"). Today that set is a wish, not a file.
- No alert says which run failed. The latest-run series have no `execution` label on purpose (Question 2), so a firing alert cannot point at a run, and a reviewer started from an alert has nothing to start from.
- ADR 0025 decision 8 puts the "AI review" panel on dashboard 1 (`cerberus-run-story`, the recorded-run story view), not on the Phase 10 run-status dashboard. The review of a run would then sit away from the status it explains.
- 14.4 (the run reviewer) depends on 14.2a and 14.2b, the `cerberus-ops-agent` IAM step and the 14.3 eval (AI plan step 5). ADR 0025 decision 10 says only that Phase 14 "starts after Phase 10", and Phases 11–13 come first by number. So nothing places 14.4 next to the Phase 10 rules and panels it must fit.
- Two other options were considered. Option A, "AI decides alerts", was rejected: it is non-deterministic, cannot be tested with `promtool`, and breaks ADR 0025 decision 1 (rules detect, GenAI explains, a human approves). Option B, no hooks and AI added later, was rejected: the query set and the alert labels would then be added to Phase 10 rules and panels that already exist, with a second round of `promtool` tests.

### Decision

Option C: Phase 10 alerting stays deterministic (AMP ruler, Alertmanager, SNS, `promtool` in CI), and Phase 10 is built with hooks for the Phase 14 agents.

- **D1. One named query set.** One file, for example `observability/queries/status.yaml`. Each entry has a name, the PromQL (always the `last_over_time(...[30d])` form) and a one-line meaning. The consumers are:
  - Phase 10 dashboard panels: the panel `expr` equals the entry.
  - Alert rules: the `expr` contains the entry verbatim, plus the condition.
  - The shared `make status` / `cerberus status` code, which loads the file.
  - ADR 0025's PromQL tool, which takes names only, never free text.

  A CI test in `code-ci.yml` fails on any Phase 10 panel or rule expression that is not built from a named entry (whitespace is normalised before comparing). Nothing is generated, so "no Grafonnet" holds.
- **D2. Alerts name the run; the latest-run series still have no `execution` label.**
  - The publisher writes one per-execution start-time series at run start and one per-execution finish-time series at run end. The finish series goes in the same remote-write request as the status. 10.2 fixes the names. The value is the Unix timestamp, so `topk(1, last_over_time(<finish series>[30d]))` returns the newest finished run.
  - The failed-run and DQ-error rules keep their conditions on the label-free series and add the label with `group_left(execution)` from the newest finished run. The never-reported rule takes it from the newest started run.
  - Rule annotations carry `cerberus run {{ $labels.execution }}` and `make review RUN={{ $labels.execution }}`. The SNS template in AMP's Alertmanager prints `.CommonLabels.execution` and the annotations.
  - Whether an alert fires still depends only on the latest status. When the next run passes, the alert clears. When it fails, the old alert resolves and a new one fires with the new execution. `cerberus_run_info{execution}` keeps value 1 for drill-down.
  - Fallback, only if the AMP ruler rejects the join: the Prometheus `query` template function in annotations (unverified on AMP).
  - No recording rules. This resolves the wording in the Decision, "Alerting and recording rules": the ruler runs alerting rules only, as the Options text already said.
  - Both the status and the finish sample go in one remote-write request. If the ruler still evaluates between them, the wrong `execution` label is pending for one evaluation only. A short `for:` on the failed-run and DQ-error rules keeps that label from firing. 10.4 picks the value, and a `promtool` test models the gap (the finish sample one evaluation late). `promtool` cannot show how AMP ingests the request.
- **D3. A reserved "AI review" panel.** The Phase 10 run-status dashboard (10.3) gets an annotation-list panel on the built-in Grafana annotations datasource, filtered by tag `cerberus-ai`. Its empty text is "No AI review yet (Phase 14)". It loads on both hosts (local Compose and the console Grafana); on the console it stays empty for now (see Consequences). It counts within the two-dashboard limit. It replaces "dashboard 1" in ADR 0025 decision 8; dashboard 1 keeps only a link to it.
- **D4. Order.** 14.2a, 14.2b, the `cerberus-ops-agent` IAM step, 14.3 and 14.4 run directly after 10.7 and before 11.1. 14.5–14.8 stay after Phase 13. ADR 0025 decisions 1–3 and 5–9 do not change: local trigger after the destroy, `--no-review`, the $2 monthly cap, the guardrails, report-only, and no AI action that changes AWS.

**What does not change:**

- AMP as the store and the ruler.
- SNS as the one place alerts arrive.
- `promtool` in CI.
- No `execution` label on the latest-run series, and `last_over_time(...[30d])`.
- No stale-data alert in AMP, and the error budget over runs.
- Question 3 (lineage).
- AI never raises, suppresses or gates an alert.

### Consequences

**Good**

- One query set serves four consumers, so the dashboard, the terminal, the alert and the agent show the same numbers.
- The failed-run, DQ-error and never-reported alerts name the run, and the review is one command away. The error-budget alert covers many runs and carries no `execution` label.
- The reviewer is built on real Phase 10 signals, and the 10.6 run pair can be replayed with `make review` at $0 compute.

**Given up**

- Two more series per run (noise-level cost).
- The join makes each rule more complex, and it needs a `promtool` test with `exp_labels: execution`.
- The consistency test must be maintained.
- Phase 11 starts about 5 PRs later.
- The user must enable Bedrock model access and do the local `cerberus-ops-agent` apply earlier.
- AI spend of up to $2 a month starts earlier. The forecast is $17.2 (ADR 0025 Context) + $2 = $19.2 of the $20 budget. Whether credits cover Bedrock is unverified.
- The console Grafana's AI review panel stays empty. Its annotations are rebuilt only from run records (ADR 0024), and reviews stay out of run records (ADR 0025 decision 8). Extending the boot rebuild to `observability/scale/reviews/` is a later Phase 14 step.

**To confirm in 10.4**

- The AMP ruler accepts the `topk` + `group_left` rule.
- `promtool` passes the same file.
- The `query` template (fallback only).

## Amendment (2026-11-20): 10.2 transport, series names and query-set format

Status: Accepted (2026-11-20). The plan is [2026-11-20-pipeline-status-exporter.md](../plans/2026-11-20-pipeline-status-exporter.md); it holds the full series table, the query-set entries and the build steps. This amendment settles what Question 2 left to 10.2's first spike: the transport, the exact series names and the query-set file format. The original text stays as written, except that two earlier statements are superseded: the "Instrumentation API" paragraph of Question 2 (OpenTelemetry as the API, and `max without (instance, job)`) by the Transport decision below, and the "90 days" retention by the Retention decision below.

### Context

- The transport check is done, from PyPI and the exporter source on contrib `main` (2026-11-20). `opentelemetry-exporter-prometheus-remote-write` 0.66b2 is beta. It has no SigV4 hook: it sends with `requests.post(auth=...)`, and SigV4 signs the body, so static headers cannot carry it. It also needs native `snappy`. It cannot both remote-write and sign for `aps`, so the fallback in "Instrumentation API" applies.
- Without its exporter, the OpenTelemetry API gives nothing for about 20 gauges written once per run. Its Prometheus translation would also add a `_s` unit suffix, `job`/`instance` labels and `target_info`.
- `cerberus_run_failed_step_info{step}` breaks the `_info` convention: an info series always has value 1, and this one must carry 0 on the steps that did not fail. Otherwise `last_over_time[30d]` would show an old failed step for 30 days.
- The retention statement in Question 2 and Option B ("90 days") is out of date. The earlier text is superseded: the workspace keeps 400 days (`retentionPeriodInDays: 400`, read 2026-11-20; default in `terraform/modules/prometheus_workspace/variables.tf`, per [ADR 0024](0024-demo-console.md)).
- YAML (the 2026-11-12 example, `status.yaml`) would need PyYAML in the console Lambda zip, which has boto3 only, against the console's "plain `json.loads` only" rule.

### Decision

- **Transport: hand-written remote write, no OpenTelemetry.** The publisher encodes the protobuf `WriteRequest` with the standard library, compresses it with snappy literal blocks and signs it with botocore SigV4 for `aps`, as `collect_run_metrics.py` already does. The series carry exactly the labels listed, with no `job`/`instance`, so queries need no `max without (instance, job)`.
- **Series names** (all float64 gauges; the plan section 5.1 has the full table):
  - Label-free latest-run series: `cerberus_run_status` (1 if `SUCCEEDED`, else 0), `cerberus_last_success_timestamp_seconds` (written on success only), `cerberus_run_started_timestamp_seconds`, `cerberus_run_finished_timestamp_seconds`, `cerberus_dq_passed`, `cerberus_dq_errors`, `cerberus_dq_warnings`, `cerberus_run_duration_seconds`, `cerberus_run_events_processed`.
  - By step: `cerberus_run_step_failed{step}` (replaces `cerberus_run_failed_step_info`; written for all 4 steps, 1 on the failed step and 0 on the others) and `cerberus_step_duration_seconds{step}`.
  - By execution: `cerberus_run_info{execution}`, `cerberus_execution_started_timestamp_seconds{execution}` and `cerberus_execution_finished_timestamp_seconds{execution}`.
  - The steps are the four Task states of the state machine (`InvokeIngestion`, `RunTransform`, `RunDbt`, `RunServingQuery`); a test parses the ASL template so the list cannot drift.
- **NaN means unknown.** A value that is not known (the data-quality suite did not run, a step was not reached, events unknown) is written as NaN, not omitted. Without it, `last_over_time` would show the previous run's value. `NaN > 0` is false, so a DQ rule cannot fire on an unknown value.
- **Write points.** At run start: the start series (`cerberus_run_started_timestamp_seconds` and the per-execution start series). At run end, in one request: the status, the finish series and the rest, repeating the start series. About 2 samples at start and 20 to 21 at end.
- **Newest-run guard.** `end --send` refuses when the newest finished run in AMP is newer than the run being published, unless `--force`. A hand re-publish of an old run cannot overwrite the latest status. If the guard query fails, it warns and continues.
- **Query-set format: JSON** at `observability/queries/status.json`, replacing the "for example `status.yaml`" of the 2026-11-12 amendment. It has a `metrics` catalogue and a `queries` list (name, PromQL, one-line meaning). A stdlib loader in `console/cerberus_console/queries.py` reads it. A CI lint checks the names, that every `cerberus_*` name in an `expr` is in the catalogue, that every catalogue selector sits inside `last_over_time(<selector>[30d])` (or the `[90d]` exception below), and that no entry uses templating. The consistency check (panels equal an entry, rules contain entries verbatim) from D1 stays.
- **One exception to "always `last_over_time(...[30d])`".** `avg_over_time` and `count_over_time` over `[90d]` are allowed, for the 10.4 error budget, which averages `cerberus_run_status` over 90 days (ADR 0021, "Error budget over runs").
- **Retention.** 400 days, as stated in Context. The 30-day reading window and the 90-day error-budget window both fit.

### Consequences

**Good**

- No new dependency beyond boto3, so the whole path is testable offline, including against a throwaway Prometheus with the remote-write receiver.
- Series names are final, so 10.3, 10.4, 10.5 and Phase 14 read one query set.
- JSON works in the Lambda, on the Python 3.9 Grafana host and in Go.

**Given up**

- The OpenTelemetry API line in the project's story.
- A small PRW encoder (protobuf and snappy literal blocks) to maintain, pinned by the end-to-end test.
- Escaped quotes in the JSON PromQL, and no comments in the file (a README explains the rules).

**To confirm**

- In the owner smoke write, then 10.6: AMP accepts literal-only snappy, NaN samples and a v0.1.0 request signed by botocore. `aws iam simulate-principal-policy` returns `implicitDeny` for `aps:RemoteWrite` today, so the root-pasted grant comes first.
- That the protobuf field numbers are right: the local end-to-end test (PR C) proves them against a real receiver.

## Amendment (2026-11-28): 30-day windows in AMP; SLO 1 from run records

Status: Accepted (2026-11-28; proposed and accepted the same day, owner answers below). The plan is [2026-11-28-amp-30-day-windows.md](../plans/2026-11-28-amp-30-day-windows.md). The original text stays as written, except that four earlier 90-day or 95-day statements are superseded (see Supersedes below).

### Context

- AMP refuses every window from 32d to 95d (measured live 2026-11-28). An instant query with `[90d]` gets HTTP 422 ("queries with long day range (32d to 95d) are currently only supported for range type queries"). The same as a range query gets 422 ("cannot include range selectors and subqueries that exceed 7d in duration"). `[31d]` returns 200 for both. The earlier "query range limit is 95" was wrong.
- Two status queries (`run_success_share_90d`, `runs_90d`) use `[90d]`, so `make status` shows "unavailable". The budget rule `CerberusErrorBudgetBurn` and three dashboard targets use `[90d]` too.
- `promtool test rules` has no 32d-95d limit, so CI passed. The budget tests run at 4d and 19d.
- Rule health is unreadable: `cerberus-admin` has no `aps:ListRules`. The alert-path smoke proves that the ruler and SNS work, not that this rule evaluates. That the budget rule is dead is unverified, but very likely.
- Run rate: 17 run records (2026-10-06 to 2026-11-08), at most 14 runs in any 30 days. The busiest 30-day window holds 14 runs with 2 failed (14.3%). With the old rule (over 5% and at least 5 runs), one failure in 5 to 19 runs fires. On 30 days the alert would fire on every single failure. That duplicates the CloudWatch page `cerberus-pipeline-run-unsuccessful` and goes beyond the SLO, which allows about 1 run in 20.
- SLO 1 is not defined over 90 days. `docs/slo.md` sets it over the trailing 20 runs. Only the alert and the two `90d` query entries use 90 days.

### Decision

1. **One window, `[30d]`, for all PromQL evaluated in AMP.** The "`[90d]` exception" and the "90-day error-budget window" of the 2026-11-20 amendment are superseded, and so is the original "90-day window (the query range limit is 95)".
2. **Names and labels.** `run_success_share_90d` becomes `run_success_share_30d` (label "Runs that passed (30 days)"). `runs_90d` becomes `runs_30d` (label "Runs in 30 days"). The dashboard panel is titled "Share of runs that passed (30 days)". The console JSON keys become `success_share_30d` and `runs_30d`.
3. **New budget-rule condition.** `CerberusErrorBudgetBurn` fires when failed runs are at least 2 and the failed share is over 5%, on `[30d]`. The failed count is `count x (1 - avg)`, built only from query-set entries. The 5-run minimum is dropped. Severity stays `ticket`. A single failure stays the CloudWatch alarm's job. Two failures in under 40 runs always exceed the 1-in-20 budget; the 5% clause covers months with 40 or more runs.
4. **SLO 1 is unchanged** (at least 95% over the trailing 20 runs). The authoritative figures come from the run records: a stdlib script `observability/scale/slo_report.py` (`make slo`, offline) reads the top-level `status` of `observability/scale/runs/*.json`. It counts terminal states only, orders runs by `start`, and prints the trailing-20 share and the 90-day share. The AMP 30-day share is the live, near-term signal only.
5. **Rule health.** Grant `aps:ListRules` and `aps:ListAlerts` (read-only, same workspace ARN) to `cerberus-admin` by one root paste. Add `make alerts-health`, which fails when any rule's health is not `ok` or it has a `lastError`.
6. **Window guard.** Every entry of `ALLOWED_WINDOWS` in `queries.py` becomes `30d`. A new cap check fails any range selector or subquery over 31d, whatever the metric, over every `expr` in `status.json`, every rule and every dashboard target. A test asserts the dashboard `time.from` is at most 31d.

### Consequences

**Good**

- `make status` works, the budget alert can evaluate, and CI blocks a wide window from coming back.

**Given up**

- The AMP budget view covers 30 days, not 20 runs.
- The record-based SLO depends on the owner collecting every run, including failed ones (a rule in `docs/scale-metrics.md`).
- One more manual step (`make slo`) and one more root paste.

**Neutral**

- Renamed JSON keys in the console output and the showcase snapshot.
- Cost: $0 for all options (a grant, a script and a query change).

**Well-Architected:** Reliability (an alert that cannot evaluate is silent; the health check and the cap close that), Operational Excellence (CI blocks the regression), Security (the new grant is read-only). Cost, Performance and Sustainability: no change.

### Supersedes

- Original "Error budget over runs": "a 90-day window (the query range limit is 95)".
- 2026-11-20, Decision: "One exception ... `avg_over_time` and `count_over_time` over `[90d]`", and the `[90d]` clause in the query-set lint.
- Original series design: "AMP accepts a query range of up to 95 days" (30 days stays safe; the real limit is 31 days, see Context).
- 2026-11-20, Retention: "the 90-day error-budget window" (the 400-day retention itself stands; storage is not the limit, the query engine is).

### Owner answers (2026-11-28)

1. SLO 1 on the records reads 88.2% (15 of 17). `docs/slo.md` "Current standing" shows it as breached and names the two failed runs.
2. Every orchestrated run since 2026-10-06 is in `observability/scale/runs/`, including failed ones. The runbook rule is: collect every run, pass or fail.
3. Budget alert: at least 2 failed and over 5%, with no 5-run minimum.
