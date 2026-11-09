# Plan: 9.3 the read-only command set (ADR 0024, build step 6)

Date: 2026-11-01. Planner: Opus. No new ADR is needed. This is implementation inside ADR 0024. It has two named deviations (section 5). Base: `main` at `bcbf804`.

User decisions (2026-11-02):
- Option A: the console workgroup, the `console/` result prefix and the `cerberus-console-cli` Athena/Glue/S3 read grants move into this step as PR 6a. PR 6a merges after the 8.10 take is recorded.
- No AMP read in 9.3 (deviation 2). Phases.md 9.3 wording becomes "reads run records, Step Functions and Athena (AMP once Phase 10's status series exist)".
- `slo` shows SLO 1 honestly and adds one context line: both failures were scale-up bottlenecks in `RunDbt`, fixed in 8.6. The line must cite the 8.6 evidence (records or Phases.md 8.6), and the executor verifies that claim before writing it. Outcome: the evidence supports only half of it. Failure 1 (`exercise-20261008T085728Z`) was a missing dbt-role grant on the new Iceberg silver path (ADR 0017, found 2026-10-08); failure 2 (`exercise-20261009T101830Z`) was Athena's 1 GiB scan cutoff at 10M, raised to 10 GiB in 8.6 (#83). The `slo` text states both causes and cites `docs/scale-metrics.md` and ADR 0017.
- Plan confirmed as written.

## 1. Question

How do we build the console command package (`status`, `runs`, `run <id>`, `cost`, `dq`, `slo`, `help`) so it is "not a shell" by construction, has $0 idle cost, needs no AWS in CI, and can run live as `cerberus-console-cli` now? The open part is risk 8 of the read-only roles plan. Step 6's local check runs every command as `cerberus-console-cli`, but the `cerberus_platform_console` workgroup and its result prefix are planned for step 7. It is needed now because the user asked to start 9.3, and step 7's Lambda imports this package.

## 2. Facts

Repo:
- F1. ADR 0024 sets the command set and its sources. `runs`, `run <id>`, `cost`, `dq` and `slo` read the run records in git. `status`, and `run <id>` detail, use the Step Functions read APIs. `status` also runs one fixed freshness query on gold, in `cerberus_platform_console` with a small cutoff. Commands never call Cost Explorer. The "not a shell" rules 1-9 cover: at most 8 tokens of at most 64 characters, an allowlist, fail-closed, output sanitising, no `subprocess`/`os.system`/`eval`/`exec` (ruff `S`), fixed SQL in an enforced workgroup, a read-only role whose one write is Athena's result object in a prefix with a 1-day lifecycle, and step-7 rate bounds. One package serves the CLI and the Lambda (`docs/adr/0024-demo-console.md` L135-178).
- F2. ADR 0021 L134-136: Phase 10's `make status` "must be the same code as Phase 9's `cerberus status` (9.3)". The AMP status series (`cerberus_run_status` and the rest, L150-158) are a Phase 10 deliverable and do not exist yet.
- F3. ADR 0024 does not name AMP as a source for any command. Phases.md 9.3 says "reads run records, Step Functions, Athena and AMP". Demo-console plan §4.4 says AMP is an "optional fixed PromQL in `run <id>`". Each run record already holds a `prometheus` summary (`peak_active_series`, Spark input and shuffle bytes).
- F4. `cerberus-console-cli` today allows only `states:DescribeStateMachine` and `ListExecutions` on the state machine, and `DescribeExecution` and `GetExecutionHistory` on `execution:cerberus-platform-orchestration:*`. Its trust is Lambda plus `user/cerberus-admin`. The header says the Athena, Glue and gold grants and the workgroup and prefix "arrive with the command set in 9.3" (`terraform/modules/console_roles/main.tf` L11-16, L80-130).
- F5. The CI managed policy `cerberus-ci-apply-console` has `athena:*` on `workgroup/cerberus_platform_console` (Sid `ManageConsoleAthenaWorkgroup`), `iam:PutRolePolicy` on `role/cerberus-console-cli`, `lambda:*` on `function:cerberus-console-*`, and `s3:*` on the site bucket `cerberus-platform-console-<account_id>` (`terraform/modules/github_oidc/main.tf` L576-640). The inline CI policy has `s3:*` on the Athena results bucket (Sids `ManageMedallionBuckets`/`ManageMedallionBucketContents`, L190-205).
- F6. `iam/cerberus-admin/policies/cerberus-admin-console-edge.json` (Sid `ConsoleAthenaWorkgroup`) gives `cerberus-admin` Get/Create/Update/Delete and tags on the console workgroup. A local plan can read it.
- F7. The results bucket `cerberus-platform-athena-results-<account_id>` is in `terraform/modules/athena`. It has one lifecycle rule, `expire-query-results`, with `filter {}` and 7 days (`results_expiration_days`). Workgroups `cerberus_platform` (not enforced, 25 GiB cutoff) and `cerberus_platform_dq` (enforced, `data_quality/` prefix) follow this pattern (`terraform/modules/athena/main.tf`, `variables.tf`).
- F8. `cerberus-serving` is the template for an Athena read role: S3 Get on gold, Glue `GetDatabase/GetTable/GetTables/GetPartitions`, Athena Start/Get/GetResults/Stop/GetWorkGroup on one workgroup, and S3 Get/Put on results (`terraform/modules/iam/main.tf` L499-560).
- F9. Gold is Iceberg (`transform/dbt/dbt_project.yml`, `+table_type: iceberg`, `schema_table_unique`). The three marts are `fct_transactions` (incremental merge), `dim_customers` and `dim_merchants`.
- F10. Run records: 14 files in `observability/scale/runs/`, 172 KB in total, all printable ASCII, and no account ID in any string value. Top-level keys: `execution, status, start, end, run_seconds, events_processed, events_per_second, silver, states[], athena_totals, prometheus, storage_snapshot, generator, cost, data_quality, collected_at`. The fields vary: `demo-7-8-take1-20261006T075445` has no `generator`, `data_quality: null`, and no `cost.complete`. Records from 2026-10-12 on add `data_quality.ledger` and `mode`.
- F11. In the records, 12 of 14 runs SUCCEEDED. Both failures stopped in `RunDbt` (`exercise-20261008T085728Z`, `exercise-20261009T101830Z`). All 14 have `run_seconds` < 1800. `RunServingQuery` engine time is 0.7-5.0 s in all 12 successful runs. `data_quality.passed` is true 12 times, false once, and null once.
- F12. `docs/slo.md` defines six SLOs. 1 (success, 95% of the trailing 20), 3 (latency < 30 min, 90%), 4 (serving < 30 s, 99%) and 5 (dbt tests, a hard gate whose miss "is a pipeline-success failure (objective 1)") can come from the records. 2 (gold freshness) and 6 (observer) need CloudWatch `FreshnessSeconds`. SLO 4 is judged on `engine_seconds` (docs/scale-metrics.md, "SLOs under load").
- F13. Python layout: no shared package. Lambdas are `python3.12` (`terraform/modules/{lineage,lambda_ingestion,observability}`). Scripts run with `uv run --no-project --with boto3` (`observability/scale/collect_run_metrics.py` header). `ingestion/requirements.txt` pins `boto3==1.43.67`. `pyproject.toml` ruff selects `E,F,I,B,UP`, py312, line length 100. `requirements-dev.txt` pins ruff 0.16.4 and pytest 9.1.1. `code-ci.yml` runs `ruff check .`, `ruff format --check .`, `pytest observability/spark_progress` (3.10) and dbt parse, and has no AWS access.
- F14. `orchestration/exercise.sh` calls `list-executions` once (L145) and polls `describe-execution` (L345).
- F15. The AWS provider is `5.100.0`, constraint `~> 5.0` (`terraform/envs/dev-standing/.terraform.lock.hcl`).

