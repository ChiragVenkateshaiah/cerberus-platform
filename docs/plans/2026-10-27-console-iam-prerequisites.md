# Plan: 9.2 IAM prerequisites for the demo console (ADR 0024, build step 2)

Date: 2026-10-27. Planner: Opus. No new ADR: implementation inside ADR 0024 (build step 2) and the ADR 0011 role model. Two deviations are named in section 5.

## User decisions (2026-10-27)

1. Account ID: the `<ACCOUNT_ID>` placeholder goes in new files only. This PR does not scrub existing files.
2. CI grants: a customer-managed policy `cerberus-ci-apply-console`, attached in `github_oidc`. The inline policy is not compacted.
3. The plan is confirmed. Branch `9.2-iam-prerequisites`.

## 1. Question

Which permissions do `cerberus-admin` and `cerberus-ci-apply` need so that every later 9.2–9.5 step can run? Those steps are the spike, the read-only roles, AMP retention, the standing edge and `envs/dev-console`. Where should each grant live, given the IAM size limits?

It is needed now because every later step needs these permissions first. The `cerberus-admin` policy can only change through a root paste. `cerberus-ci-apply` cannot edit its own policy. So both changes come first, as in the ADR 0016 order: root paste, then a local apply, then CI.

## 2. Facts

Repo:
- F1. `cerberus-admin` has six customer-managed policies. The JSON copies are in `iam/cerberus-admin/policies/`. The README says they change only by a root-console paste, and that `cerberus-admin` cannot manage its own policies (`iam/cerberus-admin/README.md`, "What's deliberately NOT granted").
- F2. Gaps in the six policies for the console:
  - The S3 statements list six named buckets and no console bucket (`cerberus-admin-storage.json`).
  - Athena allows only `cerberus_platform` and `cerberus_platform_dq` (`cerberus-admin-analytics.json`).
  - `IamPassRole` does not include `ec2.amazonaws.com`, and there are no instance-profile actions (`cerberus-admin-iam-and-governance.json`).
  - There is no `ec2:TerminateInstances`, `ec2:AuthorizeSecurityGroupIngress` or `RevokeSecurityGroupIngress` (`cerberus-admin-network.json`). `ec2:RunInstances` is already allowed on `*` (`cerberus-admin-compute.json`, `Ec2RunInstancesForNodeGroups`).
  - Lambda has no concurrency actions and no `RemovePermission` (`cerberus-admin-compute.json`).
  - Covered already: AMP `UpdateWorkspaceConfiguration` (`AmpWorkspaceMgmt`), `sts:AssumeRole` on `role/cerberus-*`, `iam:CreateServiceLinkedRole` on `*`, API Gateway `/apis` and `/apis/*`, and log groups `/aws/lambda/cerberus-*` and `/aws/apigateway/cerberus-*`.
- F3. AMP retention is a separate `aws_prometheus_workspace_configuration` resource (`terraform/modules/prometheus_workspace/main.tf`). Both principals already hold `aps:UpdateWorkspaceConfiguration`. Build step 5 needs no IAM change.
- F4. `cerberus-ci-apply` has one inline policy, `cerberus-ci-apply-policy` (`terraform/modules/github_oidc/main.tf`), and no managed policies. It has 26 Sids. `ManageVpcCore` already covers the `subnet/*` and `route-table/*` types, so the console subnet needs nothing new. `ManageLineageApi` already covers the HTTP API. The role cannot write its own policy (`ReadOwnCiIdentity`).
- F5. `dev-standing` sets `default_tags { Project = "cerberus-platform" }` (`terraform/envs/dev-standing/provider.tf`).
- F6. The account ID already appears in about 35 committed files, including all six policy JSONs. It is in git history.

