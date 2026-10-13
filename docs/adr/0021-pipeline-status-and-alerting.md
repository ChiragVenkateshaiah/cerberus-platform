# 21. Pipeline status and alerting: AMP as the store and the alert evaluator, run-end remote-write, local Grafana

Date: 2026-10-13

## Status

Proposed

## Context

Phase 9 ([plan.md](../plan.md#phase-9--pipeline-status--alerting)) exists
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
| **B. AMP** (the 7.7 workspace) with AMP's ruler and managed Alertmanager; Grafana local | AMP | AMP, always on | $0 plus cents per month for a few hundred series | Kept (AMP default retention is 150 days) |
| **C. Grafana Cloud free tier** | Grafana Cloud | Grafana Cloud | $0 | Free tier: 10,000 active series, 14 days of metrics (third-party figures, 2026; not checked against Grafana's own page) |
| **D. Amazon Managed Grafana** as the viewer | n/a | n/a | $9 a month fixed | n/a |

D is out for the reason ADR 0016 gave: one editor license is the
platform's first fixed monthly cost.

Working the choice through the pillars (most say little; three decide):

| Pillar | What it says |
|---|---|
| **Reliability** | The deciding one. "The data went stale" can only be noticed by something that is running when the data is *not* arriving. A is off when the laptop is off, so it cannot raise that alert. B and C evaluate rules on a schedule with no help from this project. 14-day retention (C) is shorter than a 30-day SLO window (docs/slo.md), so burn rate over the SLO's own window could not be computed. |
| **Operational Excellence** | B reuses the store, the IAM pattern and the PromQL client the project already has, and keeps rules and the Alertmanager config in Terraform (AMP rule group namespaces and an alert manager definition). C adds a second metrics store and a vendor account to a platform that has one. A has nothing to apply and nothing to lose, which is its appeal, and it is not enough to alert from. |
| **Cost Optimization** | Close to a tie: all three are about $0. B's cost is samples: a few hundred series written once per run is a few thousand samples a month, far under the free-tier allowance in ADR 0016 (eligibility to be confirmed from the first bill). Rule evaluation is counted by AMP as queried samples; to be confirmed from the first bill, not assumed. |
| **Security** | B keeps writes and reads SigV4-signed with IAM, no new ingress and no new credential. C needs an API key stored somewhere. |
| **Performance Efficiency, Sustainability** | Nothing sharp. Volumes are tiny. |

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
files. Grafana runs **locally** from a Docker Compose file with
provisioned datasource and dashboards, reading AMP with SigV4. Nothing runs
when nobody is looking. The Phase 9 terminal view, `make status`, runs the
same PromQL as the dashboard through the signing client the collector
already has.

**Question 2: write at the end of a run, with `remote_write`; no scrape
and no Pushgateway.** A small publisher, called by `exercise.sh` after the
collector and also available by hand, writes the run's series straight to
AMP with the Prometheus remote-write protocol, then exits. Series, each
labelled `execution` and (where it applies) `state`:

- `cerberus_run_status` (1 succeeded, 0 failed), `cerberus_run_failed_step`
  (info series, label `state`), `cerberus_run_duration_seconds`,
  `cerberus_step_duration_seconds{state}`, `cerberus_run_events_processed`;
- `cerberus_dq_passed`, `cerberus_dq_errors`, `cerberus_dq_warnings`;
- `cerberus_last_success_timestamp_seconds` (the batch-job pattern).

A sample written once looks stale to PromQL after five minutes. Every
query and rule therefore reads these series with `last_over_time(...[30d])`
(for example `time() - last_over_time(cerberus_last_success_timestamp_seconds[30d])`
for staleness). This is the cost of having no process to re-serve the last
value, which is what a Pushgateway would do. A Pushgateway would also have
to stand somewhere: in `dev-compute` it would die with the cluster, and
the fix for a failed run is exactly when it should still be there.

*Instrumentation API.* The plan asked this ADR to decide whether the
exporter uses the OpenTelemetry metrics SDK. **Yes as the API, with the
transport left to 9.2's first spike.** OpenTelemetry is the vendor-neutral
instrumentation standard, and Prometheus remote write is one of its
supported outputs. The maturity of the Python remote-write exporter, and
whether it signs for AMP (service `aps`), was **not verified** in writing
this ADR. If it cannot do both, the publisher writes the remote-write
protobuf itself (snappy-compressed, signed with the SigV4 code
`collect_run_metrics.py` already has) and keeps the OpenTelemetry API
for naming. Either way the series and queries above do not change, which
is why this is not part of the decision.

**Question 3: lineage events are uploaded after the run, not posted
during it.** Hand-started exercises will not use the HTTP route at all. The
producers write OpenLineage events to a local transport (file or console)
during the run, and `exercise.sh` uploads them to the lineage bucket as
`cerberus-admin`, an authenticated `PutObject`. The renderer already reads
that bucket. This keeps the 7.5 narrowing (the route stays closed outside
`pipeline_active`), needs no SigV4 in producers that cannot sign, and puts
a run's lineage next to its status record. **Not yet verified:** that the
dbt-ol and Spark OpenLineage listeners can write to a file or console
transport in the versions pinned in the runner image, and that the output
parses with the collector's existing handling. 9.2 checks this first. If it
fails, the fallback is to open the route for the exercise window with a
`dev-standing` variable CI does not own, which is a bigger change and
would need its own amendment.

**Dashboards: provisioned JSON, as in 7.7.** Two dashboards at most (run
status; SLO and burn rate). Grafonnet or Jsonnet would add a toolchain
for a file count that does not justify it. Revisit if the dashboards grow
past about five.

**Alerts, as code:** failed run (`cerberus_run_status == 0`), stale data
(no success in N days; N chosen in 9.4), SLO burn rate over two windows
(a fast and a slow one, following the multi-window method in the Google
SRE workbook), and a run that never reported (a started execution with no
status series after an hour).

## Consequences

**Good**

- One store for metrics (AMP), one place alerts arrive (SNS), one query
  client; Phase 9 adds no always-on resource.
- Rules are evaluated while the laptop is off, and history survives
  teardown and rebuilds.
- Status, lineage and the run record are written by the same step, so they
  describe the same run.

**Given up**

- **Grafana is not reachable from anywhere but the machine running Docker
  Compose.** No shared URL for a reviewer. The README video and `make
  status` output stand in for that. Managed Grafana ($9 a month) or Grafana
  Cloud would fix it; neither is worth it for a one-person project.
- **A run that dies before the end-of-run step publishes nothing.** The
  "never reported" alert (execution started, no series) is the safety net;
  it needs the start to be recorded too, which 9.2 must settle (publish a
  `cerberus_run_started_timestamp_seconds` at the start).
- **`last_over_time(...[30d])` in every query.** Easy to forget in a new
  panel; the dashboard and `make status` share the query set to limit that.
- **AMP's Alertmanager supports SNS only.** Fine today; a Slack or
  PagerDuty route would go through an SNS subscription.
- **A staleness alert fits a daily pipeline badly.** The pipeline runs
  only in exercise windows, so "no success in N days" would fire between
  exercises. 9.4 either scopes it to `pipeline_active` periods or
  uses a long N and labels it a warning.

**To confirm from real runs (9.2, 9.6), not from this document**

- The Python OpenTelemetry remote-write exporter versus a hand-written
  one (above).
- That dbt-ol and the Spark listener write lineage to a file transport.
- AMP's bill for rule evaluation and the first month's ingest.
- That `promtool test rules` can run over the AMP rule files unchanged
  (AMP rule files use the standard Prometheus rule format).

**Revisit if**

- The pipeline gets a standing, scheduled path again (then staleness is a
  real alert, and a Pushgateway-free design may want a heartbeat series).
- A reviewer-facing URL becomes a goal (then Grafana Cloud or Managed
  Grafana moves from "no" to a cost decision).
- Series counts grow past a few thousand (AMP cost stops being noise).
