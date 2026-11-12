# Plan: Phase 10 built with hooks for the Phase 14 agents (decision, ADR 0021 amendment)

Date: 2026-11-12. Planner: Opus. Mode: decision (an amendment to ADR 0021, Accepted 2026-11-12). Branch `decision-0021-agent-hooks`. The user chose option C on 2026-11-12.

## 1. Goal

Phase 10 alerting stays deterministic (AMP ruler, Alertmanager, SNS, `promtool` in CI). Phase 10 is also built so the Phase 14 agents (ADR 0025: rules detect, GenAI explains, a human approves) have signals to read and a place to show their output. AI never raises, suppresses or gates an alert.

## 2. Facts (V = verified in repo, U = unverified)

- V. ADR 0021 L146–149: latest-run series carry no `execution` label; L161: `cerberus_run_info{execution}` for drill-down; L275: dashboard and `make status` share the query set; L107 vs L127: "no recording rules" vs "Alerting and recording rules".
- V. ADR 0025 decision 4 (L189–197): named PromQL from a fixed query set; decision 8 (L241–242): AI review panel on dashboard 1 (`cerberus-run-story`); decision 10 (L256): "starts after Phase 10".
- V. ADR 0024 L199–216: one Grafana file set, two hosts; console annotations rebuilt from run records (L213).
- V. AI plan section 7 step 5: 14.4 depends on 14.2a, 14.2b, the IAM step and 14.3.
- U. The AMP ruler accepts `topk` with `group_left`; the `query` template function on AMP.

## 3. Decision summary

The full text is the [ADR 0021 amendment](../adr/0021-pipeline-status-and-alerting.md#amendment-2026-11-12-designed-for-the-phase-14-agents).

- D1. One named query set (for example `observability/queries/status.yaml`) used by the dashboard panels, the alert rules, `make status` / `cerberus status` and ADR 0025's PromQL tool. A CI test fails on any panel or rule expression not built from a named entry.
- D2. Alerts name the run. The latest-run series keep no `execution` label. A per-execution start series and finish series carry the timestamp, and the rules add `execution` with `group_left(execution)` from the newest run. No recording rules.
- D3. A reserved "AI review" annotation-list panel (tag `cerberus-ai`) on the Phase 10 run-status dashboard. Dashboard 1 keeps only a link.
- D4. 14.2a, 14.2b, the `cerberus-ops-agent` IAM step, 14.3 and 14.4 run directly after 10.7 and before 11.1. 14.5–14.8 stay after Phase 13.

Rejected: option A (AI decides alerts: non-deterministic, not testable with `promtool`, breaks ADR 0025 decision 1) and option B (no hooks: retrofitting means rewriting the Phase 10 rules and panels).

## 4. PR order

1. **This decision PR (docs only).** The ADR 0021 amendment (Proposed), the ADR 0025 status note, this plan, `Phases.md`, `docs/plan.md`, `checkpoint.md`.
   - Verify: `git diff main --stat` shows only these files.
   - Verify: a grep of the added lines for 12-digit numbers and account ARNs returns nothing.
   - Verify: relative links resolve.
2. **Acceptance flip (folded into PR 1 on 2026-11-12).** The user accepts; `cerberus-git` flips Proposed to Accepted in the ADR 0021 amendment and removes the "if that amendment is not accepted" clause from the ADR 0025 note.
3. **10.2a Query-set file.** The file, the loader in the 9.3 package, and the CI consistency test. No AWS.
   - Verify: pytest; the test fails on a hand-edited expression.
4. **10.2 Publisher.** Per-execution start and finish series, the finish in the same remote-write request as the status. 10.2 fixes the names and settles the spikes already listed.
5. **10.3 Dashboard.** The run-status dashboard with the reserved "AI review" panel.
   - Verify: the panel shows "No AI review yet (Phase 14)" on local Compose.
6. **10.4 Rules and Alertmanager template.** Failed run, DQ errors, never reported, error budget over runs. `promtool test rules` covers the join and `exp_labels: execution`. The SNS template prints `.CommonLabels.execution` and the annotations.
   - Verify: the AMP ruler accepts the `topk` + `group_left` rule; `promtool` passes the same file.
7. **10.5, 10.6, 10.7 as listed in `Phases.md`.** 10.5 loads the named query set. 10.6 is the live pair (one pass, one deliberate failure); the failed alert must name the execution.
8. **Phase 14 early block, per the [AI plan](2026-11-08-ai-operations-agents.md) section 7.** In order: 14.2a (step 1), 14.2b (step 2), the `cerberus-ops-agent` IAM step (step 3), 14.3 (step 4), 14.4 (step 5). Step 6 changes target: the "AI review" panel work is only the link on dashboard 1 and the 14.4 check against the run-status dashboard panel from PR 5.
   - Then Phase 11. 14.5–14.8 follow after Phase 13.

## 5. Risks

- **AMP ruler join is unverified.** The ruler may reject `topk` with `group_left`. 10.4 confirms it first.
- **The fallback is unverified.** The Prometheus `query` template function in annotations is not checked on AMP.
- **Race.** The failed-run and DQ-error rules can see the new status before the new finish sample. A short `for:` should cover it. A `promtool` test models the gap, but AMP's ingest order stays unverified until 10.4 and 10.6.
- **The consistency test is brittle.** It compares normalised expressions. A harmless panel edit fails CI until the query set changes too. That is the intent, and it needs maintenance.
- **Thin budget headroom.** Forecast $17.2 plus the $2 AI cap is $19.2 of $20. Whether credits cover Bedrock is unverified, and the budget is gross.
- **The console AI panel stays empty.** Console annotations are rebuilt from run records only (ADR 0024), and reviews stay out of run records (ADR 0025 decision 8). Extending the boot rebuild to `observability/scale/reviews/` is a later Phase 14 step.

## 6. User actions needed later

- Enable Bedrock model access (before the 14.3 live mode and 14.4).
- Do the local first apply of `cerberus-ops-agent` (the IAM step; the CI role cannot create a new role name).

## 7. Defaults (accepted by the user 2026-11-12)

- (a) 14.2–14.4 with their dependencies move before Phase 11.
- (b) 14.5–14.8 stay after Phase 13.
- (c) The "AI review" panel moves to the run-status dashboard; dashboard 1 keeps only a link.

## 8. Not in this PR

- No Terraform, no dashboard JSON, no rules, no code.
- `orchestration/annotate.sh` L304 hard-codes an account ID in an ARN. On 2026-11-12 the user decided to keep it: the ID is already in the S3 bucket names across the repo and in its history, and ADR 0025's rule covers the AI outputs only (see `checkpoint.md`, 2026-11-12).
