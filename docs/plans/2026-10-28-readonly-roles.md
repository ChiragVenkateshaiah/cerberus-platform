# Plan: 9.2 read-only roles, the console subnet and local Grafana on short-lived credentials (ADR 0024, build steps 4 and 5)

Date: 2026-10-28. Planner: Opus. No new ADR and no amendment. This is implementation inside ADR 0024. Two deviations from the demo-console plan are named in section 5. Base branch: `main` at `26ac593` (#124 merged).

User decisions (2026-10-28): plan confirmed as written. PR 4b (the local Grafana switch) is built and verified now on its branch, and merged after the 8.10 take (31 Oct / 1 Nov).

## 1. Question

How do we create `cerberus-console-cli`, `cerberus-grafana-read` and the console subnet in `dev-standing`, and move the local Grafana from the mounted `~/.aws` to short-lived `cerberus-grafana-read` credentials, without touching anything the 8.10 take needs? This is needed now because step 6 (the command set) needs `cerberus-console-cli` to assume, and step 10 needs the console subnet. ADR 0023 also lists "a read-only Grafana role (9.2)" as a follow-up.

## 2. Facts

Repo:
- F1. ADR 0024 fixes the following. `make grafana-up` assumes `cerberus-grafana-read` (AMP query plus CloudWatch read). It passes short-lived credentials (up to 12 h) as environment variables, and `~/.aws` is no longer mounted. `cerberus-console-cli` is read-only, with no `glue:UpdateTable` and no gold `s3:PutObject`. There is a console private subnet and route table, with no NAT route at rest. Sources: `docs/adr/0024-demo-console.md` L91–93, L199–204, L171–173.
- F2. Today's Compose mounts `${HOME}/.aws:/aws:ro`. It sets `AWS_PROFILE`, `AWS_SDK_LOAD_CONFIG`, `AWS_SHARED_CREDENTIALS_FILE` and `AWS_CONFIG_FILE`, and forwards host env vars only to `grafana-amazonprometheus-datasource` (`observability/grafana/compose.yaml` L23–35). The `user:` override exists only so the container can read mode-600 keys (same file, L8–11).
- F3. `make grafana-up` builds `AMP_URL` from `aws amp list-workspaces`, then runs `docker compose up -d`. `grafana-down` and `grafana-logs` pass `AMP_URL=unused` to satisfy the `:?` interpolation (`Makefile` L63–83).
- F4. Datasources are in one file, `observability/grafana/provisioning/datasources/local.yaml`. It has uids `amp` (sigV4 `default`) and `cloudwatch` (`authType: default`), and its header says that credentials come from the mounted profile. The in-cluster Grafana reads only `observability/grafana/dashboards/` (`terraform/modules/eks_observability/main.tf` L29), not this datasource file.
- F5. The in-cluster role `cerberus-grafana` has two statements. `QueryWorkspace` allows `aps:QueryMetrics, GetSeries, GetLabels, GetMetricMetadata` on the workspace. `ReadCloudWatchMetrics` allows `cloudwatch:GetMetricData, GetMetricStatistics, ListMetrics, DescribeAlarms, DescribeAlarmsForMetric, DescribeAlarmHistory` and `ec2:DescribeRegions` on `*` (`terraform/modules/eks_observability/main.tf` L93–150). This set already served the story dashboards in 7.7/7.8.
- F6. The repo pattern for a role that a human assumes is a trust on `user/cerberus-admin` with `sts:AssumeRole` and inline `aws_iam_role_policy` (`terraform/modules/iam/main.tf` L1–34, `cerberus-serving` L500+).
- F7. VPC module subnets: public `10.0.0.0/24` and `10.0.1.0/24`, private `10.0.16.0/20` and `10.0.32.0/20`, AZs `us-east-1a` and `us-east-1b`. The private subnets come from `local.private_subnets`, and `private_subnet_ids` feeds EKS and the ECS tasks (`terraform/modules/vpc/main.tf`, `outputs.tf`). The S3 gateway endpoint is attached to the private route table only.
- F8. AMP retention is `var.retention_days` with default 90. Its description cites "90 days matches the lineage event retention" (`terraform/modules/prometheus_workspace/variables.tf`). Build step 5 needs no IAM change (IAM prerequisites plan, F3).
- F9. The CI-apply console policy grants role management on exactly `role/cerberus-console-cli` and `role/cerberus-grafana-read`, without `iam:UpdateAssumeRolePolicy` (`terraform/modules/github_oidc/main.tf`, Sid `ManageConsoleIamRoles`). `ManageVpcCore` grants `ec2:*` on `subnet/*` and `route-table/*`.
- F10. The story dashboard uid is `cerberus-run-story`. It has 7 AMP panels, 2 Grafana annotation panels and 1 Mixed panel (CloudWatch), and its default time is `now-30m` (`observability/grafana/dashboards/cerberus-run-story.json`). The 2026-10-13 window is 06:35:02Z to 06:47:24Z (ADR 0022 L67). In epoch ms, 06:30Z is 1791873000000 and 06:50Z is 1791874200000.
- F11. CloudWatch's 1-minute data for the 2026-10-13 run expires "around 2026-10-28" (ADR 0024 L212–213). That is today, so the Mixed panel can be empty on that window.
- F12. The recording runbook uses the local Grafana for the 8.10 take: "`make grafana-up`; sign in before recording" (`docs/plans/2026-10-26-recording-runbook.md` L44). `exercise.sh` and `annotate.sh` post annotations with the token in `.env`, and they do not use the container's AWS credentials.
- F13. CI plans and applies only on changes to `terraform/modules/**` and `terraform/envs/dev-standing/**` (spike plan F5). `code-ci.yml` runs ruff only. shellcheck is not in CI.
- F14. `cerberus-admin` holds `sts:AssumeRole`, `iam:GetRole`/`CreateRole`/`UpdateAssumeRolePolicy` on `role/cerberus-*`, and `iam:SimulatePrincipalPolicy` on `*`. It does not hold `iam:UpdateRole` (`iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`, Sids `IamRoleMgmt`, `Sts`, `IamSimulate`).

AWS (read-only, `cerberus-admin`, us-east-1, 2026-10-28):
- F15. The project subnets are `public-a` (us-east-1a/use1-az1), `public-b` (us-east-1b/use1-az2), `private-a` (use1-az1) and `private-b` (use1-az2). `us-east-1e` is `use1-az3`, which VPC origins do not support. `10.0.2.0/24` is free. The route tables are `cerberus-platform-private-rt` and `cerberus-platform-public-rt`. There are 0 ENIs in the account.
- F16. `cerberus-grafana-read` and `cerberus-console-cli` do not exist (`NoSuchEntity`).
- F17. AMP workspace `cerberus-platform` is `ACTIVE` with `retentionPeriodInDays` 90.
- F18. `simulate-principal-policy` on `role/cerberus-ci-apply` allowed all of these: `ec2:CreateSubnet`, `CreateRouteTable`, `AssociateRouteTable`, `CreateTags`, `DeleteSubnet`, `DeleteRouteTable`, `DisassociateRouteTable`, `DescribeSubnets`, `DescribeRouteTables`; `iam:CreateRole`, `PutRolePolicy`, `TagRole`, `GetRole`, `GetRolePolicy`, `UpdateRole`, `ListRolePolicies`, `ListAttachedRolePolicies`, `ListInstanceProfilesForRole`, `DeleteRole`, `DeleteRolePolicy` on both role names; `aps:UpdateWorkspaceConfiguration` and `DescribeWorkspaceConfiguration`. It denied (implicitly) `ec2:DescribeAvailabilityZones` and `iam:UpdateAssumeRolePolicy`.

External:
- F19. Since Grafana 12.4, plugin processes get only Grafana variables, proxy variables and plugin-specific AWS settings. A plugin listed in `[plugins] forward_host_env_vars` (`GF_PLUGINS_FORWARD_HOST_ENV_VARS`) gets the host environment ([Grafana what's new, 2026-02-24](https://grafana.com/whats-new/2026-02-24-plugin-processes-no-longer-receive-all-host-environment-variables-by-default/)).
- Unverified: whether the core CloudWatch datasource in Grafana 13.2.3 runs in-process or needs forwarding. Inference: today it reads `AWS_SHARED_CREDENTIALS_FILE` without being on the forward list, and the story dashboard's CloudWatch panel worked on 2026-10-25 (ADR 0022 amendment, item 6d). That suggests it is in-process and reads the container env. The step verifies this.

Permissions: nothing is missing for this step. CI can create and manage everything in 4a (F18), and `cerberus-admin` can assume, read and simulate (F14). The CI gap (`iam:UpdateAssumeRolePolicy`) matters only if a trust policy changes later. See risk 3.

## 3. Constraints

- $0 idle. Subnets, route tables and IAM have no charge. AMP storage at 400 days is under $0.03/month (ADR 0024 estimate). `sts:AssumeRole` is free.
- `dev-compute` and the in-cluster Grafana are not touched. The local Grafana is part of the 8.10 take (F12), so its switch must not land on `main` before the take unless the user says so.
- CI applies `dev-standing` only. No local apply is needed (F18).
- Public repo: no account ID in new files (use `data.aws_caller_identity`/`var.account_id`), no emails, no secrets, and no mention of credentials files. Never stage `observability/grafana/.env`. Never print the admin password, the token or session keys.
- Follows ADR 0024 and ADR 0007/0016/0022 as already amended. Their Status notes exist, so no ADR edits are needed.

## 4. Options (packaging only; the design is fixed by ADR 0024)

- A. One PR for the whole of step 4. The roles must exist before `make grafana-up` can be tested. That needs a local `cerberus-admin` apply from the branch, and the Compose switch would land on `main` before the 8.10 take.
- B (recommended). Two PRs.
  - 4a: Terraform only (roles, subnet, plus step 5's retention). CI applies it on merge, and it does not affect 8.10.
  - 4b: the Compose, Makefile and README switch. It is verified on its branch against the real role, and merged after the take.
- C. Hold all of step 4 until after the take. This delays step 6 for no reason.

**Step 5 (AMP 400 days): fold it into 4a.** It is the same root, the same CI apply and one line plus a description, with no IAM change (F8, F18). It has its own commit and its own verify lines. Keeping it separate costs one more CI cycle and gains nothing. 400 days keeps the 2026-10-13 run until about 2027-11-17.

## 5. Recommendation

Option B. Named deviations from demo-console plan §7 (ADR text unchanged):
1. Step 4 is two PRs, 4a and 4b, so that the recording host does not change before the 8.10 take.
2. Step 5 is folded into PR 4a.

Design decisions:
- **`cerberus-grafana-read`**
  - Trust: `user/cerberus-admin`, `sts:AssumeRole`.
  - `max_session_duration = 43200` (12 h, ADR 0024).
  - Inline policy: exactly the in-cluster `cerberus-grafana` statements (F5), scoped to the workspace ARN. This is a proven set, so there is no guesswork.
- **`cerberus-console-cli`**
  - Trust: `lambda.amazonaws.com` (step 7) and `user/cerberus-admin` (step 6 local runs).
  - Default 1 h session.
  - Inline policy, Step Functions read only:
    - `states:DescribeStateMachine` and `ListExecutions` on the state machine ARN.
    - `states:DescribeExecution` and `GetExecutionHistory` on `execution:cerberus-platform-orchestration:*`.
  - Athena, Glue, gold read and the results prefix are added in step 6, together with the fixed query and its workgroup. The bytes scanned and the table set are step 6 unknowns (plan §8).
- **Console subnet** (in `terraform/modules/vpc`)
  - `aws_subnet.console`: `10.0.2.0/24`, `us-east-1a`, `map_public_ip_on_launch = false`, tagged `Name = cerberus-platform-console`, `Phase = "9"`.
  - The subnet has a `lifecycle { postcondition { condition = self.availability_zone_id != "use1-az3" } }`. Do not use any `aws_availability_zones` data source: CI is denied `DescribeAvailabilityZones` (F18).
  - Same AZ as `public-a`, where a session NAT would sit, so there is no cross-AZ NAT traffic.
  - Its own `aws_route_table.console` with no routes (local only), plus one association.
  - **Not** in `local.private_subnets`. That map feeds EKS and ECS (F7).
  - S3 gateway endpoint association: deferred to step 10. It changes a resource that `dev-compute` uses, and only step 10 needs it.
- **Local Grafana** (4b)
  - A new script, `observability/grafana/up.sh`, called by `make grafana-up`. Pattern: `token.sh`.
  - It assumes the role with `--duration-seconds` from `GRAFANA_SESSION_HOURS` (default 12, max 12). It exports the three `AWS_*` keys into the `docker compose` process env only, never to a file. It prints only the role name, the session name and the expiry.
  - The Compose file drops the mount and the four profile vars. It adds `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` (`:?set by make grafana-up`) and `AWS_REGION: us-east-1`.
  - The forward list stays as it is. Add `cloudwatch` only if the CloudWatch health check fails (F19, unverified).
  - Split `local.yaml` into `amp.yaml` and `cloudwatch.yaml`. This is pulled forward from step 10: it is harmless, and the file's credential comment changes anyway.

## 6. ADR outline

None.

## 7. Build steps (Phases.md 9.2)

### PR 4a: branch `9.2-readonly-roles` (Terraform, CI-applied)

Files:
1. `terraform/modules/console_roles/{main.tf,variables.tf,outputs.tf}` (new). Header comment: ADR 0024; standing; $0; why `console-cli` is Step Functions read only for now.
   - Variables: `account_id`, `region` (default `us-east-1`), `trusted_principal_arn`, `amp_workspace_arn`, `state_machine_arn`, `state_machine_name`.
   - Resources: `aws_iam_role.grafana_read` + `aws_iam_role_policy.grafana_read` (`cerberus-grafana-read-policy`); `aws_iam_role.console_cli` + `aws_iam_role_policy.console_cli` (`cerberus-console-cli-policy`).
   - Outputs: both ARNs and names.
2. `terraform/modules/vpc/main.tf`: the console subnet, route table and association (section 5), and one paragraph in the header (ADR 0024 amends ADR 0007). `variables.tf`: `console_subnet_cidr` (default `10.0.2.0/24`) and `console_availability_zone` (default `us-east-1a`). `outputs.tf`: `console_subnet_id` and `console_route_table_id`.
3. `terraform/envs/dev-standing/main.tf`: `module "console_roles"`. Use `trusted_principal_arn` from `data.aws_caller_identity` as in `module "iam"`, and `module.prometheus_workspace.workspace_arn` / `module.step_functions.state_machine_arn` / `state_machine_name`. Add no new literal account ID.
4. `terraform/envs/dev-standing/outputs.tf`: `console_subnet_id`, `console_route_table_id` (for `dev-console` remote state), `grafana_read_role_arn` and `console_cli_role_arn`.
5. `terraform/modules/prometheus_workspace/variables.tf` (separate commit): change the default from 90 to 400, and change the description to "400 days per ADR 0024: the 2026-10-13 and 8.10 runs stay viewable while the portfolio is in use. AWS allows 1–1095."
6. Docs:
   - Demo-console plan §7: under step 4, add a two-line note on the 4a/4b split. Under step 5, note that it is folded into 4a, with a link to this plan.
   - Phases.md 9.2 progress line, after verification.

Executor verify ($0, no AWS changes):
- `TMPDIR=$HOME/.cache/tfspiketmp terraform fmt -check -recursive terraform/`
- `terraform validate`, run in a scratch copy or with `init -backend=false`.
- `grep -rnE '[0-9]{12}' terraform/modules/console_roles` returns nothing. The `git diff` adds no account ID.
- After that, an Opus review.

Plan in CI (read-only). The PR's `terraform plan` must show exactly the following and nothing else:
- 7 to add: 2 roles, 2 role policies, the subnet, the route table and the association.
- 1 to change in place: `aws_prometheus_workspace_configuration.this`, retention 90 → 400.

The known Faker-layer replacement (#123 outcome) is the only accepted extra. Otherwise stop.

**User-approved AWS change:** merging PR 4a. The CI apply on `main` creates the roles and the subnet, and updates AMP retention. No local apply.

Post-apply verify (agent, read-only). In zsh, write `${ACCT}` with braces. `$ACCT:r` is a zsh modifier and breaks the ARN, which happened during this planning.
```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws ec2 describe-subnets --filters Name=tag:Name,Values=cerberus-platform-console \
  --query 'Subnets[].[AvailabilityZoneId,CidrBlock,MapPublicIpOnLaunch]' --output text   # use1-az1 10.0.2.0/24 False
aws ec2 describe-route-tables --filters Name=tag:Name,Values=cerberus-platform-console-rt \
  --query 'RouteTables[].[length(Routes),Routes[0].GatewayId,length(Associations)]' --output text   # 1 local 1
aws iam get-role --role-name cerberus-grafana-read --query 'Role.MaxSessionDuration'   # 43200
WS=$(aws amp list-workspaces --query "workspaces[?alias=='cerberus-platform'].workspaceId|[0]" --output text)
aws amp describe-workspace-configuration --workspace-id "$WS" \
  --query 'workspaceConfiguration.[status.statusCode,retentionPeriodInDays]' --output text   # ACTIVE 400
G="arn:aws:iam::${ACCT}:role/cerberus-grafana-read"; C="arn:aws:iam::${ACCT}:role/cerberus-console-cli"
W="arn:aws:aps:us-east-1:${ACCT}:workspace/${WS}"
aws iam simulate-principal-policy --policy-source-arn "$G" --resource-arns "$W" \
  --action-names aps:QueryMetrics aps:GetSeries aps:RemoteWrite aps:UpdateWorkspaceConfiguration aps:DeleteWorkspace \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # 2 allowed, 3 denied
aws iam simulate-principal-policy --policy-source-arn "$G" --resource-arns '*' \
  --action-names cloudwatch:GetMetricData cloudwatch:ListMetrics cloudwatch:PutMetricData cloudwatch:PutMetricAlarm cloudwatch:DeleteAlarms cloudwatch:PutDashboard iam:CreateRole s3:PutObject \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # 2 allowed, 6 denied
SM="arn:aws:states:us-east-1:${ACCT}:stateMachine:cerberus-platform-orchestration"
aws iam simulate-principal-policy --policy-source-arn "$C" --resource-arns "$SM" \
  --action-names states:DescribeStateMachine states:ListExecutions states:StartExecution states:UpdateStateMachine states:DeleteStateMachine \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # 2 allowed, 3 denied
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:states:us-east-1:${ACCT}:execution:cerberus-platform-orchestration:x" \
  --action-names states:DescribeExecution states:GetExecutionHistory states:StopExecution \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # 2 allowed, 1 denied
aws iam simulate-principal-policy --policy-source-arn "$C" --resource-arns '*' \
  --action-names glue:UpdateTable s3:PutObject athena:StartQueryExecution iam:PassRole sts:AssumeRole \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # all denied
aws sts assume-role --role-arn "$G" --role-session-name verify --duration-seconds 43200 \
  --query 'AssumedRoleUser.Arn' --output text | sed "s/${ACCT}/<ACCOUNT_ID>/"   # assumed-role/cerberus-grafana-read/verify
```
Do not record the session keys. The `--query` above prints only the ARN.

Retention check, which closes the §8 item "raising retention keeps samples": use the current Grafana from `main` (still on the mounted profile). Open `http://127.0.0.1:3000/d/cerberus-run-story?from=1791873000000&to=1791874200000`. The 7 AMP panels show data.

### PR 4b: branch `9.2-grafana-readonly-creds` (no Terraform; merge after the 8.10 take)

Files:
1. `observability/grafana/up.sh` (new, `set -euo pipefail`, no `set -x`). It moves the AMP URL lookup out of the Makefile. It gets the role ARN with `aws iam get-role --role-name cerberus-grafana-read --query Role.Arn` (no account ID in the file). It runs `aws sts assume-role ... --duration-seconds $((hours*3600)) --query Credentials --output json` and reads the fields with `jq`. It exports `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` and runs `docker compose ... up -d`. It prints the role, the session name, the expiry, and "run make grafana-up again to renew". Changed env makes Compose recreate the container, and the volume (annotations, token) stays.
2. `observability/grafana/compose.yaml`:
   - Remove the `${HOME}/.aws:/aws:ro` mount and `AWS_PROFILE`, `AWS_SDK_LOAD_CONFIG`, `AWS_SHARED_CREDENTIALS_FILE`, `AWS_CONFIG_FILE`.
   - Add the three `AWS_*` keys with `:?set by make grafana-up`, and `AWS_REGION: us-east-1`.
   - Keep `user:`, `grafana-init` and `HOME`. Reword the `user:` comment: the volume is owned by the host uid.
   - Reword the loopback comment: "short-lived read-only credentials".
3. `Makefile`:
   - `grafana-up` keeps the `.env` check and then calls `@observability/grafana/up.sh`. Its help text mentions `cerberus-grafana-read`.
   - Add `GRAFANA_STUB_ENV := AMP_URL=unused AWS_ACCESS_KEY_ID=unused AWS_SECRET_ACCESS_KEY=unused AWS_SESSION_TOKEN=unused` for `grafana-down` and `grafana-logs`.
4. `observability/grafana/provisioning/datasources/`: replace `local.yaml` with `amp.yaml` and `cloudwatch.yaml`, with the same names, uids and jsonData. The header says that credentials come from the environment (`make grafana-up`), and that the console session mounts only `amp.yaml` (ADR 0024).
5. `observability/grafana/README.md`:
   - Start: check that `cerberus-admin` can assume `cerberus-grafana-read`; renewal at 12 h; `GRAFANA_SESSION_HOURS`.
   - Fix the "drop the volume" command with the stub env.
   - Security: replace the two `~/.aws` bullets with "no AWS keys in the container; short-lived read-only session credentials, up to 12 h". Remove the chmod line that names the key files.
6. Docs:
   - Demo-console plan §8: mark the `GF_PLUGINS_FORWARD_HOST_ENV_VARS` item with the result.
   - Phases.md 9.2 line, after merge.

Executor verify ($0):
- `uvx --from shellcheck-py shellcheck observability/grafana/up.sh`
- `GRAFANA_STUB_ENV... docker compose -f observability/grafana/compose.yaml --env-file observability/grafana/.env config -q`. Use `-q` only: a plain `config` prints the admin password.
- `git status` must not list `.env`.
- `grep -rnE '[0-9]{12}|\.aws' observability/grafana Makefile` returns nothing new.

Live verify (user or agent, on the branch, not during a rehearsal; only `sts:AssumeRole`, no AWS state change):
```
make grafana-up
c=$(docker compose -f observability/grafana/compose.yaml ps -q grafana)
docker inspect "$c" --format '{{range .Mounts}}{{println .Destination}}{{end}}'      # no /aws
docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | sort   # names only; no AWS_PROFILE / AWS_SHARED_CREDENTIALS_FILE
```
- Browser, signed in: `http://127.0.0.1:3000/d/cerberus-run-story?from=1791873000000&to=1791874200000`. The 7 AMP panels show the 2026-10-13 run.
- Connections → Data sources → `CloudWatch` → "Save & test" passes. The Mixed panel can be empty on that window, because the 1-minute data expired (F11). That is not a failure.
- If the CloudWatch test fails with a credentials error, add `cloudwatch` to `GF_PLUGINS_FORWARD_HOST_ENV_VARS`, re-run, and record the result in §8.
- Restore for the take: `git checkout main && make grafana-up` brings back the current setup. The volume is unchanged.

**User-approved action:** merging 4b after the 8.10 take (31 Oct/1 Nov). No AWS change.

## 8. Risks

1. The 8.10 recording host. 4b changes the local Grafana. Merged before the take, a 12 h credential expiry or a CloudWatch forward gap could break the recording. Mitigation: merge after the take, and switch back to `main` after the branch test.
2. CloudWatch credential path (F19, unverified). Fallback: add `cloudwatch` to the forward list.
3. CI cannot change a trust policy (F18: no `iam:UpdateAssumeRolePolicy`). Get both trusts right at creation. A later trust change needs a local `cerberus-admin` apply (it has the action), or a root paste to the CI policy. `cerberus-admin` lacks `iam:UpdateRole` (F14), so a later `max_session_duration` change must go through CI.
4. Session keys sit in the container env for up to 12 h. Anyone with Docker access can read them with `docker inspect`, as they can read the admin password today. They are read-only and short-lived. The verify commands print variable names only.
5. Expired credentials fail quietly: the panels show errors. `up.sh` prints the expiry, and the README says how to renew.
6. The plan in 4a may show more than 7 + 1. Do not merge, and do not use `-target`.
7. AMP retention change. The update goes through `UPDATING`, so apply it days before the take, not during an exercise. Raising retention is expected to keep the samples. The 4a retention check confirms it.
8. Note for step 6 (not this step): demo-console plan step 6 runs every command as `cerberus-console-cli`, but the `cerberus_platform_console` workgroup and its 1-day result prefix are in step 7. Step 6's plan should move them into step 6 or drop `status` from its local check.

## 9. Open questions for the user

1. **When to merge 4b (the local Grafana switch):** answered 2026-10-28: after the 8.10 take. Both PRs are built and verified now.

Sources: [Grafana: plugin processes no longer receive all host environment variables by default](https://grafana.com/whats-new/2026-02-24-plugin-processes-no-longer-receive-all-host-environment-variables-by-default/), [Grafana 13.2 CloudWatch configure](https://grafana.com/docs/grafana/v13.2/datasources/aws-cloudwatch/configure.md).
