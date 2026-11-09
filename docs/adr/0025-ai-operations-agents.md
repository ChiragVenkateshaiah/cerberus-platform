# 25. AI operations agents: rules detect, Claude on Bedrock explains, a human approves

Date: 2026-11-08

## Status

Accepted (2026-11-08). This ADR takes 0025. The 9.7 Well-Architected ADR, planned as 0025
in [ADR 0024](0024-demo-console.md) build step 13, takes the next free number
when it is written (the precedent is [ADR 0022](0022-live-observability-for-a-recorded-run.md),
which took 0022 and moved the planned 8.11 Well-Architected ADR to 0023).
This ADR amends none of the accepted ADRs. It extends ADR 0024's
command-set package (a third consumer) and ADR 0022's annotations (a new
tag) without changing their decisions. The build steps and the facts behind
this ADR are in [the plan](../plans/2026-11-08-ai-operations-agents.md).

## Context

On 2026-11-08 the user asked for agents that check every run's metrics and
logs, and act before problems arrive. Phase 10 (the signals these agents
read) is not built yet, so its design should know who its second consumer
will be.

**Where the evidence lives today.**

- Run records: `observability/scale/runs/*.json`, in git. There are 16, of
  which 14 are tracked and 2 are untracked rehearsal records. A record is
  about 11 to 12 KB, or 3 to 4k tokens.
- Exercise logs: `observability/scale/exercises/`, local and git-ignored
  (`.gitignore` L63). There are 29 entries, 18 MB in total. One 100M log is
  245 KB, and its Spark log directory is 2.7 MB.
- AMP, CloudWatch, the Step Functions history, the data-quality results and
  the Grafana annotations from `exercise.sh`.

The 100M log holds 102 lines with `arn:aws` and one distinct 12-digit number,
an account ID. The run records hold no account ARNs. So any log text must be
masked before it reaches a prompt or a committed file.

**The labelled incident history.** Six past runs can be labelled for
evaluation:

- `exercise-20261008T085728Z`: RunDbt failed. The dbt role read only
  `silver/payments/*`, and Spark wrote `timestamptz`.
- `exercise-20261009T101830Z`: the execution FAILED after 640 s and data
  quality FAILED with 1 error. The probable cause is the 1 GiB Athena cutoff
  on the dbt merge and the DQ checks. Pinning it to this exact run is
  unverified, because the log excerpt does not show it.
- `exercise-20261012T075045Z`: 787.6 s, with two Glue `OperationTimeoutException`
  retries in RunDbt.
- `exercise-20261012T133620Z`: the FIS Spot interruption. The run SUCCEEDED, 4
  executors were decommissioned and 2 map tasks re-ran.
- `exercise-20261015T145812Z`: RunDbt Athena queue time was 230.5 s.
- `exercise-20261013T055859Z`: a 14.6-minute generator commit with no progress
  signal. The cause (an S3A rename) is only inferred (ADR 0022). This case
  is in the set because the right answer is "not found".

**The headroom finding.** ADR 0022 has the linear projection of DQ and dbt
headroom. ADR 0023 has the central finding: Athena scans grow with total
silver. The dbt merge is at about 84% of its 25 GiB cutoff and the largest DQ
check at about 68% of its 20 GiB cutoff after the 100M take. Today's
`preflight()` in `orchestration/exercise.sh` checks the identity, that there
are no EKS clusters, that the `dev-compute` state is empty, the schedule, and
that no execution is running. It does not check headroom, budget or quota.

**The forces.**

- $0 idle and no idle billed resources: no standing compute, no endpoint and
  no provisioned throughput. The budget is $20 a month, and it is gross:
  credits are excluded (`docs/plan.md`), so any Bedrock spend counts against
  it whether or not credits pay for it. The forecast is about $17.2 with the
  8.10 take. The $2 monthly AI ceiling fits inside the remaining headroom
  ($17.2 + $2 = $19.2).
- `dev-compute` destroys to nothing. The review must never delay the destroy.
- CI applies `dev-standing` only, and the CI role cannot change its own
  policy. A new role name needs a local first apply (the pattern of ADR 0016
  and ADR 0024).
- AWS-changing actions are run by the user only. This includes Bedrock model
  access and any Marketplace subscription.
- The repo is public: no account IDs, ARNs with an account, emails or secrets
  in committed files, including eval fixtures and AI review files.
- The Phase 12 parity contract: `cerberusctl` must produce the same run
  record (`docs/plan.md`).
- ADR 0021 (alerts come from AMP rules and SNS; status stays out of the
  critical path), ADR 0022 (annotations are fail-open), ADR 0024 (the command
  set is "not a shell" by construction, and visitor paths never call Cost
  Explorer), and ADR 0013 and ADR 0016 (observability stays out of the
  critical path).

**What exists and what does not.** The 9.3 command set (draft PR #128,
`console/cerberus_console/`) returns `(data, text)` per command. It has a
strict grammar, `sanitize.py`, ruff `S` rules and hostile fixtures. There is
no MCP, Bedrock or Anthropic code anywhere in the repo. On `main`,
`cerberus-console-cli` has only Step Functions reads, and `cerberus-grafana-read`
has AMP query and CloudWatch metrics read. No role reads CloudWatch Logs.