AWS (read-only, `cerberus-admin`, 2026-10-27):
- F7. `list-attached-user-policies` returned 6 policies and `list-user-policies` returned none. The default quota is 10 managed policies per user and 20 per role.
- F8. Policy sizes as IAM counts them (IAM does not count whitespace): `iam-and-governance` 4,068 of 6,144 (the file is 5,954 bytes with whitespace, which is the number ADR 0024 quotes); `compute` 3,122, `orchestration` 3,038, `storage` 2,136, `network` 1,223, `analytics` 1,061.
- F9. The `cerberus-ci-apply` inline policy is 7,060 of the 10,240-character total for inline policies per role.
- F10. AccessDenied for `cerberus-admin` on `iam:ListGroupsForUser`, `iam:GetAccountSummary`, `iam:GetPolicy` (on `ReadOnlyAccess`) and `lambda:GetAccountSettings`. These add to the ADR 0024 F19 list.
- F11. The private subnets are in `use1-az1` and `use1-az2`. us-east-1 does not support VPC origins in `use1-az3`, which is `us-east-1e` in this account.
- F12. `iam simulate-custom-policy` rejects any policy document over 2,000 characters. Simulate one statement per document.

Service Authorization Reference (read 2026-10-27):
- F13. CloudFront: `CreateDistribution` and `CreateVpcOrigin` have no resource type but support `aws:RequestTag`. `distribution` and `vpcorigin` support `aws:ResourceTag`. OAC, cache, origin-request and response-headers policies have resource types but no tag keys; their `Create*` actions and all `List*` actions take `*`. CloudFront ARNs have no region.
- F14. Cognito: every pool action is on `userpool/<id>`, and the ID is generated. `CreateUserPool`, `ListUserPools` and `DescribeUserPoolDomain` take `*`.
- F15. EC2: `TerminateInstances` and `ModifyInstanceAttribute` act on `instance` and support `aws:ResourceTag`. `DescribeImages` and `DescribeManagedPrefixLists` take `*`.
- F16. SSM: the AMI alias parameter ARN has no account: `arn:aws:ssm:us-east-1::parameter/aws/service/ami-amazon-linux-latest/*`.
- F17. VPC origin creation makes the service-linked role `AWSServiceRoleForCloudFrontVPCOrigin`. `cerberus-admin` can already create service-linked roles. The full set of EC2 and ELB reads that `CreateVpcOrigin` needs is not documented officially (unverified); a third-party list names `ec2:DescribeInstances`, `ec2:DescribeInternetGateways` and `elasticloadbalancing:DescribeLoadBalancers`.

Unverified: whether `ReadOnlyAccess` (`cerberus-ci-plan`) covers every CloudFront and Cognito read of the plan refresh; which actions Terraform's CloudFront create-with-tags authorizes.

## 3. Constraints

- $0. IAM and simulation calls are free.
- Public repo: new files must not contain the account ID. Use `<ACCOUNT_ID>` in JSON and `var.account_id` in HCL.
- `cerberus-admin`'s own policies change only by a root paste. `cerberus-ci-apply` cannot widen itself, so the first `dev-standing` apply of this change runs locally as `cerberus-admin`, before the merge.
- `dev-compute` does not change. CI applies only `dev-standing`. `envs/dev-console` is human-run, so CI gets no VPC-origin, EC2-instance or Session Manager permissions.
- Follows ADR 0024 and ADR 0011; contradicts neither.

## 4. Options

`cerberus-admin` (console needs about 6,350 counted characters):
- A. One `cerberus-admin-console` file: does not fit under 6,144 without broad wildcards.
- B. Grow the existing six files: room exists, but grants spread over four files and cannot be detached as one unit.
- C (chosen). Two new files: `cerberus-admin-console-edge` (~4,150) and `cerberus-admin-console-host` (~2,400). `cerberus-admin` goes to 8 of 10 attached policies, each with room for 403 fixes.

`cerberus-ci-apply` (console needs about 3,400 counted characters):
- A. Grow the inline policy: 7,060 + 3,400 > 10,240.
- B. Compact existing inline statements: churn in reviewed grants.
- C (chosen). A customer-managed policy `cerberus-ci-apply-console`, attached to `cerberus-ci-apply` and managed in `github_oidc`. A fourth exception to the module's inline-only convention; `cerberus-admin` needs managed-policy actions on `policy/cerberus-ci-apply-*` only.

## 5. Recommendation