AWS (read-only, `cerberus-admin`, us-east-1, 2026-11-01):
- F16. The state machine is `STANDARD` and `ACTIVE`. `list-executions` returns 34 executions. The oldest is `ace6ad33-…` (2026-08-20, 73 days ago), and the newest is `exercise-20261015T145812Z`. No 8.10 execution exists yet. Names include UUIDs, `phase7-exercise-run-N-…`, `rehearsal-7-7-…`, `demo-7-8-take1-…` and `exercise-YYYYMMDDTHHMMSSZ`.
- F17. Workgroups: `cerberus_platform`, `cerberus_platform_dq` and `primary`. `cerberus_platform_console` does not exist.
- F18. The site bucket `cerberus-platform-console-<account_id>` does not exist (HeadBucket 404). It belongs to step 7 (the CI Sid `ManageConsoleSiteBucket` and the admin Sid `ConsoleSiteBucket` name it as the site bucket).
- F19. Glue `UpdateTime`: `fct_transactions` 2026-10-15T15:23:12Z, `dim_*` 15:22:50Z-15:22:51Z, `payments_events` 15:18:25Z, and `payments_current` 2026-08-10 (no longer refreshed). Iceberg metadata per table: `fct_transactions` has 33 objects / 243,154 bytes (current metadata.json 15,259 bytes), and each `dim_*` has 3 objects / about 13.6 KB. Location pattern: `s3://cerberus-platform-gold-<ACCOUNT_ID>/cerberus_platform/<table>/<uuid>/metadata/`.
- F20. `simulate-principal-policy` on `role/cerberus-ci-apply`. Allowed: `athena:CreateWorkGroup/GetWorkGroup/UpdateWorkGroup/DeleteWorkGroup/TagResource/ListTagsForResource` on the console workgroup, `s3:PutLifecycleConfiguration/GetLifecycleConfiguration` on the results bucket, and `iam:PutRolePolicy/GetRolePolicy` on `cerberus-console-cli`. Implicit deny: `iam:UpdateAssumeRolePolicy`. **CI can create everything risk 8 needs.**
- F21. `cerberus-admin` may `sts:AssumeRole` into `cerberus-console-cli`. The role is denied `athena:StartQueryExecution`, `glue:GetTable` and `s3:GetObject` today.
- F22. Lambda account concurrency is 10, and unreserved is 10. That is a step 7 decision (demo-console plan step 7 "Open"). **Step 6 does not need it.**

