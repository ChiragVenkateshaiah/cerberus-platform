# 14. Phase 6 Well-Architected review

Date: 2026-09-07

## Status

Accepted

## Context

Phase 6 — Observability & data quality — is built and verified live
(6.1–6.5 done):

- **6.1** — a CloudWatch dashboard (`cerberus-platform-pipeline`, 9 widgets
  over the Step Functions / Lambda / Athena metrics the pipeline already
  emits) plus an hourly **freshness-probe Lambda** publishing
  `Cerberus/Pipeline` → `FreshnessSeconds{Signal}` custom metrics for how
  stale each layer's data and the last successful run are. Its first run
  caught a week-long silent failure of the daily schedule.
- **6.2** — seven CloudWatch alarms (two probe-self-health, unconditional;
  five gated on `pipeline_active`) to a dedicated `cerberus-pipeline-alerts`
  SNS topic, each notifying on `ALARM` and `OK`, each carrying a specific
  remediation pointer in its description.
- **6.3** — dbt schema/data-quality tests (`not_null`, `unique`,
  `accepted_values`, `relationships`, a custom `non_negative`) run inside
  `dbt build` on every orchestrated run; a failing invariant fails the
  `RunDbt` task and the whole execution.
- **6.4** — data lineage: a curated whole-pipeline `docs/lineage.md`, dbt's
  own model DAG on GitHub Pages, and a serverless OpenLineage collector
  ([ADR 0013](0013-lineage-openlineage-serverless-collector.md)) capturing
  runtime dataset + column lineage from both the Spark and dbt steps —
  verified end to end (Spark on EKS 2026-09-07).
- **6.5** — `docs/slo.md`: six service level objectives (pipeline success,
  gold freshness, run latency, serving-query latency, data quality,
  observer freshness), each backed by an existing CloudWatch SLI and its
  guarding alarm, with a lightweight halt-and-fix error-budget policy.

Per `Phases.md`'s cross-cutting rule, every phase closes with a
Well-Architected pass plus an ADR plus a Tool milestone. Following the
diff-based pattern ADR 0004 set up and 0006/0008/0010/0012 continued:
milestone 5 (`phase-5-cicd-complete`) is the baseline, and this ADR only
touches the questions Phase 6's work changed the honest answer to.

## What Phase 6 changed, pillar by pillar

Eight questions were re-answered against the `cerberus-platform` workload
via `aws wellarchitected update-answer`. **Three moved a risk bucket** —
the first bucket movement since milestone 1, after four consecutive phases
(2–5) held flat at 25 HIGH / 18 MEDIUM / 9 NONE / 5 N/A. That is expected
here in a way it was not for Phases 2–5: Phase 6 *is* the observability
phase, so the observability and monitoring questions are exactly where its
evidence lands.

### Moved a bucket