**The options.**

- *A. Rules only, no GenAI.* Phase 10 alerts, plus a deterministic
  `make review` that prints per-step deltas against same-scale baselines and
  a headroom projection. It costs $0 idle and $0 per use. It gives up the
  cross-layer "why": the owner still reads 200 KB logs by hand, and the
  portfolio has no GenAI signal. It is the honest core, because most of the
  detection value is arithmetic, so every other option still needs it.
- *B. A, plus Claude on Amazon Bedrock as the explanation layer.* The code
  computes the evidence. Claude explains it and proposes fixes, with
  citations. One tool registry on the 9.3 package serves the Converse tool
  loop and a local stdio MCP server. A read-only role also holds
  `bedrock:InvokeModel`. Estimates use Claude API list prices plus the 10%
  regional premium on Bedrock endpoints, and the Bedrock prices themselves
  are unverified:
  - a run review, single-shot on Haiku 5.5 (about 40k tokens in, 2k out):
    about $0.005;
  - a failure triage as a tool loop (about 150k tokens in, 5k out): about
    $0.02 on Haiku, about $0.39 on Sonnet 5.5;
  - an eval replay of about 30 runs on Haiku: about $0.60.

  It gives up deterministic output, adds a role and a model-provider
  dependency, and carries injection and leak risks that must be engineered
  down. The effort is about 8 PRs.
