# cerberus-admin's IAM policies

_7.3 — least-privilege IAM review, repaying Phase 0's `AdministratorAccess`
shortcut._

`cerberus-admin` (the human-operator IAM user created by hand in 0.2) ran
with `AdministratorAccess` from Phase 0 through the end of Phase 6. This
directory holds the six customer-managed policies that replace it, generated
from this project's actual, complete CloudTrail history rather than guessed
from the Terraform code.

## Why these aren't Terraform-managed

Every other IAM resource in this project (`terraform/modules/iam`) is
Terraform-managed. These six policies deliberately are not — managing
`cerberus-admin`'s own permissions via `cerberus-admin`'s own `terraform
apply` creates a bootstrapping risk: if a self-policy change is wrong, or an
apply is interrupted mid-way, the identity can lock itself out of the very
mechanism needed to fix it. This isn't hypothetical — it happened twice
live during this cutover (see checkpoint.md's 2026-09-29 entry): a bug in
the first draft required root intervention to push a corrected version,
specifically because `cerberus-admin` was never granted permission to
manage its own managed policies (deliberately — see below).

This mirrors `terraform/bootstrap/`'s own justification for managing the
state backend outside of the state it depends on, and is consistent with
`cerberus-admin` itself having never been Terraform-managed (it was
hand-created via CLI in 0.2, same as these policies).

These JSON files are the audit trail — the actual live policies were
created/updated via plain `aws iam create-policy` /
`aws iam create-policy-version`, not `terraform apply`.

## What's deliberately NOT granted

`cerberus-admin` cannot manage its own IAM user or these policies
(`iam:CreatePolicy`, `iam:CreatePolicyVersion`, `iam:AttachUserPolicy`,
`iam:DetachUserPolicy`, etc., scoped to itself) — confirmed via
`iam:simulate-custom-policy` before this cutover went live. Changing
`cerberus-admin`'s own permission boundary is a deliberate root-only
action, not something the identity can do to itself. If one of these
policies ever needs a real change, that requires the same root-console
path used during this cutover (see checkpoint.md).

## Methodology

Each policy's actions were derived from `cerberus-admin`'s complete
CloudTrail history (25,516 events / 241 distinct operations, spanning the
whole project since 2026-07-31 — within the default 90-day Event History,
no CloudTrail trail needed), cross-checked against every Terraform resource
type in this repo, supplemented with the data-plane actions CloudTrail's
management-events-only view doesn't show (S3 object ops, DynamoDB item
ops), and `iam:PassRole` (never its own CloudTrail event) scoped to the
exact 5 services this project's own trust policies actually use.

Every action name and every scoped resource ARN's shape was verified
against AWS's Service Authorization Reference JSON
(`servicereference.us-east-1.amazonaws.com`) — not assumed from CloudTrail's
event names, which sometimes diverge from real IAM action names (e.g. the
event `GetBucketLifecycle` requires IAM action `s3:GetLifecycleConfiguration`,
not `s3:GetBucketLifecycle`). Tested via `iam:simulate-custom-policy`
against a battery of real and deliberately-unrelated resources before ever
attaching anything live, then verified against real `terraform plan` runs
across all three roots (`bootstrap`, `dev-standing`, `dev-compute`) with
`AdministratorAccess` fully detached.

## Files

| Policy | Covers |
|---|---|
| `cerberus-admin-storage.json` | S3 (6 project buckets), DynamoDB lock table |
| `cerberus-admin-analytics.json` | Glue Data Catalog, Athena workgroup |
| `cerberus-admin-compute.json` | Lambda, ECR, ECS, EKS, one scoped KMS key |
| `cerberus-admin-orchestration.json` | Step Functions, EventBridge Scheduler, SNS, CloudWatch, Logs |
| `cerberus-admin-network.json` | EC2/VPC (`Resource: "*"` — most EC2 actions have no resource-level permission support) |
| `cerberus-admin-iam-and-governance.json` | IAM role management (`role/cerberus-*` only), `PassRole`, Well-Architected Tool, budgets/cost anomaly detection, read-only Cost Explorer + tag inventory (added 7.5), CloudTrail self-audit, API Gateway |

## Changes since 7.3

- **2026-10-02 (7.5):** `cerberus-admin-iam-and-governance` gained
  `ce:GetCostAndUsage`, `ce:GetCostForecast`, `ce:ListCostAllocationTags`
  (in `CostExplorer`) and `tag:GetResources` (new `TagCoverageRead` Sid),
  all read-only, for [docs/cost-security-summary.md](../../docs/cost-security-summary.md).
  The write-side neighbours (`ce:UpdateCostAllocationTagsStatus`,
  `tag:TagResources`) stay denied, confirmed via `iam:simulate-custom-policy`.
  Pushed as a new default policy version from the root console, the
  path described above. Verified live afterwards, when
  `ce:GetCostAndUsage` succeeded where it had returned AccessDenied. A
  standing policy-edit IAM user was considered and rejected (see the
  summary's residual risk 3).
