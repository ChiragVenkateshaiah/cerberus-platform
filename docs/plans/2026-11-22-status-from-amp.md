# Plan 10.5: terminal status view from AMP

No NEEDS DECISION. Everything below fits ADR 0021 and its two amendments. A design choice that avoids a new grant is in Open question 1.

**Goal.** `cerberus status` and `make status` run one command (`cmd_status`). They read the named query set from AMP and show it in plain words. If AMP fails, they fall back to what they show today.

**Facts (sources are on origin/main)**
- `console/cerberus_console/queries.py` already has `load()` and `queries()`. Its docstring says nothing imports it yet. `config.QUERIES_FILE` points at `observability/queries/status.json`.
- status.json has 17 entries, 16 with a `label`. Labels: "Last run", "What broke", "Last run started", "Last run finished", "Last good data", "Last run duration", "Time per step", "Events handled", "Data checks", "Data check errors", "Data check warnings", "Newest finished run", "Newest started run", "Runs that passed (90 days)", "Runs in 90 days", "Run start times", "Run finish times". Labels can be absent, so fall back to `name`.
- `sources.py` says "Phase 10 adds an AMP reader here". The `Sources` dataclass has `sfn_factory` and `freshness_factory`, and `Unavailable` carries no message. I will add `amp_factory`.
- `aws.py` is the only file that imports boto3. It lazy-imports it, has `TTLCache` (with negative TTL), uses a botocore `Config` (3 s connect, 8 s read, 2 attempts), and has `assumed_session()` for the local CLI.
- `observability/status/aws_send.py` is the pattern to copy. It uses `botocore.auth.SigV4Auth` plus `urllib`, service `aps`, a 5 s timeout, 2 attempts, and a 1 MiB read cap (`READ_MAX`). It builds the URL with `urlencode(..., quote_via=quote)`, because SigV4 signs `%20`. It reads `data["data"]["result"]`.
- `aws_send.py` finds the workspace by `aps:ListWorkspaces(alias="cerberus-platform")`. That action has no resource-level scoping. `terraform/modules/github_oidc/main.tf` L394-403 grants it on `*` for CI.
- `terraform/modules/console_roles/main.tf`: the `cerberus-console-cli` policy has no `aps:*` today. `grafana_read` already has `aps:QueryMetrics` on `var.amp_workspace_arn`. That variable already exists in the module and is wired in `terraform/envs/dev-standing/main.tf` L173.
- `console_edge` gets no AMP value today. The Lambda env has only `CERBERUS_RUNS_DIR` and `CERBERUS_STATE_MACHINE_ARN` (`console_edge/main.tf` ~L499). The zip's `source` blocks cover `cerberus_console/*.py` and `runs/*.json`.
- `module "console_edge"` and `module "console_roles"` are both in `dev-standing/main.tf`. `dev-standing/outputs.tf` L96 already exports `prometheus_endpoint`.
- CI applies `dev-standing` (`.github/workflows/terraform-apply.yml`). `ManageConsoleIamRoles` (`github_oidc/main.tf` L596) allows `PutRolePolicy` on exactly the two console roles.
- `console/tests/test_edge_config.py` pins the console-cli write set to exactly four actions (`CLI_WRITE_ACTIONS`) and checks that one policy is attached. `QueryMetrics` is read-only and does not break these tests. Add an assertion that its only `aps:` action is `aps:QueryMetrics` on the workspace ARN.
- `make cerberus CMD=status` runs `python -m cerberus_console` with boto3 as `cerberus-console-cli` (Makefile L157).
- `cmd_status` today has three sections: latest execution (Step Functions), gold freshness (Athena), and newest run record. Each section is wrapped in `_section()`, which turns any failure into the fixed UNAVAILABLE line.
- Plan Dependencies for 10.5: `docs/plans/2026-11-20-status-dashboard-and-alerts.md` L295-301.

**Settled questions**
1. **Layout.** One new first section, "Pipeline status (from Prometheus)", with `label : value` rows.
   - Last run: "passed" or "failed" from `latest_status`.
   - What broke: the `step` label of `latest_failed_step`, shown only when failed.
   - Last run started, Last run finished, Last good data: each shown as time plus age (reuse `_when` and `_age`).
   - Last run duration (`latest_run_seconds`), Events handled (`latest_events`).
   - Data checks: "passed", "failed" or "not run" when NaN. Errors and warnings are shown only when not NaN.
   - Runs that passed (90 days): a percentage, with "Runs in 90 days" beside it.
   - Newest finished run: the `execution` label.
   - Time per step: a small table, `step` label and seconds, with NaN shown as "not reached".
   - Skip `runs_started_30d`, `runs_finished_30d`, `newest_started_execution` and `latest_dq_*` detail beyond the above. They are for the dashboard and the agents.
   - Behaviour: AMP down gives UNAVAILABLE for that section and the three old sections still show. AMP up but empty gives "no data yet", not "failed". An empty `latest_failed_step` while `latest_status` is 1 is normal and prints nothing. The AMP section is added and the existing three are kept (see Open question 2).
   - The JSON `data["pipeline"]` has `available`, plus a `none` flag for no data.