Option C on both sides.
- Tag scoping where supported: CloudFront creates need `aws:RequestTag/Project = cerberus-platform`; CloudFront update/delete need `aws:ResourceTag/Project`; `UntagResource` cannot remove `Project`; EC2 terminate/modify need `aws:ResourceTag/Project`; Session Manager needs `ssm:resourceTag/Project`.
- Name or type scoping where tags are not supported: CloudFront policy types by resource type; Cognito to `userpool/*` in this region (no tag conditions, on purpose).
- `*` only where the service has no resource type (F13–F15).

Deviations from ADR 0024 and its plan step 2 (record in the plan file and README; leave the accepted ADR text as is):
1. Two admin files, not "a seventh policy". The ADR's "5,954 bytes against 6,144" counts whitespace; the counted size is 4,068. The reason for new files: the console needs more room than any one file has.
2. CI grants go in a managed policy, not as statements in the inline policy (F9).

Names fixed for later steps:
- Site bucket: `cerberus-platform-console-<account_id>`.
- Lambda: `cerberus-console-*`.
- Log groups: `/aws/lambda/cerberus-console-*` and `/aws/apigateway/cerberus-console-*`.
- Session instance role and profile: `cerberus-console-grafana*` (in `dev-console`).
- Standing roles: exactly `cerberus-console-cli` and `cerberus-grafana-read`.

## 6. ADR outline

None.

## 7. Build steps

Under Phases.md 9.2. One PR, branch `9.2-iam-prerequisites`.

### Files

1. `iam/cerberus-admin/policies/cerberus-admin-console-edge.json` (new). Account only as `<ACCOUNT_ID>`.

| Sid | Actions | Resource | Condition |
|---|---|---|---|
| `ConsoleSiteBucket` | `s3:*` | `arn:aws:s3:::cerberus-platform-console-<ACCOUNT_ID>` and `/*` | |
| `ConsoleAthenaWorkgroup` | athena `GetWorkGroup, CreateWorkGroup, UpdateWorkGroup, DeleteWorkGroup, ListTagsForResource, TagResource, UntagResource` | `workgroup/cerberus_platform_console` | |
| `ConsoleLambda` | `lambda:*` | `function:cerberus-console-*` | |
| `CloudFrontCreateTagged` | `cloudfront:CreateDistribution, CreateVpcOrigin` | `*` | `StringEquals aws:RequestTag/Project = cerberus-platform` |
| `CloudFrontChangeTagged` | `UpdateDistribution, DeleteDistribution, UpdateVpcOrigin, DeleteVpcOrigin` | `distribution/*`, `vpcorigin/*` | `StringEquals aws:ResourceTag/Project` |
| `CloudFrontReadTagInvalidate` | `GetDistribution, GetDistributionConfig, GetVpcOrigin, ListTagsForResource, TagResource, CreateInvalidation, GetInvalidation, ListInvalidations` | same two | |
| `CloudFrontUntagKeepProject` | `UntagResource` | same two | `ForAllValues:StringNotEquals aws:TagKeys = ["Project"]` |
| `CloudFrontEdgePolicies` | `cloudfront:*` | `origin-access-control/*`, `response-headers-policy/*`, `origin-request-policy/*`, `cache-policy/*` | |
| `ConsoleAccount` | `cloudfront:CreateOriginAccessControl, CreateResponseHeadersPolicy, CreateOriginRequestPolicy, CreateCachePolicy, ListDistributions, ListVpcOrigins, ListOriginAccessControls, ListCachePolicies, ListOriginRequestPolicies, ListResponseHeadersPolicies, ListDistributionsByVpcOriginId`, `elasticloadbalancing:DescribeLoadBalancers`, `lambda:GetAccountSettings` | `*` | |
| `CognitoAccount` | `cognito-idp:CreateUserPool, ListUserPools, DescribeUserPoolDomain` | `*` | |
| `CognitoUserPool` | pool: `DescribeUserPool, UpdateUserPool, DeleteUserPool, GetUserPoolMfaConfig, SetUserPoolMfaConfig`; client: `Create/Describe/Update/DeleteUserPoolClient, ListUserPoolClients`; domain: `Create/Update/DeleteUserPoolDomain`; branding: `Create/Describe/Update/DeleteManagedLoginBranding, DescribeManagedLoginBrandingByClient`; `GetUICustomization, GetLogDeliveryConfiguration`; tags: `ListTagsForResource, TagResource, UntagResource`; users: `AdminCreateUser, AdminGetUser, AdminDeleteUser, AdminDisableUser, AdminEnableUser, AdminResetUserPassword, AdminUserGlobalSignOut, ListUsers` | `arn:aws:cognito-idp:us-east-1:<ACCOUNT_ID>:userpool/*` | |

