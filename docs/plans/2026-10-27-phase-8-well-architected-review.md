# Phase 8 Well-Architected pass + ADR 0023 (8.11)

Date: 2026-10-27. Branch: `decision-phase-8-well-architected-review` from `main` (55e13b3). Docs only. $0. The only AWS writes are Well-Architected Tool writes, and the user runs them.

**User decisions (2026-10-27):** (1) milestone 8 cites the 2026-10-15 `--full` audit (data to 137.1M); no re-run after the take; ADR 0023 names this as a deliberate departure from the "run `--full` before each milestone" docstring rule. (2) Option B: ADR and answer updates now; milestone 8 is saved in a small close-out PR after the weekend video.


## 1. Question

How should Phase 8 be recorded against the Well-Architected Framework, and when should milestone 8 be saved, given that 8.10's video moves to 31 Oct / 1 Nov? This is needed now because 8.11 is the last open subtask besides the video. It is also the last chance to record the Phase 8 follow-ups in one place before Phase 9 starts.

## 2. Facts

**WA Tool (read-only, run 2026-10-27, `AWS_PROFILE=cerberus-admin`, us-east-1)**
- Workload `cerberus-platform`, id `58c236e2c7844375965d22349b460084`. Lens `wellarchitected` only, version 2025-02-25. `UpdatedAt` is 2026-09-29: no answer has changed during Phase 8.
- Current counts: 23 HIGH / 19 MEDIUM / 10 NONE / 5 N/A out of 57. Improvement items: 23 HIGH, 19 MEDIUM.
- HIGH per pillar: OE 6, Security 5, Reliability 5, Performance 2, Cost 5, Sustainability 0. Sustainability has 6 MEDIUM.
- Milestones 1 to 7 exist. Milestone 7 is `phase-7-end-to-end-validation-complete` (2026-09-29, 23/19/10/5). Milestone 6 is `phase-6-observability-and-data-quality-complete` (2026-09-07, 23/19/10/5). The baseline for this pass is **milestone 7**.
- The workload description is stale ("Phase 1 MVP reviewed here; Phase 7 is the full formal review"). `cerberus-admin` cannot fix it: `iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json` (Sid `WellArchitected`, L94-107) has no `UpdateWorkload`.
- That policy allows `UpdateAnswer`, `CreateMilestone`, `GetAnswer`, `ListAnswers`, `GetLensReview`, `ListMilestones`, `ListLensReviewImprovements`, `GetWorkload` and `GetMilestone` on the workload, plus `ListWorkloads` on `*`. The reads worked. The live write grant is **unverified**: `iam:GetPolicy` is denied, and the writes were not tried.
- Several notes still describe Phase 1, for example "No EC2 exists in Phase 1" on `compute-hardware`, `type-size-number-resources`, `withstand-component-failures` and `adapt-to-changes`.
- Notes have a 2,084-character limit. `process-culture` already uses 1,395.
- CloudTrail: `aws cloudtrail describe-trails` returns `[]`. There is still no trail.

**Phase 8 evidence (repo)**
- Run records in `observability/scale/runs/`:

  | Step | Run | Status | Run time | Run cost | Per million events | Checks | DQ scan |
  |---|---|---|---|---|---|---|---|
  | 1M | `exercise-20261015T145812Z` | SUCCEEDED | 581.2 s | $0.2945 | $0.2928 | 26 | 62,601,816,228 B |
  | 10M | `exercise-20261009T074853Z` | SUCCEEDED | 522.8 s | $0.1012 | $0.0112 | 18 | not used |
  | 100M | `exercise-20261013T055859Z` | SUCCEEDED | 742.0 s | $0.3657 | $0.0037 | 26 | 105,900,636,636 B |
  | Spot interruption | `exercise-20261012T133620Z` | SUCCEEDED | not used | not used | not used | DQ passed | not used |

  Two more 100M facts: 100,008,511 new events, and a peak of 10,370 Prometheus series.
- At $5/TB, the 1M run's data-quality scan costs about **$0.31**, which is more than the run itself. This is computed, not posted. The TB vs TiB question is still open from the 2026-10-15 review.
- `--full` audit, `observability/scale/audits/dq-full-20261015.json`: passed, 20 checks, 0 errors, 1 warning, 181,519,149,564 bytes scanned, 22.9 s. Bronze was 59,319,544,643 B by S3 listing, and bronze = silver = 137,113,940.
- The `--full` rule is in `observability/scale/data_quality.py` L42-43 and L277-279: "run it before each milestone".
- ADR 0018's amendment holds in the code. The manifest is written at `transform/spark/generate_bulk_payments.py` L358-391, and `bronze_payments_bulk_by_run` is at `terraform/modules/glue_catalog/main.tf` L181. The 2026-10-15 "ladder as run" text is in its Decision.
- ADR 0020's amendment holds in the code. Executors use `min_size = desired_size = var.executor_desired_size` (`terraform/modules/eks/main.tf` L211-213, default 1, max 4, `variables.tf` L40-49). `day_cost` filters on REGION (`observability/scale/collect_run_metrics.py` L291-309). Its docstring L295 still says "the EKS node instances are untagged", which is stale since #92.
- ADR 0017's anti-join plus append is recorded in its "Implementation notes (2026-10-08, 8.5)". No new amendment is needed.
- ADR 0016's Status already names ADR 0022's amendment.
- Athena cutoffs in `terraform/modules/athena/variables.tf` L12-21: 26843545600 (25 GiB) and 21474836480 (20 GiB). Matches the caller's live read on 2026-10-26.
- Planned 100M take, from `docs/demo-recording.md` L106-110 and L498-500 and `docs/plans/2026-10-26-recording-runbook.md` L20 and L136:
  - Silver goes to about 239M.
  - The dbt merge reaches about 21.0 GiB (about 84% of 25 GiB; ADR 0022 L245 says "about 83%").
  - The largest DQ check reaches about 13.6 GiB (about 68% of 20 GiB).
  - A second 100M would bring the dbt merge to about 29.8 GiB, over the cutoff. So there is no retake after the generator starts.
