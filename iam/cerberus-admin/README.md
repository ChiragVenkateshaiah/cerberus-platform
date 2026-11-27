# cerberus-admin's IAM policies

_7.3 — least-privilege IAM review, repaying Phase 0's `AdministratorAccess`
shortcut._

`cerberus-admin` (the human-operator IAM user created by hand in 0.2) ran
with `AdministratorAccess` from Phase 0 through the end of Phase 6. This
directory holds the six customer-managed policies that replace it (plus two
demo-console policies added in 9.2, see Files), generated
from this project's actual, complete CloudTrail history rather than guessed
from the Terraform code.

## Why these aren't Terraform-managed

Every other IAM resource in this project (`terraform/modules/iam`) is
Terraform-managed. These policies deliberately are not — managing
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

Since 9.2, `cerberus-admin` holds `iam:CreatePolicy` and
`iam:CreatePolicyVersion` on `policy/cerberus-ci-apply-*` only, for the CI
console policy. It still cannot touch `cerberus-admin-*` policies or its own
user.

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
| `cerberus-admin-console-edge.json` | Demo console, standing edge (9.2): site bucket, workgroup `cerberus_platform_console`, `cerberus-console-*` Lambda, CloudFront (create and change only with the `Project` tag), Cognito user pools |
| `cerberus-admin-console-host.json` | Demo console, session host (9.2): EC2 describe, tag-scoped terminate, security group ingress, AMI alias, Session Manager, instance profile and `PassRole` to EC2 for `cerberus-console-grafana*`, and `policy/cerberus-ci-apply-*` management |
| `cerberus-admin-launch.json` | Launch day (17.3a, [ADR 0030](../../docs/adr/0030-launch-day.md) Decision 14), the `dev-launch` root: CloudFront public key, key group, Function and KeyValueStore, KVS data plane, vended log delivery, CloudWatch Logs v2 delivery, `cerberus-platform-launch-*` buckets, `parameter/cerberus/launch/*`, instance profile and `PassRole` to EC2 for `cerberus-launch-*`, Spot cancel. Temporary: detach after 17.9 |

### Placeholder and size

The two console files hold `<ACCOUNT_ID>` instead of the account ID, because
this repo is public. Render a file before the root paste:

```
ACCT=$(AWS_PROFILE=cerberus-admin aws sts get-caller-identity --query Account --output text)
sed "s/<ACCOUNT_ID>/$ACCT/g" iam/cerberus-admin/policies/cerberus-admin-console-edge.json > /tmp/edge.json
sed "s/<ACCOUNT_ID>/$ACCT/g" iam/cerberus-admin/policies/cerberus-admin-console-host.json > /tmp/host.json
```

IAM limits a managed policy to 6,144 characters and does not count
whitespace. Check the counted size with
`jq -c . FILE | tr -d ' \n\t' | wc -c`. The file size with whitespace is
larger and is not the limit.

### Launch policy (17.3a): root paste and detach

`cerberus-admin-launch.json` is a new ninth policy. Nothing in an existing
file changes. Counted size: 5,139 of 6,144 characters (5,081 before Decision 15). It holds no Deny, and
`cerberus-admin` has 8 of 10 managed-policy slots used, so the attach fits.
Role create, tag and policy actions for `cerberus-launch-*` are already
covered by `IamRoleMgmt` (`role/cerberus-*`, no permissions boundary).
`ec2:Describe*` (so `DescribeSpotInstanceRequests`), `RunInstances`,
`CreateServiceLinkedRole` and the tag-scoped terminate also exist already.

Root paste, by Thursday 2026-11-26 evening IST (fallback at Friday noon IST
is in the ADR). Render as `cerberus-admin`, then create and attach in the
root console. No root access key is used:

```
export AWS_PROFILE=cerberus-admin
ACCT=$(aws sts get-caller-identity --query Account --output text)
F=$(mktemp)
sed "s/<ACCOUNT_ID>/${ACCT}/g" iam/cerberus-admin/policies/cerberus-admin-launch.json > "$F"
jq -c . "$F" | tr -d ' \n\t' | wc -c        # expect 5139, limit 6144
cat "$F"
```