`AdminSetUserPassword` is left out on purpose: the owner never needs to know a visitor's password.

2. `iam/cerberus-admin/policies/cerberus-admin-console-host.json` (new).

| Sid | Actions | Resource | Condition |
|---|---|---|---|
| `Ec2Read` | `ec2:Describe*`, `ec2:GetManagedPrefixListEntries` | `*` | |
| `Ec2InstanceTagged` | `ec2:TerminateInstances, ModifyInstanceAttribute, ModifyInstanceMetadataOptions` | `arn:aws:ec2:us-east-1:<ACCOUNT_ID>:instance/*` | `StringEquals aws:ResourceTag/Project` |
| `Ec2SecurityGroupIngress` | `AuthorizeSecurityGroupIngress, RevokeSecurityGroupIngress, ModifySecurityGroupRules, UpdateSecurityGroupRuleDescriptionsIngress` | `security-group/*`, `security-group-rule/*` | |
| `AmiAlias` | `ssm:GetParameter, GetParameters` | `arn:aws:ssm:us-east-1::parameter/aws/service/ami-amazon-linux-latest/*` | |
| `SessionManagerTagged` | `ssm:StartSession` | `instance/*` | `StringEquals ssm:resourceTag/Project` |
| `SessionManagerDocAndOwnSessions` | `ssm:StartSession, TerminateSession, ResumeSession` | `arn:aws:ssm:us-east-1::document/SSM-SessionManagerRunShell`, `arn:aws:ssm:us-east-1:<ACCOUNT_ID>:session/${aws:username}-*` | |
| `InstanceProfile` | iam `Create/Delete/GetInstanceProfile, AddRoleToInstanceProfile, RemoveRoleFromInstanceProfile, TagInstanceProfile, UntagInstanceProfile, ListInstanceProfileTags` | `instance-profile/cerberus-console-grafana*` | |
| `PassConsoleRoleToEc2` | `iam:PassRole` | `role/cerberus-console-grafana*` | `StringEquals iam:PassedToService = ec2.amazonaws.com` |
| `CiApplyConsolePolicy` | iam `CreatePolicy, GetPolicy, GetPolicyVersion, ListPolicyVersions, CreatePolicyVersion, DeletePolicyVersion, DeletePolicy, TagPolicy, UntagPolicy, ListPolicyTags, ListEntitiesForPolicy` | `policy/cerberus-ci-apply-*` | |

`ec2:Describe*` on `*`: read-only metadata; an enumerated list risks root-paste rounds for `aws_instance` refresh reads. `CiApplyConsolePolicy` cannot touch `policy/cerberus-admin-*`, so "cannot manage its own policies" holds.

3. `terraform/modules/github_oidc/main.tf`:
- Add `aws_iam_policy.ci_apply_console` (name `cerberus-ci-apply-console`) and `aws_iam_role_policy_attachment.ci_apply_console`. The comment explains F9 and that this is a fourth exception to the inline convention.
- Sids, mirroring the existing style:
  - `ManageConsoleSiteBucket`: `s3:*` on the bucket and `/*`, from `var.account_id`.
  - `ManageConsoleIamRoles`: the `ManageStandingIamRoles` action list minus PassRole, on exactly `role/cerberus-console-cli` and `role/cerberus-grafana-read`.
  - `PassConsoleCliRole`: `iam:PassRole` on `role/cerberus-console-cli` with `iam:PassedToService = lambda.amazonaws.com`.
  - `ManageConsoleLambda`: `lambda:*` on `function:cerberus-console-*`.
  - `ManageConsoleLogGroups`: `logs:*` on the two console log-group patterns.
  - `ManageConsoleAthenaWorkgroup`: `athena:*` on `workgroup/cerberus_platform_console`.
  - CloudFront: the same five distribution and policy-type Sids as the edge file, distribution only, no VPC origin.
  - `CreateConsoleEdgeAndPool`: `*` for the four CloudFront `Create*` policy actions, the three `List*Policies` actions, `cognito-idp:CreateUserPool` and `DescribeUserPoolDomain`.
  - `ManageConsoleUserPool`: the edge `CognitoUserPool` list without any `Admin*User` or `ListUsers` actions. Users stay outside Terraform (ADR 0024, decision 2).