- The generator commit took 875 s (`Elapsed time: 875397 ms`) with no Spark job running (`docs/plans/2026-10-25-run-story-dashboard.md` L20). The cause, S3A rename, is inferred. ADR 0018's Consequences already deferred the committer choice ("magic" committer, `spark-hadoop-cloud`).
- `docs/plan.md` L529 says "the 17 checks". Runs record 26 at 100M and 1M, and 18 at 10M. The count varies with the generated days.
- `docs/slo.md` L176 and `docs/lineage.md` L230 still say `RETIRE_ON_OR_AFTER=2026-08-17`. The real value is 2026-10-30 (`terraform/modules/lambda_ingestion/variables.tf` L11-15).
- Ingestion after 2026-10-30:
  - `ingestion/lambda/handler.py` L60-67 returns `{"status": "retired"}` with no error.
  - `terraform/modules/step_functions/` has no `Choice`, `ResultPath` or `ResultSelector`.
  - So InvokeIngestion succeeds as a no-op. This is **confirmed by code read, not run**. The take then gets 0 Lambda events, so silver's `payments/` count is unchanged.
- No Graviton or arm64 evaluation exists anywhere in `docs/` or `terraform/` (grep). Executor types are x86 4 vCPU / 16 GiB (`terraform/modules/eks/variables.tf` L34-37).
- Draft PR #107 (`phase-8-10-results`) is open. It changes only README, `docs/scale-metrics.md`, `docs/img/scale/*` and `observability/scale/charts.py`. The section "Results: 1M, 10M and 100M (8.10)" is **not on main**.

**From the caller (not re-run by me)**
- `make exercise-check` passed on 2026-10-26.
- The dev-compute plan was "44 to add, 0 to change, 0 to destroy".

## 3. Constraints

- $0 for this work. WA Tool calls are free. No idle resources. No `dev-compute` apply. CI applies `dev-standing` only, and nothing here touches Terraform.
- 8.10 stays open. This work must not flip Phase 8, plan.md's roadmap row (L148) or README. `checkpoint.md` is edited only by `/end-day`; its "ADR 0022" for 8.11 at L250 is stale and stays as is.
- Phases.md's cross-cutting rule says 8.11 is checked only when both the ADR and the milestone `phase-8-<slug>-complete` exist. plan.md's Phase 8 artifact names "Well-Architected milestone 8".
- WA Tool writes (`update-answer`, `create-milestone`) are the user's commands, run after the ADR is accepted.
- Must not contradict ADRs 0017-0022. It confirms the 0018 and 0020 amendments and amends nothing.

## 4. Options (when the answers change and when milestone 8 is saved)

**A. Do everything now.** Write ADR 0023, update the answers, and save milestone 8 now; close 8.11 after the video.
- Cost: $0, about 1 h of the user's time.
- Gives up: the milestone named "complete" is taken before the phase is complete. If the rehearsal or the take changes anything (a failed take, the exporter proven live or not), milestone 8 is already frozen. Milestones cannot be edited, so it would take a milestone 9 or an erratum.

**B. ADR and answers now, milestone after the video (recommended).**
- ADR 0023 Proposed now. After acceptance, the user runs the `update-answer` commands. The Tool's new counts are read back (read-only) and written into the ADR, which then merges as Accepted.
- Milestone 8 is saved in a small close-out PR after the video, together with checking 8.10/8.11, the plan.md row and README.
- Cost: $0. Effort: one ADR PR plus one small close-out PR.
- Gives up: for about a week the live workload is ahead of the last milestone. That is harmless, because milestones snapshot whatever is current when they are created.

**C. Wait for the video for everything.**
- Cost: $0.
- Gives up: momentum. The user asked to continue now. The evidence is complete already: plan.md's "Done when" was met on 2026-10-13/15.

Pillar notes that decide between these: Reliability and Operational Excellence favour a milestone that matches what was shipped (B, C). Operational Excellence (flow of work) favours doing the review now (A, B). B satisfies both.

**Not chosen, for any option:**
- Adding the Data Analytics Lens. It is a new lens review, would break milestone-to-milestone comparison, and is better as a Phase 9+ item.
- Updating the workload description. It needs `UpdateWorkload`, which means a root-console policy change for a cosmetic field. Record it as a follow-up.

## 5. Recommendation

**Option B.** It records the review while the evidence is fresh and keeps the milestone honest. It also matches what the caller asked for: 8.11 closes in a small follow-up after the video.

**On the `--full` audit:** cite the 2026-10-15 audit as milestone 8's audit, and do not re-run it after the take. This is open question 1. The reasons:
- A re-run at about 239M is about 316 GB, about $1.6. This is a linear estimate from 181.5 GB at 137.1M.
- It needs the DQ cutoff raised and restored again, as in #103/#104.
- Each new run is already checked in full when it is new, in ledger mode.

The ADR must name this as a deliberate departure from the docstring rule and point to plan.md's "A milestone audit that does not re-read all of bronze".

## 6. ADR outline

**File:** `docs/adr/0023-phase-8-well-architected-review.md`.
**Title:** "# 23. Phase 8 Well-Architected review".
**Date:** 2026-10-27. **Status:** Proposed.