External (read 2026-11-01):
- F23. Step Functions quotas: Standard execution history is kept "90 days after an execution is closed" (verified, this closes the §8 item). The API refill rates per second in us-east-1 are ListExecutions 5 (bucket 200), GetExecutionHistory 20 (400) and DescribeExecution 15 (300). Execution names must not contain whitespace, wildcards, brackets, ``" # % \ ^ | ~ ` $ & , ; : /`` or control characters, and can be up to 80 characters.
- F24. Step Functions pricing: "You are charged based on the number of state transitions". The page lists no charge for API reads. This is **consistent with "not billed", but the page does not state it in words.** The records show `AWS Step Functions: 0.0` on exercise days. Confirm in Cost Explorer after step 7.
- F25. Athena `BytesScannedCutoffPerQuery` has a minimum of 10,000,000 bytes (API reference). AWS provider 5.100 requires at least 10485760 (10 MiB) and rejects 10000000. The list price is $5/TB with a 10 MB minimum per query (ADR 0024, 2026-10-27), so one minimum-billed query costs about $0.00005.
- F26. Athena managed query results (`ManagedQueryResultsConfiguration`) exist in the API. Terraform support in provider 5.x is **unverified** (F15).

## 3. Constraints

- $0 idle. A workgroup, a lifecycle rule and an IAM policy have no charge. The per-call costs are in section 5.
- `dev-compute` is not touched. CI applies `dev-standing` only. The 8.10 take is this weekend. PR 6a changes the lifecycle of the shared results bucket, which the 8.10 run's dbt and DQ queries write to. **Merge 6a only after the take is recorded.** PRs #126 and #107 are not touched.
- No trust-policy change (CI lacks `iam:UpdateAssumeRolePolicy`). Both trusts already exist (F4). `cerberus-admin` lacks `iam:UpdateRole`, which does not matter here.
- Public repo: no account ID in new files. Use `data.aws_caller_identity` in Terraform, the caller identity at runtime, and `<ACCOUNT_ID>` in fixtures. No emails, secrets or credentials-file mentions. The CLI never prints session keys.
- ADR 0024 is followed, not amended. ADR 0021: the package must be reusable as `make status` later.
- Tools: `TMPDIR=$HOME/.cache/tfspiketmp` for terraform. Run ruff via `uvx ruff@0.16.4`.

## 4. Options (for risk 8; the package design is fixed by ADR 0024)

- **A (recommended, chosen). Move the workgroup, the result prefix and the `cerberus-console-cli` Athena/Glue/S3 read grants into step 6 as PR 6a (Terraform, CI-applied).**
  - Idle: $0.
  - Per use: at most about $0.00005 per uncached `status` (F25), plus one S3 PUT and GET.
  - Effort: about 80 lines of HCL and one CI cycle.
  - Gives up: nothing. Step 7 loses one item and gets simpler.
  - CI can do all of it (F20).
- B. Keep them in step 7. Step 6's live check runs `status` with the gold section shown as "unavailable".
  - $0. Less work now.
  - Gives up: the bytes-scanned measurement (§8) and the IAM proof of the fixed query move into step 7, where they get mixed with edge, JWT and Lambda debugging. Step 6's verify line ("every command works as `cerberus-console-cli`") is not met.
- C. Replace the Athena query with Glue `GetTable` `UpdateTime`.
  - $0 per call, no result write and no workgroup. F19 shows that `UpdateTime` tracks the dbt commits.
  - Gives up: the live "query engine" proof. It needs an amendment to ADR 0024 (the sources list and rules 6-7), which counts as a new decision.
  - Not recommended: ADR 0024 already accepted the Athena query, and the cost gap is about $0.00005 per call.
- D (rejected). Athena managed query results, with no S3 prefix at all. Provider support under `~> 5.0` is unverified (F26). A provider major bump is out of scope, and it changes ADR rule 7's wording.

## 5. Recommendation

**Option A, as two PRs.** Named deviations:
1. From the demo-console plan §7: the workgroup, the prefix and the read grants move from step 7 to step 6. This resolves risk 8 of the read-only roles plan.
2. From Phases.md 9.3 wording: **no AMP read in 9.3.** ADR 0024 lists no AMP source, the records already carry the Prometheus summary (F3), and the AMP status series are Phase 10's (F2). The package keeps a source interface, so Phase 10 can add an AMP reader without changing the grammar. Phases.md text: "reads run records, Step Functions and Athena (AMP once Phase 10's status series exist)".

Design (within ADR 0024):

**Result location:** `s3://cerberus-platform-athena-results-<account_id>/console/`, with a new lifecycle rule `expire-console-results` (prefix `console/`, 1 day). Where lifecycle rules overlap, S3 applies the shortest expiration. Not in the site bucket: that bucket is served through CloudFront OAC, and query results do not belong next to public files.

**Workgroup** `cerberus_platform_console` in `terraform/modules/athena`, next to `data_quality`:
- `enforce_workgroup_configuration = true`
- `bytes_scanned_cutoff_per_query = 10485760` (the provider minimum, about 39 times the 270 KB of metadata in F19)
- `publish_cloudwatch_metrics_enabled = true`
- `force_destroy = true`
- output `s3://<results>/console/`

