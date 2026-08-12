# 6. Phase 2 Well-Architected review

Date: 2026-08-12

## Status

Accepted

## Context

Phase 2 — event-driven ingestion — is built and verified (2.1–2.5 done):
the Lambda ingestion function and its EventBridge Scheduler trigger run on
managed infrastructure now, the Lambda's own least-privilege IAM role was
built and verified in 1.6's pattern, ADR 0005 records the push-vs-pull
decision, and this session confirmed the scheduler fires genuinely
unattended (2026-08-12T00:00 UTC, no manual trigger, 8 partitions written)
before retiring `cerberus-payments.timer` — the last Phase 0 systemd
ingestion path.

Per `Phases.md`'s cross-cutting rule, every phase closes with a
Well-Architected pass plus an ADR. Unlike 1.13 (ADR 0004), which was the
Tool's first-ever pass and so answered all 57 questions from a blank
workload, this pass is the diff 1.13 explicitly set up: milestone 1
(`phase-1-mvp-complete`) is the baseline, and this ADR only touches the
questions Phase 2's actual work changed the honest answer to — re-walking
all 57 from scratch would mostly re-confirm Phase 1's already-recorded
answers.

## What Phase 2 actually changed, pillar by pillar

Three questions were re-answered against the `cerberus-platform` workload
in the Well-Architected Tool, each backed by something Phase 2 concretely
built or verified — not a re-read of the same evidence with a different
label:

**Operational Excellence / `observability`** — was `NONE OF THESE`
selected (HIGH). Added **"Implement application telemetry"**: the Lambda
emits structured log lines to CloudWatch on every invocation (run start,
per-partition upload, completion count) — genuinely queryable
(`aws logs tail`), not local-only text. This was exercised for real this
session, not just described: the unattended-fire confirmation that
justified retiring the systemd timer was read directly out of these logs.
Stayed **HIGH** — one selected choice out of six isn't enough for the Tool
to move the bucket, and that's honest: KPI identification, dependency
telemetry, and distributed tracing are all still absent, correctly
deferred to Phase 6.

**Reliability / `fault-isolation`** — already had `use_bulkhead` selected
(HIGH) for ADR 0002's three-bucket/three-role split. Added **"Automate
recovery for components constrained to a single location"**: the systemd
timer's dependency on the operator's own login session was a real
single-location failure mode, not a theoretical one — `Persistent=true`'s
catch-up behavior fired an unprompted run at 04:41 UTC this very morning,
live evidence of exactly the fragility ADR 0005 named as motivation for
moving off it. The EventBridge Scheduler → Lambda path has no such
dependency; it fires whether or not any machine is logged in, confirmed
directly (2026-08-12T00:00 UTC). Also stayed **HIGH** — the data plane
itself (S3, one region) is still single-location by design, correctly
Phase 3's job, and that larger gap dominates the question's risk.

**Cost Optimization / `select-service`** — added **"Perform cost analysis
for different usage over time"**: ADR 0005 (2.4) priced the EventBridge/
Lambda path at 10 vs. 30 days against real measured data rates (~283 KB / 8
S3 PUTs per daily run) before deciding to keep the 10-day retirement cap —
negligible either way (~$0.0004 vs. ~$0.0014 total), so the cap stayed on
data-volume grounds, not cost, but the *analysis itself* is exactly this
best practice. This one **did move**, MEDIUM → **NONE** — five of seven
choices were already selected from Phase 1's service decisions (1.7's
Spark-vs-Python call, ADR 0002's Parquet choice, Terraform's licensing
awareness), and this was the missing one.

**Considered, not changed:** `permissions` (Security) and `identities`
(Security) both gained real new evidence this phase — a fourth IAM role,
`cerberus-ingestion-lambda`, the first in this project trusted by an AWS
service principal (`lambda.amazonaws.com`) rather than assumed by a human
via `sts:AssumeRole` — but it's the same least-privilege pattern already
credited via `sec_permissions_least_privileges` and
`sec_identities_unique`, not a new capability the Tool has a distinct
checkbox for. Recorded here rather than forced into an answer edit that
wouldn't reflect a genuinely new choice.

## Overall

Milestone 1 (`phase-1-mvp-complete`, 2026-08-10) → milestone 2
(`phase-2-event-driven-ingestion-complete`, 2026-08-12):

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 1 | 26 | 19 | 7 | 5 |
| Milestone 2 | 26 | 18 | 8 | 5 |

One question net-improved (`select-service`, MEDIUM → NONE). Two more
(`observability`, `fault-isolation`) gained real, specific evidence without
crossing the Tool's risk threshold — worth recording honestly rather than
either hiding the non-move or padding the diff with a bucket change the
evidence doesn't support.

## Consequences

- Phase 2 is now fully closed — 2.1–2.6 all done.
- The small diff is the point, not a shortcoming: Phase 2's scope (an
  ingestion trigger swap) was never going to move Operational Excellence's
  organizational questions or Reliability's multi-AZ gap — those remain
  correctly attributed to Phase 6 and Phase 3 respectively, unchanged from
  ADR 0004.
- Milestone 2 becomes the baseline 3.8's pass diffs against, continuing the
  chain ADR 0004 started.
- Two mechanisms writing to bronze in parallel (noted as a live risk in
  checkpoint.md since 2026-08-11) is resolved as of this session —
  `cerberus-payments.timer` is disabled and unlinked, and the EventBridge
  Scheduler → Lambda path is bronze's only ingestion mechanism.