Use the same shape as ADR 0014/0015: Context; "What Phase 8 changed, pillar by pillar" with "Moved a bucket" filled after the Tool runs, "New evidence, no bucket move" and "Considered, not changed"; Overall table; Consequences; Follow-ups. Pillar walkthrough sections are right here, because this is a review ADR (checkpoint L3578-3580). Every number needs a source path. Do not link a heading in `docs/scale-metrics.md` that exists only on #107; name "draft PR #107" instead.

**Context**
- Phase 8 thesis (plan.md L256-266). Subtasks 8.1-8.9 done with PRs. 8.10: write-up in draft #107, video on 31 Oct / 1 Nov.
- Baseline is milestone 7 (2026-09-29, 23/19/10/5). The workload has not changed since then (read 2026-10-27).
- Unlike Phase 7, Phase 8 built new compute, scaling and cost machinery. Many answers written in Phase 1 ("no EC2 yet") are now out of date.
- ADRs 0017-0022 made in the phase, with one line each.
- Amendments confirmed against code: ADR 0018 (manifest, by-run table, ladder as run) and ADR 0020 (executor min = `--executor-nodes`, cost still by region, Spot fallback unmeasured). Cite the paths in section 2.
- The `--full` audit (record path, numbers) and its scope: data up to 137.1M, before the 1M run and the take. State the user's decision from open question 1.
- 8.10 results so far, from the run records: the ladder table in section 2, and the RunDbt queue-time finding (230.5 s at 1M).

**Pillar walk.** These are proposed answer changes. The Tool decides the buckets.
- **Cost Optimization**
  - `type-size-number-resources` (HIGH): add cost modeling (the 1M/10M/100M ladder priced per million events) and automatic sizing on metrics (Cluster Autoscaler, Spark dynamic allocation).
  - `pricing-model` (MEDIUM): add "implement pricing models for all components" (Spot executors, On-Demand driver, pay-per-use elsewhere; ADR 0020).
  - `manage-demand-resources` (HIGH): add the demand analysis (executor count planned from the event count, `--executor-nodes`).
  - `monitor-usage` (HIGH): add detailed sources (Cost Explorer by service and usage type in the collector), KPIs ($/M events) and allocation by workload metric. Caveat: scoped by region, and EKS hours read low.
  - `govern-usage` (HIGH): add goals and targets ($20 Budget with alerts, $0 idle).
  - Declined: quantify business value; "keep up to date with new releases" (weak evidence).