**The fixed query** (a constant string with no formatting; table names are constants):
```sql
SELECT 'fct_transactions' AS table_name, max(committed_at) AS last_commit FROM "cerberus_platform"."fct_transactions$snapshots"
UNION ALL SELECT 'dim_customers', max(committed_at) FROM "cerberus_platform"."dim_customers$snapshots"
UNION ALL SELECT 'dim_merchants', max(committed_at) FROM "cerberus_platform"."dim_merchants$snapshots"
```
This reads Iceberg metadata only. `payments_current` is excluded because it is stale since 2026-08-10 (F19).

**New `cerberus-console-cli` statements** (no write except the results prefix):
- `RunConsoleQuery`: `athena:StartQueryExecution, GetQueryExecution, GetQueryResults, StopQueryExecution, GetWorkGroup` on the console workgroup only.
- `ReadGoldCatalog`: `glue:GetDatabase, GetTable` on the catalog, `database/cerberus_platform`, and exactly `table/cerberus_platform/{fct_transactions,dim_customers,dim_merchants}`.
- `ReadGoldMetadata`: `s3:GetObject` on `<gold_arn>/cerberus_platform/<table>/*/metadata/*` for the three tables only (`for t in var.gold_table_names`). Gold data files stay unreadable.
- `WriteConsoleResults`: `s3:GetObject, PutObject, AbortMultipartUpload` on `<results_arn>/console/*`.
- `ListConsoleResults`: `s3:GetBucketLocation` on the results bucket, unconditioned. `ListConsoleResultsPrefix`: `s3:ListBucket` on the results bucket, conditioned on `s3:prefix` `console/*`. Accepted executor deviation: the plan had one statement; it is split in two, so six statements in total.
- The metadata-only S3 scope and the exact Glue set are **unverified for Athena's engine**. If the live run gets AccessDenied, widen to `<gold_arn>/cerberus_platform/*`, add `glue:GetTables`, add `s3:ListBucket` on the results bucket without the `s3:prefix` condition (HeadBucket checks ListBucket with no prefix key), and add `s3:ListBucket` on the gold bucket with `s3:prefix` `cerberus_platform/*`. All are still read only (risk 2).

**Package:** `console/cerberus_console/`, stdlib plus boto3. boto3 is imported lazily in `aws.py` only, so tests need only pytest.

| File | Role |
|---|---|
| `config.py` | Constants: `STATE_MACHINE_NAME`, `WORKGROUP`, `DATABASE`, `GOLD_TABLES`, `FRESHNESS_SQL`, limits, cache TTLs, `RUNS_DIR` (env `CERBERUS_RUNS_DIR`, else `<repo>/observability/scale/runs`) |
| `grammar.py` | Input validation and the allowlist table; returns a `Command(name, args)` or raises `Refused` |
| `records.py` | Loads `*.json` from `RUNS_DIR` (max 200 files, max 256 KB each, `json.loads` only). Tolerates missing or extra keys. A file that does not parse is skipped and counted, never fatal |
| `sources.py` | Protocols `StepFunctionsReader`, `FreshnessReader` (an AMP reader is added in Phase 10) |
| `aws.py` | boto3 implementations, `Config(connect_timeout=3, read_timeout=8, retries={"max_attempts": 2, "mode": "standard"})`, in-process TTL cache (ListExecutions 30 s, freshness 300 s), and `assumed_session()` for the CLI |
| `commands.py` | One function per command → `(data: dict, text: str)` |
| `render.py` | Plain-text tables, ASCII only |
| `sanitize.py` | Output whitelist and caps (below) |
| `api.py` | `dispatch(argv, sources) -> Response`; `handle_body(body: str, is_base64: bool, sources)`; `lambda_handler(event, context)` (HTTP API v2 payload, used by step 7) |
| `__main__.py` | CLI: `python -m cerberus_console [--json] <argv...>`. Always assumes `cerberus-console-cli` (account from `sts.get_caller_identity()`, `RoleSessionName=cerberus-console-local`, 900 s). Runs the same `dispatch`. Exit codes: 0 ok, 2 refused/not found, 3 unavailable |

Entry points: the CLI for local use (and later `make status`, ADR 0021). `cerberus_console.api.lambda_handler` for step 7. Step 7 decides packaging (it bundles `observability/scale/runs/*.json` and sets `CERBERUS_RUNS_DIR` and `CERBERUS_STATE_MACHINE_ARN`). The local CLI derives the state machine ARN from the assumed session's account. No ARN is ever built from visitor input.

**Grammar** (rules applied in order, each with the fixed refusal):
1. Body (`handle_body`): at most 2,048 bytes before parsing. Valid base64 if `isBase64Encoded`. The JSON must be an object with exactly one key, `argv`. Duplicate keys are refused (`object_pairs_hook`).
2. `argv` is a `list` of 1-8 `str`. A `bool`, `int`, `None`, `dict` or nested list is refused.
3. Every token matches `re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}", tok, re.ASCII)`. Use `fullmatch`, never `match` with `$` (which accepts a trailing newline). This one rule rejects shell metacharacters, spaces, `/`, `..`, control characters, NUL and all non-ASCII (lookalikes, bidi), as well as empty and over-long tokens.
4. One optional leading `cerberus` is stripped once. The next token must be in the table, exact lowercase.

