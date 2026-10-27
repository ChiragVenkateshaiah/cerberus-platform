# 23. Phase 8 Well-Architected review

Date: 2026-10-27

## Status

Accepted (2026-10-27). The build and the full note texts are in
[the plan](../plans/2026-10-27-phase-8-well-architected-review.md).

## Context

Phase 8 (scale validation) is done except for the 8.10 demo video, which
moves to 31 October or 1 November. 8.11 is the last other open subtask. This
review records Phase 8 against the Well-Architected Framework in one place
before Phase 9 starts.

**What Phase 8 built.** Subtasks 8.1 to 8.9 are done, each with its PRs. 8.10
is half done: the results write-up is in draft PR #107 and the video is not
recorded. The phase thesis is in `docs/plan.md` (Phase 8, "Thesis"): apply
real load, and find what it breaks.

**Baseline.** The baseline is milestone 7
(`phase-7-end-to-end-validation-complete`, 2026-09-29), at 23 HIGH, 19
MEDIUM, 10 NONE, 5 N/A. The workload has not changed since: `list-workloads`
on 2026-10-27 shows `UpdatedAt` 2026-09-29. No answer
changed during Phase 8.

**Why this pass is not like Phase 7's.** ADR 0015 reviewed 7.1-7.3, which built little new. Phase 8
built compute, scaling and cost machinery: Spark executors on a Spot node
group, Cluster Autoscaler, a bulk generator, Iceberg tables, a per-run
metrics collector and a local Grafana view on AMP with a Spark progress exporter (ADR 0022). Many answers were written in
Phase 1 and still say "no EC2 exists yet". They are out of date, so the notes
are rewritten in full (one sentence kept for each earlier phase).

**Decisions made in the phase.** One line each:

- ADR 0017: Iceberg tables and incremental processing (anti-join plus append).
- ADR 0018: bulk events land in bronze as JSON Lines under `payments_bulk/`.
- ADR 0019: keep the ECS wrapper for Spark submission, with stated triggers.
- ADR 0020: an On-Demand system group, a Spot executor group and Cluster Autoscaler.
- ADR 0021 (Phase 10.1, written during Phase 8): pipeline status and alerting on AMP.
- ADR 0022: a local Grafana on AMP for the recorded run.

**Two earlier amendments, checked against the code.** This ADR confirms them
and amends nothing.

- *ADR 0018, "each run ends with a `_manifest.json`".* The manifest is
  written in `transform/spark/generate_bulk_payments.py` (L358-391), and the
  table `bronze_payments_bulk_by_run` is in
  `terraform/modules/glue_catalog/main.tf` (L181). The "ladder as run" text
  is in the ADR's Decision.
- *ADR 0020, "what was built differs in three places".* The executor group
  has `min_size = desired_size = var.executor_desired_size`
  (`terraform/modules/eks/main.tf` L211-213; default 1, max 4, in
  `variables.tf` L40-49). `day_cost` in
  `observability/scale/collect_run_metrics.py` (L291-309) still filters on
  REGION. Spot fallback to fewer executors was not measured. One stale line
  remains in code, not in the ADR: the `day_cost` docstring (L295) still says
  the EKS node instances are untagged, which has been false since #92. It is
  in the follow-ups.

ADR 0017's anti-join plus append is recorded in its "Implementation notes
(2026-10-08, 8.5)", so it needs no amendment. ADR 0016's Status already names
ADR 0022's amendment.

**The `--full` audit.** `observability/scale/audits/dq-full-20261015.json`
passed: 20 checks, 0 errors, 1 warning, 181,519,149,564 bytes scanned in 22.9
s. Bronze and silver both held 137,113,940 events, and bronze was
59,319,544,643 bytes by S3 listing. The audit ran before the 1M rehearsal and
before the 100M take, so its scope is data up to 137.1M events.

**Decision 1 (user, 2026-10-27): milestone 8 cites this audit.** There is no
`--full` re-run after the take. This is a deliberate departure from the rule
in `observability/scale/data_quality.py` (L42-43 and L277-279): "run it before
each milestone". A re-run at about 239M events would scan about 316 GB (about
$1.6, a linear estimate from 181.5 GB at 137.1M). It would also need the data
quality cutoff raised and restored again, as in #103 and #104. Each new run
is already checked in full while it is new, in ledger mode. The cheaper
milestone audit is a planned follow-up: `docs/plan.md`, "A milestone audit
that does not re-read all of bronze".

