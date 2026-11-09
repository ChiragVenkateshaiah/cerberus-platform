# Plan: AI operations agents (decision, ADR 0025)

Date: 2026-11-08. Planner: Opus. Base: `main` at `87d5fde`. Mode: decision (new ADR, status Proposed). Branch `decision-ai-ops-agents`, in a new worktree. The main checkout stays on `main`.

User decisions (2026-11-08): the three changes from the discussion in section 5 are accepted (local trigger first, reviews in their own files, no AI action changes AWS). The monthly AI spend ceiling is $2, enforced in code.

## 1. Question

How should Cerberus add GenAI operations agents that review every run, explain failures with evidence and propose fixes, without breaking $0 idle, the read-only and human-approval rules, or ADR 0021's alerting design? The decision is needed now for two reasons. The user asked for an ADR before the dashboard changes, #132 and the 100M take. Phase 10 (the signals these agents read) is next in line, so its design should know who its second consumer will be.

## 2. Facts (V = verified in repo or AWS docs, U = unverified)

Repo and runs:
- V. The next free ADR file number is 0025. No branch or open PR has a file 0025 or higher (checked with `git ls-tree` on every local branch, and the files of PRs #107, #126–#132). However, ADR 0024 build step 13 (L281) and `docs/plans/2026-10-27-demo-console.md` L298 name "ADR 0025" for the future 9.7 Well-Architected pass. There is a precedent for moving a planned number: ADR 0022 L175 says "The 8.11 Well-Architected ADR becomes ADR 0023; this ADR takes 0022."
- V. There are 16 run records in `observability/scale/runs/`: 14 tracked and 2 untracked rehearsal records (`rehearsal-20261107T081206Z.json`, `rehearsal-1m-20261108T060517Z.json`). Two runs FAILED: `exercise-20261008T085728Z` and `exercise-20261009T101830Z`. A record is about 11–12 KB (about 3–4k tokens).
- V. The exercise logs are git-ignored (`.gitignore` L63, `observability/scale/exercises/`). There are 29 entries, 18 MB in total. One 100M log is 245 KB, and its Spark log directory is 2.7 MB. The 100M log contains 102 lines with `arn:aws` and one distinct 12-digit number (an account ID). The run records contain no account ARNs (grep).
- V. Known incidents that can be labelled for evaluation:
  - `085728Z`: RunDbt failed. The dbt role read only `silver/payments/*`, and Spark wrote `timestamptz` (checkpoint L2876–2883).
  - `101830Z`: the execution FAILED after 640 s and data quality FAILED with 1 error (`exercises/exercise-20261009T101830Z.log` L246, L274). Cause: the 1 GiB Athena cutoff on the dbt merge and the DQ checks, from the 8.6 narrative (checkpoint L135–138). Pinning it to this exact run is U (the log excerpt does not show it).
  - `20261012T075045Z`: 787.6 s, with two Glue `OperationTimeoutException` retries in RunDbt (checkpoint L158–160).
  - `20261012T133620Z`: the FIS Spot interruption. The run SUCCEEDED, 4 executors were decommissioned and 2 map tasks re-ran (checkpoint L169–176).
  - `20261015T145812Z`: RunDbt Athena queue time was 230.5 s (checkpoint L214–217).
  - `20261013T055859Z`: a 14.6-minute generator commit with no progress signal. The cause (S3A rename) is only inferred (ADR 0022 L273–276). This is a case where the right answer is "not found".
- V. Pre-flight inputs:
  - ADR 0022 L47–53 has the linear DQ and dbt headroom projection. ADR 0023 has the central finding: Athena scans grow with total silver (dbt merge at about 84% of 25 GiB and the largest DQ check at about 68% of 20 GiB after the 100M take).
  - The CloudWatch SEARCH 14-day index note is in `docs/plans/2026-11-07-dashboard-polish.md` L215, not in the journey-freeze plan.
  - Today's `preflight()` (`orchestration/exercise.sh` L108–152) checks the identity, that there are 0 EKS clusters, that the `dev-compute` state is empty, the schedule, and that no execution is RUNNING. It does not check headroom, budget or quota.
- V. `exercise.sh` runs the collector at L369 and the DQ verdict annotation at L376. Cost comes a day later (`--cost-only`, L380). Annotations are fail-open (ADR 0022 amendment, J5).
- V. The 9.3 command set (draft PR #128, `console/cerberus_console/`) returns `(data, text)` per command. It has a strict grammar, `sanitize.py`, ruff `S` rules and hostile fixtures (`console/tests/fixtures/runs/hostile-*.json`). There is no MCP, Bedrock or Anthropic code anywhere in the repo (grep).
- V. The read-only roles on `main` (`terraform/modules/console_roles/main.tf`):
  - `cerberus-console-cli` has only Step Functions reads.
  - `cerberus-grafana-read` has AMP query and CloudWatch metrics read (plan 2026-10-28, F5).
  - No role reads CloudWatch Logs.
  - The CI role manages exactly these two role names (`github_oidc`, Sid `ManageConsoleIamRoles`; F9). `cerberus-admin` can assume `role/cerberus-*` (F14).
- V. The dashboards (uncommitted at plan time, worktree `cerberus-8.10-journey-freeze`, now PR #134): `cerberus-run-story` "1 · Run Overview: progress, quality, cost", `cerberus-run-live` "2 · Run Health: compute and throughput", `cerberus-spark-on-eks` "3 · Spark and Cluster Diagnostics".
- V. The AWS Budget is gross cost, with credits excluded (`docs/plan.md` L681). So any Bedrock spend counts against $20 whether or not credits pay for it. The forecast was about $17.2 with the 8.10 take (ADR 0022, ADR 0024).
- V. Phases 11–13 are cited by number in `README.md`, `checkpoint.md`, `docs/plan.md`, `Phases.md` (the cross-cutting list "11.7, 12.7, 13.7") and the accepted ADR 0019 L108 ("Phase 13's streaming ingestion").

External (read 2026-11-08):
- V. Claude API list prices per MTok (input/output): Haiku 5.5 $0.10/$0.50 for prompts up to 100k tokens ($0.50/$2.50 above that), Sonnet 5.5 $2/$10, Opus 5.5 $4/$20. On Bedrock, regional endpoints cost 10% more than global endpoints (Anthropic pricing page).
- U. Bedrock's own Claude prices: the AWS pricing page did not render the Anthropic table. Also U: whether Haiku 5.5 and Sonnet 5.5 are offered in us-east-1.
- U. Whether AWS promotional credits cover Claude on Bedrock. Community reports say the first invocation starts an AWS Marketplace subscription and that some Marketplace-billed models are not covered by credits.
- V (partly). CloudWatch investigations allow 150 AI investigations a month per account and 2 at a time. A per-investigation fee is not stated (U).

## 3. Constraints

- $20/month gross budget and $0 idle. No standing compute, no endpoint and no provisioned throughput.
- `dev-compute` destroy-leaves-nothing. The review must never delay the destroy.
- CI applies `dev-standing` only. The CI role cannot change its own policy, so a new role name needs a local first apply (the ADR 0016 and ADR 0024 pattern).
- AWS-changing actions are run by the user only. This includes the Bedrock model access and Marketplace subscription.
- Public repo: no account IDs, ARNs with an account, emails or secrets in committed files, including eval fixtures and AI review files.
- Must not contradict:
  - ADR 0021: alerts come from AMP rules and SNS, and status stays out of the critical path.
  - ADR 0022: annotations are fail-open.
  - ADR 0024: the command set is "not a shell" by construction, and visitor paths never call Cost Explorer.
  - ADR 0013 and ADR 0016: observability stays out of the critical path.
  - The Phase 12 parity contract: `cerberusctl` must produce the same run record (`docs/plan.md` L518–521).
- This ADR amends none of them (see section 6).

## 4. Options

**A. Rules only, no GenAI.** Phase 10 alerts, plus a deterministic `make review` that prints per-step deltas against same-scale baselines and a headroom projection.
- Cost: $0 idle and $0 per use.
- Effort: small.
- What it gives up: nothing explains why across layers. The owner still reads 200 KB logs by hand. There is no GenAI signal in the portfolio.
- Pillar note: this is the honest core. Most of the detection value (deltas, headroom, the 14-day SEARCH note) is arithmetic, so options B, C and D all still need it.

**B. A + Claude on Amazon Bedrock as the explanation layer (the accepted discussion).**
- The code computes the evidence. Claude explains it and proposes fixes, with citations.
- Tools: one registry built on the 9.3 package, exposed in-process to the Bedrock Converse tool loop and as a local stdio MCP server.
- Identity: a read-only role, `cerberus-ops-agent`, that also has `bedrock:InvokeModel`.
- Cost: $0 idle. Estimates at Claude API list prices plus 10% regional, with Bedrock prices U:
  - Run review, single-shot on Haiku 5.5 (about 40k tokens in, 2k out): about $0.005.
  - Failure triage as a tool loop (about 150k tokens in total, 5k out): about $0.02 on Haiku, about $0.39 on Sonnet 5.5.
  - Eval replay of about 30 runs on Haiku: about $0.60.
- Effort: about 8 PRs.
- What it gives up: nondeterministic output, a new IAM role, a model-provider dependency, and the injection and leak risk that must be engineered down.

**C. Managed AIOps.** Third-party SaaS (Datadog Bits AI, PagerDuty AIOps, Grafana Cloud's assistant) or AWS CloudWatch investigations.
- Cost: SaaS has monthly fees or plan limits (U). CloudWatch investigations has a 150-a-month quota and its fee is U.
- What it gives up:
  - SaaS needs a vendor account and API key, and it ships data out. ADR 0021 rejected Grafana Cloud on the same grounds.
  - None of them see the git run records, the local Spark logs or AMP (U for CloudWatch investigations).
  - CloudWatch investigations leans on CloudTrail, and no trail exists (ADR 0023 item 14).
  - It is configuration, not engineering, so it shows little in a portfolio.
- Worth a footnote: CloudWatch investigations as a comparison later.

**D. B, but the Anthropic API direct (or Claude Platform on AWS) instead of Bedrock.**
- Same models. Global pricing (10% below Bedrock regional). Often first to get new models.
- What it gives up:
  - An API key must be stored. ADR 0021's security argument prefers IAM with no credential.
  - Direct API spend is outside AWS Budgets and Cost Explorer, so the cost guardian cannot see it.
  - Claude Platform on AWS bills through Marketplace CCUs. Its auth model for this use is U.
- Effort is the same as B.

Pillar tensions that decide:
- *Security against usefulness:* explanation needs log reads, and logs are attacker-shaped text. This is resolved structurally: no write tools, a read-only role, account masking before any prompt, logs passed as quoted data, and an output validator.
- *Cost against reasoning quality:* Sonnet triage costs about as much as a 100M run ($0.37). This is resolved by computing deltas in code, using Haiku by default, moving to Sonnet only on an eval result, and a hard token cap per run and per month.
- *Operational Excellence, determinism against an LLM:* rules gate, the model never gates, and the eval score is the acceptance test.
- Reliability: the agents are fail-open, after the destroy and out of the critical path.
- Performance and Sustainability: little to decide. Latency does not matter after a run, and fewer tokens are better.

## 5. Recommendation

Option B, built on A, with three changes from the discussion (all accepted by the user on 2026-11-08):

1. **Trigger: local first, not EventBridge.** At the end of a Step Functions execution, three inputs do not exist yet:
   - the run record and the DQ verdict, written by the laptop's collector afterwards (`exercise.sh` L369–376);
   - the Spark driver logs, saved only locally and git-ignored, with `dev-compute` already destroyed;
   - the cost, which arrives a day later.

   An AWS-side Lambda would review a run it cannot see. So the reviewer is a fail-open step that `exercise.sh` calls after the destroy and the account check (`--no-review` turns it off). `make review RUN=<id>` runs it by hand. EventBridge to Lambda moves to "Revisit if": an unattended scheduled path returns, or the run records move to S3.
2. **The review goes in a sibling file, not inside the run record.** The path is `observability/scale/reviews/<run-id>.json` plus `.md`. The run record is the deterministic oracle for Phase 12 parity and for the console fixtures, so nondeterministic text must not enter it.
3. **No AWS-changing "safe action".** The project rule is that only the user runs AWS changes. The cost guardian prints the exact clean-up command, and the user runs it. The safe-action list is local only: write the review files, post a Grafana annotation (the J5 pattern), and write a draft issue or PR body to a file. The pre-flight block is a rule in `preflight()`. It is never a model verdict.

Monthly AI spend ceiling: $2, enforced in code (user decision 2026-11-08).

Why B wins: A is cheap but leaves the cross-layer explanation (the user's actual ask) to the owner. C cannot see the run records or local logs, and adds a vendor. D adds an API key and makes spend invisible to the budget and the cost guardian. B keeps IAM-only access, spend on the AWS bill, and the project's own evidence, at about a cent per run.

Positioning: the agents reason over Cerberus's own rules and evidence across AWS services. They do not compete with Databricks. In Phase 11 a Databricks job result could become one more evidence source.

## 6. ADR outline

**Title:** `25. AI operations agents: rules detect, Claude on Bedrock explains, a human approves`. File `docs/adr/0025-ai-operations-agents.md`. Date 2026-11-08.

**Status:** Proposed. Add one line: "This ADR takes 0025. The 9.7 Well-Architected ADR, planned as 0025 in ADR 0024 build step 13, takes the next free number when it is written (the precedent is ADR 0022)." Amends none. It extends ADR 0024's package (a third consumer) and ADR 0022's annotations (a new tag), without changing their decisions.

**Context:**
- The user's ask (2026-11-08): check every run's metrics and logs, and act before problems arrive.
- Where the evidence lives today, from section 2: records in git, logs local and git-ignored, AMP, CloudWatch, the Step Functions history, DQ results, annotations.
- The labelled incident history (the six cases).
- The headroom finding (ADR 0022 and ADR 0023).
- The forces: $0 idle, the gross $20 budget, a public repo, AWS changes by the user only, the Phase 12 parity contract.
- The tensions from section 4, written as prose. No Pillars section.

**Decision:**
1. The principle: rules detect, GenAI explains and proposes, a human approves.
2. Five roles, built in this order:
   1. Run reviewer: report only.
   2. Failure triage: a draft issue or PR body to a file.
   3. Pre-flight: rules in `preflight()` that may block, plus a model summary.
   4. Cost guardian: estimate against posted cost after `--cost-only`, and a check that nothing is left running. It proposes commands but never runs them.
   5. DQ analyst: report only.
3. Model: Claude on Amazon Bedrock through the Converse API with tool use. The model is not pinned in the ADR. The default family is Haiku, and the eval decides any move to Sonnet. Bedrock Agents, AgentCore and Bedrock Guardrails are not used: each adds managed surface or per-use fees for little gain over a 200-line loop.
4. Tools: one registry on the 9.3 package.
   - New tools: run-scoped log extraction (named source, error lines, a time window, size caps), named PromQL from a fixed query set, Step Functions history, and per-query Athena stats.
   - Same grammar rules as ADR 0024: no free-text queries.
   - Exposed in-process to the runner and as a local stdio MCP server (the project's first). There is no network MCP endpoint.
   - The new tools are not reachable from the console API.
5. Trigger: local, fail-open, after the destroy and the account check, never before. EventBridge is deferred.
6. Identity: a new role, `cerberus-ops-agent`, in `dev-standing`.
   - Grants: read-only Step Functions, AMP query, CloudWatch metrics, logs read on the named log groups, Athena `GetQueryExecution`, budgets and quotas read, `ce:GetCostAndUsage` (cost guardian only, a fixed number of calls), and `bedrock:InvokeModel` on named inference profiles.
   - Assumed by `cerberus-admin`. There is no Bedrock grant on `cerberus-admin`.
7. Guardrails:
   - Evidence-or-silence, enforced by code: each claim must cite an evidence id the tools returned, and the validator drops uncited claims.
   - Logs are wrapped as data, and their instructions are ignored by the system prompt and by tool design.
   - Account IDs and ARNs are masked before any prompt and before any file write.
   - Token caps per call, per run and per month, enforced in code. The monthly AI spend ceiling is $2.
   - Every action that leaves the laptop needs human approval.
8. Outputs:
   - The review file pair.
   - A Grafana annotation tagged `cerberus-ai`, shown in an "AI review" annotation-list panel on dashboard 1.
   - A two-layer text: a 3-line plain summary for any department, then engineer detail with citations.
9. Evaluation: replay the labelled incidents plus at least 3 clean runs, 3 repeats each.
   - Score: incidents found, cited-claim validity, and false findings on clean runs.
   - Proposed bar: at least 5 of 6 incidents, 100% of claims cited, at most 1 false finding across the clean runs.
   - Fixtures are masked excerpts.
10. Placement: Phase 14. It starts after Phase 10. It is numbered 14 so that 11–13 keep the numbers cited in the accepted ADR 0019, the README and the checkpoint.

**Consequences:**
- Good:
  - A cross-layer explanation for every run, at about a cent.
  - $0 idle.
  - Evidence stays in the account's IAM model.
  - One tool registry serves the agent, MCP and (later) Go.
  - The eval gives a measured score, not a demo claim.
- Given up:
  - Nondeterministic text (kept out of the run record).
  - A new role and a local first apply.
  - Dependence on Bedrock model availability.
  - Agents only for runs started from the laptop.
  - A small eval set (n is about 9), so the score is noisy.
  - Spend that may not be covered by credits (U), and that counts against the gross budget either way.
- To confirm in build:
  - Bedrock prices and model IDs in us-east-1.
  - Model access and Marketplace subscription steps.
  - Whether credits cover Bedrock Claude.
  - The Python MCP SDK version.
  - The real tokens per review.
- Revisit if:
  - A scheduled path returns: EventBridge on Step Functions `FAILED`/`TIMED_OUT`/`ABORTED` to a Lambda.
  - Run records move to S3.
  - AI spend exceeds the monthly cap.
  - Phase 12 ports the tools to Go: keep the registry contract.
  - CloudTrail is enabled: then CloudWatch investigations becomes a fair comparison.

## 7. Build steps (after acceptance; one PR each)

0. **Now (this decision PR):** the ADR (Proposed), this plan, the `Phases.md` Phase 14 section, the cross-cutting list (add 14.8), the `docs/plan.md` roadmap row and Phase 14 detail section, a README "⬜ Phase 14" line, and the "ADR 0025" to "next free number" edits in ADR 0024 L281 and `docs/plans/2026-10-27-demo-console.md` L298. These hunks do not overlap #129's hunks (L12, L345).
   - Verify: `git diff main --stat` shows only these files.
   - Verify: `git diff main | grep -E '^\+.*([0-9]{12}|arn:aws)'` returns nothing.
   - Verify: relative links resolve.
   - Do not commit the two untracked rehearsal records.
1. **14.2a Deterministic core** (`agents/cerberus_agents/`, mirroring `console/`): per-step deltas against same-scale baselines, the linear headroom projection, and evidence objects with ids.
   - Verify: pytest over all 16 records, and a golden output for the 100M record. No AWS and no model.
2. **14.2b Tool registry, masking, caps and the stdio MCP server.**
   - Verify: pytest with hostile log fixtures (injection strings, ANSI, ARNs), ruff `S`, and the MCP tool list checked locally. No AWS.
3. **IAM: the `cerberus-ops-agent` module plus a `github_oidc` extension.** The user does a local first apply and enables Bedrock model access.
   - Verify: a `simulate-principal-policy` allow/deny matrix (deny `s3:PutObject`, `states:StartExecution`, `iam:*`).
   - Verify: one tiny `converse` call costs under $0.001.
4. **14.3 Eval set and harness:** masked fixtures for the 6 incidents and 3 or more clean runs, `labels.json`, `make agents-eval` (offline stub plus a live Bedrock mode).
   - Verify: the stub run passes in CI, and the live score is recorded in the PR.
5. **14.4 Run reviewer:** a Converse single-shot, the evidence validator, the review file pair, the `cerberus-ai` annotation, and the `exercise.sh` hook after the account check (`--no-review`).
   - Verify: the eval bar is met.
   - Verify: a replay on the 1M rehearsal.
   - Verify: with Bedrock denied, `exercise.sh` still exits 0 with one warning line.
6. **Dashboard 1 "AI review" panel** (after the journey-freeze merge).
   - Verify: on the 1M window the panel shows the review, and the plain summary reads correctly for a non-engineer.
7. **14.5 Failure triage:** a tool loop, triggered when the execution is not SUCCEEDED or DQ failed. It writes a draft issue or PR body to a file. The user or `cerberus-git` files it.
   - Verify: incidents `085728Z` and `101830Z` are diagnosed with cited lines.
8. **14.6 Pre-flight rules, cost guardian and DQ analyst.**
   - Verify: a fixture at a projected 237M blocks the pre-flight.
   - Verify: a stale-SEARCH case warns.
   - Verify: the cost guardian runs on the 1M record's `--cost-only` data.
9. **14.7 Live check:** one passing and one deliberately failed exercise (pair it with 10.6 if timed together).
   - Verify: correct review and triage, and the AI cost recorded.
10. **14.8 Well-Architected pass, ADR and milestone** `phase-14-ai-operations-agents-complete`.

**`Phases.md` new section:**

```
## Phase 14 — AI operations agents ⬜

_Added 2026-11-08. Starts after Phase 10; numbered 14 so Phases 11–13 keep
their numbers. ADR 0025._

- [ ] 14.1 ADR: AI operations agents (rules detect, Claude on Bedrock
      explains, a human approves; local trigger; read-only role; $0 idle)
- [ ] 14.2 Deterministic review core and the agent tool registry on the 9.3
      command set: masking, size caps, a local stdio MCP server
- [ ] 14.3 Evaluation: labelled replay set from past runs (failed runs,
      Glue timeouts, Spot interruption, Athena queue time, clean runs) and a
      scored harness
- [ ] 14.4 Run reviewer (first agent, report only): review file, Grafana
      annotation and an "AI review" panel on dashboard 1
- [ ] 14.5 Failure triage: root cause with cited log lines and metric
      values; a draft issue or PR for human approval
- [ ] 14.6 Pre-flight rules (Athena headroom, budget, Spot quota, CloudWatch
      SEARCH index), cost guardian and data-quality analyst
- [ ] 14.7 Live check: one passing and one deliberately failed exercise,
      reviewed and triaged correctly; AI cost recorded
- [ ] 14.8 Well-Architected pass + ADR
```

**`docs/plan.md` roadmap row** (after row 13):

```
| 14 | AI operations agents | Claude on Amazon Bedrock (Converse API tool use), a local MCP server over the read-only command set, an evaluation set replayed from past runs | _(Amazon Bedrock docs; MCP specification; Anthropic tool-use and evaluation docs)_ | ⬜ Planned |
```

Also add a "Phase 14 — AI operations agents" detail section after Phase 13, in the same shape as Phase 10. Its sections are Goal, Gap it closes, Why this skill set, Stack, The central decision, Out of scope and Done when.
- Out of scope: autonomous AWS changes, an always-on agent, fine-tuning, and a visitor-facing agent on the console.
- Done when: 14.7 passes, the eval bar is met, and the stack is $0 idle.
- Artifact: a short video of a failed run triaged with citations, the ADR, and milestone 14.

**Files to change in this PR:**
- `docs/adr/0025-ai-operations-agents.md` (new)
- `docs/plans/2026-11-08-ai-operations-agents.md` (this plan)
- `Phases.md`
- `docs/plan.md`
- `README.md`
- `docs/adr/0024-demo-console.md` (L281, one phrase)
- `docs/plans/2026-10-27-demo-console.md` (L298, one phrase)

## 8. Risks

- **Hallucinated causes.** Mitigation: the validator, plus the "not found" eval case (the generator commit).
- **Prompt injection from logs.** Mitigation: no write tools and data framing, with residual risk accepted.
- **Account-ID leak** to the provider or into committed files. Mitigation: masking and the diff grep in CI.
- **Cost runaway in a tool loop.** Mitigation: hard token caps and the $2 monthly ceiling. Sonnet only after an eval result.
- **Credits may not cover Bedrock Claude (U).** The spend counts against the gross budget either way.
- **Model availability or IDs differ in us-east-1 (U).**
- **A small eval set** gives a noisy score. Repeats are reported with their spread.
- **The MCP SDK version and maturity are U.** The in-process path does not depend on MCP.

## 9. Open questions for the user

Answered 2026-11-08: (1) the three changes are accepted; (2) the monthly AI spend ceiling is $2.

Sources:
- [Claude pricing (Anthropic)](https://platform.claude.com/docs/en/about-claude/pricing)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [CloudWatch investigations (AWS docs)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Investigations.html)
- [AWS re:Post: AWS credits for Bedrock](https://repost.aws/questions/QULMmXNMRwRvGSYm6OGt6e3Q/aws-credits-for-bedrock)
- [AWS re:Post: Claude Opus 4.5 billed under AWS Marketplace](https://repost.aws/questions/QUrl2nATrQRWi1g2CV5ra5eA/claude-opus-4-5-is-being-billed-under-aws-marketplace)
- [AWS re:Post: does CloudWatch AI operations charge](https://repost.aws/questions/QUwb-YVonJT3qUwIG7bXfy-g/does-cloudwatch-ai-operations-charge)