| Command | Arguments accepted | Source |
|---|---|---|
| `help` | none, or one command name from the table | static |
| `status` | none | SFN + Athena + newest record |
| `runs` | none (newest 50 records) | records |
| `run` | exactly one: `latest` or a known id | records, plus SFN detail if within 90 days |
| `cost` | none (the ladder), or one known id | records |
| `dq` | none (newest record with DQ), or one known id | records |
| `slo` | none | records |

A "known id" is an id that exists in the loaded records or in the cached `ListExecutions` names (at most 2 pages of 100). Lookup is by exact dictionary membership. The AWS call then uses the `executionArn` that AWS returned, never a string built from the token. An unknown id gets the fixed `not_found` text, with no echo.

**Response JSON** (`data` is sanitised too):
```json
{"ok": true,  "command": "status", "text": "...", "data": {...}}
{"ok": false, "error": "refused",     "text": "Not an allowed command. Type help for the list."}
{"ok": false, "error": "not_found",   "text": "No run with that id. Type runs for the list."}
{"ok": false, "error": "unavailable", "text": "That command is not available right now. Try again later."}
```
`api.py` also returns a status code (200 / 400 / 404 / 503) for step 7 to use. Any exception that escapes a command becomes `unavailable`. The exception is logged with type name only (`logging`, no message text and no traceback in the response).

**Sanitising** (applied to every string in `data` and to `text`, after rendering):
- Keep only printable ASCII 0x20-0x7E plus `\n`. `\t` becomes a space, and every other character becomes `?`. This removes ESC/CSI/OSC (including OSC 52), C1 (0x80-0x9F), DEL, NUL, bidi overrides, zero-width characters and U+2028/U+2029.
- Redact account IDs inside ARNs: `(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)\d{12}` becomes `\1<ACCOUNT_ID>`. ARNs are not rendered anyway; this is a backstop.
- Caps: a field is at most 200 characters (cut, with `...`). A table is at most 50 rows. `text` is at most 16 KiB. The serialised response is at most 64 KiB (cut rows, then add `(truncated)`).
- SFN `cause` text is never output. Only the failed state name and the `error` code are shown (both sanitised and capped at 64 characters). `GetExecutionHistory` is called with `includeExecutionData=False`, so execution input and output are never fetched. `DescribeExecution` is not used.

**Per command: calls, output, cost and failure mode**

| Command | AWS calls | Text output | Cost per call | On failure |
|---|---|---|---|---|
| `help` | none | the command list, one line each | $0 | n/a |
| `status` | `ListExecutions(maxResults=20)` (cache 30 s). If the newest is RUNNING: `GetExecutionHistory(reverseOrder=True, maxResults=50, includeExecutionData=False)` → the current state. Athena: `StartQueryExecution(WorkGroup=console, QueryExecutionContext={Database})`, then `GetQueryExecution` polls (0.5 s backoff, 12 s deadline, then `StopQueryExecution`), then `GetQueryResults`. Cache 300 s | Latest execution (name, status, start, duration, current or failed state). Gold freshness per table (last commit, age). Newest record summary. `data.gold.bytes_scanned` | SFN: $0 (F24). Athena: at most 10 MB billed, about $0.00005, plus S3 PUT about $0.000005 | Each section shows a fixed `unavailable`. The command still returns `ok`. A top-level exception returns `unavailable` |
| `runs` | none | Table: execution, status, start (UTC), events, seconds, run USD, DQ pass | $0 | `unavailable` if no record loads |
| `run <id>` | Optional `GetExecutionHistory(maxResults=500, includeExecutionData=False)`, at most 2 pages, only if the id is in the SFN list | Record: status, times, events, events/s, silver counts, per-state seconds and Athena USD, cost summary, DQ summary, peak series. SFN detail: per-state timings and the failed state/error code, "history kept 90 days after close" | $0 | The SFN part shows `unavailable`, and the record part still shows |
| `cost [id]` | none (`ce:*` is never granted) | Ladder: run, events, `run_usd`, `usd_per_million_events`, day `usd`, `estimated`/`complete`. With an id: top 8 `by_service` and `rate_excludes`. Footnote: "From the collector's Cost Explorer reading; this command makes no Cost Explorer call." | $0 | `not_found` / `unavailable` |
| `dq [id]` | none | Passed, errors, warnings, then each check: name, severity, pass, violations, detail (capped at 120). A null DQ gives "No data-quality record for this run (the suite was added in 8.4)." | $0 | as above |
| `slo` | none | Trailing 20 records, newest first. SLO 1: succeeded/total (now 12/14 = 85.7%, not met), plus one cited context line (User decisions). SLO 3: `run_seconds` < 1800 (14/14). SLO 4: `RunServingQuery` `engine_seconds` < 30 (12/12). SLO 5: "a dbt test failure fails the run; see SLO 1" (docs/slo.md wording). SLOs 2 and 6: "measured from CloudWatch FreshnessSeconds; not available here." | $0 | `unavailable` |