1. Sign in to the console as root. Open IAM, Policies, Create policy, JSON.
2. Paste the printed JSON. Name the policy `cerberus-admin-launch`.
3. Open Users, `cerberus-admin`, Add permissions, Attach policies directly.
   Attach `cerberus-admin-launch`.
4. Sign out of root. In the shell, run `rm -f "$F"`.

Then check, as `cerberus-admin`, in the same shell (so `ACCT` is set). Each
line must print `allowed`, except where noted:

```
P="arn:aws:iam::${ACCT}:user/cerberus-admin"
aws iam simulate-principal-policy --policy-source-arn $P --action-names cloudfront:CreatePublicKey cloudfront:CreateKeyGroup cloudfront:CreateFunction cloudfront:CreateKeyValueStore cloudfront:ListFunctions --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names cloudfront:PublishFunction --resource-arns "arn:aws:cloudfront::${ACCT}:function/cerberus-launch-x" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names cloudfront-keyvaluestore:PutKey cloudfront-keyvaluestore:UpdateKeys --resource-arns "arn:aws:cloudfront::${ACCT}:key-value-store/x" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names cloudfront:AllowVendedLogDeliveryForResource --resource-arns "arn:aws:cloudfront::${ACCT}:distribution/E1" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names logs:PutDeliverySource logs:PutDeliveryDestination --resource-arns "arn:aws:logs:us-east-1:${ACCT}:delivery-source:cerberus-launch-x" "arn:aws:logs:us-east-1:${ACCT}:delivery-destination:cerberus-launch-x" --query 'EvaluationResults[].[EvalActionName,EvalResourceName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names logs:DescribeDeliveries logs:DescribeConfigurationTemplates ssm:DescribeParameters ssm:DescribeInstanceInformation freetier:GetFreeTierUsage --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names s3:PutBucketPolicy s3:CreateBucket s3:ListBucketMultipartUploads s3:PutMetricsConfiguration s3:GetMetricsConfiguration --resource-arns arn:aws:s3:::cerberus-platform-launch-x --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names s3:PutObjectTagging s3:GetObjectTagging s3:AbortMultipartUpload --resource-arns arn:aws:s3:::cerberus-platform-launch-x/k --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names ssm:PutParameter ssm:GetParameter ssm:DeleteParameter ssm:AddTagsToResource --resource-arns "arn:aws:ssm:us-east-1:${ACCT}:parameter/cerberus/launch/cookies" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names iam:CreateInstanceProfile iam:AddRoleToInstanceProfile --resource-arns "arn:aws:iam::${ACCT}:instance-profile/cerberus-launch-x" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names iam:UntagRole iam:ListRoleTags iam:UpdateRole --resource-arns "arn:aws:iam::${ACCT}:role/cerberus-launch-x" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names iam:PassRole --resource-arns "arn:aws:iam::${ACCT}:role/cerberus-launch-x" --context-entries ContextKeyName=iam:PassedToService,ContextKeyValues=ec2.amazonaws.com,ContextKeyType=string --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
aws iam simulate-principal-policy --policy-source-arn $P --action-names ec2:CancelSpotInstanceRequests --resource-arns "arn:aws:ec2:us-east-1:${ACCT}:spot-instances-request/sir-1" --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
```

Must be `implicitDeny` (the scope holds): `cloudfront:PublishFunction` on
`function/cerberus-console-x`, `s3:PutBucketPolicy` on
`cerberus-platform-bronze-${ACCT}`, `ssm:PutParameter` on
`parameter/cerberus/other`, `iam:PassRole` on `role/cerberus-x` with
`iam:PassedToService=ec2.amazonaws.com`, `iam:AttachUserPolicy` on
`user/cerberus-admin`, `iam:CreatePolicyVersion` on
`policy/cerberus-admin-launch`, and `cloudfront:UpdateDistribution` on a
distribution without the `Project` tag (no `aws:ResourceTag/Project` context).

Detach only after `launch-check` is 0: stage 2 needs this policy. First
confirm that no `cerberus-launch-*` role remains
(`aws iam list-roles --query "Roles[?starts_with(RoleName,'cerberus-launch-')].RoleName"`).

Detach after 17.9 (the cost read and the final `launch-check` of 0): in the
root console, Users, `cerberus-admin`, remove `cerberus-admin-launch`.

