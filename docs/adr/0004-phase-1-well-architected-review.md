# 4. Phase 1 Well-Architected review

Date: 2026-08-10

## Status

Accepted

## Context

Phase 1's MVP is built and verified (1.1–1.12 done): the medallion pipeline
runs end to end, `terraform apply`/`terraform destroy` were tested live
against real infrastructure (1.11), and a reviewer can run a real Athena
query against gold and get a result (1.10). Per `Phases.md`'s cross-cutting
rule, every phase closes with a Well-Architected pass plus an ADR — this is
that pass for Phase 1.

Two review mechanisms exist in this project, deliberately used at different
times per the 2026-08-05 decision recorded in checkpoint.md:

1. **Pillars as a design lens**, applied directly while writing ADRs 0002
   and 0003 — asking what each pillar has to say about a decision *before*
   building it.
2. **The AWS Well-Architected Tool**, which reviews a workload that already
   exists. At 1.1 there was nothing built yet, so this was explicitly
   deferred to this ADR rather than run against an empty account.

This ADR is the first use of mechanism 2. A workload (`cerberus-platform`,
`us-east-1`, environment `PREPRODUCTION`) was created in the Tool against
the default **AWS Well-Architected Framework** lens — all 57 questions
across the six pillars were answered based on what Phase 1 actually built,
not aspirationally — and the result saved as milestone 1
(`phase-1-mvp-complete`). The **Data Analytics Lens** was deliberately *not*
run as a second Tool pass this round: per the 2026-08-05 decision it's used
as reading material informing judgment calls (as it already did for ADRs
0002/0003), not click-through in the Tool — doubling to ~114 questions for
a project this size would mostly produce overlapping signal. Revisit at
7.4's full formal review if the Framework lens turns out to miss something
analytics-specific.

## Pillar-by-pillar review

Risk counts below are the Tool's own output (`HIGH` / `MEDIUM` / `NONE` /
`NOT_APPLICABLE`, out of each pillar's question count) — not self-assessed.

### Cost Optimization — 5 HIGH / 2 MEDIUM / 3 NONE / 1 N/A (of 11)

**Strong:** the billing alarm + SNS (0.2) is real proactive monitoring, not
theoretical; `Project`/`Phase`/`Layer` tagging is real cost attribution;
ADR 0002's Parquet/compression/partitioning choices were made explicitly
against Athena's per-TB-scanned pricing; the Athena workgroup's
`bytes_scanned_cutoff_per_query` (1.9) is a real throttle; `terraform
destroy` is a genuine, *tested* decommissioning process (1.11), not just a
documented intention.

**Flagged, honestly:** no Cost Explorer/CUR, no budget beyond the $10
alarm threshold, no multi-account cost governance (single account by
design — repaid at 7.3), nothing to right-size yet (no EC2 exists in
Phase 1). These track to Phase 5 (CI/CD cost gates) and 7.5 (cost summary).

### Operational Excellence — 6 HIGH / 4 MEDIUM / 1 NONE (of 11)

**Strong:** this is the pillar the Tool scores hardest and the one this
project is actually best at in substance — `checkpoint.md`/`Phases.md`/
`/end-day` is a real continuous-improvement and status-communication loop;
`docs/notes/day-NN.md` and `article.md` are literal knowledge management
and lessons-learned sharing; git history is small, frequent, reversible
changes; Terraform *is* the configuration management system; 1.11 is real
functional and resiliency testing against live infrastructure, not a
tabletop exercise.

**Flagged, honestly:** most Operational Excellence questions assume an
*organization* — priorities, culture, and support-readiness genuinely don't
have multi-person answers for a solo project, so several read as gaps even
though nothing is broken. Observability and event/incident response are
real, not-yet-built gaps, explicitly Phase 6's job.

### Reliability — 7 HIGH / 3 MEDIUM / 2 NONE / 1 N/A (of 13)

**Strong:** 1.11 *is* this pillar's best evidence — a real backup, destroy,
and restore cycle proved bronze is the one genuinely non-reproducible
layer, and that every job (the generator, the transform, dbt) is
idempotent and full-rebuild by design, not just claimed to be. ADR 0002's
three-bucket, three-role split is a real bulkhead, verified by hand in 1.6
(assumed each role, confirmed denied actions, not just declared policies).

