# 10. Phase 4 Well-Architected review

Date: 2026-08-20

## Status

Accepted

## Context

Phase 4 — orchestration — is built and verified live (4.1–4.4 done): ADR
0009 chose Step Functions over Airflow; the state machine (Lambda →
ECS Fargate transform/dbt tasks → Athena, per-state retries and timeouts
tuned to each step's actual idempotency) was applied for real, six live-only
bugs were found and fixed, and a full orchestrated execution succeeded
end to end — `InvokeIngestion` → `RunTransform` (a real Spark job on EKS)
→ `RunDbt` → `RunServingQuery`, all `SUCCEEDED`, with real settled-revenue
data returned by the demo query. A scoped `terraform destroy` afterward
left the orchestration layer (ECR, ECS task definitions, the state
machine, the scheduler) standing, exactly as ADR 0009's cost bet predicted.

Per `Phases.md`'s cross-cutting rule, every phase closes with a
Well-Architected pass plus an ADR. Following the diff-based pattern ADR
0004 set up and ADR 0006/0008 continued: milestone 3
(`phase-3-scalable-compute-complete`) is the baseline, and this ADR only
touches the questions Phase 4's actual work changed the honest answer to
or added genuine new evidence for — re-walking all 57 from scratch would
mostly re-confirm Phase 1–3's already-recorded answers.

## What Phase 4 actually changed, pillar by pillar

Three questions were re-answered against the `cerberus-platform` workload
in the Well-Architected Tool, each backed by something Phase 4 concretely
built and verified live this session:

**Reliability / `mitigate-interaction-failure`** — already had "Throttle
requests," "Control and limit retry calls," and "Make systems stateless
where possible" selected. Added **"Set client timeouts"**: every Task
state in `orchestration/state_machine.asl.json.tftpl` carries an explicit
`TimeoutSeconds`, each tuned to its downstream's real behavior rather than
one blanket value — 120s for the ingestion Lambda invoke, 2100s for the
Spark-on-EKS transform task, 900s for the dbt task, 300s for the Athena
serving query. This is the outer safety net against a native integration
or ECS task hanging past its own internal poll-loop bound
(`entrypoint_transform.sh`'s own `SPARK_POLL_MAX_ATTEMPTS`/
`REPAIR_POLL_MAX_ATTEMPTS`), not a value picked once and copied four
times. **Stayed HIGH** — 4 of 7 choices selected isn't enough to move the
bucket, but the same question's already-selected "Control and limit retry
calls" is also materially stronger now: 4.3 made retries per-state and
idempotency-aware rather than blanket — `InvokeIngestion` deliberately has
*no* Retry block (ADR 0005: a Step Functions-level retry would re-invoke
the generator and duplicate unseeded data into append-only bronze, the
exact risk ADR 0005 eliminated one layer down), while `RunTransform`/
`RunDbt` retry twice with backoff because both are fully idempotent
end to end. Recorded in the answer's notes even though it doesn't add a
new checkbox.

**Reliability / `monitor-aws-resources`** — already had "Monitor all
components," "Send notifications," and "Analyze logs" selected. Added
**"Monitor end-to-end tracing of requests through your system"**: 4.3
added X-Ray tracing to the Step Functions state machine, the orchestration
layer's first real distributed trace across Lambda → ECS Fargate
(transform) → ECS Fargate (dbt) → Athena, not just isolated per-component
logs. **Stayed HIGH** — 4 of 8 choices selected, honest partial credit;
aggregated metrics, automated response, and a regular monitoring-scope
review are still absent, correctly Phase 6's job.

**Operational Excellence / `observability`** — already had "Implement
application telemetry" selected (Phase 2's Lambda logging). Added
**"Implement distributed tracing"** — the same X-Ray evidence as above,
answering this pillar's own instrumentation-practice question rather than
Reliability's monitoring one. The two questions ask genuinely different
things about the same infrastructure change (does a fault-detection
practice exist vs. does an engineering practice exist), which is why the
Tool credits the same underlying evidence in both places, same as ADR
0008 crediting the multi-AZ node placement only where it actually applied.
**Stayed HIGH** — 2 of 5 choices selected; KPI dashboards, user-experience
telemetry, and dependency telemetry against external systems are still
Phase 6.

**None of the three moved a risk bucket** — worth stating plainly rather
than glossing over, since ADR 0004/0006/0008 each moved at least one.
Phase 4's real strength (idempotency-aware retries, per-state timeouts,
distributed tracing) landed inside questions that were already
multi-select HIGH/MEDIUM with several boxes checked from earlier phases;
adding one more genuinely-earned box didn't cross whatever threshold the
Tool uses internally. The overall workload risk counts are unchanged from
milestone 3 (25 HIGH / 18 MEDIUM / 9 NONE / 5 N/A) — an honest outcome,
not a sign the pass found nothing.