**Worst-case `status` cost (input to step 7, not a step 6 decision).** At 10 concurrent warm containers (the account limit, F22), each re-querying at most every 300 s, that is 86,400 queries a month, about $4.32 in Athena plus $0.43 in S3 PUTs. Uncached at 2 rps it would be about $259 a month, which is why the cache is required. Step 7's throttling and concurrency set the real bound.

**Ruff and banned calls.**
- Add `console/ruff.toml` with `extend = "../pyproject.toml"`. Under `[lint]`, set `extend-select = ["S", "TID251"]`.
- Set `[lint.flake8-tidy-imports.banned-api]` for `subprocess`, `os.system`, `os.popen`, `os.execv`, `os.execvp`, `os.spawnv`, `pickle`, `marshal`, `shelve`, `ctypes` and `importlib.import_module`.
- Set `[lint.per-file-ignores] "tests/**" = ["S101"]`.
- Ruff finds the nested config, so the root `ruff check .` in CI applies it.
- A pytest AST test also fails on any call to `eval`, `exec`, `compile` or `__import__`, and on any import of `subprocess`/`os.system`/`os.popen` in `cerberus_console/`.

## 6. ADR outline

None. Implementation inside ADR 0024.

## 7. Build steps (Phases.md 9.3)

### PR 6a: branch `9.3-console-workgroup` (Terraform, CI-applied; merge after the 8.10 take)

Files:
1. `terraform/modules/athena/main.tf`:
   - Add `aws_athena_workgroup.console` with the settings in section 5. Its comment cites ADR 0024 rules 6-7 and the F19 metadata size.
   - Add a second rule in `aws_s3_bucket_lifecycle_configuration.results`: `id = "expire-console-results"`, `filter { prefix = "console/" }`, `expiration { days = var.console_results_expiration_days }`.
   - `variables.tf`: `console_bytes_scanned_cutoff_bytes` (default `10485760`, described as "10 MiB (10485760) is the AWS provider's minimum (the Athena API minimum is 10,000,000 bytes); the three gold metadata trees total about 270 KB, 2026-11-01") and `console_results_expiration_days` (default `1`).
   - `outputs.tf`: `console_workgroup_name` and `console_results_prefix` (`"console/"`).
2. `terraform/modules/console_roles/main.tf`:
   - Add the six statements in section 5.
   - Rewrite the header paragraph on `cerberus-console-cli`: Step Functions read, one fixed Athena query, gold metadata read only, and the results prefix is its only write.
   - `variables.tf`: `athena_workgroup_name`, `athena_results_bucket_arn`, `athena_results_prefix`, `gold_bucket_arn`, `glue_database_name` and `gold_table_names` (default `["fct_transactions", "dim_customers", "dim_merchants"]`, with a comment that it must match `console/cerberus_console/config.py` `GOLD_TABLES`).
3. `terraform/envs/dev-standing/main.tf` `module "console_roles"`: pass `module.athena.console_workgroup_name`, `module.athena.results_bucket_arn`, `module.athena.console_results_prefix`, `module.s3_medallion.bucket_arns["gold"]` and `module.glue_catalog.database_name`. Add no literal account ID. `outputs.tf`: `console_workgroup_name`.
4. Docs:
   - Demo-console plan §7: under step 6, add a note that the workgroup, the prefix and the grants moved here, with a link. Under step 7, remove "and the workgroup".
   - Read-only roles plan risk 8: add a one-line "Resolved in the command-set plan".

Executor verify ($0, no AWS change):
- `TMPDIR=$HOME/.cache/tfspiketmp terraform fmt -check -recursive terraform/`
- `terraform validate` with `init -backend=false` in a scratch copy.
- `git diff main -- terraform | grep -E '[0-9]{12}'` returns nothing.

The CI plan must show exactly the following. Anything else means stop: do not merge, and do not use `-target`.
- 1 to add: `module.athena.aws_athena_workgroup.console`.
- 2 to change in place: `module.athena.aws_s3_bucket_lifecycle_configuration.results` (one rule added) and `module.console_roles.aws_iam_role_policy.console_cli`.
- The known Faker-layer replacement (layer replaced, `ingest_payments` layers updated) is the only accepted extra.

**User-approved AWS change 1:** merge PR 6a after the 8.10 take is recorded. The CI apply creates the workgroup and updates the lifecycle and the role policy.