- *C. Managed AIOps*: a third-party SaaS (Datadog Bits AI, PagerDuty AIOps,
  Grafana Cloud's assistant) or AWS CloudWatch investigations. SaaS needs a
  vendor account and API key and ships data out, which is the ground on which
  ADR 0021 rejected Grafana Cloud. None of them see the git run records or
  the local Spark logs. CloudWatch investigations has a quota of 150 AI
  investigations a month and 2 at a time, and a per-investigation fee that is
  unverified. It also leans on CloudTrail, and no trail exists (ADR 0023,
  item 14). It is configuration, not engineering, so it shows little in a
  portfolio. It is worth a later comparison.
- *D. B, but the Anthropic API directly, or Claude Platform on AWS.* The same
  models, at global prices 10% below Bedrock regional. It needs a stored API
  key, where ADR 0021's security argument prefers IAM with no credential.
  Direct API spend is outside AWS Budgets and Cost Explorer, so the cost
  guardian cannot see it. The auth model of Claude Platform on AWS for this
  use is unverified.

**The tensions that decide.**

*Security against usefulness.* An explanation needs log reads, and logs are
attacker-shaped text. This is resolved structurally: no write tools, a
read-only role, account masking before any prompt, logs passed as quoted
data, and an output validator.

*Cost against reasoning quality.* A Sonnet triage costs about as much as a
100M run (about $0.37, ADR 0023). This is resolved by computing the deltas in code,
using Haiku by default, moving to Sonnet only on an eval result, and a hard
token cap per run and per month.

*Operational Excellence: determinism against an LLM.* Rules gate and the
model never gates. The eval score is the acceptance test.

Reliability needs little deciding: the agents are fail-open, run after the
destroy, and sit outside the critical path. The same holds for Performance
and Sustainability. Latency does not matter after a run, and fewer tokens are
better.

## Decision

**Option B, built on A.** The decisions below include the user's two answers
of 2026-11-08.

**User decisions (2026-11-08).**

1. The three changes below are accepted: a local trigger first (not
   EventBridge), reviews in their own files (not in the run record), and no
   AI action that changes AWS.
2. The monthly AI spend ceiling is $2, enforced in code.

**1. The principle.** Rules detect, GenAI explains and proposes, a human
approves.

**2. Five roles, built in this order.**

1. Run reviewer: report only.
2. Failure triage: a draft issue or PR body written to a file.
3. Pre-flight: rules in `preflight()` that may block, plus a model summary.
   The block is a rule. It is never a model verdict.
4. Cost guardian: the estimate against the posted cost after `--cost-only`,
   and a check that nothing is left running. It proposes the exact clean-up
   commands and never runs them.
5. DQ analyst: report only.

**3. Model.** Claude on Amazon Bedrock through the Converse API with tool
use. The model is not pinned in this ADR. The default family is Haiku, and
the eval decides any move to Sonnet. Bedrock Agents, AgentCore and Bedrock
Guardrails are not used: each adds managed surface or per-use fees for little
gain over a loop of about 200 lines.

**4. Tools.** One registry built on the 9.3 package.

- New tools: run-scoped log extraction (a named source, error lines, a time
  window and size caps), named PromQL from a fixed query set, the Step
  Functions history, and per-query Athena stats.
- The same grammar rules as ADR 0024: no free-text queries.
- Exposed in-process to the runner and as a local stdio MCP server, the
  project's first. There is no network MCP endpoint.
- The new tools are not reachable from the console API.

**5. Trigger.** Local and fail-open. At the end of a Step Functions
execution three inputs do not exist yet: the run record and the DQ verdict
(written afterwards by the laptop's collector, `exercise.sh` L369 to L376),
the Spark driver logs (saved only locally, with `dev-compute` already
destroyed), and the cost (a day later, `--cost-only`). An AWS-side Lambda
would review a run it cannot see. So the reviewer is a step that `exercise.sh`
calls after the destroy and the account check, never before. `--no-review`
turns it off, and `make review RUN=<id>` runs it by hand. EventBridge to
Lambda is deferred (see "Revisit if").

**6. Identity.** A new role, `cerberus-ops-agent`, in `dev-standing`.

- Grants: read-only Step Functions, AMP query, CloudWatch metrics, logs read
  on the named log groups, Athena `GetQueryExecution`, budgets and quotas
  read, `ce:GetCostAndUsage` (cost guardian only, a fixed number of calls),
  and `bedrock:InvokeModel` on named inference profiles.
- Assumed by `cerberus-admin`. There is no Bedrock grant on `cerberus-admin`.
- The CI role manages exactly the two console role names today (`github_oidc`,
  Sid `ManageConsoleIamRoles`), so this role needs a `github_oidc` extension
  and a local first apply by the user, who also enables Bedrock model access.

**7. Guardrails.**

- Evidence-or-silence, enforced by code: each claim must cite an evidence id
  that the tools returned, and the validator drops uncited claims.
- Logs are wrapped as data. The system prompt and the tool design ignore any
  instructions inside them.
- Account IDs and ARNs are masked before any prompt and before any file
  write.
- Token caps per call, per run and per month, enforced in code. The monthly
  AI spend ceiling is $2.
- Every action that leaves the laptop needs human approval. No AI action
  changes AWS. The safe-action list is local only: write the review files,
  post a Grafana annotation (the pattern of ADR 0022, J5), and write a draft
  issue or PR body to a file.

**8. Outputs.**

- The review file pair, `observability/scale/reviews/<run-id>.json` and
  `.md`. The run record stays untouched: it is the deterministic oracle for
  Phase 12 parity and the console fixtures, so nondeterministic text must not
  enter it.
- A Grafana annotation tagged `cerberus-ai`, shown in an "AI review"
  annotation-list panel on dashboard 1.
- Two-layer text: a 3-line plain summary for any department, then engineer
  detail with citations.

**9. Evaluation.** Replay the six labelled incidents plus at least 3 clean
runs, 3 repeats each.

- Score: incidents found, cited-claim validity, and false findings on clean
  runs.
- Proposed bar: at least 5 of 6 incidents, 100% of claims cited, and at most
  1 false finding across the clean runs.
- Fixtures are masked excerpts. The generator-commit case expects "not
  found".

**10. Placement.** Phase 14. It starts after Phase 10. It is numbered 14 so
that Phases 11 to 13 keep the numbers cited in the accepted ADR 0019, the
README and the checkpoint.

**Rejected.**

- Option A alone: it leaves the cross-layer explanation, the user's actual
  ask, to the owner. It stays as the deterministic core of option B.
- Option C: it cannot see the run records or the local logs, and it adds a
  vendor.
- Option D: it adds an API key and makes spend invisible to the budget and
  the cost guardian.
- EventBridge to Lambda as the first trigger: the Lambda cannot see the run
  record, the logs or the cost (decision 5).
- Writing the review into the run record (decision 8).
- Any model-driven action on AWS, including a model verdict that blocks
  pre-flight, and any AWS-changing "safe action" (decisions 2 and 7).

## Consequences

**Good**

- A cross-layer explanation for every run, at about a cent (an estimate; the
  tokens per review are measured in build).
- $0 idle, with no standing compute, endpoint or provisioned throughput.
- Evidence stays in the account's IAM model: no stored credential, and spend
  on the AWS bill where the cost guardian can see it.
- One tool registry serves the agent, MCP and, later, Go.
- The eval gives a measured score, not a demo claim.

**Given up**

- Nondeterministic text, kept out of the run record.
- A new role and a local first apply.
- Dependence on Bedrock model availability.
- Agents only for runs started from the laptop.
- A small eval set (n is about 9), so the score is noisy. Repeats are
  reported with their spread.
- Spend that may not be covered by credits (unverified), and that counts
  against the gross budget either way.
- Residual prompt-injection risk from log text, accepted and reduced by
  design (no write tools, data framing, the validator).

**To confirm in build**

- Bedrock prices, model IDs and whether Haiku 5.5 and Sonnet 5.5 are offered
  in us-east-1 (all unverified).
- The model access and Marketplace subscription steps, run by the user.
- Whether AWS credits cover Bedrock Claude (unverified; community reports say
  some Marketplace-billed models are not covered).
- The Python MCP SDK version and maturity (unverified). The in-process path
  does not depend on MCP.
- The real tokens per review.
- The per-investigation fee of CloudWatch investigations (unverified).

**Revisit if**

- A scheduled path returns: EventBridge on Step Functions `FAILED`,
  `TIMED_OUT` or `ABORTED` to a Lambda.
- Run records move to S3.
- AI spend exceeds the monthly cap.
- Phase 12 ports the tools to Go: keep the registry contract.
- CloudTrail is enabled: then CloudWatch investigations becomes a fair
  comparison.
