# 8. Phase 3 Well-Architected review

Date: 2026-08-18

## Status

Accepted

## Context

Phase 3 — scalable compute — is built and verified live (3.1–3.7 done): ADR
0007's VPC/EKS design was applied for real, a PySpark job ran on the
resulting EKS cluster via the Spark Operator, its output was verified in
silver and the Glue catalog, and the full stack was destroyed cleanly
afterward. Unlike the plan-only state this phase sat in since 2026-08-14,
every claim in this pass is backed by something that actually ran on AWS
this session, not a `terraform plan`.

Per `Phases.md`'s cross-cutting rule, every phase closes with a
Well-Architected pass plus an ADR. Following the diff-based pattern ADR
0004 set up and ADR 0006 continued: milestone 2
(`phase-2-event-driven-ingestion-complete`) is the baseline, and this ADR
only touches the questions Phase 3's actual work changed the honest answer
to — re-walking all 57 from scratch would mostly re-confirm Phase 1/2's
already-recorded answers.

## What Phase 3 actually changed, pillar by pillar

Three questions were re-answered against the `cerberus-platform` workload
in the Well-Architected Tool, each backed by something Phase 3 concretely
built or verified live this session — not a re-read of the same evidence
with a different label:

**Reliability / `fault-isolation`** — already had `use_bulkhead` (the
three-bucket/three-role split) and `single_az_system` (recovery capability
for the NAT Gateway's deliberate single-AZ placement, per ADR 0007's Cost
tradeoff) selected. Added **"Deploy the workload to multiple locations"**:
the EKS managed node group genuinely spans both private subnets —
confirmed live via `kubectl get nodes -o wide`, two `Ready` nodes on
different subnet CIDRs (`10.0.19.90`, `10.0.44.247`) in `us-east-1a` and
`us-east-1b`. This is the compute layer's first real multi-AZ deployment
in this project (Phase 1/2's S3/Lambda are inherently regional, not a
multi-AZ *decision* the way a node group placement is). **This moved the
bucket: HIGH → NONE** — all three non-null choices for this question are
now selected.

**Operational Excellence / `ready-to-support`** — already had
`use_runbooks` and `informed_deploy_decisions` selected. Added **"Use
playbooks to investigate issues"**: today's live pass produced three
genuine playbooks, not runbooks — each is a real investigate-diagnose-fix
sequence for an incident actually encountered, not a routine procedure
written in advance. The Spark Operator's Ivy dependency resolution failing
inside its own `$HOME=/nonexistent` pod, `cerberus-spark`'s missing
Kubernetes RBAC surfacing as a live `Forbidden` error mid-job, and the
NAT-Gateway-before-node-readiness destroy-order failure (`context deadline
exceeded`, traced to both nodes going `NotReady` once NAT was destroyed
underneath them) were all diagnosed live and are now written up in
`checkpoint.md`'s Notes/blockers as reusable investigation guides for the
next person who hits the same symptom. Stayed **HIGH** — 3 of 6 choices
selected isn't enough to move the bucket, and that's honest: personnel
capability and formal Operational Readiness Reviews are still absent,
correctly out of scope for a solo project.

**Reliability / `manage-service-limits`** — was `NONE OF THESE` selected
(the worst state — zero credited awareness). Added **"Be aware of your
default quotas... know which cloud resource constraints... are potentially
impactful"**: the first node-group launch failed outright
(`InvalidParameterCombination`), which prompted checking the actual EC2
On-Demand vCPU quota (`aws service-quotas get-service-quota`, confirmed
healthy at 32) and separately discovering the real constraint — this
18-day-old AWS account is still under AWS's new-account Free-Tier-only EC2
launch restriction, unrelated to any quota number. That constraint is now
durably documented (in `checkpoint.md`'s Notes/blockers and in the `eks`
module's own `node_instance_types` comment) rather than left as
one-session tribal knowledge. Stayed **HIGH** — this was reactive
discovery during a live failure, not the proactive, ongoing quota-review
practice the question is really asking about, so one selected choice out
of seven is an honest partial credit, not a claim of mature quota
management.

**Considered, not changed:**

- **Security / `identities`** — `cerberus-spark`'s IRSA role (OIDC
  federation from the EKS cluster's identity provider to an IAM role via
  `sts:AssumeRoleWithWebIdentity`) is a genuinely new *mechanism* in this
  project — the first identity that's neither a human-assumed role (Phase
  1) nor an AWS-service-principal trust (Phase 2). But the unselected
  choice this would map to, "rely on a centralized identity provider," is
  explicitly scoped to *workforce* identities ("employees and
  contractors") in the Tool's own description — this project has one human
  operator, not a workforce to federate. Same shape as ADR 0006's decision
  on `cerberus-ingestion-lambda`: real new evidence, no matching checkbox,
  not forced.
- **Sustainability / `sus_hardware`** — the `m5.large` → `m7i-flex.large`
  node instance type switch happened to land on a newer, more
  energy-efficient instance family, which is what the unselected choice
  ("continually monitor and use new instance types... for energy
  efficiency") describes. But the switch was driven entirely by the
  Free-Tier launch restriction, not an energy-efficiency evaluation —
  crediting it here would overstate what actually motivated the decision,
  so it's noted rather than selected.
- **Cost Optimization / `manage-demand-resources`, `type-size-number-resources`**
  — Phase 3's whole design *is* "supply resources dynamically" (spin up
  per job, destroy after) and its instance choice *is* "select resource
  type/size... based on data" (headroom for a small Spark driver/executor
  over EKS's own system-pod overhead) — but both choices were already
  selected from Phase 1/2's own service decisions, not newly unlocked by
  Phase 3. No edit forced.

## Overall

Milestone 2 (`phase-2-event-driven-ingestion-complete`, 2026-08-12) →
milestone 3 (`phase-3-scalable-compute-complete`, 2026-08-18):

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 2 | 26 | 18 | 8 | 5 |
| Milestone 3 | 25 | 18 | 9 | 5 |

One question fully resolved (`fault-isolation`, HIGH → NONE — the compute
layer's first genuine multi-AZ deployment). Two more
(`ready-to-support`, `manage-service-limits`) gained real, specific,
live-discovered evidence without crossing the Tool's risk threshold —
worth recording honestly rather than either hiding the non-move or padding
the diff with a bucket change the evidence doesn't support.

## Consequences

- Phase 3 is now fully closed — 3.1–3.8 all done.
- The small diff is the point, not a shortcoming: Phase 3's scope (compute)
  was never going to move Cost Optimization's organizational governance
  questions or Security's workforce-identity questions — those remain
  correctly attributed to later phases and this project's solo-operator
  shape, unchanged from ADR 0004/0006.
- The three live-pass playbooks captured in `checkpoint.md`'s Notes /
  blockers (Ivy cache path, Spark-on-K8s RBAC, NAT/destroy-order) are the
  concrete artifact behind `ready-to-support`'s partial credit — they're
  written to be acted on directly by a future session, not just narrative.
- Milestone 3 becomes the baseline 4.5's pass diffs against, continuing the
  chain ADR 0004 started.