Deleting the policy is optional; the JSON file stays as the audit trail.

Why some grants are wide:

- `ec2:CancelSpotInstanceRequests` is not tag-scoped. The request ID
  (`sir-*`) does not exist before launch, and the cancel is a cleanup action
  on a temporary policy. It can only cancel Spot requests, not terminate
  instances.
- `logs:*Delivery` on `delivery:*`: a delivery ARN holds a generated ID, so
  it cannot carry the `cerberus-launch-` prefix. The source and destination
  ARNs stay prefixed.
- `cloudfront:AllowVendedLogDeliveryForResource` on `distribution/*`: the
  distribution ID does not exist until the distribution is created, so the
  ARN cannot be named. The action only allows log delivery from a
  distribution; it cannot change one.

Risk: `cerberus-admin` is already admin-equivalent. `IamRoleMgmt` (no
permissions boundary) plus `sts:AssumeRole` on `role/cerberus-*` lets it
create an admin role and assume it. So "cannot change its own policies" holds
for direct calls only. `PassLaunchRoleToEc2` adds one more path to the same
end, on EC2. The detach after 17.9 removes that path only; the older paths
stay. The fix is a permissions boundary on `IamRoleMgmt`, which needs its own
decision.

`SecureString` needs no KMS grant with the default `aws/ssm` key ([Parameter
Store access](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-access.html)).
Omit `--key-id` and use the standard tier (4,096 bytes maximum). Do not call
`kms:DescribeKey`; it is denied. The 17.6 smoke confirms it.

For `simulate-custom-policy`, pass one statement per input; an input over
2,000 characters is rejected.

Two limits of the checks. `simulate-principal-policy` does not model the
request tags on `CreateDistribution`. The KeyValueStore ARN uses an ID, not
the name, so that statement uses `key-value-store/*`.

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
- **2026-10-03 (7.7):** `cerberus-admin-iam-and-governance` gained three
  Amazon Managed Service for Prometheus (AMP) Sids for
  [ADR 0016](../../docs/adr/0016-prometheus-for-eks-spark.md):
  `AmpWorkspaceAccount` (`aps:CreateWorkspace`, `aps:ListWorkspaces`, on
  `*` because neither action supports a resource type), `AmpWorkspaceMgmt`
  (describe/delete, alias, tags, and the retention setting) and `AmpQuery`
  (`QueryMetrics`, `GetSeries`, `GetLabels`, `GetMetricMetadata`). The
  last two are scoped to `workspace/*` in `us-east-1`. Action names were
  checked against AWS's service reference and against the provider source.
  `aws_prometheus_workspace`'s read always calls
  `DescribeLoggingConfiguration`, so that action is included even though
  no logging is configured. `iam:simulate-custom-policy` showed the 15
  intended actions allowed. It also showed `RemoteWrite` (the in-cluster
  agent's IRSA role holds that), the logging/resource-policy/rule-group/
  alert-manager writes, `CreateScraper` and every other region all denied.
  The two new IRSA roles need nothing here: `IamRoleMgmt` already covers
  `cerberus-*` roles with inline policies.
- **2026-10-03 (7.7, second paste):** added `AmpTagOnCreate`
  (`aps:TagResource` on `arn:aws:aps:us-east-1:131715059025:*`).
  The first local apply 403'd: a tagged `CreateWorkspace` (and
  `default_tags` always tags it) also checks `aps:TagResource` against the
  workspaces *collection* ARN. That ARN isn't in the Service Authorization
  Reference, and `iam:simulate-custom-policy` can't evaluate it at all (it
  returns `implicitDeny` even for `"Resource": "*"`), so the live apply is
  the only verification. The console's policy validator also rejects that
  ARN literally (an error, not a warning), so the grant uses the
  region/account wildcard instead. It's `TagResource` only, and the
  workspace is this account's only AMP resource. Nothing was orphaned: the 403 came before any
  workspace existed. `cerberus-ci-apply` got the same grant in
  `terraform/modules/github_oidc`.