Post-apply verify (agent, read-only; in zsh write `${ACCT}` with braces):
```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws athena get-work-group --work-group cerberus_platform_console \
  --query 'WorkGroup.Configuration.[EnforceWorkGroupConfiguration,BytesScannedCutoffPerQuery,ResultConfiguration.OutputLocation]' \
  --output text | sed "s/${ACCT}/<ACCOUNT_ID>/"        # True 10485760 s3://cerberus-platform-athena-results-<ACCOUNT_ID>/console/
aws s3api get-bucket-lifecycle-configuration --bucket "cerberus-platform-athena-results-${ACCT}" \
  --query 'Rules[].[ID,Filter.Prefix,Expiration.Days]' --output text   # expire-query-results "" 7 ; expire-console-results console/ 1
C="arn:aws:iam::${ACCT}:role/cerberus-console-cli"
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:athena:us-east-1:${ACCT}:workgroup/cerberus_platform_console" \
  --action-names athena:StartQueryExecution athena:GetQueryResults athena:UpdateWorkGroup athena:DeleteWorkGroup \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text      # 2 allowed, 2 denied
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:athena:us-east-1:${ACCT}:workgroup/cerberus_platform" \
  --action-names athena:StartQueryExecution --query 'EvaluationResults[].EvalDecision' --output text   # implicitDeny
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:s3:::cerberus-platform-athena-results-${ACCT}/console/x" \
  --action-names s3:PutObject s3:GetObject s3:DeleteObject \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text      # 2 allowed, DeleteObject denied
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:s3:::cerberus-platform-athena-results-${ACCT}/data_quality/x" "arn:aws:s3:::cerberus-platform-gold-${ACCT}/cerberus_platform/fct_transactions/u/data/x.parquet" \
  --action-names s3:PutObject s3:GetObject --query 'EvaluationResults[].[EvalActionName,EvalResourceName,EvalDecision]' --output text | sed "s/${ACCT}/<ACCOUNT_ID>/g"   # all denied
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:s3:::cerberus-platform-gold-${ACCT}/cerberus_platform/fct_transactions/u/metadata/x.json" \
  --action-names s3:GetObject s3:PutObject --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # Get allowed, Put denied
aws iam simulate-principal-policy --policy-source-arn "$C" \
  --resource-arns "arn:aws:glue:us-east-1:${ACCT}:table/cerberus_platform/fct_transactions" \
  --action-names glue:GetTable glue:UpdateTable glue:DeleteTable \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text      # 1 allowed, 2 denied
aws iam simulate-principal-policy --policy-source-arn "$C" --resource-arns '*' \
  --action-names ce:GetCostAndUsage aps:QueryMetrics states:StartExecution iam:PassRole \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text      # all denied
```

### PR 6b: branch `9.3-command-set` (Python; no Terraform; can be built in parallel with 6a)

Files:
1. `console/cerberus_console/{__init__,__main__,config,grammar,records,sources,aws,commands,render,sanitize,api}.py` (section 5).
2. `console/ruff.toml` (section 5) and `console/conftest.py` (empty, so pytest puts `console/` on `sys.path`).
3. `console/tests/`:
   - `test_grammar.py`: every refusal case below returns byte-identical refusal text that contains no input substring.
     - JSON body: not JSON, not an object, extra key, duplicate `argv`, over 2,048 bytes, bad base64, missing body.
     - argv shape: not a list, empty list, 9 tokens, a 65-character token, and `int`/`bool`/`None`/`dict`/list tokens.
     - Tokens: `;`, `$(id)`, a backtick, `|`, `&&`, `>`, a space inside a token, `\n`, `\r`, `\x00`, `../`, `/etc/passwd`, `STATUS`, fullwidth `status` (U+FF53...), U+202E (RTL override), U+200B (zero-width space), `-h`, `--json` in the API path, `cerberus cerberus status`, `status extra`, `run`, `run a b`, and `run` with an id of 65 characters.
   - `test_sanitize.py`: inputs `\x1b[31m`, `\x1b]52;c;SGVsbG8=\x07`, `\x1b]8;;http://x\x1b\\`, `\x9b31m`, `\x7f`, U+202E, U+2028, NUL and a 10,000-character string → output only `[\x20-\x7e\n]` and within the caps. An ARN with twelve `1`s (built at runtime, not as a literal) is redacted.
   - `test_commands.py`: each command on the fixtures. Check the key fields in `data`, check that `text` stays under the caps, check that the `slo` numbers equal F11 for the fixture set, and check that `cost` calls no source (the fake factory raises if asked).
   - `test_api.py`: `lambda_handler` with HTTP API v2 events (`body` as a string, `isBase64Encoded` true and false). Fail-closed: a fake source that raises `Exception("arn:aws:states:us-east-1:<12 digits>:execution:x boom")` gives `unavailable` with none of that text. A malformed record file is skipped. An Athena timeout calls `StopQueryExecution` and gives a gold section of `unavailable`.
   - `test_real_records.py`: every file in `observability/scale/runs/` loads, and every command renders within the caps. No AWS (the sources are fakes). This guards against drift when the 8.10 record lands.
   - `test_banned_calls.py`: the AST check.
   - `test_tables_match_iam.py`: parses the `gold_table_names` default in `terraform/modules/console_roles/variables.tf` with a regex and checks that it equals `config.GOLD_TABLES`. (If PR 6b is reviewed before 6a merges, this test reads the 6a file on its branch; order the merges 6a then 6b, or make the test skip when the variable is absent.)
4. `console/tests/fixtures/`:
   - `runs/`: copies of `exercise-20261013T055859Z.json`, `exercise-20261008T085728Z.json` and `demo-7-8-take1-20261006T075445.json`, plus a synthetic `hostile-20990101T000000Z.json` whose strings carry the sanitiser inputs.
   - `sfn/list_executions.json`, `sfn/history_running.json` and `sfn/history_failed.json`, with ARNs written as `arn:aws:states:us-east-1:<ACCOUNT_ID>:…`, plus an `error` value that carries ANSI.
   - `athena/freshness_rows.json`, plus a variant with hostile cell text.