**Operational Excellence / `workload-observability`** ("How do you utilize
workload observability in your organization?") — **MEDIUM → NONE**.
Milestone 5's note said in as many words: *"No metrics, traces, or
dashboards yet -- Phase 6's job."* Phase 6 did that job. Added three
choices — **create dashboards** (6.1's dashboard), **analyze workload
metrics** (the freshness probe's custom metrics plus the free
`AWS/States`/`AWS/Lambda` metrics), **analyze workload traces** (4.3's
X-Ray, now surfaced from the dashboard) — joining the already-selected
"create actionable alerts" (reinforced from one billing alarm to seven
pipeline alarms) and "analyze workload logs". Five of five real choices
selected.

**Reliability / `monitor-aws-resources`** ("How do you monitor workload
resources?") — **HIGH → MEDIUM**. Added **define and calculate metrics
(aggregation)** — the freshness probe *computes* `FreshnessSeconds` from
S3 object ages and the state machine's last `SUCCEEDED` execution (a
derived signal CloudWatch has no native form of), 6.2's
`cerberus-pipeline-run-unsuccessful` is a metric-math alarm summing three
failure metrics, and `docs/slo.md` defines the SLI formulas — and
**regularly review monitoring scope and metrics** (the per-phase
Well-Architected pass is that review; `docs/slo.md`'s Maintenance section
commits to revisiting thresholds and SLIs). Deliberately did **not** select
"automate responses": 6.2's alarms notify a human by design, they do not
auto-remediate.

**Performance Efficiency / `process-culture`** ("What process do you use to
support more performance efficiency?") — **HIGH → MEDIUM**. Milestone 5's
note flagged this as *"Phase 6 territory"*. Added **establish KPIs** (the
run-latency SLO plus `ExecutionTime` and the per-integration timing
metrics), **use monitoring solutions to understand where performance is
critical** (the dashboard's "Pipeline execution duration" and "Step
integration timing" widgets, and its X-Ray pointer for per-named-state
latency), and **review metrics at regular intervals** (the per-phase pass).
Not "load test" — that is Phase 7's scaled synthetic workload — and not
"automation to remediate".

### Genuine new evidence, no bucket move

**Operational Excellence / `observability`** (HIGH) — added **identify key
performance indicators**: `docs/slo.md` defines six SLOs, each tied to a
named CloudWatch metric and shown on the dashboard. `application_telemetry`
and `distributed tracing` were already selected; `user-experience
telemetry` is N/A (no interactive users) and `dependency telemetry` does
not apply — every dependency is an AWS-native service already covered by
the metrics. 3 of 5 real choices; **stays HIGH**.

**Operational Excellence / `event-response`** (HIGH) — moved off "None of
these" for the first time (ADR 0010 recorded it there honestly). Added
**have a process per alert** (every 6.2 alarm's description names the
specific next step — the log group to check, "use X-Ray to find the
bottleneck", "check the execution history"), **communicate status through
dashboards** (6.1), and **prioritize operational events based on business
impact** (`docs/slo.md`'s error-budget policy ranks the objectives —
observer-freshness burning "blocks everything" because the rest can no
longer be measured). Still **not** claiming a formal
incident/problem-management process, escalation paths, customer
communication, or automated response — solo scale, one email recipient,
and `docs/slo.md` says so explicitly. 3 of 8; **stays HIGH**, but the
honest answer genuinely changed.

**Operational Excellence / `operations-health`** (NONE) — no new checkbox
available (already 3 of 3 real), but `docs/slo.md` makes "measure ops
goals and KPIs with metrics" and "review metrics and prioritize
improvement" concrete rather than aspirational: measurable objectives with
error budgets, and a prioritisation rule (budget exhausted → reliability
work precedes the next phase). **Stays NONE.**

**Operational Excellence / `dev-integ`** (MEDIUM) — added **implement
practices to improve code quality**: 6.3's dbt test suites run in the
pipeline on every run, and 5.3's ruff + sqlfluff lint Python and the dbt
models on every PR — static analysis plus enforced tests, not just manual
review (the gap milestone 5's note named). 7 of 11; **stays MEDIUM**.

**Reliability / `mitigate-interaction-failure`** (HIGH) — added **fail
fast and limit queues**: 6.3's data-quality gate means a bad invariant
fails `RunDbt` immediately and stops the execution, rather than writing
bad data into gold and letting the serving query return it. This is
plan.md's Phase 6 "done when" — *bad data fails the pipeline loudly
instead of landing silently* — expressed as a Well-Architected choice.
5 of 8; **stays HIGH**.

## Considered, not changed

- **Reliability / `backing-up-data`** (MEDIUM) — Phase 6 added no backup
  capability; 6.4's lineage collector bucket has a 90-day lifecycle
  expiry, which is retention, not backup. Unchanged.
- **Operational Excellence / `ready-to-support`** (HIGH) — 6.1's
  `pipeline_active` runbook and 6.5's error-budget policy are more
  operational documentation, but the same "runbooks / playbooks / informed
  decisions" choices are already selected and the remaining ones
  (personnel capability, consistent operational-readiness review, support
  plans) don't apply at solo scale. Reinforced in spirit, no checkbox.
- **Security / `detect-investigate-events`** (MEDIUM) — ADR 0012 flagged
  this as "real Phase 6 territory" for log aggregation. Phase 6 added
  CloudWatch dashboards and alarms over *operational* metrics, not a
  security log-aggregation or threat-detection capability (no GuardDuty,
  no Security Hub, no CloudTrail analysis pipeline). The honest answer
  stays unchanged — that is 7.3 / Phase 7 territory, not this phase.
- **Cost Optimization** — 6.4's collector and 6.1/6.2's observability
  layer are all zero-idle-cost serverless (ADR 0013's central point), but
  that is more of the service-selection discipline Phases 1–4 already
  credited, not a new cost practice. No Cost question's answer changed.
- **Sustainability** — unchanged (0 HIGH, as since milestone 1).

## Overall

Milestone 5 (`phase-5-cicd-complete`, 2026-08-24) → milestone 6
(`phase-6-observability-and-data-quality-complete`, 2026-09-07):

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 5 | 25 | 18 | 9 | 5 |
| Milestone 6 | 23 | 19 | 10 | 5 |

Three questions moved: `workload-observability` MEDIUM→NONE,
`monitor-aws-resources` HIGH→MEDIUM, `process-culture` HIGH→MEDIUM. Five
more gained genuinely new evidence or a new checkbox without crossing the
Tool's internal threshold (`observability`, `event-response`,
`operations-health`, `dev-integ`, `mitigate-interaction-failure`).

This is the first bucket movement since milestone 1. ADR 0010 and 0012
both observed that "opens new ground" and "moves a risk bucket" are not
the same claim, after Phases 4 and 5 each opened new ground without moving
anything. Phase 6 is the counter-case, and the reason is specific rather
than encouraging: a phase whose entire purpose is observability will move
the observability questions, because that is what those questions ask
about. It does not imply Phase 7 will move buckets — 7.3's least-privilege
review is the next real candidate, and only for Security.

## Consequences

- **Phase 6 is now fully closed** — 6.1–6.6 all done. Milestone 6 is the
  baseline 7.4's platform-wide review diffs against.
- **The three HIGH questions Phase 6 left untouched in its own pillars**
  (`priorities`, `ops-model`, `org-culture` in Operational Excellence) are
  all organisational — they assume a team, business stakeholders, and a
  support structure a solo project does not have. They are unlikely to
  move before Phase 7's write-up reframes the workload's context, if then.
- **`event-response` and `observability` are the near-misses** — both
  gained real evidence and stayed HIGH. A formal alert-to-action runbook
  document (beyond the one-line alarm descriptions) would likely move
  `event-response`; that is a candidate for Phase 7 or a follow-up, not a
  gap this ADR papers over.
- **The data-quality gate (6.3) is now Well-Architected evidence in two
  pillars** — `dev-integ` (code quality) and `mitigate-interaction-failure`
  (fail fast) — a clean example of one build decision showing up as
  concrete evidence in more than one place, the same way ADR 0012 noted
  for ADR 0011's OIDC design.