- In the inline `ReadOwnCiIdentity`, add `iam:GetPolicy, GetPolicyVersion, ListPolicyVersions` on `aws_iam_policy.ci_apply_console.arn`. No write actions.
- No new variables. ARNs from `var.account_id` and `var.region`. Measure the managed policy size from `terraform show -json` / rendered JSON (estimate ~3,400).

4. `iam/cerberus-admin/README.md`: six plus two console policies; two rows in the Files table; a "Placeholder and size" note (render command; IAM counts characters without whitespace); a "Changes since 7.3" entry written after the paste with the date and verification results.
5. `docs/plans/2026-10-27-demo-console.md` §7 step 2: a two-line note on the two deviations.
6. After verification: a Phases.md 9.2 progress note ("IAM prerequisites done YYYY-MM-DD (#PR)").

### Pre-paste verification (agent, read-only)

- Render each file with the account ID; check `jq -c . | tr -d ' \n\t' | wc -c` is at most 6,144.
- Run `simulate-custom-policy` one statement per document against the allow/deny list. Expected: CreateDistribution allowed with the tag and denied without; UntagResource of `Project` denied; AdminSetUserPassword denied; PassRole of `cerberus-console-cli` to EC2 denied; CreatePolicyVersion on `policy/cerberus-admin-*` denied and on `policy/cerberus-ci-apply-*` allowed; TerminateInstances on an untagged instance denied.

Result (executor, 2026-10-27): counted sizes are edge 4,216, host 2,363 and the CI managed policy 4,143 (rendered with a dummy account ID), against an estimate of about 3,400 for the CI policy. All are at most 6,144. The inline policy grows by about 125 characters (7,060 to about 7,185 of 10,240). All simulation cases matched their expected result.

### User-run steps (change AWS)

1. Render each file:
   ```
   ACCT=$(AWS_PROFILE=cerberus-admin aws sts get-caller-identity --query Account --output text)
   sed "s/<ACCOUNT_ID>/$ACCT/g" iam/cerberus-admin/policies/cerberus-admin-console-edge.json > /tmp/edge.json
   ```
   Same for `host`.
2. Sign in as root. IAM → Policies → Create policy → JSON. Paste, name `cerberus-admin-console-edge`, create. Repeat for `cerberus-admin-console-host`.
3. IAM → Users → `cerberus-admin` → Add permissions → Attach policies directly. Attach both. Sign out of root.
4. Local apply before the merge, from the PR branch: `export AWS_PROFILE=cerberus-admin; make standing-plan`. Must show exactly 2 to add (`aws_iam_policy.ci_apply_console` and the attachment), 1 in-place change (`aws_iam_role_policy.ci_apply`), nothing else (the Faker-layer replacement is the only accepted extra). Otherwise stop. Then `make standing-apply`.
5. Merge the PR. The CI apply on main must show no `github_oidc` diff.

### Post-paste and post-apply verification (agent, read-only)