- **Performance Efficiency**
  - `compute-hardware` (HIGH): add compute metrics (Prometheus/AMP) and right-sizing (8.6: 1×1 GB → 2×2 GB executors, −25%).
  - `data-management` (HIGH): add data-store performance metrics (Athena engine and queue seconds per state, #105; Iceberg file counts at compaction).
  - `process-culture` (MEDIUM): add **load test**, which ADR 0015 declined until there was a ramp toward a limit. Phase 8 is that ramp, and it found the limits (Athena cutoffs at 10M and 100M). Also add "a process to improve performance" (8.6's one change at a time). Declined: automated remediation.
  - `performing-architecture` (MEDIUM): add benchmarking (ADR 0018's local OOM table, 8.6 before/after).
- **Reliability**
  - `adapt-to-changes` (MEDIUM): add reactive (the ASG replaced the interrupted Spot node, 2 nodes back in about 40 s), proactive (autoscaler on pending executors) and load tested.
  - `manage-service-limits` (HIGH): add "accommodate fixed quotas through architecture" (executor max of 16 vCPU against a 32 Spot quota; a separate DQ workgroup and cutoffs). Declined: quota monitoring and automation.
  - `withstand-component-failures` (HIGH): add "fail over to healthy resources" (FIS test: 4 executors decommissioned gracefully, tasks re-ran, DQ passed). Declined: "automate healing on all layers" (driver and single NAT) and graceful degradation (Spot fallback unmeasured, ADR 0020).
  - `testing-resiliency` (HIGH): update the note only (FIS reinforces chaos engineering, which is already selected).
- **Operational Excellence**
  - `evolve-ops` (MEDIUM): add operations metrics reviews (per-run records, and the 2026-10-15 close-out review that found the Athena double count, #102).
  - Unchanged: `observability`, `ready-to-support`, and the 3 organisational HIGHs.
- **Security**
  - New grants, all scoped: `cerberus-spark` delete on `payments_bulk/` only; CA IRSA and FIS role tag-scoped; CloudWatch read for `cerberus-admin` through the root-console path (again).
  - `permissions` gets a note only. `identities` stays HIGH: keys are still not rotated, and static admin keys are now also mounted into the local Grafana (ADR 0022).
  - `detect-investigate-events` is unchanged: no trail, checked 2026-10-27.
- **Sustainability**
  - Spot and scale-down help. The executor min = desired keeps the planned nodes up between apply and job.
  - DQ scans and the dbt merge re-read the whole of silver each run.
  - Graviton was never evaluated. No answer changes.

**The central finding.** Phase 8's increments are incremental in Spark but not in Athena. The dbt merge and the DQ checks grow with total silver, not with the batch:
- 1M: DQ scan 62.6 GB, about $0.31, more than the run.
- The take leaves 83-84% and 68% of the cutoffs.

Cause: the realistic time spread (plan.md L568-596) was never built, and the DQ checks are not incremental.

**Overall table.** Two columns: "Milestone 7" (23/19/10/5) and "Workload after the 8.11 answers (date)". The second is filled from `get-lens-review` after the user runs the updates. Add a line saying milestone 8 is saved at close-out.

**Consequences / follow-ups.** One list. Name the owning phase where one exists.
1. The shared workgroup is at about 83-84% of 25 GiB after the take; the next 100M fails dbt. The DQ 20 GiB holds about one more 100M. No retake after `[generate] done`.
2. Incremental DQ checks. The DQ scan now costs more than a 1M run.
3. Read-only Grafana role (9.2). Remove the in-cluster Grafana (9.1).
4. Generator commit of 875 s with no Spark job. Test the S3A magic committer (ADR 0018's deferred choice); the cause is inferred.
5. Dynamic allocation sized to the input: 16 executors at 1M gave almost no speed-up.
6. Open from the 2026-10-15 review: bytes written not measured; Athena computed vs posted ($0.61 vs $0.574, TB vs TiB); about 1,706 s of apply, waits and destroy not attributed; EKS cluster-hours read low.
7. The ingestion Lambda retires on 2026-10-30. After that InvokeIngestion is a no-op success (code read, not run), and the daily orchestrated path adds no data.
8. Stale docs: plan.md L529 "17 checks"; slo.md L176 and lineage.md L230 retirement date; collector docstring L295 "untagged".
9. Workload description stale (needs `UpdateWorkload`).
10. Data Analytics Lens not applied.
11. Value checksum and the cheaper milestone audit (plan.md Planned later work).
12. `use_lockfile`.
13. `BatchGetQueryExecution` missing from `cerberus-admin`.
14. Still no CloudTrail trail.


## 7. Build steps

All steps belong to Phases.md **8.11** (existing subtask).

1. **PR "decision": ADR 0023 Proposed + this plan copy.** Branch `decision-phase-8-well-architected-review`, draft PR.
   - Optional: one progress line on Phases.md 8.11 ("ADR 0023 Proposed; milestone 8 after the 8.10 video"). It must not check 8.11.
   - Verify: `ls docs/adr` ends at 0023; links resolve on main; no edits to checkpoint.md, plan.md L148 or README.
   - Opus review, at most 2 rounds.
2. **User accepts, then runs the `update-answer` commands** (section 9). Then I read back `get-lens-review` and `list-answers`, read-only.
   - Executor fills the Overall table and "Moved a bucket" from the Tool's counts, and sets Status to `Accepted (date)`.
   - Same PR. Merge only with the user's approval.
3. **Small docs PR (optional, separate):** follow-up 8. Fix plan.md L529 ("17 checks" → "26 checks at 100M; the count varies with the generated days"), slo.md L176 and lineage.md L230 (retirement date), and the collector docstring L295.
   - Verify: the grep in section 8 returns nothing stale.
4. **After the video (close-out PR, weekend or after):**
   - 8.10 closes as in checkpoint "Next up" item 1 (#107 merged).
   - The user runs `create-milestone`. I verify it with `list-milestones`.
   - Add a dated "Milestone 8" line to ADR 0023 with the Tool's counts. If the take changed any answer, run `update-answer` before the milestone.
   - Check 8.10 and 8.11, mark Phase 8 ✅ in Phases.md, flip plan.md L148, update README. `/end-day` updates the checkpoint.

## 8. Facts for the executor to re-verify (exact commands)

- `ls /home/chirag/projects/cerberus/docs/adr` → last file is 0022.
- `jq '{passed,errors,warnings,bytes_scanned,seconds,checks:(.checks|length)}' /home/chirag/projects/cerberus/observability/scale/audits/dq-full-20261015.json`
- `jq -c '{status,run_seconds,events_processed,silver:.silver.events,dq:.data_quality.passed,n:(.data_quality.checks|length),dqb:.data_quality.bytes_scanned,run:.cost.run_usd,perm:.cost.usd_per_million_events}' /home/chirag/projects/cerberus/observability/scale/runs/exercise-2026101{5T145812Z,3T055859Z}.json /home/chirag/projects/cerberus/observability/scale/runs/exercise-20261009T074853Z.json`
- `sed -n 205,215p /home/chirag/projects/cerberus/terraform/modules/eks/main.tf`
- `sed -n 291,310p /home/chirag/projects/cerberus/observability/scale/collect_run_metrics.py`
- `sed -n 12,22p /home/chirag/projects/cerberus/terraform/modules/athena/variables.tf`
- `sed -n 104,111p /home/chirag/projects/cerberus/docs/demo-recording.md`
- `sed -n 240,250p /home/chirag/projects/cerberus/docs/adr/0022-live-observability-for-a-recorded-run.md`
- `sed -n 58,68p /home/chirag/projects/cerberus/ingestion/lambda/handler.py`
- `grep -rn "Choice" /home/chirag/projects/cerberus/terraform/modules/step_functions/` → expect nothing.
- `grep -rn "17 checks\|2026-08-17" /home/chirag/projects/cerberus/docs/plan.md /home/chirag/projects/cerberus/docs/slo.md /home/chirag/projects/cerberus/docs/lineage.md`
- `sed -n 94,116p /home/chirag/projects/cerberus/iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`

## 9. WA Tool commands

**Read-only, run by me on 2026-10-27, with results**
- `aws wellarchitected list-workloads`: `cerberus-platform`, 23/19/10/5, `UpdatedAt` 2026-09-29.
- `aws wellarchitected list-milestones --workload-id 58c236e2c7844375965d22349b460084`: milestones 1 to 7. Milestone 7 is `phase-7-end-to-end-validation-complete`, 2026-09-29, 23/19/10/5.
- `aws wellarchitected get-lens-review --workload-id 58c236e2c7844375965d22349b460084 --lens-alias wellarchitected`: per-pillar HIGH is OE 6, Sec 5, Rel 5, Perf 2, Cost 5, Sus 0. Lens 2025-02-25.
- `aws wellarchitected list-lens-review-improvements ...`: 23 HIGH, 19 MEDIUM.
- `aws wellarchitected list-answers` and `get-answer` on 33 questions. The selected choices are in section 6.
- `aws cloudtrail describe-trails`: `[]`.

**Writes, for the user after the ADR is accepted** (step 2). `update-answer` **replaces** the whole selected set and the note. Each note must be ≤ 2,084 characters. Rewrite the stale Phase 1 notes in full, keeping one sentence for each earlier phase. The executor puts the full note texts in this plan file. Template:

```
W=58c236e2c7844375965d22349b460084
q=<question-id>; NOTE='<new note text>'
[ ${#NOTE} -le 2084 ] || echo "note too long: ${#NOTE}"
aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
  --question-id $q --selected-choices <full list below> --notes "$NOTE"
```

Full selected sets. New choices are marked with `+`.
- `type-size-number-resources`: cost_type_size_number_resources_data, +cost_type_size_number_resources_cost_modeling, +cost_type_size_number_resources_metrics
- `pricing-model`: cost_pricing_model_analysis, +cost_pricing_model_implement_models
- `manage-demand-resources`: cost_manage_demand_resources_buffer_throttle, cost_manage_demand_resources_dynamic, +cost_manage_demand_resources_cost_analysis
- `monitor-usage`: cost_monitor_usage_define_attribution, cost_monitor_usage_config_tools, cost_monitor_usage_org_information, +cost_monitor_usage_detailed_source, +cost_monitor_usage_define_kpi, +cost_monitor_usage_allocate_outcome
- `govern-usage`: cost_govern_usage_policies, cost_govern_usage_controls, cost_govern_usage_groups_roles, cost_govern_usage_track_lifecycle, +cost_govern_usage_goal_target
- `compute-hardware`: perf_compute_hardware_select_best_compute_options, perf_compute_hardware_scale_compute_resources_dynamically, perf_compute_hardware_understand_compute_configuration_features, +perf_compute_hardware_collect_compute_related_metrics, +perf_compute_hardware_configure_and_right_size_compute_resources
- `data-management`: perf_data_use_purpose_built_data_store, perf_data_evaluate_configuration_options_data_store, perf_data_implement_strategies_to_improve_query_performance, +perf_data_collect_record_data_store_performance_metrics
- `process-culture`: perf_process_culture_establish_key_performance_indicators, perf_process_culture_use_monitoring_solutions, perf_process_culture_review_metrics, perf_process_culture_keep_workload_and_services_up_to_date, +perf_process_culture_load_test, +perf_process_culture_workload_performance
- `performing-architecture`: perf_architecture_understand_cloud_services_and_features, perf_architecture_evaluate_trade_offs, perf_architecture_guidance_architecture_patterns_best_practices, perf_architecture_factor_cost_into_architectural_decisions, perf_architecture_use_policies_and_reference_architectures, perf_architecture_use_data_driven_approach, +perf_architecture_use_benchmarking
- `adapt-to-changes`: rel_adapt_to_changes_autoscale_adapt, +rel_adapt_to_changes_reactive_adapt_auto, +rel_adapt_to_changes_proactive_adapt_auto, +rel_adapt_to_changes_load_tested_adapt
- `manage-service-limits`: rel_manage_service_limits_aware_quotas_and_constraints, +rel_manage_service_limits_aware_fixed_limits
- `withstand-component-failures`: rel_withstand_component_failures_notifications_sent_system, +rel_withstand_component_failures_failover2good
- `evolve-ops`: ops_evolve_ops_process_cont_imp, ops_evolve_ops_perform_rca_process, ops_evolve_ops_feedback_loops, ops_evolve_ops_knowledge_management, ops_evolve_ops_drivers_for_imp, ops_evolve_ops_validate_insights, ops_evolve_ops_share_lessons_learned, ops_evolve_ops_allocate_time_for_imp, +ops_evolve_ops_metrics_review
- Note only, same choices: `testing-resiliency` (rel_testing_resiliency_rca_resiliency, rel_testing_resiliency_test_non_functional, rel_testing_resiliency_failure_injection_resiliency, rel_testing_resiliency_game_days_resiliency) and `permissions` (sec_permissions_define, sec_permissions_least_privileges, sec_permissions_emergency_process, sec_permissions_continuous_reduction, sec_permissions_share_securely_third_party, sec_permissions_analyze_cross_account).

Then I run read-only `get-lens-review` and give the new counts to the executor.

**At close-out, after the video** (step 4):
```
aws wellarchitected create-milestone --workload-id 58c236e2c7844375965d22349b460084 \
  --milestone-name "phase-8-scale-validation-complete"
```

## 10. Open questions for the user

1. **Milestone 8's `--full` audit.** Cite the 2026-10-15 audit (data to 137.1M; recommended)? Or re-run `--full` after the take, at about $1.6 (estimate) plus a cutoff raise and restore through CI? The answer changes ADR 0023's Context and the close-out steps.
2. **Option B timing.** Do you agree to update the answers now and save milestone 8 only after the video? If you prefer A (milestone now), step 4 shrinks to the Phases/plan/README flip.

## 11. Review checklist (for the Opus review of the executor's PR)

- File is `docs/adr/0023-phase-8-well-architected-review.md`. Heading "# 23. ...". Status `Proposed`. Date 2026-10-27. Same section shape as ADR 0014/0015.
- The baseline is milestone 7, not milestone 6.
- No bucket move is claimed before the Tool reports it. Predictions are marked as proposed.
- Every number traces to a path in section 2 or 8. No number comes only from #107. No anchor links into #107-only headings.
- The ADR 0018 and 0020 amendments are confirmed with code paths. No other ADR is amended.
- Declined choices are named with reasons: graceful degradation, auto-heal all layers, quota monitoring, rotation, trail, Graviton, automated remediation.
- The follow-up list includes all 14 items in section 6. The open questions from 2026-10-15 are stated as open.
- No edits to checkpoint.md, plan.md L148 or README. 8.10 and 8.11 are not checked. Any Phases.md change is a progress note only.
- The WA write commands are in the plan as user-run. Each note is ≤ 2,084 characters, and the full selected sets match section 9.
- Natural professional English, matching ADR 0022's plainer style.

## 12. Proposed WA Tool note texts (added by the executor)

Each block is a complete, ready-to-run command for the user, to run after ADR 0023 is accepted. The note is read from a quoted heredoc, because several notes contain apostrophes. The length check stays in each block and skips the command when the note is too long. Every note is at most 2,084 characters; the length is shown in the heading. The Phase 1 sentence is kept in each rewritten note, and the stale "No EC2 exists in Phase 1" text is replaced. The selected choices are the full sets from section 9 (verified against the live answers on 2026-10-27, read-only).

Run `export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1` first. `update-answer` writes to the live workload. These are the only writes in this review.

### `type-size-number-resources` (558 characters)

```
W=58c236e2c7844375965d22349b460084
q=type-size-number-resources
NOTE=$(cat <<'EOF'
Phase 1: S3, Glue and Athena are serverless, so there was no instance to size. Phase 8 (8.6-8.9): the 1M, 10M and 100M ladder is priced per million events from the run records in observability/scale/runs/ ($0.2928, $0.0112, $0.0037). That is the cost model. 8.6 right-sized the executors at 10M with a before and after run (RunTransform 323.3 s to 241.6 s, -25%; run cost rose from $0.101 to $0.133). Cluster Autoscaler and Spark dynamic allocation size the executor count from pending work (ADR 0020, 8.8). Not claimed: Graviton (arm64) was never evaluated.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices cost_type_size_number_resources_data cost_type_size_number_resources_cost_modeling cost_type_size_number_resources_metrics \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `pricing-model` (646 characters)

```
W=58c236e2c7844375965d22349b460084
q=pricing-model
NOTE=$(cat <<'EOF'
Phase 1: Athena per-TB pricing drove ADR 0002's Parquet, compression and partitioning choices; everything else is pay-as-you-go. Phase 8 (ADR 0020): the pricing model is chosen per component. Spark executors run on a Spot node group. The driver and system pods run On-Demand, so a Spot reclaim does not take the driver (in the 8.8 AWS FIS test the driver ran on, `driver killed: 0`). Athena, Lambda, Step Functions, ECS Fargate and AMP are pay-per-use. No reserved capacity or Savings Plan: dev-compute exists only during an exercise, so there is no steady use to commit to. Spot fallback when no Spot capacity exists was not measured (ADR 0020).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices cost_pricing_model_analysis cost_pricing_model_implement_models \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `manage-demand-resources` (616 characters)

```
W=58c236e2c7844375965d22349b460084
q=manage-demand-resources
NOTE=$(cat <<'EOF'
Phase 1: the Athena workgroup bytes_scanned_cutoff_per_query is an explicit cost throttle; S3, Glue and Athena scale dynamically with zero idle cost. Phase 8 (8.8-8.9): demand is analysed before a run. The executor count is planned from the event count and set with exercise.sh --executor-nodes, which becomes the executor node group minimum and desired size (ADR 0020 amendment; terraform/modules/eks/main.tf). Dynamic allocation and Cluster Autoscaler handle the rest, up to 4 executor nodes. Limit seen: Spark asked for 16 executors even at 1M events with almost no speed-up, so sizing to the input is still open.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices cost_manage_demand_resources_buffer_throttle cost_manage_demand_resources_dynamic cost_manage_demand_resources_cost_analysis \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `monitor-usage` (586 characters)

```
W=58c236e2c7844375965d22349b460084
q=monitor-usage
NOTE=$(cat <<'EOF'
Phase 1: Project/Phase/Layer tags are the attribution categories; billing alarm and SNS are the configured cost tool. Phase 8: observability/scale/collect_run_metrics.py reads Cost Explorer by service and usage type for each run day (the detailed source). It writes a run record with run cost and cost per million events (the KPI) in observability/scale/runs/, so cost is allocated to a workload metric, events processed. Caveats: cost is scoped by region, not by Project tag; EKS cluster-hours read low; computed and posted Athena cost differ (TB vs TiB, still open). Not claimed: CUR.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices cost_monitor_usage_define_attribution cost_monitor_usage_config_tools cost_monitor_usage_org_information cost_monitor_usage_detailed_source cost_monitor_usage_define_kpi cost_monitor_usage_allocate_outcome \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `govern-usage` (535 characters)

```
W=58c236e2c7844375965d22349b460084
q=govern-usage
NOTE=$(cat <<'EOF'
Phase 1: the Project/Phase/Layer tagging convention is the policy; the billing alarm is the control; the three least-privilege IAM roles are the groups and roles mechanism; Phases.md tracks lifecycle. Phase 7 (7.3): cerberus-admin was cut to scoped policies. Phase 8 (8.2): goals and targets. AWS Budgets alerts at $15 and $20 a month (docs/plan.md budget: $20 a month) and a $0 idle target, checked at each teardown by an account-wide check that no EKS cluster, NAT gateway or EIP remains (ADR 0020). Still a single account by design.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices cost_govern_usage_policies cost_govern_usage_controls cost_govern_usage_groups_roles cost_govern_usage_track_lifecycle cost_govern_usage_goal_target \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `compute-hardware` (610 characters)

```
W=58c236e2c7844375965d22349b460084
q=compute-hardware
NOTE=$(cat <<'EOF'
Phase 1: 1.7 ruled out Spark for plain Python at that data volume, a real compute-selection decision; Athena, Glue and S3 scale dynamically with no instances to size. Phase 3: Spark on EKS. Phase 8: compute metrics are collected (Spark and node metrics through Prometheus to AMP, ADR 0016; per-run records in observability/scale/runs/). 8.6 right-sized the executors with a before and after run (1 x 1 GB to 2 x 2 GB, RunTransform 323.3 s to 241.6 s, -25%; docs/scale-metrics.md). ADR 0020 scales the executor nodes with Cluster Autoscaler. Executor nodes are x86 4 vCPU / 16 GiB; Graviton was never evaluated.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices perf_compute_hardware_select_best_compute_options perf_compute_hardware_scale_compute_resources_dynamically perf_compute_hardware_understand_compute_configuration_features perf_compute_hardware_collect_compute_related_metrics perf_compute_hardware_configure_and_right_size_compute_resources \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `data-management` (720 characters)

```
W=58c236e2c7844375965d22349b460084
q=data-management
NOTE=$(cat <<'EOF'
Phase 1: S3+Glue+Athena+dbt is purpose-built for this analytics workload; Parquet vs JSON and partition granularity were evaluated in ADR 0002; Parquet+Snappy+dt= partitioning+bytes-scanned-cutoff improve query performance and cost. No caching layer -- not warranted at this scale. Phase 8: silver and gold are Iceberg tables (ADR 0017) with compaction. Data-store performance is recorded per run: Athena bytes scanned, engine seconds and queue seconds per state (collector, #105) and Iceberg file counts at compaction (for example 80 files into 22 at 100M; docs/scale-metrics.md). The records show the dbt merge and DQ scans grow with total silver, not the batch; the 25 GiB and 20 GiB cutoffs are the limit (ADR 0022).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices perf_data_use_purpose_built_data_store perf_data_evaluate_configuration_options_data_store perf_data_implement_strategies_to_improve_query_performance perf_data_collect_record_data_store_performance_metrics \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `process-culture` (1074 characters)

```
W=58c236e2c7844375965d22349b460084
q=process-culture
NOTE=$(cat <<'EOF'
Baseline: mid-project Terraform install + dbt version pinning (keep up-to-date). Phase 6 adds three: ESTABLISH KPIS -- docs/slo.md's run-latency objective (a full ingest->transform->serve cycle in under 30 min, against the 57-min sum of the ASL state timeouts) plus AWS/States ExecutionTime and the per-integration LambdaFunctionRunTime/ServiceIntegrationRunTime metrics; USE MONITORING SOLUTIONS -- 6.1's dashboard has 'Pipeline execution duration' and 'Step integration timing (avg)' widgets, and a text widget pointing at X-Ray for per-state latency; REVIEW METRICS AT REGULAR INTERVALS -- the per-phase Well-Architected pass. Phase 7 (7.4): 3 runs at 10x volume (~6 min each) did not earn LOAD TEST, because it was a one-time bump with no search for a ceiling. Phase 8 (8.3-8.9) earns it: the 1M, 10M and 100M ladder is a ramp toward limits, and it found them (Athena cutoffs raised in 8.6 and 8.9; docs/scale-metrics.md). WORKLOAD PERFORMANCE PROCESS -- 8.6 changed one thing at a time and measured each. Still not claiming AUTOMATION TO REMEDIATE (alarms notify only).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices perf_process_culture_establish_key_performance_indicators perf_process_culture_use_monitoring_solutions perf_process_culture_review_metrics perf_process_culture_keep_workload_and_services_up_to_date perf_process_culture_load_test perf_process_culture_workload_performance \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `performing-architecture` (633 characters)

```
W=58c236e2c7844375965d22349b460084
q=performing-architecture
NOTE=$(cat <<'EOF'
Medallion lakehouse is a deliberately adopted reference pattern; ADR 0002 factors cost in explicitly; daily (not hourly) partitioning was a data-driven response to Phase 0's actual small-file problem. Phase 8 adds benchmarking: ADR 0018 measured the generator's file formats locally on the cluster image (including OutOfMemoryError cases), 8.6 benchmarked executor sizing with before and after runs (RunTransform 323.3 s to 241.6 s), and the 1M, 10M and 100M ladder gives time and cost per million events at each size (observability/scale/runs/). Not claimed: a rival architecture (for example Graviton) benchmarked against this one.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices perf_architecture_understand_cloud_services_and_features perf_architecture_evaluate_trade_offs perf_architecture_guidance_architecture_patterns_best_practices perf_architecture_factor_cost_into_architectural_decisions perf_architecture_use_policies_and_reference_architectures perf_architecture_use_data_driven_approach perf_architecture_use_benchmarking \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `adapt-to-changes` (623 characters)

```
W=58c236e2c7844375965d22349b460084
q=adapt-to-changes
NOTE=$(cat <<'EOF'
Phase 1: S3/Glue/Athena scale automatically with no capacity management. Phase 8: REACTIVE -- Cluster Autoscaler and the Auto Scaling group replace and add Spot executor nodes; in the 8.8 interruption test (exercise-20261012T133620Z) two new Spot nodes were Ready about 40 s after the scale-up and the run still SUCCEEDED. PROACTIVE -- Spark dynamic allocation asks for executors when tasks back up and the autoscaler adds nodes for pending executors (ADR 0020). LOAD TESTED -- the 1M, 10M and 100M ladder (100M in 742.0 s; exercise-20261013T055859Z) and the interruption test. Limit: the executor group maximum is 4 nodes.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices rel_adapt_to_changes_autoscale_adapt rel_adapt_to_changes_reactive_adapt_auto rel_adapt_to_changes_proactive_adapt_auto rel_adapt_to_changes_load_tested_adapt \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `manage-service-limits` (547 characters)

```
W=58c236e2c7844375965d22349b460084
q=manage-service-limits
NOTE=$(cat <<'EOF'
Phase 1: service quotas exist but are not tracked or monitored. Phase 8 (8.2, ADR 0020): the limits are known and designed around. Spot and On-Demand vCPU quotas are 32 each; the executor group maximum (4 nodes of 4 vCPU, 16 vCPU) stays inside the Spot quota. Athena limits are handled by architecture: a separate data-quality workgroup and per-query bytes-scanned cutoffs sized for each step (25 GiB shared, 20 GiB data quality; terraform/modules/athena/variables.tf). Still a gap: no quota monitoring or alarm, and no automation to raise limits.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices rel_manage_service_limits_aware_quotas_and_constraints rel_manage_service_limits_aware_fixed_limits \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `withstand-component-failures` (628 characters)

```
W=58c236e2c7844375965d22349b460084
q=withstand-component-failures
NOTE=$(cat <<'EOF'
Phase 1: only the billing alarm's SNS notification existed; there was no standing compute to fail over. Phase 8 (8.8, #96): FAIL OVER TO HEALTHY RESOURCES -- an AWS FIS experiment interrupted the Spot node holding 4 executors during a run. EKS drained it, all 4 executors decommissioned gracefully, 2 shuffle map tasks re-ran, the run SUCCEEDED and data quality passed (docs/scale-metrics.md). Not claimed: auto-healing on all layers (the Spark driver is a single On-Demand pod and there is one NAT gateway), graceful degradation (Spot fallback when no capacity exists was not measured, ADR 0020), or defined SLAs per component.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices rel_withstand_component_failures_notifications_sent_system rel_withstand_component_failures_failover2good \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `evolve-ops` (618 characters)

```
W=58c236e2c7844375965d22349b460084
q=evolve-ops
NOTE=$(cat <<'EOF'
This is the project's strongest Operational Excellence area: /end-day + checkpoint.md is a continuous-improvement loop; the 2026-08-06 gap backfill and stale-checkout fix are real post-incident analyses; docs/notes/day-NN.md and article.md are literal knowledge management and lessons-learned sharing; the per-phase Well-Architected pass is the improvement driver. Phase 8 adds OPERATIONS METRICS REVIEWS: every exercise writes a run record (time, cost, bytes, data quality) in observability/scale/runs/, and the 2026-10-15 close-out review of those records found the Athena double count and re-priced the runs (#102).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices ops_evolve_ops_process_cont_imp ops_evolve_ops_perform_rca_process ops_evolve_ops_feedback_loops ops_evolve_ops_knowledge_management ops_evolve_ops_drivers_for_imp ops_evolve_ops_validate_insights ops_evolve_ops_share_lessons_learned ops_evolve_ops_allocate_time_for_imp ops_evolve_ops_metrics_review \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `testing-resiliency` (510 characters)

```
W=58c236e2c7844375965d22349b460084
q=testing-resiliency
NOTE=$(cat <<'EOF'
7.1/7.2 (2026-09-29): scaled TRANSACTION_COUNT 200->2000 (10x) and verified 3 full orchestrated executions succeeded end-to-end at the new volume -- a real, verified scalability test, not a one-off. Phase 8 (8.8, #96): chaos engineering reinforced. An AWS FIS experiment (aws:ec2:send-spot-instance-interruptions) interrupted the Spot node holding 4 executors during a run; the run SUCCEEDED and data quality passed. 8.9 tested scale up to 100M events (742.0 s). Not claimed: playbooks to investigate failures.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices rel_testing_resiliency_rca_resiliency rel_testing_resiliency_test_non_functional rel_testing_resiliency_failure_injection_resiliency rel_testing_resiliency_game_days_resiliency \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `permissions` (725 characters)

```
W=58c236e2c7844375965d22349b460084
q=permissions
NOTE=$(cat <<'EOF'
7.3 (2026-09-29): cerberus-admin's AdministratorAccess replaced with 6 scoped policies built from real CloudTrail history (continuous_reduction, reinforced). The root-console break-glass path used to push corrected policy versions (documented in iam/cerberus-admin/README.md) is now this project's defined emergency access process for the one identity that cannot self-service its own permissions. Phase 8 (note only, no new choice): new grants are scoped. cerberus-spark may delete only under bronze payments_bulk/ (terraform/modules/iam_spark); Cluster Autoscaler IRSA and the FIS role are limited by resource tag; a read-only CloudWatch metrics grant went to cerberus-admin through the same root-console path (2026-10-25).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sec_permissions_define sec_permissions_least_privileges sec_permissions_emergency_process sec_permissions_continuous_reduction sec_permissions_share_securely_third_party sec_permissions_analyze_cross_account \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

Run 2026-10-27 by Claude at the user's request; all 15 succeeded; result in ADR 0023 Overall.
