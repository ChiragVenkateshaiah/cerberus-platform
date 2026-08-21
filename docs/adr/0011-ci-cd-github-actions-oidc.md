# 11. CI/CD: GitHub Actions + OIDC, and splitting envs/dev

Date: 2026-08-21

## Status

Proposed

## Context

Phase 5's goal ([plan.md](../plan.md#phase-5--cicd)) is "no manual `apply`
-- changes ship through a pipeline," with plan.md's stack line naming AWS
CodePipeline and 5.1/5.2 naming the concrete behavior: `terraform plan` on
PR, `apply` on merge. Working through *what actually runs that* surfaced
that plan.md's named stack doesn't fit the behavior it's paired with:
CodePipeline is a merge/branch-triggered continuous-delivery tool, not
built around reacting to a GitHub pull request the way 5.1 describes.
GitHub Actions is -- the repo already lives on GitHub, and a PR-triggered
check is exactly what its `pull_request` event exists for. This ADR
follows the same pattern 0005/0009 did: make the inherited stack line a
reasoned decision rather than a carried-over assumption, this time because
investigating it surfaced that the assumption doesn't actually fit.

**A second, more consequential problem surfaced while designing what CI
would actually plan/apply against:** `terraform/envs/dev` is one root
module with one state file, holding both the resources that cost nothing
sitting idle (S3, IAM, Glue, Athena, the ingestion Lambda, the
orchestration layer -- ECR/ECS task defs/Step Functions) and the
resources ADR 0007/0009 deliberately keep destroyed between exercises
(VPC's NAT Gateway, EKS, Spark Operator, the Spark job's service account,
cerberus-spark's IRSA role). A naive `terraform apply` on every merge
would try to reconcile the *whole* graph against whatever's declared --
including recreating the entire EKS/VPC-NAT/Spark stack from scratch on
every single merge, since it's destroyed more often than not. That
directly breaks the cost/spin-up discipline held since Phase 3, and no
amount of GitHub Actions configuration fixes it on its own -- the state
itself has to stop mixing the two lifecycles.

Working the two decisions through the Well-Architected pillars (per the
method in checkpoint.md's reference section):

| Pillar | What it asks of these decisions |
|---|---|
| **Cost Optimization** | The deciding pillar for the state split, not the tool choice. CI applying the whole root on every merge would create NAT Gateway + EKS (~$0.10/hr control plane alone) on every single merge to main -- a portfolio project's commit cadence turned into a standing bill. Splitting the state so CI only ever touches the always-free-or-fixed-cost half removes this risk structurally, not by convention or a comment nobody has to obey. |
| **Security** | The deciding pillar for the auth mechanism. OIDC federation (no long-lived AWS keys stored in GitHub at all) is the only option consistent with this project's identity discipline since 1.6 -- every role so far is assumed via STS/IRSA/a service principal, never a long-lived key. A second, repo-being-public consideration: `terraform plan` has to run on every PR to be useful as a check, including PRs from forks -- a single CI role with write permissions trusted for any branch/PR would hand a fork's PR the ability to mutate real AWS infrastructure. This is what forces two roles, not one (see Decision). |
| **Reliability** | A cross-state split introduces two new one-directional data dependencies (`terraform_remote_state` reads: dev-compute reading dev-standing's `orchestration_transform_role_arn` and a handful of VPC/bucket outputs) where there were previously none -- a real, if modest, new failure mode (a stale or unreadable standing state would block a compute-side plan). Weighed against the alternative -- a single state where a human's local `terraform apply` without `-target` could recreate the whole compute stack by accident, a mistake this project has already made once during 3.7's targeted-destroy discovery -- the split is the more reliable design, not less. |
| **Operational Excellence** | Splitting state adds a second root module and a second Makefile target family to remember (`standing-*` vs `compute-*`) -- genuine new operational surface. Offset by what it buys: CI's blast radius becomes self-evident from which root a change touches, rather than requiring a human to remember which `-target` flags are safe (the exact class of mistake the Notes/blockers destroy-target list already exists to prevent). |
| **Performance Efficiency** | Not a meaningful factor for either decision at this project's scale -- one PR at a time, a handful of resources per plan. |
| **Sustainability** | Follows Cost, as in every prior ADR here -- not creating a NAT Gateway/EKS control plane per merge is also not burning compute for no reason. |

**The tension worth naming:** this split makes `terraform/modules/vpc` and
`terraform/modules/iam` no longer map 1:1 onto "one concern, one module,"
the convention this project has held since Phase 1 -- each now has a
sibling (`vpc_nat`, `iam_spark`) carved out purely because of *which root
applies it*, not because the underlying resource has a different logical
purpose. That's a real cost of this design, conceded rather than hidden:
the alternative (one `vpc`/`iam` module, and CI always passing an explicit
`-target` list naming only the standing resources) avoids the module split
but reintroduces exactly the fragility problem `ingestion_lambda_role_arn`
and its siblings were built to prevent in 3.7/4.4 -- a target list that
silently goes stale the moment a new standing module is added and nobody
remembers to update the CI config to match. State-level separation makes
the boundary structural instead of a convention a future session has to
remember; this project has already paid for forgetting that convention
twice (3.7, 4.4's `role_arns` false-dependency bug), so the module split is
accepted as the smaller cost.

## Decision

**GitHub Actions, authenticating to AWS via OIDC federation, against a
`terraform/envs/dev-standing` root split out of the old `envs/dev`.**

**The split**, matching this project's existing per-concern module
granularity (`spark_job` already split out of `spark_operator`):

- **`envs/dev-standing`** (CI-managed): `s3_medallion`, `glue_catalog`,
  `athena`, `iam` (trimmed to its 8 non-Spark roles), `vpc` (trimmed to
  the free core -- VPC, subnets, IGW, route tables with no inline NAT
  route, the S3 gateway endpoint), `lambda_ingestion`,
  `orchestration_runner`, `step_functions`, and a new `github_oidc` module
  (the OIDC provider + CI's own IAM roles, described below).
- **`envs/dev-compute`** (human-run only, per exercise, never CI): a new
  `vpc_nat` module (EIP + NAT Gateway + a standalone `aws_route` attaching
  it to dev-standing's private route table -- not an inline route block,
  since that table lives in a different state), `eks`, `spark_operator`,
  `spark_job`, and a new `iam_spark` module holding just `cerberus-spark`'s
  role -- moved out of `iam` because its whole trust policy depends on the
  EKS OIDC provider, making it lifecycle-coupled to compute, not to the
  standing roles.
- The only cross-state reads are one-directional, compute depending on
  standing (`terraform_remote_state`): `vpc_id`, `private_subnet_ids`,
  `public_subnet_a_id`, `private_route_table_id`, `bucket_arns`
  (bronze/silver, for `iam_spark`'s policy), and
  `orchestration_transform_role_arn` (already a standalone IAM output,
  read for `spark_job`'s EKS access entry). No cycle either direction --
  standing never reads anything from compute.
- Both roots dropped the hardcoded `profile = "cerberus-admin"` from their
  provider and backend blocks (envs/dev's own convention until now) --
  CI authenticates via OIDC-injected environment variables, which a
  hardcoded profile literal would silently break. Local runs now need
  `export AWS_PROFILE=cerberus-admin` set in the shell instead of relying
  on the HCL to say so.

**Two IAM roles, not one, because this repo is public:**

- **`cerberus-ci-plan`**: trust policy matches any workflow run in this
  repo (`repo:<owner>/<repo>:*`) -- necessary, since `terraform plan` has
  to check every PR including ones from forks. Permissions are read-only
  across every service `envs/dev-standing` touches, plus read access to
  the Terraform state object and the DynamoDB lock table. A fork's PR can
  therefore never do more than read already-declared infrastructure
  metadata, regardless of what its own (possibly attacker-modified)
  workflow file requests.
- **`cerberus-ci-apply`**: trust policy matches only
  `repo:<owner>/<repo>:ref:refs/heads/main` -- a token with this `sub`
  claim can only be minted by a workflow run whose ref is `main`, which
  for this repo only happens after a direct push or a merged PR, both
  gated behind repo-collaborator write access. This is the role that
  carries create/update/delete permissions, name-prefix-scoped wherever
  the service supports it -- most importantly IAM, where it can manage
  only `cerberus-ingestion*`/`cerberus-transform`/`cerberus-serving`/
  `cerberus-orchestration-*`, never `cerberus-admin`, never the
  compute-side `cerberus-spark`, and never its own `cerberus-ci-*` roles --
  no path to self-escalation.
- The GitHub OIDC token's `sub` claim always names the *base* repository a
  workflow ran in, never a fork's, so the repo-slug match alone already
  excludes fork-originated tokens from ever satisfying either trust
  policy; the `ref:refs/heads/main` condition on `cerberus-ci-apply` is
  what additionally separates "any PR in this repo can plan" from "only a
  push to main can apply."

**Two workflows** (`.github/workflows/terraform-plan.yml`,
`terraform-apply.yml`), both scoped to `terraform/modules/**` and
`terraform/envs/dev-standing/**` only -- a docs-only or article PR never
triggers either. Plan posts its output as a PR comment via the GitHub CLI
(`gh`, using the default `GITHUB_TOKEN`, not a third-party marketplace
action) when the PR originates from this repo, not a fork -- fork PRs get
a read-only default token and the comment step is skipped rather than
failing loudly. No `terraform_version` is pinned in either workflow;
`hashicorp/setup-terraform` resolves latest stable itself, on the same
"verify, don't guess a version number" discipline the 2026-08-17 Spark
image saga established the hard way.

**AWS CodePipeline is explicitly rejected** for this specific job (PR
checks), not as a broader statement about AWS-native CI/CD -- nothing
about `terraform plan` on a GitHub PR needs CodePipeline's own
capabilities, and adopting it here would mean bolting a GitHub source
stage onto a tool oriented around branch-triggered continuous delivery, to
get a PR-check workflow GitHub Actions already does natively.

## Consequences

- **This is the first infrastructure decision in this project's history
  that required a live state migration as part of landing the ADR, not
  just new resources.** `envs/dev`'s existing state (s3_medallion,
  glue_catalog, athena, vpc-core, iam's 8 standing roles,
  lambda_ingestion, orchestration_runner, step_functions -- everything
  currently applied, since EKS/Spark/NAT/cerberus-spark were already
  destroyed as of 4.4's post-live-pass teardown) moves into
  `dev-standing`'s state via `terraform state mv`, address-for-address,
  with zero resource recreation. `dev-compute`'s state starts genuinely
  empty -- the next Spark exercise creates its stack fresh, the same as
  any other spin-up cycle, just from a new root.
- **5.1 is not done until this migration is actually run and verified**
  (`terraform plan` on `dev-standing` comes back showing only
  `github_oidc`'s new resources, `dev-compute` shows a clean fresh-apply
  plan, not an error) -- consistent with this project's standing rule that
  "written and plan-verified" isn't "applied and verified live" (3.2's
  original discipline, repeated at 4.2/4.4). This ADR documents the
  design; the checkpoint records when the migration actually ran.
- **A new attack surface exists that didn't before**: a public GitHub
  repo now has two IAM roles federated to it. Both are scoped tightly
  (plan is read-only; apply is name-prefix-scoped and `ref`-restricted),
  but this is a genuinely new class of risk this project didn't carry
  through Phases 1-4, worth carrying into 7.3's eventual least-privilege
  review rather than treating as closed the day it's built.
- **The `iam`/`vpc` modules' policy scoping in `cerberus-ci-apply` is a
  good-faith first pass, not exhaustively verified against every AWS ARN
  format quirk** (ECS task-definition ARNs in particular don't cleanly
  match a single `cerberus-*` wildcard the way S3/Glue/Lambda ARNs do) --
  conceded up front rather than discovered later, the same shape as ADR
  0009's Spark-on-EKS friction point. Expect real `AccessDenied` fixes
  during the first live `terraform apply` run through `cerberus-ci-apply`,
  the same way 4.4 found six real IAM/config bugs no amount of `plan`
  could have caught.
- **5.4 (green build badge on README)** naturally follows once
  `terraform-plan.yml` has run at least once on a real PR against `main`
  -- left to that subtask, not this one.
- Deferred, not decided against: whether `dev-compute`'s own lifecycle
  (spin up for an exercise, tear down after) should itself eventually gain
  any automation (a manually-triggered `workflow_dispatch` job, say) is
  explicitly out of scope here -- ADR 0007/0009's whole premise is that a
  human decides when an exercise happens, and nothing about Phase 5's goal
  requires automating that decision away.