**Decision 2 (user, 2026-10-27): the answers now, the milestone later.** The
ADR and the answer updates happen now. Milestone 8 is saved in a small
close-out PR after the video. Milestones cannot be edited, so a milestone
named "complete" taken before the phase is complete would be frozen if the
rehearsal or the take changed anything. The cost is that for about a week the
live workload is ahead of the last milestone. That is harmless, because a
milestone snapshots whatever is current when it is created.

**Results so far, from the run records** (`observability/scale/runs/`):

| Step | Run | Status | Run time | Run cost | Per million events | Checks |
|---|---|---|---|---|---|---|
| 1M | `exercise-20261015T145812Z` | SUCCEEDED | 581.2 s | $0.2945 | $0.2928 | 26 |
| 10M | `exercise-20261009T074853Z` | SUCCEEDED | 522.8 s | $0.1012 | $0.0112 | 18 |
| 100M | `exercise-20261013T055859Z` | SUCCEEDED | 742.0 s | $0.3657 | $0.0037 | 26 |

The 100M run processed 100,008,511 new events. The Spot interruption test
(`exercise-20261012T133620Z`) also SUCCEEDED, with data quality passed. At 1M
the RunDbt state spent 230.5 s in Athena queue time
(`exercise-20261015T145812Z.json`, `queue_seconds` per state), the finding
behind #105.

**Pillars that decide.** Reliability and Operational Excellence favour a
milestone that matches what was shipped, so after the video. Operational
Excellence (flow of work) favours doing the review now. Decision 2 meets both.

## What Phase 8 changed, pillar by pillar

These are the answer changes made on 2026-10-27. The 15 `update-answer`
commands all succeeded, so the live `UpdateAnswer` grant of `cerberus-admin`
is verified. The Tool decides the buckets; the result below is from
`get-lens-review`, read the same day (workload `UpdatedAt`
2026-10-27T00:28:38Z). The full selected sets and note texts are in section 9
and section 12 of the plan. The bucket shown in brackets in the lists below is
the bucket before the update.

**Moved a bucket**

- HIGH to MEDIUM: `type-size-number-resources`, `compute-hardware`,
  `data-management`.
- HIGH to NONE: `manage-demand-resources`, `monitor-usage`.
- MEDIUM to NONE: `adapt-to-changes`, `process-culture`,
  `performing-architecture`, `evolve-ops`.

**Gained evidence, stayed in the same bucket:** `govern-usage` (HIGH),
`manage-service-limits` (HIGH), `withstand-component-failures` (HIGH),
`pricing-model` (MEDIUM). `testing-resiliency` (HIGH) and `permissions`
(MEDIUM) got a note only.

### New evidence, by pillar

**Cost Optimization**

- `type-size-number-resources` (HIGH): add cost modeling (the 1M, 10M and
  100M ladder priced per million events) and automatic sizing on metrics
  (Cluster Autoscaler, Spark dynamic allocation).
- `pricing-model` (MEDIUM): add "implement pricing models for all
  components": Spot executors, an On-Demand driver, pay-per-use elsewhere
  (ADR 0020).
- `manage-demand-resources` (HIGH): add the demand analysis. The executor
  count is planned from the event count (`exercise.sh --executor-nodes`).
- `monitor-usage` (HIGH): add a detailed source (Cost Explorer by service and
  usage type, in the collector), a KPI (cost per million events) and
  allocation to a workload metric. The caveat is stated in the note: cost is
  scoped by region, and EKS cluster-hours read low.
- `govern-usage` (HIGH): add goals and targets. AWS Budgets alerts at $15 and
  $20 (Phases.md 8.2) and a $0 idle target.

**Performance Efficiency**

- `compute-hardware` (HIGH): add compute metrics (Prometheus on AMP) and
  right-sizing (8.6: 1 x 1 GB to 2 x 2 GB executors, RunTransform 323.3 s to
  241.6 s, -25%).
