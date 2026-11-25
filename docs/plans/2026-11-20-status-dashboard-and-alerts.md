# Plan: 10.3 pipeline-status dashboard and 10.4 alerting as code

Date: 2026-11-20. Planner: Opus. Mode: plan for Phases.md 10.3 and 10.4, with notes for 10.5 and 10.6. It reads `origin/main` at `6a29682` (#171 merged; #172 is an open draft with the console failed-step fix, which is independent of this work). No ADR amendment is needed (section 6).

## 0. Summary for the owner

1. Alert rules go in one YAML file, `observability/alerts/status.rules.yaml`. Terraform (`aws_prometheus_rule_group_namespace`) loads it into AMP in `dev-standing`, as ADR 0021 already decided. There are no Grafana-managed alerts.
2. Alerts route through AMP's Alertmanager to the existing SNS topic `cerberus-pipeline-alerts`, which already has one confirmed email subscription. The topic policy must add `aps.amazonaws.com` and keep today's default statement.
3. There are four alerts. Each one adds the run name (`execution`) with an explicit `on()` join:
   - failed run;
   - DQ errors;
   - never reported (started more than 1 h ago with no finish);
   - error budget (more than 5% of runs failed in 90 days, with at least 5 runs). The error-budget alert has no run name.
4. There are no recording rules. The error budget uses the `[90d]` `avg_over_time` and `count_over_time` exception. Four new query-set entries are added.
5. One dashboard, `cerberus-pipeline-status`, built for everyone:
   - a plain-words top row: did the last run pass, data checks, last good data, pass rate;
   - then step by step, history, and a runs table that links to the run-story view;
   - then the reserved "AI review" panel.
6. Offline checks in CI:
   - `check_dashboard` and `check_rule_expr`;
   - `promtool check rules` and `promtool test rules`, including the label race and NaN;
   - `amtool check-config`;
   - a render check that runs every panel query through a throwaway Grafana and Prometheus (Docker, no AWS).
7. The order is 10.4a (rules and tests), 10.3a (dashboard), 10.3b (render check), 10.4b (Terraform and IAM; the owner applies locally first), then a 10.4c owner check.
8. Owner steps:
   - two root pastes (10.2's `aps:RemoteWrite`, then the 10.4 rule and Alertmanager actions);
   - one local `dev-standing` apply, because the CI role cannot widen its own policy.
9. A proposed alert-path check rule fires on `make status-smoke`. That proves AMP's ruler (with `topk` and `group_left`), the topic policy and the email before 10.6. The real failed-run alert is 10.6.
10. Idle cost stays at $0. Rule evaluation is about $0.01 a month.

## 1. Question

How are the Phase 10 status series shown and alerted on, so that anyone in the company can read the state of the pipeline and the owner gets an email that names the run? Everything must stay as code, be checked offline, and add no idle cost.

Why now: 10.2 is built (PRs A–D merged). 10.3 gates the public showcase (`docs/plans/2026-11-20-databricks-free-edition-showcase.md` L33). 10.4 is needed before the 10.6 live pair.

## 2. Facts (V = verified, U = unverified)

**ADR 0021 and its amendments**
- V. Rules and the Alertmanager configuration are Terraform in `dev-standing` (`aws_prometheus_rule_group_namespace`, `aws_prometheus_alert_manager_definition`). They deliver through SNS topic `cerberus-pipeline-alerts`, with `promtool test rules` in `code-ci.yml` (Decision, Q1).
- V. The AMP-owned alerts are failed run, DQ errors above zero, never reported, and the error budget over runs.
  - The error budget is the failed share from the 90-day average of `cerberus_run_status`, firing above 5% with at least 5 runs. 10.4 fixes the exact expressions.
  - There is no stale-data alert in AMP and there are no recording rules.
- V. Amendment 2026-11-12, D2:
  - Rules add `execution` with `group_left(execution)` from the newest finished run; never-reported takes it from the newest started run.
  - Annotations carry `cerberus run {{ $labels.execution }}` and `make review RUN=...`, and the SNS template prints `.CommonLabels.execution`.
  - A short `for:` on the failed-run and DQ rules covers the gap between the status sample and the finish sample. A `promtool` test models it.
- V. D3: an "AI review" annotation-list panel on the run-status dashboard, tag `cerberus-ai`, empty text "No AI review yet (Phase 14)". It loads on both hosts.
- V. "Two dashboards at most (run status; SLO and burn rate)" (ADR 0021, Dashboards).
- V. The 2026-11-20 amendment allows only `last_over_time[30d]`, plus `avg_over_time` and `count_over_time` over `[90d]` for the error budget.

**Query set (`observability/queries/status.json` and README)**
- V. 13 entries. `latest_failed_step` is wrapped in parentheses.
- V. Panels must equal an entry; rules must contain entries verbatim (`check_rule_expr`).
- V. `__name__` is optional in results.
- V. Joins must use an explicit `on()` or `ignoring()`.
- V. No entry may use templating.
- V. Only `title`, `description` and `content` fields may name a status metric.

**AMP quotas** (`docs.aws.amazon.com/prometheus/.../AMP_quotas.html`, read 2026-11-20)
- V. Query time range: 95 days.
- V. Minimum rule evaluation interval: 30 s.
- V. Samples older than 1 hour are refused.
- V. Out-of-order window: 60 s by default.
- V. Rules per workspace: 2,000.
- V. Templates in an Alertmanager definition: 100.

**SNS topic `cerberus-pipeline-alerts`** (`aws sns get-topic-attributes`, read-only)
- V. One confirmed subscription, 0 pending, no KMS key.
- V. Its policy is only `__default_statement_ID`: Principal `*` with a `StringEquals` owner condition, covering Publish and the management actions.
- V. Defined in `terraform/modules/observability/alarms.tf` L22-33. There is no `aws_sns_topic_policy` today.

**IAM**
- V. `cerberus-ci-apply` (`terraform/modules/github_oidc/main.tf`): `ManageAlertsTopic` (L383-390) includes `sns:SetTopicAttributes`. The aps statements (L401-428) cover only workspace CRUD and tags. There are no rule-group-namespace or Alertmanager actions.
- V. The CI role cannot widen its own policy. The 2026-10-27 pattern was a root paste, then a local `dev-standing` apply as `cerberus-admin`, then CI (`docs/plans/2026-10-27-console-iam-prerequisites.md` L15, L54, L168).
- V. `cerberus-admin`:
  - `aps:ListRuleGroupsNamespaces` and `aps:DescribeAlertManagerDefinition` are denied (read 2026-11-20).
  - `sns:SetTopicAttributes` is allowed (`iam/cerberus-admin/policies/cerberus-admin-orchestration.json` L53).
  - `aps:RemoteWrite` is merged but the paste is still pending (10.2).
  - `cerberus-admin-iam-and-governance.json` is at 4,100 of 6,144 characters.
- U. Whether the AWS-managed `ReadOnlyAccess` on `cerberus-ci-plan` covers `aps:DescribeRuleGroupsNamespace` and `aps:DescribeAlertManagerDefinition`. The first `terraform-plan` run shows this.

**Workflows**
- V. `terraform-plan.yml` (L24-36) and `terraform-apply.yml` (L17-29) run only on `terraform/**` plus a listed set of "code that dev-standing's modules read with file()". `observability/alerts/**` is not in that list.
- V. `code-ci.yml` runs on `observability/**` and `console/**`. Jobs: `status-tests` (3.12, boto3 pinned), `status-e2e` (Docker, `prom/prometheus:v3.15.0@sha256:efd7…`) and `console-tests` (3.12). `requirements-dev.txt` has no PyYAML.

**Grafana**
- V. Provisioning loads every JSON in `observability/grafana/dashboards/` (`provisioning/dashboards/cerberus.yaml`). The AMP datasource uid is `amp`. The image is `grafana/grafana:13.2.3`.
- V. Existing dashboards:
  - `1 · Run Overview: progress, quality, cost` (`cerberus-run-story`, `now-30m`, refresh 15 s, schema 41);
  - `2 · Run Health…` (`cerberus-run-live`);
  - `3 · Spark and Cluster Diagnostics` (`cerberus-spark-on-eks`).
- V. The console build (`observability/grafana/console/build.py` L26-45, `dashboards.py` L190-210):
  - copies every repo dashboard;
  - transforms three of them by uid;
  - raises if any CloudWatch reference is left.
  So the status dashboard must use only AMP and the built-in Grafana datasource.
- V. `observability/grafana/console/test_build.py` L32-38 pins the output to exactly four files. A new dashboard breaks this test until the list is updated.
- V. Console home: `cerberus-runs` ("0 · Recorded runs"), `default_home_dashboard_path` in `grafana.ini.tmpl` L70.

**Run and DQ durations** (the 17 records)
- V. The longest gap from start to collected is about 16 min (`demo-100m-20261108T135119Z`: 859 s run, then collected 75 s later). SLO 3's slow alarm fires at 45 min (`docs/slo.md` L57).

**SLOs**
- V. SLO 1: at least 95% of runs reach `SUCCEEDED` over the trailing 20 runs, with a 5% budget. Its guard today is the CloudWatch alarm `cerberus-pipeline-run-unsuccessful`, which is gated by `pipeline_active` (`docs/slo.md` L55).

**Showcase**
- V. The showcase status values are computed from the run records, with "parity with `make status-e2e`" (`docs/plans/2026-11-20-databricks-free-edition-showcase.md` L34, L272).

## 3. Constraints

- **Cost:** $0 idle.
  - AMP bills rule evaluation as query samples. Five rules every 60 s over at most a few hundred samples each is roughly 10⁸ samples a month, about $0.01 at $0.10 per billion (U until the first bill).
  - SNS email: the first 1,000 a month are free.
  - No new standing compute.
- **CI applies `dev-standing` only.** The first apply, which widens `cerberus-ci-apply`, is a local apply by the owner (2026-10-27 pattern). Claude never applies and never pastes.
- **No account ID, topic ARN or workspace ID in repo files.** Terraform builds the ARNs. The rule YAML holds none.
- **Do not contradict:**
  - ADR 0021: AMP ruler; SNS as the one place alerts arrive; no recording rules; no `execution` label on the latest-run series; the AI panel.
  - ADR 0024: one Grafana file set; the console Grafana has AMP only.
  - ADR 0025: AI never raises or suppresses alerts; the agent tool takes names only.
- **Owner-run:** anything that writes to AWS or to a running Grafana.
- **Audience:** the dashboard is read as a story by every department, in plain words, with a production-level look.

## 4. Options (only where a real choice remains)

**4.1 Where rules live and how they reach AMP.** ADR 0021 decides this, so it is listed only to close it.
- A. Terraform `aws_prometheus_rule_group_namespace` with `data = file(<repo yaml>)`, applied by CI. **Chosen (ADR 0021).** promtool tests the same file.
- B. Owner-run `aws amp put-rule-groups-namespace`. Rejected: drifts from code, and is an owner AWS write every time.
- C. Grafana-managed alerts. Rejected: they need a running Grafana (ADR 0024 runs Grafana only per session), so alerts would stop when nobody is looking. This breaks ADR 0021's "rules are evaluated while the laptop is off".

**4.2 Routing.** ADR 0021 decides this.
- AMP Alertmanager `sns_configs` to the existing `cerberus-pipeline-alerts` topic, with `sigv4: {region: us-east-1}` and `send_resolved: true`.
- The topic policy (new `aws_sns_topic_policy` in the observability module) must hold two statements:
  - (1) the current default statement, kept equivalent: account-owner condition, the same actions, so the CloudWatch alarms keep publishing;
  - (2) `Service: aps.amazonaws.com` with `sns:Publish` and `sns:GetTopicAttributes`, conditioned on `aws:SourceAccount` and `aws:SourceArn` = the workspace ARN.
- A Grafana contact point is rejected for the same reason as 4.1 C.

**4.3 Never reported.** Two designs:
- (a) `latest_started > latest_finished` with `for: 1h`. This depends on the ruler keeping `for` state, and AMP's behaviour across ruler restarts is U.
- (b) **Chosen.** An explicit time test, with no long `for`:
  `((last_over_time(cerberus_run_started_timestamp_seconds[30d]) - on() last_over_time(cerberus_run_finished_timestamp_seconds[30d])) > 0) and on() ((time() - last_over_time(cerberus_run_started_timestamp_seconds[30d])) > 3600)`, then joined with the newest started execution.
  - 1 h is 4 times the longest real gap (about 16 min) and above the 45-min slow alarm.
  - It stays firing until a later run finishes, or for at most 30 days. That is correct: the run really never reported.
  - It cannot fire before the first run, because the series do not exist yet.

**4.4 Error budget without recording rules.**
- Two new entries:
  - `run_success_share_90d`: `avg_over_time(cerberus_run_status[90d])`;
  - `runs_90d`: `count_over_time(cerberus_run_status[90d])`.
- Rule: `((1 - avg_over_time(cerberus_run_status[90d])) > 0.05) and on() (count_over_time(cerberus_run_status[90d]) >= 5)`.
- Each run writes exactly one `cerberus_run_status` sample, so the average is the pass share. A `--force` re-publish counts twice; the publisher README says so.
- Deviation to record in `docs/slo.md`: SLO 1 says "trailing 20 runs", while AMP measures 90 days (the 95-day limit, no recording rules). With fewer than 20 runs in 90 days the two agree; with more, 90 days is wider.
- The CloudWatch alarm stays the guard during `pipeline_active` windows.

**4.5 Dashboard layout.** One dashboard (see open question 2). uid `cerberus-pipeline-status`, title "4 · Pipeline Status: did the last run pass?". Default range `now-30d` to `now`, no auto-refresh (the data changes once per run). Only AMP plus the built-in `-- Grafana --` datasource.

- **Row 1, "Right now, in plain words"** (for everyone). Stat tiles with value mappings, no PromQL visible:
  - "Last run": `latest_status`, 1 = "Passed" (green), 0 = "Failed" (red), no data = "No run yet".
  - "What broke": `latest_failed_step`, legend `{{step}}`, no value = "Nothing, the last run passed".
  - "Data checks": `latest_dq_passed`, 1 = "Passed", 0 = "Failed", NaN = "Not run".
  - "Last good data": `last_success`, unit `dateTimeFromNow` ("3 days ago").
  - "Runs that passed (90 days)": `run_success_share_90d`, percent, threshold 95% (SLO 1), plus `runs_90d` as "out of N runs".
  - A text panel, "How to read this page": five short lines, one per tile, written for a non-engineer. It has no numbers, so it can never be wrong.
- **Row 2, "The last run, step by step"** (operations):
  - bar gauge `latest_step_seconds` (`{{step}}`, in steps order);
  - stats `latest_run_seconds`, `latest_events`, `latest_dq_errors`, `latest_dq_warnings` (NaN = "Not run");
  - stats `latest_started` and `latest_finished` (date-time).
- **Row 3, "History"**:
  - state timeline of `latest_status` over the range (Passed/Failed bands);
  - time series of `run_success_share_90d` with a 95% threshold line.
- **Row 4, "Runs, and how to look closer"**:
  - a table from `runs_started_30d` and `runs_finished_30d` (new entries: `last_over_time(cerberus_execution_started_timestamp_seconds[30d])` and the finished one). It uses the Grafana transformations "join by field" (`execution`) and "add field from calculation" (×1000 for ms).
  - A data link per row to `/d/cerberus-run-story?from=<started ms>&to=<finished ms>`.
  - A text panel: "To see one run in detail: `cerberus run <execution>` in the terminal."
- **Row 5, "AI review (Phase 14)"**: an `annolist` panel, tags `["cerberus-ai"]`, not limited to this dashboard. Description and empty text: "No AI review yet (Phase 14)". Whether `annolist` supports custom empty text in Grafana 13.2.3 is U; if it does not, the panel title carries it.
- **Every panel has a plain-language `description`** (one or two sentences, no jargon). A test enforces this (10.3a).
- **Drill-down by `cerberus_run_info{execution}`:** not needed as a panel. The runs table already carries `execution` through the start and finish series. `cerberus_run_info` stays for 10.5 and Phase 14.

**4.6 Offline verification of the dashboard.**
- CI, static: `check_dashboard`, plus a new dashboard lint:
  - descriptions present;
  - only the `amp` and `-- Grafana --` datasources;
  - no CloudWatch, so it is console-safe;
  - every query-set entry used by a panel exists.
- CI, render (10.3b): the 10.2c throwaway Prometheus plus a throwaway `grafana/grafana:13.2.3`. A test-only provisioning file sets a datasource with uid `amp`, type `prometheus`, URL `http://prometheus:9090`. Publish the FAILED, start and SUCCEEDED fixtures as in `test_e2e.py`. Then for every panel target, `POST /api/ds/query` and assert no error and the expected value (Last run = 1 after the SUCCEEDED push, and so on).
  - U: whether Grafana resolves a panel's `{type: grafana-amazonprometheus-datasource, uid: amp}` against a test datasource of type `prometheus`. Fallback: the test rewrites the type in a temp copy of the dashboard (expressions untouched).
- Local only, optional: a Playwright screenshot of the page (the `console/cerberus_live_check` pattern, `uv run --with playwright==1.65.1`) to a git-ignored folder, for PR review and the README. It is not in CI.

## 5. Recommendation

- 4.1 A and 4.2: ADR 0021, as written.
- 4.3 (b), the explicit 1 h test.
- 4.4: the two `[90d]` entries.
- 4.5 and 4.6: one dashboard, the static checks plus the API render check in CI, and screenshots only locally.
- Evaluation interval 60 s. `for: 2m` on failed run and DQ errors; `for: 0` on never reported and the error budget, whose conditions are already time-based.
- Severity labels: `page` for failed run and never reported, `ticket` for DQ errors and the error budget.

**Alert expressions** (each entry is verbatim, as `check_rule_expr` requires):
- **Failed run:** `(last_over_time(cerberus_run_status[30d]) == 0) + on() group_left(execution) (0 * topk(1, last_over_time(cerberus_execution_finished_timestamp_seconds[30d])))`
- **DQ errors:** `(last_over_time(cerberus_dq_errors[30d]) > 0) + on() group_left(execution) (0 * topk(1, last_over_time(cerberus_execution_finished_timestamp_seconds[30d])))`. NaN > 0 is false, so a suite that did not run never fires.
- **Never reported:** 4.3 (b) `+ on() group_left(execution) (0 * topk(1, last_over_time(cerberus_execution_started_timestamp_seconds[30d])))`
- **Error budget:** 4.4. No `execution` label.
- **Alert-path check** (open question 1): `vector(1) + on() group_left(execution) (0 * topk(1, last_over_time(cerberus_publisher_smoke[10m])))`, severity `info`, `for: 0`. It fires for 10 minutes after `make status-smoke ARGS=--send` and then resolves. The smoke row gains `execution="smoke-<UTC stamp>"` (a publisher change).

**Annotations**, in plain words:
- `summary`: "The latest pipeline run failed."
- `description`: "Run {{ $labels.execution }} did not finish successfully. To see which step stopped it: cerberus run {{ $labels.execution }}. AI review (Phase 14): make review RUN={{ $labels.execution }}."

**SNS template:**
- Subject (at most 100 characters): `[Cerberus {{ .Status | toUpper }}] {{ .CommonLabels.alertname }} {{ .CommonLabels.execution }}`
- Body: the annotations, plus a resolved line.

## 6. ADR

None needed. ADR 0021 and its amendments decide the rule deployment, the routing, the error-budget form, the `execution` join and the AI panel. This plan fixes the values that 10.4 was told to pick.

Additive items to record without an amendment: the alert-path check rule (if accepted) and the 90-day vs 20-run note. Record both in Phases.md 10.4 and `docs/slo.md`. After 10.4c, write the "To confirm in 10.4" results (ruler accepts `topk` + `group_left`; promtool passes the same file) as a dated "Confirmed" line under the 2026-11-12 amendment.

## 7. Build steps (one PR each)

**PR 10.4a: rules, tests and Alertmanager template. Offline.**
- Files:
  - `observability/alerts/status.rules.yaml`: one group `cerberus-status`, `interval: 60s`, four rules (five with the check rule).
  - `observability/alerts/status.rules.test.yaml`: promtool unit tests.
  - `observability/alerts/alertmanager.yaml.tftpl`: `alertmanager_config` and `template_files`, with `${topic_arn}` as the only variable.
  - `observability/alerts/README.md`
  - `observability/queries/status.json`: add `run_success_share_90d`, `runs_90d`, `runs_started_30d`, `runs_finished_30d`. The optional `label` field work (lint in `console/cerberus_console/queries.py`, queries README, tests, and a `label` on every entry) is in this PR (owner answer 3).
  - `observability/status/publish.py` and `test_publish.py`: the smoke `execution` label (if open question 1 is yes).
  - `console/tests/test_alert_rules.py`: loads the rules with `yaml.safe_load`. Every alert `expr` must pass `check_rule_expr`, and every non-budget alert must have `{{ $labels.execution }}` in its annotations.
  - `requirements-dev.txt`: add `PyYAML` pinned (dev and CI only; the version is U at build time).
  - `.github/workflows/code-ci.yml`: new job `alert-rules`. It runs promtool from the same pinned Prometheus image, `promtool check rules` and `promtool test rules`, then amtool from `prom/alertmanager:<pinned tag@digest>` (`amtool check-config` on the template rendered with a dummy ARN by a small script).
  - Makefile `alerts-test` (Docker, no AWS).
  - `docs/slo.md`: SLO 1 guard adds the AMP error-budget alert, plus the 90-day note.
- promtool test cases:
  1. A FAILED run gives `CerberusRunFailed` with `exp_labels {execution, severity}` after 2 m; the next passing run resolves it.
  2. **Race:** the status sample is at t and the finish sample one evaluation later. The alert with the wrong (old) execution must never fire; at 3 m only the new execution fires.
  3. DQ errors 2 fires; DQ NaN does not; DQ 0 does not.
  4. Never reported: a start with no finish has no alert at 59 m and fires at 61 m with the started execution. Start followed by finish within 16 min: no alert.
  5. Error budget: 1 failure in 4 runs, no alert (under 5 runs); 1 in 5, fires; 1 in 20, no alert (exactly 5%, strict `>`).
  6. Alert-path check: fires while a smoke sample is under 10 m old, carries `execution`, and is gone at 11 m.
- Verify:
  - `make alerts-test`;
  - `cd console && uv run --no-project --python 3.12 --with pytest==9.1.1 --with PyYAML==<pin> python -m pytest -q tests/test_alert_rules.py tests/test_queries.py`;
  - `make status-e2e` (the new entries evaluate);
  - ruff.

**PR 10.3a: dashboard JSON and static checks. Offline.**
- Files:
  - `observability/grafana/dashboards/cerberus-pipeline-status.json` (section 4.5)
  - `observability/grafana/console/test_build.py`: add `cerberus-pipeline-status.json` to the L33 list.
  - `console/tests/test_status_dashboard.py`: `check_dashboard` is empty; every panel has a `description`; the datasources are only `amp` and `-- Grafana --`; there is no `cloudwatch` anywhere; the `annolist` panel has tag `cerberus-ai`; Row 1 tiles have value mappings for 1, 0 and NaN or no data.
  - `observability/grafana/README.md`: a section on the new dashboard.
- Verify:
  - `pytest console/tests/test_status_dashboard.py tests/test_queries.py`;
  - `pytest observability/grafana/console` (3.9 job);
  - `make grafana-up` (owner, local; it reads AMP and shows "No run yet" until 10.6).

**PR 10.3b: render check. Offline (Docker).**
- Files:
  - `observability/grafana/render_check/provisioning/datasources/test-prometheus.yaml` (uid `amp`, type `prometheus`, URL to the Prometheus container; test-only)
  - `observability/grafana/render_check/run.sh` (a Docker network with Prometheus v3.15.0 and Grafana 13.2.3, both pinned, both bound to 127.0.0.1; publish the fixtures; run the test; trap removes both)
  - `observability/grafana/render_check/test_render.py` (every panel target through `/api/ds/query`, with value asserts after each push)
  - optional `screenshot.py` (Playwright, local only, writes to a git-ignored folder)
  - Makefile `status-render`
  - `code-ci.yml`: the `status-e2e` job also runs `run.sh`
- Verify: `make status-render` passes; CI is green; containers are gone afterwards.

**PR 10.4b: Terraform and IAM. CI plans; the owner applies locally first.**
- Files:
  - `terraform/modules/pipeline_alerts/{main,variables,outputs}.tf`:
    - `aws_prometheus_rule_group_namespace "status"` (`name = "cerberus-status"`, `data = file("${path.module}/../../../observability/alerts/status.rules.yaml")`);
    - `aws_prometheus_alert_manager_definition` (`templatefile(".../alertmanager.yaml.tftpl", { topic_arn = var.alerts_topic_arn })`).
  - `terraform/modules/observability/alarms.tf`: `aws_sns_topic_policy` with the two statements (4.2) and a new variable `amp_workspace_arn`.
  - `terraform/envs/dev-standing/main.tf`: wire both modules.
  - `terraform/modules/github_oidc/main.tf`, `ci_apply`: new Sid `ManageAmpRulesAndAlerting`. Actions: `aps:CreateRuleGroupsNamespace`, `PutRuleGroupsNamespace`, `DescribeRuleGroupsNamespace`, `DeleteRuleGroupsNamespace`, `ListRuleGroupsNamespaces`, `CreateAlertManagerDefinition`, `PutAlertManagerDefinition`, `DescribeAlertManagerDefinition`, `DeleteAlertManagerDefinition`, plus `aps:TagResource` and `UntagResource` on `rulegroupsnamespace/*`. Scope: workspace and rule-groups-namespace ARNs built from `var.account_id`.
  - `.github/workflows/terraform-plan.yml` and `terraform-apply.yml`: add `observability/alerts/**` to the "read with file()" list.
  - `iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`: the same aps actions in a new Sid `AmpRulesAndAlerting`, with the same resource pattern as the existing aps statements. Do not add a new account-ID line; extend the existing `workspace/*` statement's actions, and add the `rulegroupsnamespace/*` resource only through the same form already used. `iam/cerberus-admin/README.md`: "paste pending".
- Verify (offline):
  - `terraform fmt -check`;
  - `terraform validate`;
  - CI `terraform-plan` shows exactly: 2 to add (namespace, Alertmanager definition), 1 to add (topic policy), 1 in-place change (`ci_apply` policy), plus the known Faker-layer churn;
  - a grep on the diff for 12-digit numbers is empty.
- Owner (writes):
  1. Root-paste the admin policy.
  2. On the PR branch: `make standing-plan`. The plan must match the CI plan; otherwise stop.
  3. `make standing-apply`.
  4. Merge. The CI apply should then show no changes.
- Built 2026-11-21. Notes for the record:
  - The read-only plan showed 3 resources to add (namespace, Alertmanager definition, topic policy), 1 in-place change (`ci_apply` policy) and the known Faker churn.
  - The module is `terraform/modules/pipeline_alerts`. The observability module gained its own `aws_caller_identity` data source for the policy.
  - The admin policy's `Resource` for `AmpQueryAndStatusWrite` became a list with `arn:aws:aps:us-east-1:*:rulegroupsnamespace/*` (no new account-ID line), and the statement also got the three tag actions, so the owner's local apply can tag the namespace.
  - `cerberus-ci-plan` (ReadOnlyAccess) allows the Describe and List actions (checked with `iam simulate-principal-policy`).
  - Owner steps are pending. The runbook is in `observability/alerts/README.md`, "Putting the rules live (owner)".

**10.4c: owner check. No PR, $0, no cluster.**
1. After the 10.2 and 10.4 pastes: `aws amp describe-rule-groups-namespace --workspace-id <id> --name cerberus-status` shows ACTIVE. `aws amp describe-alert-manager-definition` shows ACTIVE.
2. `make status-smoke ARGS=--send`. An email "[Cerberus FIRING] CerberusAlertPathCheck smoke-…" should arrive within about 3 min, and a RESOLVED email after about 10 min. This confirms that the AMP ruler accepts `topk` + `group_left`, that the topic policy works, and that the template prints `execution`.
3. Record the result in Phases.md 10.4 and in the ADR 0021 "Confirmed" line.

**Dependencies for later steps**
- **10.5:**
  - `make status` and `cerberus status` load `status.json` through `console/cerberus_console/queries.py`;
  - an `AmpReader` in `sources.py`;
  - the Lambda zip `source` block for `observability/queries/status.json` (`console_edge/main.tf` L39-40);
  - `aps:QueryMetrics` on the workspace for `cerberus-console-cli` (`console_roles`; CI-applied, `ManageConsoleIamRoles`).
  - It reads only documented labels. It can reuse Row 1's plain words.
- **10.6:** the live pair checks:
  - the dashboard: Row 1 Failed and then Passed;
  - the terminal;
  - the `CerberusRunFailed` email naming the failed execution;
  - the RESOLVED email after the passing run.
  Lineage live check (from 10.2). AMP bill line items.
- **Phase 14 step 6:** a link on `cerberus-run-story` to the AI review panel (ADR 0021 D3).
- **15.x and 11.2:** the showcase reads run records, not AMP. Open question 3 keeps the plain words shared.

## 8. Unverified items

- The SNS topic policy form for AMP (`aps.amazonaws.com`, `aws:SourceArn` and `aws:SourceAccount`), taken from the AMP docs pattern; not re-read.
- That the CI plan role's `ReadOnlyAccess` covers the new Describe and List actions.
- AMP ruler acceptance and behaviour for `topk` + `group_left`, and whether `for` state survives ruler restarts. Confirmed in 10.4c.
- AMP Alertmanager `sns_configs` with `sigv4`, and the subject and message templating. Confirmed in 10.4c.
- Grafana 13.2.3: `annolist` custom empty text; datasource resolution by uid across types in the render check.
- The PyYAML pin and the `prom/alertmanager` tag and digest for amtool (pick at build time; pin by digest as in PR C).
- AMP rule-evaluation billing (the first bill).

## 9. Owner answers (2026-11-20)

All three answers follow the recommendations.

1. Yes. Keep a permanent alert-path check rule. The smoke row gets `execution="smoke-<UTC stamp>"`.
2. One Phase 10 dashboard (status plus an SLO row).
3. Yes. Add an optional plain-language `label` to each query-set entry.