2. **AmpReader** (`aws.py`, because only that file may import boto3; the protocol goes in `sources.py`).
   - Signing: reuse `botocore.auth.SigV4Auth` and `AWSRequest` with `urllib`, as `aws_send.py` does. This is the same lazy-import pattern. Credentials come from the session (the Lambda role, or `assumed_session()` locally).
   - Endpoint: see Open question 1. The default is env `CERBERUS_AMP_QUERY_URL` (from Terraform). Locally, `make status` has no env var, so `AwsAmpReader` falls back to `aps:ListWorkspaces(alias=cerberus-platform)`. That needs a second grant on the CLI role, so I recommend the owner decides it.
   - Limits: 4 s timeout and 2 attempts (shorter than `aws_send.py`, because the Lambda timeout is 25 s), 256 KiB read cap, at most 100 series per entry, a global 5 s deadline. All 14 or so queries run sequentially, so the Lambda timeout must cover this (check `lambda_timeout_seconds`).
   - Cache: a `TTLCache` of 30 s with a negative TTL of 60 s, so a flood of visitors costs a handful of AMP calls. Queries are the fixed `expr` strings from status.json. No visitor input reaches a query.
   - Parse: take only `metric.step`, `metric.execution` (both optional) and `value[1]`. `float()` the value, so "NaN" gives None. Ignore `__name__` and every other label. Pass each string through `sanitize.py` and cap it at `config.FIELD_CHARS`. Drop non-vector `resultType`, malformed rows and non-finite values (except NaN to None).
   - The reader is called by name, as ADR 0021 requires. `amp.query(name)` looks up the `expr` in the loaded set. An unknown name raises.
3. **IAM.** In `console_roles/main.tf`, add a statement `QueryStatusMetrics` to the `console_cli` policy: `aps:QueryMetrics` on `var.amp_workspace_arn`. The Lambda role is the same role (`cerberus-console-cli`), so this covers both Lambda and local use.
   - It is CI-applied: `ManageConsoleIamRoles` already covers `PutRolePolicy` on this role, and trust is unchanged. No owner IAM step, unlike 10.4b, which widened `cerberus-ci-apply`.
   - The Lambda env var change needs `lambda:UpdateFunctionConfiguration` for CI. This is unverified, but the existing apply path already updates this function.
   - If Open question 1 is answered "list by alias", you would also need `aps:ListWorkspaces` on `*` for `cerberus-console-cli`. That statement is allowed by the same CI grant but needs a decision.
4. **`make status`.** Add a Makefile target, `status: ## READ-ONLY, owner-run: pipeline status ...`, running `$(MAKE) cerberus CMD=status`. Document that it needs `cerberus-admin` credentials to assume `cerberus-console-cli`. Offline (no AWS), `cmd_status` shows UNAVAILABLE for the AWS sections and the record summary still prints, so no extra fallback code is needed.
5. **Tests** (`console/tests/`). Fixtures in `fixtures/amp/` use the real Prometheus API shape: `{"status":"success","data":{"resultType":"vector","result":[{"metric":{...},"value":[1699999999.1,"1"]}]}}`.
   - Cases: `__name__` present and absent; value "NaN", "+Inf", "" and non-numeric; an empty result; resultType matrix or scalar; `status:"error"`; HTTP 5xx and 4xx; a timeout.
   - Hostile labels: control characters, ANSI, a 10 KB string, a newline, and markup in `step` and `execution`. Assert that they come out sanitised and capped.
   - Size cap test: a 2 MiB reply is truncated and fails closed. Row cap test: 500 series.
   - Command tests: layout, the fallback, "no data yet", and JSON output. Add the new fixtures to the 9.3 safety suites (`test_hostile_corpus.py`, `test_fuzz.py`, `test_banned_calls.py`). The banned-calls test must allow `urllib.request` only in `aws.py`.
   - Also add IAM tests (see Facts) and a test that `status.json` is in the Lambda zip.

**Steps (3 PRs)**
- **10.5a, code only (no Terraform).**
  - Files: `sources.py` (`AmpReader` protocol and `amp_factory`), `aws.py` (`AwsAmpReader`, wiring in `build_sources`), `config.py` (the caps and TTLs), `commands.py` (`cmd_status` and the plain-words layout), `queries.py` (a `by_name()` helper), and the tests and fixtures above.
  - Acceptance: `make verify` passes, and the tests show the offline fallback and the UNAVAILABLE and "no data yet" paths.
