# Plan: 17.4 launch session tooling

Date: 2026-11-25. Planner: Sonnet (`cerberus-planner`).

## Binding corrections (main session; these win)

1. No IAM policy file changes. `CloudFrontEdgePolicies` in
   `cerberus-admin-console-edge.json` already allows every action on
   cache policies and OACs; the plan's "Missing for stage 2" is wrong.
   Whether that file is attached is checked by the simulate step.
2. Instance `PutObject` on `results/*` goes beyond ADR 0030 Decision 6 ("seed
   writes"). Build it as one isolated statement and name it in the report;
   the owner decides on it (`escalate: opus-security`).
3. Egress DNS: follow Decision 6 and check that the VPC resolver works with
   the existing rules before adding a port 53 rule.
4. `session` copies k6 results and the run record out of the build bucket
   before stage 2. Collection failure never delays or skips a destroy.
5. Stage 1 steps are independent: parameter delete, key shred and instance
   termination each run even if another fails; any failure gives a non-zero
   exit and a loud message. Stage 1 applies the default PEM, so no valid
   signer remains.
6. Without HOLD no CDN logs are promised. With HOLD, `launch-collect` repeats.
7. Ledger CLI is the shared contract with 17.5: `python3 launch/ledger.py
   guard --next-usd N` exits 0 only if the run is allowed (non-zero on every
   error); `record --run-id ID --kind session|exercise --estimate-usd N`;
   `correct --run-id ID --usd N`. `cost_baseline.json` is the owner's to
   generate; never invent its numbers.
8. CDN values are copied verbatim in type; 17.5 declares every column string.


Run A measures KVS propagation of `release_at` after apply 2 (unverified).

## Plan

**Plan 17.4: launch session tooling (Tier C; Tier S parts flagged).** Read against origin/main d8974fe. No conflict with ADR 0030, so no NEEDS DECISION.

**1. Goal.** Build `launch/` (scenarios, k6, `plan_bytes.py`, ledger) and four orchestration scripts with Make targets `launch-session`, `launch-collect`, `launch-check`, `launch-destroy`. This is Phase 17.4. Nothing here writes to AWS except through owner-run commands.

**2. Facts**
- U2 (V): AWS load-testing page, https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/load-testing.html. It has no notice or approval step. It bans Lambda@Edge viewer triggers and Origin Shield, and recommends multi-region clients, per-client DNS and spreading over all returned IPs. **The owner sends no notice.** The article must say the test is single-region and not a CloudFront assessment (ADR 0030).
- Built root (V): `launch_init.sh` exists. Env outputs are `domain_name, distribution_id, key_group_id, build_bucket, log_bucket, instance_id, kvs_arn`. Variables are `public_key_pem, release_at_epoch, create_load_gen, minutes, shutdown_margin_minutes, instance_type, k6_*`. The cookie parameter is `/cerberus/launch/session-cookies`. The role has no `results/*` write, and there is no `public_key_id` output and no budget variable.
- IAM (V): no `ssm:SendCommand` or `GetCommandInvocation`, so the script cannot run commands on the instance. The instance must run k6 itself from `user_data`. `StartSession` exists but is interactive only.
- `Makefile` has `launch-plan` and `launch-function-test`. The `code-ci` job `launch-edge` exists, and its path filter already covers `launch_edge/**`.

**3. Steps (one PR, or two if large: first PR is steps 1-3, second is 4-8)**
1. `launch/scenarios/{a,b,c,d,p}.json`. Fields: clients, iterations, object sizes, `bytes_gb`. Planned GB: A 5, B 200, C 105, D 49 (b+c+d = 354), P 2. `SCENARIO` accepts a, b, c, d, bcd, p.
   `launch/k6/*.js` use `shared-iterations` only, never duration.
   Test: iterations × size equals `bytes_gb`, and k6 scripts contain no `duration`.
2. `launch/plan_bytes.py` (layer 1). It refuses a session over 400 GB, and refuses when month-to-date plus session exceeds 900 GB (probe P bytes included). Month-to-date is the larger of the ledger and CloudWatch `BytesDownloaded`. It prints the nftables budget (plan × 1.10). It takes `--mtd-gb` offline.
   Test: 399.9 is allowed, 400.1 is refused, 900 boundary, bcd = 354.
3. `launch/ledger.py` and `launch/cost_baseline.json`. A target `launch-baseline` is new and read-only: it writes November Usage through 11-24 (Cost Explorer, record type Usage, credits excluded). The ledger is `observability/launch/ledger.jsonl`. Refuse when reported + estimate + next run > $25.00. Also refuse when the baseline is absent or Cost Explorer errors. `destroy` and `collect` skip this check.
   Test: refuse at 25.01, refuse with no baseline, and an entry exists and is corrected after a SIGTERM.
4. `orchestration/launch_session.sh`, copied from `console_session.sh` (preflight, y/N, `setsid` destroy, EXIT trap).
   - Flags: `--dry-run`, `--yes`, env `SCENARIO MINUTES PREWARM HOLD`. Make passes `ARGS=`.
   - Key (live): `mktemp -d` under `$XDG_RUNTIME_DIR` and fail if it is unset or not tmpfs. RSA-2048, mode 0700. The trap `shred`s and removes it.
   - Order: bytes, ledger, apply the public PEM, wait for `Deployed`, sign cookies, put the parameter, apply with `create_load_gen=true`.
   - Cookies: custom policy for `https://<domain>/*`, expiry = mint + MINUTES, CloudFront base64 (+ → -, = → _, / → ~). `put-parameter` uses `--type SecureString --tier Standard`, no `--key-id`, `--value file://`, and `--tags Project`. Delete first, because `--tags` conflicts with `--overwrite`. The script asserts the size is 4,096 bytes or less.
   - `release_at` is explicit: PREWARM uses the default sentinel. A live run uses now + the schedule offset.
   - Probe 403 on `/license` before T0.
   - Layer 4: poll `BytesDownloaded` each minute since start. Above budget, run stage 1.
   - Stage 1: `apply -var create_load_gen=false` (no `-target`), then `delete-parameter`, then remove the key.
   - Stage 2: `destroy` with a `-refresh=false` retry, then `launch_check`.
   - PREWARM: no instance, no key. A failed apply runs both stages. A successful run prints a deadline and no stage 2. HOLD: the same, with the 24 h deadline. Without either flag, the trap runs stage 1 then stage 2.
   - Dry run: no `aws` and no `terraform` call. It prints the commands, bytes and a ledger estimate.
5. `orchestration/launch_destroy.sh`: init, stage 1 (delete a leftover parameter), stage 2, check. It needs no shell state.
6. `orchestration/launch_check.sh`, from `console_check.sh`. It reports 0 for each of: distribution (total minus the standing edge, plus tag), function, KVS, public key, key group, cache policy and OAC (prefix `cerberus-launch-`), log source, destination and delivery, instances (tag `Stack=dev-launch`), volumes, spot requests, SG, role, instance profile (`get-instance-profile` by fixed name), parameter (`describe-parameters` filter, no decrypt), both buckets (`head-bucket` by computed name), and state. Any AWS error prints `error` and fails.
7. `orchestration/launch_collect.sh` plus `launch/cdn_fields.json`, the single allowlist. The contract is below.
8. Module edits, because the instance runs by itself:
   - `user_data.sh.tftpl`: pinned k6 (version and sha256), nftables `quota over <budget> bytes drop` on input, scenario from S3, results written to `results/*`, then `shutdown`.
   - New `budget_bytes` variable and `public_key_id` output (module and env).
   - Role: `PutObject` on `results/*` of the build bucket only.
   - `shutdown_margin_minutes` = 30 (unverified).
   - Update `static.test.mjs`.
   - **Needs `escalate: opus-security` review.**
9. Make: a 17.4 block placed right after `launch-function-test`. `code-ci`: extend job `launch-edge` with pytest, `shellcheck` and a paths addition for `launch/**` and `orchestration/launch_*.sh`.

**4. Collect to bronze contract (17.5 must match)**
- Target: `s3://cerberus-platform-bronze-<acct>/downloads_cdn/run_id=<id>/part-<16 hex of sha256(source key)>.json`, then `_manifest.json` last.
- Format: uncompressed UTF-8 JSON Lines, one object per line, with the original CloudFront key names. Keys are verbatim and may contain parentheses or hyphens: 12 fields.
- Allowlist: `timestamp(ms)`, `x-edge-request-id`, `x-edge-location`, `x-edge-result-type`, `x-edge-response-result-type`, `sc-status`, `sc-bytes`, `cs-method`, `cs-uri-stem`, `time-taken`, `time-to-first-byte`, `cs-protocol`. No extra fields are added, and the run id is in the path only.
- Manifest: `run_id`, `files`, `lines`, `fields`, `window_start`, `window_end`, `collected_at`.
- Rules: lines are filtered to the session window from the run record. Existing keys are skipped. Every line's keys must be a subset of the allowlist, or nothing is copied. Paths and values (except `x-edge-request-id` and `timestamp(ms)`) are scanned with a non-digit-bounded 12-digit regex. Without a bound, 13-digit timestamps would match. The `run_id` regex is `^[a-z0-9-]{1,40}$`.
- 17.5 renames the keys to snake_case in dbt only. Dedup key is `x-edge-request-id`.
- Logs exist only for HOLD runs, because stage 2 deletes the log bucket. Otherwise k6 output is the evidence.

**5. Ownership**
- 17.4 owns `launch/**`, `orchestration/launch_{session,collect,check,destroy}.sh`, the Make launch targets, `launch_edge` module edits and the code-ci job.
- 17.5 owns `transform/**`, `data_quality_downloads.py` and `launch_exercise.sh`, plus the `launch-exercise` Make target. 17.5 appends its Make block at the end of the file. 17.4 does not touch it.
- Neither agent edits `Phases.md`: adjacent lines 422-425 would conflict. The main session ticks both lines after the merges.

**6. Verify.** `make verify`, `shellcheck`, `make launch-function-test`, and pytest with stubs for `aws`, `terraform`, `k6`, `openssl` on PATH. Required failure-path tests:
- EXIT-trap destroy after a failed apply, SIGINT and SIGTERM.
- Refusal over 400 GB, over 900 GB, and over $25.
- Key directory gone after every exit path.
- Check exit 1 and `error` on any stubbed AWS failure.
- Dry run asserts the stub call log is empty.
- Repo scan: no `PRIVATE KEY`, no account ID.

**7. Owner steps and IAM**
- The owner runs `make launch-baseline` before Run A, then `launch-session`, `launch-destroy` and `launch-collect`.
- Missing for stage 2: `cloudfront:GetCachePolicy`, `GetCachePolicyConfig`, `UpdateCachePolicy`, `DeleteCachePolicy`, `GetOriginAccessControl`, `GetOriginAccessControlConfig`, `UpdateOriginAccessControl` and `DeleteOriginAccessControl`. The `console-edge` file has only Create and List, and its attach state is unverified (#187). Before the root paste, run `simulate-principal-policy` for these. If any are denied, add them to `cerberus-admin-launch.json` (5,081 of 6,144 characters, fits).
- Covered (V): `ssm:*Parameter` and `DescribeParameters`, `cloudwatch:GetMetricStatistics`, `ce:GetCostAndUsage`, `tag:GetResources`, `ec2:Describe*`, `ListAllMyBuckets`, `iam:GetRole`, `GetInstanceProfile`, `logs:Describe*`, bronze Put and List, `ListDistributions`. `CreateDistribution` and `UpdateDistribution` need the `Project` tag, which `default_tags` supplies.

**8. Risks**
- The nftables quota and the CloudFront log field names are untestable offline. Run A proves them.
- CloudWatch lag makes layer 4 coarse.
- Spot capacity for `c6gn.xlarge`.
- k6 per-client DNS may need port 53 egress, which would be a module change.
- The 30-minute margin is unverified.

**9. Open questions (recommended answer)**
1. Add the 8 cache-policy and OAC actions to `cerberus-admin-launch.json` before the paste? Yes, if the simulation denies them.
2. Allow the instance role `PutObject` on `results/*` of the build bucket? Yes, because there is no SendCommand path. Needs the opus-security review.

## Deviations after the design check (main session, 2026-11-25)

The first build did not implement the approved design (ADR 0030 "Changes from
the launch plan", Decisions 3, 4, 12, 13; decision plan section 2). Corrected:

1. **Content.** Step 1's "iterations x size = `bytes_gb`" is gone. The build is
   64 distinct random 64 MiB chunks `build/<sha256>.bin` plus `build/manifest.json`.
   The patch is 8 chunks `patch/<sha256>.bin` with `patch/manifest.json`; D has a
   second patch set with `patch/manifest-2.json`. `launch/seed.py` runs on the
   instance (generate, hash, upload, write the manifests); k6 reads the local
   manifests; the laptop checks and probe P read the manifest through the signed edge.
   `launch/scenarios/sets.json` holds the sets and the unverified timing numbers.
2. **Runs.** A: 1 client, full build, licence 403, wait for the release, licence 200,
   patch (4.832 GB, 74 requests). B: 50 clients, full build, ramp 30 min, no gate
   (214.748 GB, 3,200). C: gated at T0, patch for 50, 1,000,000 licence requests
   (shared iterations, paced, at most 1,667 per s), 20 late full builds (112.760 GB,
   1,001,681 with the gate request). D: cold `patch2` for 50 at T0, then a warm repeat by
   1 in a second k6 run (27.380 GB, 409). P: first 30 build chunks (2.013 GB, 31).
   `bcd` = 354.889 GB, with P 356.902 GB. `plan_bytes.py` sums the exact bytes (chunk
   requests x 64 MiB plus the 17 B / 18 B licence bodies) through `launch/scenario.py`.
   The warm repeat adds 0.537 GB to the "about 354 GB" of the ADR table.
3. **Schedule.** `scenario.py schedule` derives the seed list, T0, the minimum and the
   default `MINUTES`, and the maximum from the scenario data. T0 falls after the runs
   before the first gated run plus a 5 min margin (bcd: +53 min, after B). The cookie
   lifetime and the instance shutdown follow `MINUTES`. Maximum: 120, or minimum + 30.
4. **Grants.** None added; the manifests are under `build/*` and `patch/*`.
5. **k6 counts.** `summaryTrendStats` has p(50) and p(99); counters `req_build`,
   `req_patch`, `req_licence`, `req_manifest`, `bytes_*`. `run.json` gets
   `k6_requests` (integer, the sum of `http_reqs` of every run summary and probe P),
   `k6_requests_by_type`, `k6_complete` and `curl_requests`, written before stage 2.
   `launch_collect` keeps `cdn_logs_collected`.
6. **shellcheck.** Clean (the unused margin variable is gone; one targeted SC2016 disable).
7. **Apply order.** Apply 1: PEM only, default `release_at`, no instance; wait for
   `Deployed`; mint; put the parameter; apply 2: the same PEM, explicit `release_at`,
   and the instance. A pre-instance 403 probe and a post-apply 403 probe both run.
   The wait for the release in k6 is a sleep, not a poll.
8. **Real k6.** `launch/tests/test_k6.py` runs k6 2.4.0 (`K6_BIN` or PATH; skipped
   when absent): `k6 inspect` of every scenario, and shrunk runs against a local HTTP
   stub (`EDGE_SCHEME=http`, accepted for 127.0.0.1 and localhost only).

Unverified: all numbers in `sets.json` `timing_unverified` (boot 10 min, seed 25 MB/s,
client 200 Mbit/s, link 4 Gbit/s, margin 5, prepare 5, slack 15, drain 1); seeding speed
of 64 MiB chunks on the instance; the arm64 k6 build and real CloudFront behaviour of
`Content-Length` on chunks (the check compares it with the manifest).