- **2026-10-25 (8.10):** `cerberus-admin-orchestration` gained
  `CloudwatchMetricsRead` (`cloudwatch:GetMetricData`,
  `cloudwatch:GetMetricStatistics`, `cloudwatch:ListMetrics`), read-only,
  for the local Grafana's Step Functions panel
  ([ADR 0022](../../docs/adr/0022-live-observability-for-a-recorded-run.md)).
  On `*` because these three actions do not support resource-level
  permissions. Pushed as a new default policy version from the root
  console, the path described above. Verified live afterwards:
  `list-metrics` on `AWS/States` and `get-metric-data` (the Grafana
  panel's call) succeeded where they had returned AccessDenied.
- **2026-10-27 (9.2):** root created two customer-managed policies,
  `cerberus-admin-console-edge` and `cerberus-admin-console-host`, and
  attached both to `cerberus-admin` (now 8 of 10 managed policies). They
  cover the demo console's standing edge and its per-session host
  ([ADR 0024](../../docs/adr/0024-demo-console.md)). Verified live
  afterwards. Reads that had returned AccessDenied now succeed:
  `cloudfront list-distributions`, `cognito-idp list-user-pools`,
  `ec2 describe-managed-prefix-lists` (CloudFront origin-facing),
  `ec2 describe-images`, `ssm get-parameter` (the AL2023 arm64 AMI alias)
  and `lambda get-account-settings`. `iam:simulate-principal-policy` on
  `user/cerberus-admin` matched expectations. `CreateDistribution` and
  `CreateVpcOrigin` are allowed with the `Project` request tag, and
  `CreateDistribution` is denied without it. `TerminateInstances` on an
  untagged instance is denied. `AdminCreateUser` is allowed and
  `AdminSetUserPassword` is denied. `CreatePolicyVersion` is denied on
  `policy/cerberus-admin-console-edge` and allowed on
  `policy/cerberus-ci-apply-console`. `PassRole` of
  `cerberus-console-grafana` to EC2 is allowed, and
  `aps:UpdateWorkspaceConfiguration` on the workspace is allowed. The CI
  role's side is recorded in the plan's outcome section
  ([docs/plans/2026-10-27-console-iam-prerequisites.md](../../docs/plans/2026-10-27-console-iam-prerequisites.md)).
- **2026-11-09 (9.2, standing edge, plan A1 and risk 10):**
  `cerberus-admin-console-edge` gained two statements. `ApiGatewayTags`
  allows `apigateway:GET`, `POST` and `DELETE` on
  `arn:aws:apigateway:us-east-1::/tags/*`: the first local apply of the
  standing edge failed on `CreateApi` with `AccessDenied` on
  `/tags/arn:aws:apigateway:us-east-1::/v2/apis/*`, so creating a tagged
  HTTP API needs it. `HttpApiLogDelivery` allows `logs:CreateLogDelivery`,
  `GetLogDelivery`, `UpdateLogDelivery`, `DeleteLogDelivery` and
  `ListLogDeliveries` on `*` (these actions take no resource ARN), for the
  stage's access log. `iam simulate-principal-policy` showed all five as
  `implicitDeny` before the change. A second apply then failed on
  `CreateStage` with `AccessDenied` on `apigateway:TagResource` for
  `/apis/<id>/stages`, so a third statement, `ApiGatewayStageTags`, allows
  `apigateway:TagResource` and `UntagResource` on
  `arn:aws:apigateway:us-east-1::/apis/*`. Counted size after the change:
  4,730 of 6,144 characters. `cerberus-ci-apply-console` does not get either
  statement: CI changes the API's tags or the stage's log settings only
  when they change ([the standing-edge plan](../../docs/plans/2026-11-02-standing-edge.md)).
- **2026-11-20 (9.7, PR 2, ADR 0026 finding A3):**
  `cloudwatch:DescribeAlarms` on `*` (the action has no resource-level scoping,
  so the alarm-ARN grant in `cerberus-admin-orchestration` never matched it)
  for the owner's read-back of the live alarms. `iam simulate-principal-policy`
  showed `implicitDeny` before the paste. `cerberus-ci-apply` needs nothing: it
  already allows the alarm actions on `cerberus-*` and `DescribeAlarms` on `*`.
  **Moved 2026-11-25:** the grant first sat in `cerberus-admin-console-edge` as
  `AlarmsRead`. The root console refused to save that file ("The policy failed
  legacy parsing"): its `ApiGatewayStageTags` statement uses
  `apigateway:TagResource` and `UntagResource`, which the editor flags as
  invalid actions (lines 195-196, Errors: 2). Instead the action is now in the
  `CloudwatchAccount` statement of `cerberus-admin-orchestration` (3,066 of
  6,144 counted characters); `console-edge` is back to 4,730. The paste is not
  done yet; this line is updated when it is. The `ApiGatewayStageTags` actions
  are an open question: AWS lists tagging under `apigateway:PATCH`, `POST` and
  `PUT`, so the statement needs a corrected grant before `console-edge` can be
  pasted again.
- **2026-11-20 (10.2d, [ADR 0021](../../docs/adr/0021-pipeline-status-and-alerting.md)
  amendment):** `cerberus-admin-iam-and-governance` gains `aps:RemoteWrite` in
  the statement now named `AmpQueryAndStatusWrite` (was `AmpQuery`). It stays
  on `workspace/*` in `us-east-1`; no new ARN line. The pipeline status
  publisher (`observability/status/publish.py --send`) signs its remote-write
  as `cerberus-admin`. Counted size after the change: 4,100 of 6,144
  characters. The paste is pending: push the file as a new default policy
  version from the root console, the path described above, then check
  `aws iam simulate-principal-policy ... --action-names aps:RemoteWrite`
  returns `allowed`. Until then `exercise.sh` preflight warns and the status
  publish fails open. This line is updated when the paste is done.
- **2026-11-21 (10.4b, [ADR 0021](../../docs/adr/0021-pipeline-status-and-alerting.md)
  amendment):** `cerberus-admin-iam-and-governance` gains, in
  `AmpQueryAndStatusWrite`, the AMP rule and Alertmanager actions:
  `aps:CreateRuleGroupsNamespace`, `PutRuleGroupsNamespace`,
  `DescribeRuleGroupsNamespace`, `DeleteRuleGroupsNamespace`,
  `ListRuleGroupsNamespaces`, `CreateAlertManagerDefinition`,
  `PutAlertManagerDefinition`, `DescribeAlertManagerDefinition`,
  `DeleteAlertManagerDefinition`, and the three tag actions
  (`ListTagsForResource`, `TagResource`, `UntagResource`). The statement's
  `Resource` is now a list: the existing `workspace/*` line and
  `arn:aws:aps:us-east-1:*:rulegroupsnamespace/*` (the rule-group actions take
  a `rulegroupsnamespace` ARN; the account part is `*`, so the file gets no new
  account-ID line). Counted size after the change: 4,511 of 6,144 characters.
  The paste is pending. It is needed for the owner's own describe and put of
  rule groups and for the first local `make standing-apply` of 10.4b (CI's
  role cannot widen its own policy, so the owner applies first). One paste of
  this file also carries the 10.2d `aps:RemoteWrite` change above. The steps
  are in [observability/alerts/README.md](../../observability/alerts/README.md#putting-the-rules-live-owner).
  This line is updated when the paste is done.
- **2026-11-25 (17.3a, [ADR 0030](../../docs/adr/0030-launch-day.md) Decision 14):**
  new file `cerberus-admin-launch.json` (ninth slot), counted size 5,081 of
  6,144 characters. The `console-edge` file is not edited. Every action name
  was checked against the Service Authorization JSON for `cloudfront`,
  `cloudfront-keyvaluestore`, `logs`, `s3`, `ssm`, `iam`, `ec2` and
  `freetier`. The paste and the detach after 17.9 are pending; this line is
  updated when they are done.
- **2026-11-26 (17.1, ADR 0030 Decision 15):** `LaunchBuckets` gained
  `s3:PutMetricsConfiguration` and `s3:GetMetricsConfiguration`; counted size
  5,139. Root pasted and attached the policy on 2026-11-26; the
  `simulate-principal-policy` checks printed `allowed`. A pre-paste
  `simulate-custom-policy` check must test one statement only (for example
  `jq -c '{Version, Statement: [.Statement[] | select(.Sid=="LaunchBuckets")]}'`):
  that API refuses a policy longer than 2,000 characters. Detach after 17.9 is
  pending.