- `data-management` (HIGH): add data-store performance metrics (Athena engine
  and queue seconds per state, #105; Iceberg file counts at compaction).
- `process-culture` (MEDIUM): add **load test**. ADR 0015 declined it because
  Phase 7's volume bump was not a ramp toward a limit. Phase 8 is that ramp,
  and it found the limits: the Athena cutoffs were raised for 10M and again
  for 100M. Also add a process to improve performance (8.6 changed one thing
  at a time and measured each).
- `performing-architecture` (MEDIUM): add benchmarking (ADR 0018's local
  out-of-memory table, 8.6's before and after).

**Reliability**

- `adapt-to-changes` (MEDIUM): add reactive (the Auto Scaling group replaced
  the interrupted Spot node, with new nodes Ready in about 40 s), proactive
  (the autoscaler acts on pending executors) and load tested.
- `manage-service-limits` (HIGH): add "accommodate fixed quotas through
  architecture": the executor maximum of 16 vCPU sits inside the 32 vCPU Spot
  quota, and a separate data quality workgroup has its own cutoff.
- `withstand-component-failures` (HIGH): add "fail over to healthy
  resources". In the FIS test 4 executors were decommissioned gracefully, 2
  tasks re-ran and data quality passed (`docs/scale-metrics.md`, "Spot
  interruption test").
- `testing-resiliency` (HIGH): note only. The FIS test reinforces chaos
  engineering, which is already selected.

**Operational Excellence**

- `evolve-ops` (MEDIUM): add operations metrics reviews. Every run has a
  record, and the 2026-10-15 close-out review of those records found the
  Athena double count (#102).

### Considered, not changed

- **Cost Optimization:** "quantify business value" and "keep up to date with
  new releases": the evidence is weak.
- **Performance Efficiency:** automated remediation. Alarms notify only.
- **Reliability:**
  - Quota monitoring and automation: quotas are known and designed around,
    not monitored.
  - Automated healing on all layers: the Spark driver is a single pod and
    there is one NAT gateway.
  - Graceful degradation: "falls back to fewer executors" was not measured
    (ADR 0020).
- **Operational Excellence:** `observability`, `ready-to-support` and the
  three organisational HIGHs (`priorities`, `ops-model`, `org-culture`) are
  unchanged. They measure a team and a support structure a solo project does
  not have.
- **Security:** the new grants are all scoped: `cerberus-spark` may delete
  only under `payments_bulk/` (`terraform/modules/iam_spark/main.tf`); the
  Cluster Autoscaler role and the FIS role are limited by resource tag; and
  `cerberus-admin` gained a read-only CloudWatch metrics grant through the
  root-console path (`iam/cerberus-admin/README.md`, 2026-10-25).
  - `permissions` gets a note only.
  - `identities` stays HIGH: access keys are still not rotated, and static
    admin keys are now also mounted into the local Grafana (ADR 0022).
  - `detect-investigate-events` is unchanged: `aws cloudtrail
    describe-trails` returns `[]` (checked 2026-10-27), so there is still no
    trail.
- **Sustainability:** no answer changes. Spot executors and scale-down help.
  Against that, the executor minimum equals desired size, so the planned nodes
  stay up between the apply and the job, and the data quality scans and the
  dbt merge re-read the whole of silver each run. Graviton was never
  evaluated: there is no arm64 evaluation in `docs/` or `terraform/`, and the
  executor types are x86 4 vCPU / 16 GiB (`terraform/modules/eks/variables.tf`
  L34-37).
- **Data Analytics Lens:** not applied. It would be a new lens review and
  would break milestone-to-milestone comparison. It is a Phase 9 or later item.
- **Workload description:** it still says "Phase 1 MVP reviewed here; Phase 7
  is the full formal review". `cerberus-admin` cannot change it: the
  `WellArchitected` statement in
  `iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`
  (L94-107) has no `UpdateWorkload`. Fixing a cosmetic field would need a
  root-console policy change, so it is a follow-up.

### The central finding

Phase 8's increments are incremental in Spark but not in Athena. The dbt
merge and the data quality checks grow with total silver, not with the batch.

- At 1M the data quality scan read 62,601,816,228 bytes
  (`exercise-20261015T145812Z.json`). At $5 per TB that is about $0.31
  (computed, not posted), which is more than the run itself ($0.2945). The
  TB vs TiB question is still open from the 2026-10-15 review.
- The planned 100M take leaves silver at about 239M events. The dbt merge
  then reaches about 21.0 GiB (about 84% of the 25 GiB shared cutoff) and the
  largest data quality check about 13.6 GiB (about 68% of the 20 GiB cutoff).
  Sources: `docs/demo-recording.md` L104-111 and ADR 0022's follow-ups.
  ADR 0022 says "about 83%"; that is its own earlier estimate, and this
  ADR uses the later `docs/demo-recording.md` figure.
- A second 100M would bring the dbt merge to about 29.8 GiB, over the cutoff.
  So there is no retake after the generator starts.

The cause is that the realistic time spread (`docs/plan.md`, Planned later
work) was never built, and the data quality checks are not incremental.

## Overall

Milestone 7 (`phase-7-end-to-end-validation-complete`, 2026-09-29) to the
workload after the 8.11 answers:

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 7 | 23 | 19 | 10 | 5 |
| Workload after the 8.11 answers (2026-10-27) | 18 | 18 | 16 | 5 |

By pillar, HIGH / MEDIUM after the updates (milestone 7 HIGH in brackets):

| Pillar | HIGH | MEDIUM |
|---|---|---|
| Operational Excellence | 6 (6) | 2 |
| Security | 5 (5) | 3 |
| Reliability | 5 (5) | 3 |
| Performance Efficiency | 0 (2) | 2 |
| Cost Optimization | 2 (5) | 2 |
| Sustainability | 0 (0) | 6 |

Nine questions moved a bucket. The moves are in Cost Optimization, Performance
Efficiency, Reliability and Operational Excellence, where Phase 8 built new
compute, scaling and cost machinery. Security and Sustainability did not
move.

Milestone 8 (`phase-8-scale-validation-complete`) is not saved yet. It is
saved in the close-out PR after the 8.10 video (Decision 2). The
`UpdateAnswer` grant is verified by the run above; `CreateMilestone` has not
been tried.

## Consequences

Each item names the owning phase where one exists.

1. The shared workgroup is at about 83-84% of 25 GiB after the take, and the
   next 100M fails dbt. The data quality cutoff of 20 GiB holds about one more
   100M. Do not retake after `[generate] done`.
2. Make the data quality checks incremental. The scan now costs more than a
   1M run.
3. A read-only Grafana role (9.2). Remove the in-cluster Grafana (9.1).
4. The generator commit took 875 s with no Spark job running
   (`docs/plans/2026-10-25-run-story-dashboard.md`). The cause, S3A rename,
   is inferred. Test the S3A "magic" committer (`spark-hadoop-cloud`), which
   ADR 0018 deferred.
5. Size dynamic allocation to the input: Spark asked for 16 executors at 1M
   events with almost no speed-up.
6. Still open from the 2026-10-15 review: bytes written are not measured;
   Athena computed against posted cost ($0.61 against $0.574, TB vs TiB,
   unverified); about 1,706 s of apply, waits and destroy is not attributed;
   EKS cluster-hours read low.
7. The ingestion Lambda retires on 2026-10-30
   (`terraform/modules/lambda_ingestion/variables.tf` L11-15). After that,
   `handler.py` (L60-67) returns `{"status": "retired"}` with no error, and
   `terraform/modules/step_functions/` has no `Choice`, `ResultPath` or
   `ResultSelector`. So InvokeIngestion succeeds as a no-op and the daily
   orchestrated path adds no data. This is from reading the code, not from a
   run.
8. Stale docs, fixed in a separate small docs PR: `docs/plan.md` L529 says
   "the 17 checks" (runs record 26 at 100M and 1M and 18 at 10M; the count
   varies with the generated days); `docs/slo.md` L176 and `docs/lineage.md`
   L230 give `RETIRE_ON_OR_AFTER=2026-08-17` where the real value is
   2026-10-30; and the `day_cost` docstring (L295) says "untagged".
9. The workload description is stale and needs `UpdateWorkload` (see above).
10. The Data Analytics Lens is not applied.
11. A value checksum, and the cheaper milestone audit (`docs/plan.md`,
    Planned later work).
12. `use_lockfile` for Terraform state locking.
13. `BatchGetQueryExecution` is missing from `cerberus-admin`.
14. There is still no CloudTrail trail.

**Close-out, after the video.** In a small PR: 8.10 closes (draft PR #107
merged), the user runs `create-milestone` for
`phase-8-scale-validation-complete`, and a dated "Milestone 8" line with the
Tool's counts is added here. If the take changed any answer, `update-answer`
runs before the milestone. Then 8.10 and 8.11 are checked, Phase 8 is marked
done in `Phases.md`, and the `docs/plan.md` roadmap row and the README are
updated.
