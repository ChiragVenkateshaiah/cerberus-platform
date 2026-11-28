# Plan: ADR 0021 amendment, 30-day windows in AMP, SLO 1 from run records (2026-11-28)

Source: Opus decision agent, 2026-11-28. Owner direction: "option 1" (30-day
windows for everything evaluated in AMP; the longer SLO figures come from the
run records).

Two points corrected against the request:

- SLO 1 is not defined over 90 days. `docs/slo.md` line 55 sets its window to
  the trailing 20 runs. Only the alert `CerberusErrorBudgetBurn` and the two
  `90d` query entries use 90 days.
- The guard is mostly built. `console/cerberus_console/queries.py:24`
  (`ALLOWED_WINDOWS`) already checks every window in the query set, and the
  dashboard and rule checks already force their PromQL to be query-set
  entries. The main guard is a one-line change plus a cap check.

## 1. Question

How do the status queries, the error-budget alert and the dashboard measure
SLO 1 now that AMP refuses every window from 32d to 95d? It is needed now
because `make status` shows "unavailable" and the budget alert most likely
never evaluates.

## 2. Facts

- **AMP limit.** Measured live 2026-11-28:
  - An instant query with `[90d]` gets HTTP 422 ("queries with long day range
    (32d to 95d) are currently only supported for range type queries").
  - The same as a range query gets 422 ("cannot include range selectors and
    subqueries that exceed 7d in duration").
  - `[31d]` returns 200 for both.
  - So a dashboard time range over 31d would also fail with the existing
    `[30d]` selectors.
- **Where `[90d]` is used today:**
  - `observability/queries/status.json:32-33`: `run_success_share_90d`,
    `runs_90d`.
  - `observability/alerts/status.rules.yaml:57`: `CerberusErrorBudgetBurn`.
  - `observability/grafana/dashboards/cerberus-pipeline-status.json`: three
    targets (lines 469, 480, 1354).
  - Code and tests: `console/cerberus_console/commands.py:122-224` (labels and
    the JSON keys `success_share_90d`, `runs_90d`),
    `observability/showcase/status.json:142-146`,
    `observability/status/test_e2e.py:106-188`,
    `console/tests/test_queries.py:130-196`,
    `console/tests/test_status_amp.py:42-188`,
    `console/tests/test_showcase.py:366`.
- **Window lint today.** `queries.py:24-28` maps `last_over_time` to 30d and
  `avg_over_time`/`count_over_time` to 90d. `check_windows` (line 244) applies
  this map to query-set entries. `check_dashboard` (line 422) and
  `check_rule_expr` (line 474) require any `cerberus_*` use to be a query-set
  entry, verbatim. Gap: a selector that is not in the catalogue is not checked
  (for example `cerberus_publisher_smoke[10m]` in the alert-path rule).
- **Why CI did not catch it.** `promtool test rules` (`Makefile:125`,
  `.github/workflows/code-ci.yml:141-159`) has no 32d-95d limit. The budget
  tests run at 4d and 19d (`status.rules.test.yaml:221-246`).
- **Rule health.** Unreadable: `cerberus-admin` has no `aps:ListRules`
  (`iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json:227-243`).
  The alert-path smoke proves that the ruler and SNS work. It does not prove
  that this rule evaluates. That the rule is dead is unverified, but very
  likely.
- **SLO 1.** The objective is at least 95% of terminal runs `SUCCEEDED` over
  the trailing 20 runs. The budget is about 1 run in 20
  (`docs/slo.md:55,62-85`). The text at lines 76-85 explains the alert's
  90-day window by "an AMP query spans at most 95 days", which is now wrong.
  The CloudWatch alarm `cerberus-pipeline-run-unsuccessful` already pages on
  the first failed run (`slo.md:72-74`).
- **Run records.** 17 files in `observability/scale/runs/`. Each has a
  top-level `status` and `start` (ISO UTC), written by
  `collect_run_metrics.py:505`. The owner runs the collector by hand after each
  orchestrated run; it is not scheduled. Dates: 2026-10-06 to 2026-11-08 (14
  runs from 10-06 to 10-15, 3 runs from 11-07 to 11-08). 15 are `SUCCEEDED`; 2
  are `FAILED` (`exercise-20261008T085728Z`, `exercise-20261009T101830Z`).
- **Runs per 30 days.** At most 14 (run 1 to run 15 spans 32 days). The trailing 30 days (from 10-29) hold 3.
  The busiest window holds 14 runs with 2 failed (14.3%). With the existing
  rule (over 5% and at least 5 runs), one failure in 5-19 runs fires, so on 30
  days, at this rate, the alert fires on every single failure. That duplicates
  the CloudWatch page and goes beyond the SLO, which allows 1 in 20.
- **SLO 1 from the records today.** The trailing 20 runs are all 17 records:
  15/17 = 88.2%, below 95%. The 90-day window (from 2026-08-30) holds the same
  17 runs. The 30-day share is 3/3 = 100%.
- **Retention.** AMP keeps 400 days (ADR 0021, 2026-11-20 amendment). Storage is
  not the limit; the query engine is.

## 3. Constraints

- $20 a month and $0 idle. Every change here is code, a query or a grant.
- The `dev-compute` destroy contract is not touched. CI applies `dev-standing`
  only. The rule-group change follows the 10.4b apply path.
- ADRs touched: ADR 0021 "Error budget over runs" ("90-day window (the query
  range limit is 95)"), and the 2026-11-20 amendment ("One exception ...
  `[90d]`", "Retention ... 90-day error-budget window"), which are superseded.
  ADR 0016: SLO definitions stay in `docs/slo.md`.

## 4. Options (inside the owner's direction)

**A. Window: 30d or 31d.** 30d matches every other lookback and the dashboard
default `now-30d`, and the lint keeps one value. 31d is AMP's exact edge with no
margin. **Choose 30d.**

**B. Alert condition on 30 days.**
1. Keep over 5% and at least 5 runs. Fires on every single failure at about 15
   runs a month: a duplicate of the CloudWatch page.
2. Raise the minimum to 20 runs. 30 days never held 20 runs, so it never fires.
3. **At least 2 failed runs in 30 days and the failed share over 5%.** One
   failure stays the CloudWatch alarm's job. Two failures in under 40 runs
   always exceed the 1-in-20 budget. The 5% clause covers months with 40 or
   more runs. The 5-run minimum is dropped (the 2-failure floor replaces it).
   In the October data it would have fired on 10-09 (2 of 9): correct.

**C. Rule health.**
1. Grant `aps:ListRules` and `aps:ListAlerts` (read-only, same paste) to
   `cerberus-admin`. Add `make alerts-health`, which fails when any rule's
   health is not `ok` or it has a `lastError`. $0, about an hour plus one root
   paste.
2. CI only: a static window cap. Prevents this failure, not the next
   AMP-only limit.
3. Only the alert-path smoke. Proves the path, not each rule.
**Choose 1 plus the CI cap.** promtool cannot reproduce AMP limits.

### Pillar questions (short)

- Reliability: will an alert that cannot evaluate stay silent? Yes, today.
  Hence the health check.
- Operational excellence: can CI stop a wide window being added again? Yes.
- Cost: all options are $0.
- Security: the new grant is read-only, on the same workspace ARN.
- Performance and sustainability: no change.

## 5. Recommendation

1. **Window `[30d]`** for every PromQL window evaluated in AMP. Rename
   `run_success_share_90d` to `run_success_share_30d` (label "Runs that passed
   (30 days)") and `runs_90d` to `runs_30d` (label "Runs in 30 days"). Retitle
   the dashboard panel "Share of runs that passed (30 days)". Rename the JSON
   keys to `success_share_30d` and `runs_30d`.
2. **SLO 1 keeps its definition** (at least 95%, trailing 20 runs). The
   authoritative figures come from the run records. A new stdlib script,
   `observability/scale/slo_report.py` (`make slo`, offline, no AWS), reads the
   top-level `status` of each `observability/scale/runs/*.json`. It counts
   terminal states only (`SUCCEEDED` pass; `FAILED`, `TIMED_OUT`, `ABORTED`
   failures), orders runs by `start`, and prints the trailing-20 share (the SLO)
   and the 90-day share, each with its run count. The owner runs it after each
   collected run and at `/end-day`, and copies the figures into `docs/slo.md`
   "Current standing" with the date. The AMP 30-day share is the live,
   near-term signal only. The SLO 1 text changes only in the measurement
   paragraph (lines 76-85) and the table's "Guarding alarm" cell.
3. **`CerberusErrorBudgetBurn`: fix it now** (very likely dead) as Option B3, on
   `[30d]`. Fires when failed runs >= 2 and the failed share > 5%. The failed
   count is written as `count x (1 - avg)`, built only from the two query-set
   entries, so `check_rule_expr` passes. Keep `round(..., 0.001)`. Severity
   stays `ticket`.
4. **Add `aps:ListRules` and `aps:ListAlerts`** to `cerberus-admin` (one root
   paste) and add `make alerts-health`.
5. **Guard:** set every entry of `ALLOWED_WINDOWS` to `"30d"`; add a cap check in
   `queries.py` (any range selector or subquery over 31d fails, whatever the
   metric; units `d`, `w`, `y` converted to days); run the cap over every `expr`
   in `status.json`, every rule in `status.rules.yaml` (not only catalogue uses)
   and every dashboard target; assert in
   `console/tests/test_status_dashboard.py` that the dashboard `time.from` is at
   most 31d. It runs in the existing `make verify` and code-ci pytest job.

## 6. ADR outline

Amendment section appended to `docs/adr/0021-pipeline-status-and-alerting.md`.

- **Title:** "Amendment (2026-11-28): 30-day windows in AMP; SLO 1 from run
  records".
- **Status:** Proposed. Add a status line under "## Status", in the style of
  lines 15-17.
- **Context:** the AMP limit with the measurements; two status queries fail so
  `make status` is unavailable; the budget rule and three panels use `[90d]`;
  promtool does not model the limit; rule health is unreadable without
  `aps:ListRules`; the run-rate numbers and their effect on the 5%/5-run rule.
- **Decision:** (1) one window, `[30d]`, for all AMP-evaluated PromQL,
  superseding the 2026-11-20 "`[90d]` exception", the "90-day error-budget
  window" statement and the original "90-day window (the query range limit is
  95)"; (2) the query names and labels above; (3) the new budget-rule condition
  and why CloudWatch owns single failures; (4) SLO 1 unchanged, with
  record-based figures from `slo_report.py` over
  `observability/scale/runs/*.json`, field `status`; (5) the `aps:ListRules` and
  `aps:ListAlerts` grant and `make alerts-health`; (6) the 31-day cap check in
  `queries.py`.
- **Consequences:** positive: status works, the budget alert evaluates, the
  regression is blocked in CI. Negative: the AMP budget view covers 30 days, not
  20 runs; the record-based SLO depends on the owner collecting every run
  including failed ones; one more manual step (`make slo`); one more root paste.
  Neutral: renamed JSON keys in the console output and the showcase snapshot.

`docs/slo.md` changes in the same PR: lines 55 and 76-85, and "Current
standing" gets the record figures.

## 7. Build steps (each one PR, under Phase 10.4 and 10.5 in `Phases.md`)

1. The ADR amendment and the `docs/slo.md` text (docs only). Verify:
   `make verify` and a review against this plan.
2. 30-day switch and guard (one PR; the lint couples the files): `queries.py`
   (`ALLOWED_WINDOWS`, cap check, messages at lines 247-276), `status.json` (2
   entries), `status.rules.yaml` (new rule, comment and annotation text "last 30
   days"), `status.rules.test.yaml` (1 failure in 15: no fire; 2 failures in 9:
   fire; 2 failures in 60 runs: no fire; a failure that leaves the window after
   30d), the dashboard (3 targets, panel title), `commands.py`,
   `observability/showcase/status.json`, the tests in Facts,
   `observability/queries/README.md:44-47`. Verify: `make verify`,
   `make alerts-test`; negative tests: an entry with `[32d]` fails the lint, a
   rule with `foo[90d]` fails.
3. The run-record SLO report: `observability/scale/slo_report.py`, a test with
   fixture records, the `make slo` target. Verify: on today's records it prints
   trailing-20 = 15/17 (88.2%) and 90-day = 15/17.
4. Rule health: `aps:ListRules` and `aps:ListAlerts` in the policy JSON and a
   `make alerts-health` script (SigV4 GET `/api/v1/rules`, signed as
   `observability/status/aws_send.py`). Verify: unit test with a canned reply.
5. Owner steps: root paste of the policy; local apply of the rule-group
   namespace (10.4b path); `make alerts-health` shows all rules `ok`;
   `make status` returns all 14 queries; `make slo`, then update "Current
   standing"; then the 10.4c and 10.6 live checks.

## Owner answers (2026-11-28)

1. SLO 1 on the records reads 88.2%. "Current standing" shows it as breached,
   naming the two failed runs (`exercise-20261008T085728Z`,
   `exercise-20261009T101830Z`). Answer: yes, show it.
2. Every orchestrated run since 2026-10-06 is in `observability/scale/runs/`,
   including failed ones. Answer: confirmed. Add a runbook rule: collect every
   run, pass or fail.
3. Budget alert: at least 2 failed and over 5% (no 5-run minimum). Answer: the
   recommended condition.
