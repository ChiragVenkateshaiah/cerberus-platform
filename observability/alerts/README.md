# Alerts as code (pipeline status)

The alert rules and the Alertmanager definition for pipeline status. The
decision is in [ADR 0021](../../docs/adr/0021-pipeline-status-and-alerting.md)
and its amendments. The plan is
[2026-11-20-status-dashboard-and-alerts.md](../../docs/plans/2026-11-20-status-dashboard-and-alerts.md).

Nothing here is deployed yet. PR 10.4b adds the Terraform that loads these files
into AMP (`aws_prometheus_rule_group_namespace` and
`aws_prometheus_alert_manager_definition`) in `dev-standing`.

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
