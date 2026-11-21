# Alerts as code (pipeline status)

The alert rules and the Alertmanager definition for pipeline status. The
decision is in [ADR 0021](../../docs/adr/0021-pipeline-status-and-alerting.md)
and its amendments. The plan is
[2026-11-20-status-dashboard-and-alerts.md](../../docs/plans/2026-11-20-status-dashboard-and-alerts.md).

Nothing here is live until the owner steps below are done. The Terraform that
loads these files into AMP (`aws_prometheus_rule_group_namespace` and
`aws_prometheus_alert_manager_definition`) is `terraform/modules/pipeline_alerts`,
called from `dev-standing` (PR 10.4b).

| File | What it is |
|---|---|
| `status.rules.yaml` | One group, `cerberus-status`, every 60 s. Five alert rules. No recording rules. |
| `status.rules.test.yaml` | promtool unit tests for the rules. |
| `alertmanager.yaml.tftpl` | The AMP Alertmanager definition: route, SNS receiver, and the subject and message templates. `${topic_arn}` is the only variable. |
| `render_alertmanager.py` | Renders the template with a dummy ARN, for `amtool check-config`. No AWS. |

## The rules

| Alert | Fires when | Severity | `for` |
|---|---|---|---|
| `CerberusRunFailed` | the newest run did not succeed | `page` | 2m |
| `CerberusDataQualityErrors` | the newest run had data-quality errors above 0 | `ticket` | 2m |
| `CerberusRunNeverReported` | a run started more than 1 hour ago and no run has finished since | `page` | 0s |
| `CerberusErrorBudgetBurn` | more than 5% of runs in 90 days failed, with at least 5 runs | `ticket` | 0s |
| `CerberusAlertPathCheck` | `make status-smoke ARGS=--send` wrote a smoke sample in the last 10 minutes | `info` | 0s |

- Each expression contains query-set entries from
  [`observability/queries/status.json`](../queries/status.json) verbatim.
  `console/tests/test_alert_rules.py` checks it with `queries.check_rule_expr`.
- Every rule except the error budget adds the run name (`execution`) with
  `+ on() group_left(execution) (0 * topk(1, <entry>))`. The newest finished (or
  started) run supplies the name. The annotations print it as
  `cerberus run {{ $labels.execution }}` and `make review RUN={{ $labels.execution }}`.
- `for: 2m` on the failed-run and DQ rules covers the gap between the status
  sample and the finish sample of one run. For a moment the join still names the
  previous run. That wrong-name alert never lasts 2 minutes. The promtool race
  test models it.
- The error budget rounds the failed share to 0.001 before the `> 0.05` test. In
  floating point `1 - 0.95` is slightly above 0.05, so without the rounding
  exactly 1 failure in 20 runs would fire.
- The alert-path check never fires on its own. It proves the whole chain (ruler,
  topic policy, template, email) before a real failure does.

## Run the tests

```
make alerts-test
```

It needs Docker and nothing else: no AWS, no network (the containers run with
`--network none`). It runs `promtool check rules`, `promtool test rules` and
`amtool check-config` from images pinned by digest. CI runs the same checks in
the job `alert-rules` of `.github/workflows/code-ci.yml`. The Python checks are
in `console/tests/test_alert_rules.py`.

## The email

The SNS subject is `[Cerberus FIRING] <alertname> <execution>`. The execution is
cut to 50 characters, so the subject is always at most 100 characters (SNS limit):
the longest fixed part is 46 characters. The body holds the summary, the
description, the severity and the start (and resolve) time.

Route timing is `group_wait: 30s`, `group_interval: 5m` and
`repeat_interval: 24h`. A failed status stays true until the next run, possibly
for 30 days, so the 4 hour default would send about 6 emails a day. The first
email arrives about 3.5 minutes after a failure: up to 60 s for the rule
evaluation, 2 minutes of `for`, and 30 s of `group_wait`.

## Putting the rules live (owner)

PR 10.4b adds the Terraform. Nothing reaches AMP until the owner does these
steps, in this order. The CI role (`cerberus-ci-apply`) cannot widen its own
policy: the PR changes that policy and the PR needs the new rights to create the
rules. Think of a new employee who needs a key to open the room that holds the
key cabinet. A person with the master key (you, with `cerberus-admin`) lets them
in the first time. After that, CI runs alone.

1. **Root-paste the admin policy.** Sign in to the AWS console as the root user.
   Open IAM, Policies, `cerberus-admin-iam-and-governance`, then Edit, then JSON.
   Replace the text with the whole of
   `iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json` from the
   PR branch and choose Save changes. This makes a new default version. One
   paste covers both the 10.2d `aps:RemoteWrite` change and the 10.4b actions.
   The background is in [iam/cerberus-admin/README.md](../../iam/cerberus-admin/README.md)
   (the 2026-11-20 and 2026-11-21 "Changes" entries). Then update both entries
   from "paste pending" to the date of the paste.
2. **Check the paste.** Both answers must be `allowed`:
   ```
   U=$(AWS_PROFILE=cerberus-admin aws sts get-caller-identity --query Arn --output text)
   AWS_PROFILE=cerberus-admin aws iam simulate-principal-policy --policy-source-arn "$U" \
     --action-names aps:RemoteWrite aps:PutRuleGroupsNamespace aps:CreateAlertManagerDefinition \
     --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
   ```
3. **Plan on the PR branch.** Run `make standing-plan`. It must show exactly
   these new or changed resources, plus the known Faker layer churn
   (`aws_lambda_layer_version.faker` replaced, the ingestion Lambda updated):
   - `module.observability.aws_sns_topic_policy.alerts` (create; it replaces the
     topic's default policy with an equivalent first statement and the AMP statement)
   - `module.pipeline_alerts.aws_prometheus_rule_group_namespace.status` (create)
   - `module.pipeline_alerts.aws_prometheus_alert_manager_definition.status` (create)
   - `module.github_oidc.aws_iam_role_policy.ci_apply` (update in place)

   The plan must match the CI plan comment on the PR. If it differs, stop.
   Before you apply, check that no Terraform apply is running:
   `gh run list --workflow terraform-apply.yml --limit 3`. A running one holds
   the state lock, so wait and try again.
4. **Apply locally.** Run `make standing-apply`. CI cannot do this first apply
   (see above). If the apply stops after it created the rule namespace but
   before the Alertmanager definition, fix the cause and run
   `make standing-apply` again. Do not use `-target`.
5. **Merge the PR right after the local apply.** Do not merge any other PR that
   touches `terraform/**` or the workflow paths between the local apply and this
   merge. A CI apply from a `main` without this code would try to remove the
   three new resources. It would fail partway, because it lacks the rights, and
   leave a mixed state that only this merge repairs. After the merge, the CI
   apply on `main` must show no changes.
6. **Check AMP.** Both must say `ACTIVE` (use the workspace ID of the
   `cerberus-platform` workspace, `aws amp list-workspaces`):
   ```
   aws amp describe-rule-groups-namespace --workspace-id <id> --name cerberus-status
   aws amp describe-alert-manager-definition --workspace-id <id>
   ```
7. **Prove the whole path.** Run `make status-smoke ARGS=--send`. An email
   "[Cerberus FIRING] CerberusAlertPathCheck smoke-..." must arrive within about
   3 minutes. The RESOLVED email follows after about 10 minutes. Record the
   result in `Phases.md` (10.4) and in the "Confirmed" line of ADR 0021.
