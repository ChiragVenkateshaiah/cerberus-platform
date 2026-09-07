# Service level objectives

_Phase 6.5. The reliability targets for the platform, the indicators behind
them, and what happens when a target is missed. Backed entirely by signals
[6.1](../terraform/modules/observability/) and
[6.2](../terraform/modules/observability/alarms.tf) already emit — this is
the write-up that turns those metrics and alarms into objectives, not new
instrumentation._

## The dormancy model

SLOs assume a service that is *meant to be running*. This platform is
**dormant by default**: `pipeline_active = false`
([ADR 0011, amended](adr/0011-ci-cd-github-actions-oidc.md)), the daily
orchestration schedule is `DISABLED`, and the EKS cluster the transform
step needs is torn down between exercises (ADR 0007). That is the normal
state, not an outage — running paid compute 24/7 to fire one daily job is
exactly what this project spent three phases avoiding.

So the objectives split in two:

| Class | Applies | Examples |
|---|---|---|
| **Active-window** | only while `pipeline_active = true` (a compute exercise is running) | pipeline success, gold freshness, run latency |
| **Always-on** | continuously, regardless of `pipeline_active` | the freshness probe runs hourly |

An "active window" starts when `pipeline_active` is flipped to `true` and
merged, and ends when it is flipped back. Measurement and error-budget
accounting for active-window objectives only count time and runs inside
those windows.

---

## Service level indicators

Every SLI below is already published — no code changes for 6.5.

| SLI | Metric | Meaning |
|---|---|---|
| **Run outcome** | `AWS/States` `ExecutionsSucceeded`, `ExecutionsFailed`, `ExecutionsTimedOut`, `ExecutionsAborted` (dimension `StateMachineArn`) | Terminal state of each orchestrated run. Success rate = `Succeeded / (Succeeded + Failed + TimedOut + Aborted)`. |
| **Last-success age** | `Cerberus/Pipeline` `FreshnessSeconds{Signal=PipelineRun}` | Seconds since the state machine last reached `SUCCEEDED`, sampled hourly by the freshness probe ([`freshness_probe/handler.py`](../observability/freshness_probe/handler.py)). |
| **Gold freshness** | `FreshnessSeconds{Signal=GoldData}` | Seconds since the newest object was written anywhere in the gold bucket (dbt marts + `payments_current`). |
| **Run latency** | `AWS/States` `ExecutionTime` (dimension `StateMachineArn`, `Maximum`) | Wall-clock duration of a run, on the state-machine clock. Excludes the manual `terraform apply` that brings up EKS — that is a human step before the run, not part of it. One datapoint per run. |
| **Step latency** | `AWS/States` `LambdaFunctionRunTime`, `ServiceIntegrationRunTime`, `ActivityRunTime` | Per-integration timing. CloudWatch does not break these out by named state — the dashboard points at X-Ray / execution history for true per-state latency. |
| **Serving query** | `AWS/Athena` `TotalExecutionTime`, `EngineExecutionTime` (dimension `WorkGroup=cerberus_platform`); query *success* via `RunServingQuery` in the state machine (a failed Athena query fails that state → fails the execution) | Duration and success of the demo query against gold. Athena publishes no per-query success metric to CloudWatch, so success is observed through the orchestration step, not a dedicated metric. |
| **Data quality** | dbt `build` exit status → `RunDbt` ECS task exit → `ExecutionsFailed` | 6.3's schema/data-quality tests run inside `dbt build`; a failure fails the task, the state, and the run. |
| **Observer health** | `AWS/Lambda` `Invocations`, `Errors` (dimension `FunctionName=cerberus-freshness-probe`) | Whether the freshness probe itself is running and succeeding. If it stops, every `FreshnessSeconds` SLI silently goes stale-blind. |

---

## The objectives