**Flagged, honestly:** no multi-AZ/multi-region (single-location by design
at this stage — VPC/networking is explicitly Phase 3's job), no *automated*
backups (1.11's backup was a deliberate one-off action, not scheduled), no
service-quota monitoring, no formal RTO/RPO. Several component-failure
questions read HIGH partly because there's no standing compute yet to fail
over — most of this sub-area doesn't have a subject until Phase 2/3.

### Performance Efficiency — 3 HIGH / 1 MEDIUM / 1 N/A (of 5)

**Strong:** 1.7 explicitly ruled out Spark in favor of plain Python at this
data volume — a real, reasoned compute decision, not a default; Athena/
Glue/S3 are serverless and auto-scaling with nothing to size; Parquet +
Snappy + `dt=` partitioning were chosen specifically for query performance
and cost per ADR 0002.

**Flagged, honestly:** no performance KPIs, monitoring, or load testing —
nothing to measure yet at synthetic-data scale, but a real gap before this
would hold up under real traffic. Networking is `NOT_APPLICABLE`: no VPC
exists in Phase 1.

### Security — 5 HIGH / 3 MEDIUM / 1 NONE / 2 N/A (of 11)

**Strong:** this project's most mature pillar in substance — root MFA with
no routine root use (0.2); every workload role is assumed via STS for
temporary credentials, never long-lived keys; least-privilege scoped and
*iteratively tightened* across 1.6/1.8/1.9/1.10 as real needs appeared, not
over-provisioned upfront; boundaries verified by hand in 1.6, not just
declared; SSE-S3 + public-access-block + Terraform-enforced encryption on
every bucket; ADR 0003's PII-handling decision means nothing sensitive-
looking is ever generated in the first place — there's no unmasked data to
protect because none exists.

**Flagged, honestly:** no multi-account separation (Phase 0's
`AdministratorAccess` shortcut is deliberately repaid at 7.3, not here), no
incident-response plan, no automated security testing/pipeline (Phase 5),
no centralized log aggregation beyond systemd journal.

### Sustainability — 0 HIGH / 6 MEDIUM (of 6)

**Strong:** the only pillar with zero HIGH-risk items. Serverless-by-default
(S3, Glue, Athena, DynamoDB — all fully managed) means literally minimum
hardware for current demand; weather ingestion's retirement (data purged,
timer/service files removed once superseded, not left running unused) is a
concrete example, not a principle on paper; 1.11's backup-scope decision —
back up only bronze, since everything else is reproducible — is *exactly*
the Tool's own "back up data only when difficult to recreate" best
practice, arrived at independently before this review ran.

**Flagged, honestly:** `us-east-1` was chosen for consistency with Phase
0's existing hand-built resources, not for sustainability — noted
honestly rather than retrofitted as a sustainability decision after the
fact.

## Overall

**26 HIGH / 19 MEDIUM / 7 NONE / 5 NOT_APPLICABLE**, 57 questions, Framework
lens, milestone 1 (`phase-1-mvp-complete`) saved 2026-08-10 in the Well-
Architected Tool (`cerberus-platform` workload, `us-east-1`).

## Consequences

- Phase 1 is now fully closed — this is 1.13's artifact, the last Phase 1
  subtask.
- The HIGH/MEDIUM items aren't a new backlog; nearly all map to work
  already scheduled: observability, event response, and incident response
  → Phase 6; multi-account separation, formal DR objectives, and
  service-quota monitoring → Phase 7 (7.3's least-privilege repay, 7.4's
  full review, 7.5's cost/security summary); automated testing/rollback and
  pipeline security assessment → Phase 5 (no CI/CD exists yet); the
  compute-sizing and networking questions marked `NOT_APPLICABLE` become
  real once Phase 2's Lambda and Phase 3's EKS/VPC exist.
- Milestone 1 is the baseline every later phase's Well-Architected pass
  (2.6, 3.8, …) diffs against — that diff, not a single point-in-time
  score, is the actual portfolio artifact: evidence the platform's risk
  posture is improving, not just growing.
- The Data Analytics Lens stays deferred as Tool click-through. If 7.4's
  full review surfaces an analytics-specific gap the Framework lens
  couldn't catch, that's the trigger to add it as a second lens — not a
  default assumption going in.