- These reads now succeed: `aws cloudfront list-distributions`; `aws cognito-idp list-user-pools --max-results 10`; `aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing`; `aws ec2 describe-images --owners amazon --max-items 1`; `aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`; `aws lambda get-account-settings` (record `ConcurrentExecutions`).
- `aws iam simulate-principal-policy` on `user/cerberus-admin` with the same list, plus `aps:UpdateWorkspaceConfiguration` (allowed).
- `aws iam list-attached-role-policies --role-name cerberus-ci-apply` shows `cerberus-ci-apply-console`.
- `simulate-principal-policy` on `role/cerberus-ci-apply`: allowed `cloudfront:CreateDistribution` (with tag), `cognito-idp:CreateUserPoolClient`, `lambda:CreateFunction` on `cerberus-console-x`, `iam:CreateRole` on `cerberus-grafana-read`; denied `cognito-idp:AdminCreateUser`, `cloudfront:CreateVpcOrigin`, `ec2:RunInstances`, `iam:CreatePolicyVersion` on `policy/cerberus-ci-apply-console`, `iam:CreateRole` on `cerberus-grafana`.

### Risks

1. Hidden authorization checks on first use (CloudFront create-with-tags, Cognito domain, HTTP API access-log delivery `logs:CreateLogDelivery` — unverified). Live tests are build steps 3 and 7. Each admin fix is one root paste; the files keep room.
2. Tag conditions fail closed: `envs/dev-console` must set the same `default_tags`.
3. Local apply from a branch: if the plan shows more than the `github_oidc` diff, stop. Do not use `-target`.
4. `ReadOnlyAccess` coverage for CloudFront/Cognito reads in `cerberus-ci-plan` is unverified; step 7's PR plan will show it.
5. Pre-existing: `cerberus-admin` can create and assume any `cerberus-*` role (part of ADR 0023's `identities` HIGH). No new path here.
6. `ManageConsoleIamRoles` grants `AttachRolePolicy` and `PutRolePolicy` without an `iam:PolicyARN` condition. With `PassConsoleCliRole` and `lambda:*`, CI can give a console Lambda any permissions. This is the same pattern as `ManageStandingIamRoles`. Tighten it in the 9.3 roles step.
7. For later steps: the console subnet must not be in `us-east-1e` (`use1-az3`); ADR 0024's reserved concurrency of 2 needs enough account concurrency. Measured 2026-10-27: the account limit is 10 (see the outcome section).

Sources: IAM and STS quotas; CloudFront VPC origins; CloudFront service-linked roles; AWS Fundamentals VPCOrigin permissions; the Service Authorization Reference JSON (`servicereference.us-east-1.amazonaws.com/v1/{cloudfront,cognito-idp,ec2,ssm,iam}/*.json`).

## Outcome (2026-10-27)

Root created `cerberus-admin-console-edge` and `cerberus-admin-console-host` and attached them to `cerberus-admin` (8 of 10 managed policies). The pre-paste denied reads now succeed, and `simulate-principal-policy` on `user/cerberus-admin` matched every expectation (details in `iam/cerberus-admin/README.md`).

Local apply of `dev-standing` as `cerberus-admin` from a saved plan: "3 added, 2 changed, 1 destroyed". That is the `cerberus-ci-apply-console` policy and its attachment created, and the inline `cerberus-ci-apply-policy` updated in place. The rest is the known Faker-layer churn: layer version 60 replaced by 61, and `cerberus-ingest-payments` moved to the new layer. A re-plan right after showed "No changes".

`cerberus-ci-apply` now has the managed policy attached. Counted sizes: inline 7,206 of 10,240, managed 4,143 of 6,144. `simulate-principal-policy` on the role:

- Allowed: `cloudfront:CreateDistribution` (tagged), `cognito-idp:CreateUserPoolClient`, `lambda:CreateFunction` on `cerberus-console-x`, `iam:CreateRole` on `cerberus-grafana-read`, `GetPolicy` and `ListPolicyTags` on its own console policy.
- Denied: `cloudfront:CreateVpcOrigin`, `cognito-idp:AdminCreateUser`, `iam:CreateRole` on `cerberus-grafana`, `ec2:RunInstances`, `iam:CreatePolicyVersion` on its own console policy.

New finding (replaces the unverified item in risk 7): the account Lambda concurrency limit is 10 (`ConcurrentExecutions` 10, `UnreservedConcurrentExecutions` 10). AWS requires at least 10 unreserved, so ADR 0024's reserved concurrency of 2 for the command Lambda will be rejected. The options are a Service Quotas increase (free) or relying on API Gateway throttling alone. This is to be decided at the standing-edge step.