5. `console/README.md`: what the package is, the grammar table, the response contract, the cost per command, how to run it locally, and "no shell, no write". Keep it short, in the style of `observability/grafana/README.md`.
6. `.github/workflows/code-ci.yml`: add `console/**` to `paths`, and add a job `console-tests` (Python 3.12, `pip install -r requirements-dev.txt`, `pytest console`). No `id-token`, no AWS.
7. `Makefile`: `cerberus: ## run one console command locally as cerberus-console-cli (CMD="status"; CMD="--json run latest")`, which runs `cd console && uv run --no-project --with boto3==1.43.67 python -m cerberus_console $(CMD)`.
8. Docs, after the live check:
   - Demo-console plan §8: mark both step 6 items. The Step Functions item: retention 90 days verified (quotas page), and API reads not listed as billed. The Athena item: the measured bytes and the 10 MB cutoff.
   - Phases.md 9.3: the wording change (deviation 2), a progress line, then the tick.

Executor verify ($0, no AWS):
- `uvx ruff@0.16.4 check .` and `uvx ruff@0.16.4 format --check .`
- `uvx ruff@0.16.4 check console --show-settings | grep -E '"S"|S[0-9]{3}|TID251'` shows S active.
- `uvx --with pytest==9.1.1 pytest console -q` passes.
- `grep -rnE '[0-9]{12}' console/` returns nothing.

### Live check (after 6a is applied and 6b is on its branch or merged)

**User-approved AWS action 2.** This is not strictly read-only. Each `status` runs one Athena query of at most about $0.00005 and writes one result object under `console/`, which expires after 1 day.
```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
make cerberus CMD="help"
make cerberus CMD="status"
make cerberus CMD="--json status" | jq '.data.gold'          # bytes_scanned recorded; expect well under 1 MB, billed 10 MB
make cerberus CMD="runs"
make cerberus CMD="run latest"
make cerberus CMD="run exercise-20261013T055859Z"          # record plus SFN detail (inside 90 days)
make cerberus CMD="cost"
make cerberus CMD="cost exercise-20261013T055859Z"
make cerberus CMD="dq"
make cerberus CMD="slo"
make cerberus CMD="run nope-1"; echo $?                    # not_found, 2
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws s3 ls "s3://cerberus-platform-athena-results-${ACCT}/console/" | wc -l   # 2 (result + .metadata) per uncached status
```
Pass: every command prints, no traceback, the exit codes are as listed, and `bytes_scanned` is under 10,485,760. If the run gets AccessDenied, apply risk 2's widening in a follow-up commit to 6a and re-run.

## 8. Exact AWS commands for the user to approve

1. Merge PR 6a after the 8.10 take, which triggers the CI apply of `dev-standing`.
2. The live check block above (Athena queries of about $0.00005 each).

Everything else is read-only (the post-apply verify).

## 9. Risks

1. **8.10 timing.** 6a changes the lifecycle of the shared results bucket in place. Merge only after the take is recorded, never during a run.
2. **The IAM scope is too narrow for Athena.** Athena may need more than `…/metadata/*` or `glue:GetTables`. The fallback is still read only: `<gold>/cerberus_platform/*`, `glue:GetTables` on the same three tables, `s3:ListBucket` on the results bucket without the `s3:prefix` condition (HeadBucket checks ListBucket with no prefix key), and `s3:ListBucket` on the gold bucket with `s3:prefix` `cerberus_platform/*`. It costs one more CI cycle.
3. **Visitor cost amplification in step 7.** The cache bounds it to about $4.75 a month at the account concurrency limit (section 5). Step 7 must keep the cache and set throttling.
4. **Step Functions history expiry.** The 2026-08-20 executions leave around 2026-11-18. `run <id>` then shows the record only, and says so. Recheck on 2026-11-19: `ace6ad33-…` gone confirms the 90 days for this account.
5. **`slo` shows SLO 1 not met** (12 of 14 = 85.7%, both failures in RunDbt during the 10M scale-up). This is visible to visitors and is honest per docs/slo.md. The user chose a cited context line. The evidence showed two different causes (a missing dbt-role grant, then the 1 GiB Athena cutoff fixed in 8.6), so the line states both (see User decisions).
6. **Record schema drift** (the 8.10 record may add fields). The loader tolerates missing and extra keys, and `test_real_records.py` guards it.
7. **The ListExecutions quota is shared with `exercise.sh`** (refill 5/s, F23). The 30 s cache keeps the console far below it, and `exercise.sh` polls `DescribeExecution`, which the console never calls.
8. **Lambda boto3 vs the local pin** (1.43.67). Only long-stable APIs are used.
9. **No trust change is needed** (CI lacks `iam:UpdateAssumeRolePolicy`). If one appears, it needs a local `cerberus-admin` apply.

## 10. Open questions for the user

Answered 2026-11-02; see User decisions at the top.

Sources: [Step Functions service quotas](https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html), [Step Functions pricing](https://aws.amazon.com/step-functions/pricing/), [Athena WorkGroupConfiguration](https://docs.aws.amazon.com/athena/latest/APIReference/API_WorkGroupConfiguration.html), [CloudFormation ManagedQueryResultsConfiguration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-athena-workgroup-managedqueryresultsconfiguration.html).