| # | Objective | Class | Window | Error budget | Guarding alarm |
|---|---|---|---|---|---|
| 1 | **Pipeline success** — ≥ 95% of orchestrated runs reach `SUCCEEDED` | active | trailing 20 runs (or the active window, whichever is shorter) | 5% (≈ 1 run in 20) | `cerberus-pipeline-run-unsuccessful` |
| 2 | **Gold freshness** — gold data is < 24h old ≥ 95% of the time | active | the active window | 5% of window-hours | `cerberus-freshness-gold-data` (fires at 36h) |
| 3 | **Run latency** — a run completes in < 30 min ≥ 90% of the time | active | trailing 20 runs | 10% | `cerberus-pipeline-execution-slow` (fires at 45 min) |
| 4 | **Serving query** — the demo query succeeds in < 30s ≥ 99% of runs | active | trailing 20 runs | 1% | (none dedicated — via alarm 1) |
| 5 | **Data quality** — 100% of gold-writing runs pass every dbt test | active | every run | 0% (hard gate) | (via alarm 1) |
| 6 | **Observer freshness** — the freshness probe runs successfully every hour ≥ 99% of the time | always-on | trailing 30 days | 1% (≈ 7h/month) | `cerberus-freshness-probe-silent`, `cerberus-freshness-probe-errors` |

### 1 — Pipeline success

The headline objective: when the pipeline is supposed to run, does it
finish. Measured as the ratio of `SUCCEEDED` executions to all terminal
executions over the trailing 20 runs. 95% leaves room for roughly one
transient failure per 20 runs — an ECS task blip, an EKS API hiccup, an
Athena throttle — without burning the objective. `RunTransform` and
`RunDbt` each retry twice on any error ([4.3](adr/0009-orchestration-step-functions-vs-airflow.md)),
so a run only counts as failed after those retries are exhausted.

The guarding alarm fires on the *first* unsuccessful run, not at the 95%
line — the alarm means "look now", the SLO means "the trend is
acceptable". A single failure pages but does not necessarily breach.

### 2 — Gold freshness

During an active window a healthy daily run refreshes the dbt marts and
`payments_current`. The objective is that the newest gold object stays
under 24 hours old — i.e. at most one daily cycle is ever missed. Measured
from `FreshnessSeconds{GoldData}` sampled hourly: the fraction of samples
in the window under 86,400 is the SLI.

The alarm threshold (36h) is deliberately looser than the objective (24h):
36h means "two cycles missed, definitely broken"; 24h is the target we
want to hold. The gap between them is the early-warning zone.

`FreshnessSeconds{PipelineRun}` (last-success age) is the same signal from
the orchestration side and is guarded by `cerberus-freshness-pipeline-run`;
it is not a separate objective because a stale `PipelineRun` and stale
`GoldData` almost always move together, and objective 1 already covers "the
run failed".

### 3 — Run latency

The four state timeouts in the ASL sum to a 57-minute theoretical ceiling
(120s ingest + 2100s transform + 900s dbt + 300s serving). Observed runs
are far under that — the Phase 4 demo run and the 2026-09-07 exercise both
completed in single-digit minutes for the containerised steps. 30 minutes
is a comfortable target with headroom under the 45-minute alarm, and it is
a duration a reviewer would consider "prompt" for a full
ingest→transform→serve cycle. Measured from `ExecutionTime` (Maximum, one
datapoint per run).

Real percentiles (p90/p99) are the usual latency-SLI statistic, but a
once-daily pipeline does not produce the population for them — with one
datapoint per run, "90% of the trailing 20 runs" is the honest
approximation.

### 4 — Serving query

The MVP's definition-of-done is "a reviewer runs one Athena query against
gold and gets a result" — this objective keeps that fast and reliable. The
query is a cheap aggregate read over the gold marts; 30s and 99% are
generous for that. Success is observed through `RunServingQuery` (a failed
query fails the state); duration through `TotalExecutionTime` on the
workgroup. If the query path ever gets its own dedicated
success/latency metric it becomes a first-class alarm; today it rides on
objective 1.

### 5 — Data quality

Not a budgeted SLO — a hard gate. 6.3's tests (`not_null`, `unique`,
`accepted_values`, `relationships`, `non_negative`) run inside `dbt build`
on every run; any failure fails `RunDbt`, fails the execution, and trips
`cerberus-pipeline-run-unsuccessful`. There is no acceptable rate of bad
data reaching gold — the objective is 100%, and a miss is a
pipeline-success failure (objective 1), not a separate budget to spend.
This is plan.md's Phase 6 "done when" — _bad data fails the pipeline
loudly instead of landing silently_ — expressed as an objective.

### 6 — Observer freshness