- **10.5b, Makefile and docs.** `status` target, the `console/README.md` text, and a note in the 9.3 help line for `status`.
  - Acceptance: `make status` offline prints the record section and no traceback.
- **10.5c, Terraform (only after #176 merges).**
  - Files: `console_roles/main.tf` (the `aps:QueryMetrics` statement), `console_edge/main.tf` (add `local.queries_file` as a third `source` block with filename `observability/queries/status.json`, plus env `CERBERUS_QUERIES_FILE=/var/task/observability/queries/status.json` and `CERBERUS_AMP_QUERY_URL`), `console_edge/variables.tf`, and the `dev-standing/main.tf` wiring from `module.prometheus_workspace.prometheus_endpoint`. `config.QUERIES_FILE` otherwise resolves to `parents[2]`, which is wrong inside the zip.
  - Add a URL allowlist in `aws.py` `_base_ok`, checked before signing: https only, host exactly `aps-workspaces.<config.REGION>.amazonaws.com` (no wildcard, no subdomain), no port, no userinfo, path `^/workspaces/ws-[a-z0-9-]+/?$`.
  - Add a test in `test_edge_config.py` for the `aps:` statement and the zip source block.
  - Acceptance: `make verify` passes, and the plan shows only the policy, the zip and the env change.

**Verify.** `make verify` (offline, runs ruff, the console tests, `terraform fmt` and the account-number scan). Also run `make verify-full` only if Docker is available. It is not needed for 10.5.

**Owner steps**
1. After 10.5c merges, CI applies. Then run `make status` as `cerberus-admin`, and check the live terminal with `status`.
2. If the answer to Open question 1 is "list by alias", the owner pastes nothing. CI can apply it, because `ManageConsoleIamRoles` allows `PutRolePolicy`.
3. Do not apply 10.5c locally. Order: 10.5c must not merge between the owner's local apply of #176 and #176's own merge, because the CI apply would then run on a stale state and might revert or conflict. Merge 10.5a and 10.5b at any time, since they change no Terraform.

**Risks and unverified**
- **Security tier S.** 10.5c widens the IAM role `cerberus-console-cli`, which the public console Lambda runs as. It gains read access to all metrics in the AMP workspace (`aps:QueryMetrics`, workspace scope only). Mitigations: queries are fixed constants, only three label or value fields are parsed, and output is sanitised and capped. The reviewer must treat 10.5c as security-tier S.
- AMP query cost and rate. The real cost bound is the stage throttle (1 rps, burst 3), invite-only Cognito sign-in and the 30 s cache. Concurrency is NOT reserved (`command_reserved_concurrency` default -1). The AMP query rate limit is shared per workspace with Grafana (unverified). The AMP query price estimate is unverified.
- Sequential AMP queries (risk materialised, measured live 2026-11-28 with `make status`): the first of 17 queries took about 2.2 s (connection setup) and each next about 0.77 s, so the shared 5 s deadline ran out after 5 queries and the whole Pipeline status section was unavailable (`pipeline status failed: Unavailable`). Fixed in 10.5 by `AwsAmpReader.query_many`: up to 8 parallel threads (`AMP_MAX_WORKERS`) under one overall deadline of 10 s (`AMP_DEADLINE_SECONDS`; the Lambda timeout is 25 s). Cost note stays: the stage throttle (1 rps, burst 3) bounds callers, each status now makes up to 17 parallel AMP queries, and the 30 s cache serves repeats.
- `topk(1, ...)` returns a series with an `execution` label. Behaviour on AMP is the same as in 10.4c (unverified there too).
- CI permission for the Lambda update is verified: `lambda:*` on `cerberus-console-*` at `terraform/modules/github_oidc/main.tf` ~L622.

**Open questions**
1. Where does the Lambda get the AMP endpoint? Recommended: Terraform passes it as env var `CERBERUS_AMP_QUERY_URL` from the existing `prometheus_endpoint` output. This needs no `aps:ListWorkspaces` grant, so the policy stays narrowest. For local `make status`, read the same value with `terraform output` in the Makefile, or accept `AMP_QUERY_URL=` as an argument. Do not add `ListWorkspaces` on `*`.
2. Keep Athena freshness and the run-record sections below the new AMP section? Recommended: yes, and keep them unchanged. This keeps the 9.3 output stable.
3. Should the live terminal show the "Time per step" table? Recommended: yes, capped at 12 rows.

## Owner answers (2026-11-22)

1. The Lambda gets the AMP endpoint from env `CERBERUS_AMP_QUERY_URL`, set by Terraform (no `aps:ListWorkspaces` grant). Locally, `make status` accepts the same value from `AMP_QUERY_URL=` or from `terraform output`.
2. Keep the Athena freshness and run-record sections below the new AMP section, unchanged.
3. Show the "Time per step" table, capped at 12 rows.