**Considered, not changed:**

- **Cost Optimization / `select-service`** (already NONE — every choice
  selected) and **`manage-demand-resources`**'s already-selected "Supply
  resources dynamically" — ADR 0009's central bet was that Step
  Functions/Fargate/ECR cost nothing sitting idle, unlike Airflow/MWAA's
  standing infrastructure. 4.4's scoped destroy is real, live confirmation
  of that bet: the orchestration layer was deliberately left standing
  after `terraform destroy` while EKS and the NAT Gateway (the genuinely
  billed pieces) came down, and it cost nothing to leave up. Genuine new
  evidence, but it reinforces choices already credited from Phase 1/2/3's
  own service-selection decisions — no unselected choice in either
  question maps to "confirmed a prior cost decision held under a live
  teardown," so nothing was force-selected.
- **Security / `permissions`** (already MEDIUM, "Grant least privilege
  access" and "Reduce permissions continuously" both selected) — two of
  the six live-discovered bugs were genuine least-privilege gaps:
  `cerberus-orchestration-transform` was missing `glue:GetDatabase` and
  silver bucket read (needed by `MSCK REPAIR TABLE`), and
  `cerberus-orchestration-dbt` never got read access to
  `payments_events`, the dbt source table its models `SELECT FROM`. Both
  are exactly what "reduce permissions continuously" already credits —
  iterative tightening as real needs surface, caught by actually running
  the pipeline (4.4) rather than assumed correct from `plan`/`validate`.
  Real reinforcement of an already-selected choice, not a new one.
- **Operational Excellence / `event-response`** (HIGH, "None of these"
  selected) — the six live-discovered bugs (a security-group description
  charset violation, an unsupported shell flag, a fabricated ASL resource
  ARN, a wrong EventBridge target service name, and the two IAM gaps
  above) were all found and fixed through ad hoc live debugging during
  4.4, not a formal incident/event-management process. Tempting to credit
  "prioritize operational events based on business impact" or "use a
  process for event, incident, and problem management," but there wasn't
  one — each bug was chased down and fixed as it appeared, not triaged
  against a defined process. Staying at "None of these" is the honest
  answer; a real gap at this solo scale, not one Phase 4 closes.
- **Security / `securely-operate`** (HIGH, "Automate deployment of
  standard security controls" already selected) — every one of the six
  live fixes shipped as a Terraform code change, reviewed and applied the
  same way as every other IAM/config edit in this project. Real
  reinforcement, no new checkbox: the choice already credits exactly this
  practice.

## Overall

Milestone 3 (`phase-3-scalable-compute-complete`, 2026-08-18) → milestone 4
(`phase-4-orchestration-complete`, 2026-08-20):

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 3 | 25 | 18 | 9 | 5 |
| Milestone 4 | 25 | 18 | 9 | 5 |

No question moved buckets this pass. Three questions
(`mitigate-interaction-failure`, `monitor-aws-resources`, `observability`)
gained real, specific, live-verified evidence — per-state timeouts tuned
to actual downstream behavior, idempotency-aware retries, and X-Ray
distributed tracing across the full orchestrated pipeline — without
crossing the Tool's internal risk threshold. Consistent with ADR 0008's
`ready-to-support`/`manage-service-limits` precedent: worth recording
honestly rather than padding the diff with a bucket change the evidence
doesn't support.

## Consequences

- Phase 4 is now fully closed — 4.1–4.5 all done.
- The zero-bucket-movement result is itself informative for future
  phases: Phase 4's actual engineering (idempotency-aware retries,
  tuned timeouts, distributed tracing) was real and non-trivial, but it
  landed inside questions Phase 1–3 had already partially answered.
  Phases whose work is more orthogonal to what's already been credited
  (e.g. Phase 5's CI/CD, which opens entirely new Operational Excellence
  and Security ground) are more likely to move buckets than a phase like
  this one that deepens existing practices.
- The six live-discovered bugs (SG description charset, an unsupported
  shell flag, a fabricated ASL resource ARN, a wrong EventBridge target
  service name, and two IAM permission gaps) are the concrete evidence
  behind this pass's Reliability/Security reinforcement — a repeat of
  Phase 3's `ready-to-support` lesson that live verification (4.4) finds
  what `plan`/`validate` structurally cannot.
- Milestone 4 becomes the baseline 5.5's pass diffs against, continuing
  the chain ADR 0004 started.