The one always-on objective. The freshness probe
([`freshness_probe/handler.py`](../observability/freshness_probe/handler.py))
runs hourly on its own EventBridge schedule, independent of
`pipeline_active`. Every `FreshnessSeconds`-based SLI and alarm depends on
it, so "is the observer alive" is itself an objective: ≥ 99% of hourly runs
succeed over a trailing 30 days (≈ 7 hours of tolerated gap per month).
`cerberus-freshness-probe-silent` (3-of-3 missing hours) and
`cerberus-freshness-probe-errors` guard it.

---

## Error-budget policy

The budget is the allowed shortfall — 5% of runs for objective 1, and so
on. While a budget has room, normal work continues. **When an objective's
budget is exhausted, reliability work on that objective takes priority over
starting the next phase's features until the objective recovers.**

Concretely, for this project:

- If objective 1, 2, or 3 burns its budget during Phase 6 or 7, the fix
  for the underlying failure is done before the next planned subtask
  starts — not deferred behind a `checkpoint.md` note.
- A burn is recorded in `checkpoint.md`'s session history with the runs
  that caused it, so the pattern is visible across sessions.
- The always-on objective (6) burning means the observability layer itself
  is unreliable — that blocks everything, since the other objectives can
  no longer be measured.

This is deliberately lightweight: there is no separate on-call rotation, no
incident review process (the six live-pass bugs in Phase 4 were fixed ad
hoc, and ADR 0010 recorded that honestly). The policy is a commitment to
sequencing — fix reliability before building more — not a process.

---

## Not SLOs

Deliberately excluded, with the reason:

| Not measured | Why |
|---|---|
| **Bronze data freshness** | The ingestion Lambda is capped by `RETIRE_ON_OR_AFTER=2026-08-17` ([ADR 0005](adr/0005-push-vs-pull-ingestion.md)), so bronze does not refresh from the orchestrated run — new data needs a manual `generate_payments.py`. Bronze freshness is a manual-generation concern, not a pipeline-health signal. No `BronzeData` alarm either, for the same reason. |
| **Infrastructure uptime** | EKS, the NAT Gateway, and the Spark stack are spin-up/destroy by design (ADR 0007/0011). "The cluster is down" is the intended steady state, not downtime. |
| **CI/CD availability** | GitHub Actions and the `terraform plan`/`apply` workflows are dev-time infrastructure, not a runtime service users depend on. Their health is visible in the README build badges. |
| **True latency percentiles** | A once-daily pipeline does not produce the datapoint population for p90/p99. Objective 3 uses "N of the trailing 20 runs" as the honest stand-in until there is enough history. |
| **Cost as an SLO** | Covered by the Phase 0 `cerberus-billing-alarm-10usd` and each phase's Well-Architected cost review — a budget alarm, not a service objective. |

---

## Current standing

Honest accounting, 2026-09-07:

- The orchestrated pipeline has reached `SUCCEEDED` end to end a **handful
  of times** — the Phase 4 live-verification run (2026-08-20) and the
  2026-09-07 lineage exercise (Spark transform + `dbt build`, verified
  against live Athena). Between those, the daily schedule ran red for a
  week (2026-08-21 → 08-27, caught by the freshness probe's first run)
  because it was `ENABLED` with no cluster — the failure that led directly
  to the `pipeline_active` gate.
- That is **not enough run history for a real error-budget burn
  calculation**. This document defines the targets and the measurement
  method; the trailing-20-runs windows start accumulating meaningful data
  from the next sustained active window (most likely Phase 7's scaled-up
  workload).
- The always-on objective (6) *is* measurable now — the freshness probe
  has run hourly since 2026-08-27 with the only gap being deliberate
  (the 2026-09-01 `pipeline_active` work did not touch it). It is meeting
  99%.

---

## Feeds 6.6

This document is direct evidence for the Well-Architected **Reliability**
pillar (workload SLIs/SLOs defined, error budget policy, monitored against
alarms) and **Operational Excellence** (understanding operational health,
a defined response to degradation). 6.6's pass references it rather than
re-deriving it.

## Maintenance

Revisit when:

- an alarm threshold changes (the objective and its guarding alarm should
  stay in the looser-alarm / tighter-objective relationship described
  above),
- a new SLI becomes available (e.g. a dedicated Athena query-success
  metric would promote objective 4 to a first-class alarm),
- Phase 7's scaled workload produces enough run history to replace the
  "trailing 20 runs" approximation with real percentiles.
