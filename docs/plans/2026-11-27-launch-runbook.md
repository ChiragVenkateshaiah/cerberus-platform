# Runbook: Phase 17.6 live launch runs (Friday 2026-11-27, Saturday 2026-11-28)

Date: 2026-11-26. Mode: owner checklist, derived from the code on `main` after
#199/#200 and the review-fix, cleanup and results-tooling PRs #202-#204 (not from memory). Sources: `docs/plans/2026-11-25-launch-day.md`
(plan), `docs/adr/0030-launch-day.md` (ADR), `iam/cerberus-admin/README.md`,
the `launch-*` Make targets, `orchestration/launch_*.sh`, `launch/ledger.py`,
`launch/plan_bytes.py`, `launch/scenario.py`, `launch/scenarios/`.
Where the plan and the ADR disagree, the ADR wins (ADR "Changes from the
launch plan"). Every number marked (est) is an estimate from a dry run or an
unverified code constant. Value the code does not state is written `unknown`.

## 1. Status

| When | What | Source |
|---|---|---|
| Thu 2026-11-26 evening IST | Root pastes `cerberus-admin-launch` and attaches it; owner runs the simulate checks | ADR Decision 14; IAM README |
| Fri 2026-11-27 noon IST | Deadline for the paste. If it is not done, fall back to telemetry only (no edge) | ADR Decision 14 |
| Fri 2026-11-27 | Smoke: `make launch-plan`, Run A (`SCENARIO=a`), then 1M-event telemetry exercise | plan section 7 |
| Sat 2026-11-28 | `PREWARM=1` edge about 4 h before; then Runs B, C, D (`SCENARIO=bcd`) with probe P inside the session; collect logs; 100M-event exercise; `launch-check` | ADR Decision 13; plan section 7 |
| By Sun 2026-11-29 noon IST | Stage 2 done if `HOLD=1` was used (`launch-check` stays red until then) | ADR Decision 13 |
| Sun 2026-11-29, Mon 2026-11-30 | Pull the results and the cost, render, commit (section 3, Steps 11 and 12); Cost Explorer lags about 24 h, so pull the cost on Monday | plan section 5; `launch/results_pull.py` |
| Tue 2026-12-01 | Read-only Cost Explorer confirmation; Budget alert back to $20 | ADR Decision 12; `docs/adr-status.md` |

Exact clock times for each run are not set by the plan or the ADR: `unknown`.
Run A starts after the paste is checked; B-D start after the PREWARM edge has
been up about 4 h.

Roles: the owner runs every AWS write (`make launch-session`, `launch-collect`,
`launch-destroy`, `launch-exercise`, `standing-apply`, the root paste). Agents
and Claude Code run read-only commands only (`make launch-check`, `describe`,
`list`, `get`, `simulate-principal-policy`, `terraform plan -lock=false`). Claude
Code auto mode blocks `terraform apply` and `destroy`: run them from your own terminal.

Shell for every command below: `export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1`
(the scripts default to both). Never run the session with `set -x`: it holds
the cookie value.

## 2. Prerequisites (do all before Run A)

1. [ ] On updated `main`, apply the standing root locally. CI apply after #199
   failed because GitHub cannot build the runner image.
   ```
   git checkout main && git pull
   make standing-init
   AWS_PROFILE=cerberus-admin make standing-plan
   AWS_PROFILE=cerberus-admin make standing-apply
   ```
   Expected plan: the image `null_resource` and maybe Faker churn. Stop on any
   other change and ask. (The task card gives this expectation; the code does not
   list the expected resources: `unknown`.)
2. [x] Thursday root paste of `cerberus-admin-launch`, then the
   `simulate-principal-policy` checks. Follow `iam/cerberus-admin/README.md`,
   section "Launch policy (17.3a): root paste and detach" (counted size must be
   5139 of 6144; done 2026-11-26). Every simulate line must print `allowed`; the listed
   `implicitDeny` cases must hold.
3. [ ] Install k6 on this machine (probe P runs from here: `launch_session.sh`
   stops in preflight if `k6` is missing; override the path with `K6_BIN`).
   Version 2.4.0, the version pinned in `terraform/envs/dev-launch/variables.tf`
   (`k6_version`). The repo pins the sha256 of the linux-arm64 archive only
   (`k6_sha256` = `7bb415f59d81ad649a86f6da6b3e1bd2e4e64e84909deef13e9bca70608abccb`,
   used by the instance). It does not pin a laptop checksum (this machine is
   x86_64): download `k6-v2.4.0-linux-amd64.tar.gz` and the release's checksums
   file from `https://github.com/grafana/k6/releases/tag/v2.4.0`, then
   `sha256sum -c` the archive against that file before you extract it.
   Check `k6 version` prints 2.4.0. The published amd64 sha256
   (checked 2026-11-26) is `5a5ecf23529ccf93135bc7e5b0c1cd5126ecf5f2672e22eed1556a0ab74abb87`.
4. [ ] Account Budget alert is $40 (raised 2026-11-25, `docs/adr-status.md`). Return it
   to $20 after the 2026-12-01 read.
5. [ ] `make launch-baseline` (read-only Cost Explorer; writes
   `launch/cost_baseline.json`, once; it refuses to overwrite). It also creates the empty
   ledger `observability/launch/ledger.jsonl` (an existing ledger is kept, never truncated).
   Expect `baseline written through 2026-11-24: <amount> USD`. Then commit both files
   (owner/`cerberus-git`). Without the baseline every `launch-session` and `launch-exercise`
   refuses. A missing ledger refuses too (a deleted ledger would hide earlier spend): run
   `make launch-baseline` again only if the baseline is also missing; otherwise restore the ledger from git.
6. [ ] Review fixes: the Opus security review findings F1 (key rotation between the two
   applies) and F2 (the account-number scan refusing our own chunk names) are fixed and merged
   (#202, #203). Pull `main` and repeat the dry runs (Step 1) before Run A. No finding blocks
   the root paste.
6a. [ ] Use ONE checkout for the whole weekend and commit `observability/launch/ledger.jsonl`
   after each run (review F3): a fresh checkout without the ledger forgets earlier spend and
   bytes, and the guard refuses without it. Commit the new `observability/launch/runs/<run_id>/`
   files in the same commit.
7. [ ] `make launch-plan`: read-only; `launch_init.sh` then `terraform plan` with no load
   generator. Expect a plan that creates the edge and nothing else, exit 0. Stop
   on a permission error (the paste is not attached) or any change outside `dev-launch`.
8. [ ] Offline sanity: `make launch-test` and `make launch-function-test`
   (stubs, no AWS). Both must pass.
9. [ ] `XDG_RUNTIME_DIR` exists and is tmpfs (`stat -f -c %T "$XDG_RUNTIME_DIR"`
   prints `tmpfs`), plus `jq openssl curl python3 shred setsid timeout` installed. The
   session stops in preflight otherwise.
10. [ ] Pick an evidence folder OUTSIDE the repo, for example `~/launch-evidence/`. Raw
    terraform output can hold account IDs; do not commit raw session logs.

## 3. Steps

Common to every live session (`launch_session.sh`, from the code):

- Preflight: tools, tmpfs, AWS identity, `launch_init.sh`, no existing launch
  instance, `plan_bytes.py` (layer 1), `ledger.py guard` (the $25 rule). Any
  failure exits 1 before anything is created.
- Without `--yes` it asks `[y/N]`. Answer `y` only if the printed estimate matches
  the dry run.
- It records a ledger entry (`observability/launch/ledger.jsonl`) before the
  apply and corrects it at exit.
- The EXIT trap always runs stage 1 (terminate instance, delete the cookie
  parameter, remove the private key, via a terraform apply with
  `create_load_gen=false`), copies k6 results to
  `observability/launch/runs/<run_id>/`, then stage 2 (destroy and check) unless
  `PREWARM` or `HOLD` is set. Stage 1 terminates the instance directly (tag
  `Stack=dev-launch`), then applies. If the stage 1 apply fails twice, or a byte-budget stop ended
  the run, stage 2 runs even with `HOLD` (`HOLD is ignored: running stage 2 now`).
- A trap does not survive SIGKILL or power loss: the instance shuts itself down at
  `MINUTES` plus a margin of 30 min (`shutdown_margin_minutes`, unverified).
- The run id is `s<MMDDHHMMSS>-<scenario>` (UTC) unless `LAUNCH_RUN_ID` is set. Write
  it down: collect and the results table need it.
- Save the terminal log: run the command as
  `make launch-session ... 2>&1 | tee ~/launch-evidence/<name>.log` and read the
  exit code of `make` from `${pipestatus[1]}` (zsh) or `${PIPESTATUS[0]}` (bash).
  The script itself writes no log file.

### Step 1. Dry runs (no AWS, no cost)

```
make launch-session SCENARIO=a   ARGS=--dry-run
make launch-session SCENARIO=bcd ARGS=--dry-run
make launch-session SCENARIO=bcd PREWARM=1 ARGS=--dry-run
make launch-session SCENARIO=bcd HOLD=1 MINUTES=90 ARGS=--dry-run
```
- Calls: `launch/scenario.py`, `plan_bytes.py --offline`, `ledger.py estimate`. No aws,
  terraform, openssl, k6 or curl.
- Expect exit 0 and these values (dry run on this branch, 2026-11-25; est):

| Scenario | MINUTES (min = default) | Release at | Planned GB incl. probe P | budget_bytes | Layer 4 stop limit (bytes) | Ledger est |
|---|---|---|---|---|---|---|
| a | 44 | +22 min | 6.845 | 5,315,022,068 | 7,529,614,580 | $1.50 |
| bcd | 88 | +53 min | 356.902 | 390,377,540,153 | 392,592,132,665 | $1.79 |
| b (info) | 67 | +52 min | 216.762 | 236,223,201,280 | | $1.65 |
| c (info) | 50 | +19 min | 114.773 | 124,035,880,691 | | $1.54 |
| d (info) | 43 | +19 min | 29.394 | 30,118,458,182 | | $1.49 |
| p (info) | 36 | +21 min | 2.013 | 2,214,592,512 | 2,214,592,512 | $1.44 |

  Runs: a = `a-0`; bcd = `b-0 c-0 d-0 d-1`. Maximum MINUTES is 120. PREWARM dry run
  prints planned GB 0, ledger est $1.20 and "would end ... 24 h deadline".
- Numbers carry commas so the account-number scan passes. Evidence: paste the dry-run output into the evidence folder.
- Stop if: exit not 0, or a number differs from the table (the scenario files
  changed since this runbook).

### Step 2. Gate (before each live step)

Run these read-only checks right before the step. They are the same guards the
session runs in preflight, so a failure here saves a start.
```
python3 launch/plan_bytes.py a            # exit 0 prints "allowed"; 2 refused; 3 error
python3 launch/ledger.py guard --next-usd 1.50
python3 launch/ledger.py estimate --minutes 44 --gb 6.845
make launch-check                         # must be all zeros before a new session
```
- `plan_bytes.py`: refuses a session over 400 GB or month-to-date plus session over 900 GB.
- `ledger.py guard`: reads Cost Explorer (read-only), the baseline and the ledger. Prints
  `attributable: reported X + ledger Y + next Z = T (stop above 25.00)`. Exit 0 allowed,
  1 refused, 2 error (fail closed). For bcd use `--next-usd 1.79`.
- Stop if: any exit is not 0, the baseline is absent, or `launch-check` shows a non-zero.
- Gate for exercises: `make launch-exercise ARGS="--check"` (read-only preflight:
  `exercise.sh --check`, the spend guard, the account lookup; records nothing).

### Step 3. Run A (Friday smoke): one client, full build and patch

```
make launch-session SCENARIO=a HOLD=1 MINUTES=60
```
With `HOLD=1` the CDN logs exist (owner may drop `HOLD`: then use `make launch-session SCENARIO=a MINUTES=60`
and Run A proves nothing about the logs). Destroy this edge before the Saturday PREWARM, and within its printed deadline.
`MINUTES=60` is a margin for the manual check: after the release time and before the
session ends, in a second terminal, run
```
curl -s -o /dev/null -w '%{http_code}\n' "https://$(terraform -chdir=terraform/envs/dev-launch output -raw domain_name)/license"
```
Expect 403: without a cookie, the signature check comes before the Function.
Compare the CloudWatch sum with the k6 bytes by hand (review F7).
ADR Decision 13 says logs exist only for a HOLD run, and Run A is said to prove
the CloudFront log field names (`terraform/envs/dev-launch/README.md`, "Unverified").
With `HOLD=1`, run `make launch-destroy` by the printed deadline (24 h).
- Calls: terraform apply 1 (edge, public PEM, no instance), `aws cloudfront wait
  distribution-deployed`, cookie signing, `ssm put-parameter` (SecureString), `s3 cp`
  of scenarios, curl `/license` (expect 403), terraform apply 2 (instance,
  explicit `release_at`), polling `cloudwatch get-metric-statistics` each 60 s, stage 1,
  stage 2.
- Expect, in order: `preflight`, `identity`, `terraform init: ok`, `no launch instance: ok`,
  `bytes: ...`, `attributable: ...`; the estimate prompt (about $1.50); `applying the edge`;
  `cookies signed (N bytes); not printed`; `cookie parameter written`; `probe: /license
  is 403 before T0`; `checks: no cookie is 403, a signed cookie on a build object is
  200`; `probe P: running from this machine`; `the run finished`; `STAGE 1`;
  `private key directory removed`; `STAGE 2`; `launch_check ok`. Exit 0.
- Time: minimum 44 min of run (est), plus edge create/deploy wait and stage 2
  (allow 30 min for the destroy; delete duration is unverified). Total: `unknown`.
- Cost: about $1.50 by the ledger (est; ledger = 74 min of the all-in $0.40/h rate
  + $1.00 flat allowance). Bytes: 6.845 GB planned.
- Keep: the terminal log; `observability/launch/runs/<run_id>/run.json`
  (`k6_requests`, `k6_complete`, `curl_requests`); `.../results/*` (k6 summaries);
  `.../probe-p.json`; the new `observability/launch/ledger.jsonl` lines.
- This run decides several ADR 0030 items (section 7): read `results/` for the
  nftables quota (did the instance stop at budget plus 10%), the licence 403 then
  200 order, KVS propagation of `release_at`, and the seed throughput.
- Stop if: any `STOP:` line; a request without a cookie is not 403; a signed request
  on the build manifest is not 200 (the signature is not proven); `/license` answers
  200 before T0; `BYTE BUDGET EXCEEDED`; `BytesDownloaded was unreadable 5 minutes in a
  row`; `SESSION NOT CLEANLY ENDED`; `STAGE 2 FAILED`. Then follow section 5.

### Step 4. Collect CDN logs (HOLD runs only)

```
make launch-collect RUN_ID=<run_id>
```
- Calls: `sts get-caller-identity`, `s3api list-objects-v2` on the log bucket,
  `launch/cdn_filter.py` (field allowlist `launch/cdn_fields.json`, checked BEFORE the
  first copy), `s3 cp` to `bronze/downloads_cdn/run_id=<id>/`, manifest last.
- Expect: `N log file(s) listed` then `collected: X part(s) copied, Y already there`,
  `manifest written`, `run record: cdn_logs_collected = true`. Exit 0.
- Without `HOLD=1`: `no log bucket: logs exist only for a HOLD run ... Nothing collected.`
  Exit 0. That is correct, not an error.
- `no log files yet` (exit 0): delivery lags. ADR: usually within an hour, can be 24 h
  late, reliable about 4 h after enabling. Run it again later. It is repeatable and
  skips existing keys.
- Time: seconds to minutes. Cost: S3 requests only, not counted.
- Keep: terminal output; `run.json` with `cdn_logs_collected: true`.
- Stop if: `the logs were refused. Nothing was copied.` (exit 2) or `a log path holds a
  12-digit run`. Do not copy by hand. Report which; the field allowlist or privacy
  rule failed. Run `make launch-destroy` anyway: collect is never blocking.

### Step 5. Exercise (Friday: 1M-event telemetry smoke)

```
make launch-exercise ARGS="--check"
make launch-exercise ARGS="--generate 1000000"
```
Read `make compute-plan` first: the first run also applies the `iam_spark` downloads
grant (header of `launch_exercise.sh`).
- Calls: `sts`, `exercise.sh --check`, `ledger.py guard`/`record`, `terraform init/plan/apply`
  of `dev-compute`, `aws eks update-kubeconfig`, `kubectl` (SparkApplication generate and
  promote), then `terraform destroy` of `dev-compute` (before dbt), `dbt build` (Athena),
  `observability/launch/data_quality_downloads.py`.
- Optional flags (real): `--yes`, `--generator-executors N` (default 2),
  `--executor-nodes N` (default 1), `--run-id ID`, `--congestion two-pass|curve`,
  `--estimate-usd N` (default 1.00). The default run id is `dl-<EVENTS>-<UTC stamp>`.
- Expect: prompt `Apply dev-compute (about $0.40/hour until the destroy)? [y/N]`;
  `generator:` and `promote:` lines (an `appended N new events` line); `destroy took Ns`;
  `after destroy: EKS 0, NAT 0, EIP 0, running instances 0`; `dbt build` success; final
  `launch exercise done: cluster destroyed, silver and gold built, data quality passed`. Exit 0.
  Exit 3 = data quality failed; exit 1 = dbt failed, DQ did not run, or the destroy
  or the leftover check failed; exit 2 = bad argument or refused by the guard.
- Time: `unknown` for 1M. The app timeout is 5400 s per Spark app (unverified).
- Cost: the guard estimate defaults to $1.00 (unverified: about $0.40/h x 1 h plus an
  allowance). The ledger is corrected at exit from cluster seconds x $0.40/h + $0.25
  (the script's `ALLOWANCE_USD`; see section 8, item 3).
- Keep: `observability/launch/exercises/launch-exercise-<stamp>.log` (account masked as
  `<ACCOUNT_ID>`); `observability/launch/runs/<run_id>/run.json` (`stage`, `promote`,
  `dbt_exit`, `data_quality_exit`, `cdn_models_built`, `cdn_logs_collected`); ledger lines.
- A rerun adds nothing (silver is idempotent): this is the evidence for the "silver load is
  idempotent" claim. To prove it, run the same `--run-id` again only if the owner agrees
  (the plan does not require it): `unknown`.
- Stop if: `REFUSED by the spend guard`; `DESTROY FAILED`; `WARNING: something billable is
  still up`; `LEDGER CORRECTION FAILED`. Then run `make compute-destroy` and the checks in
  section 5.

### Step 6. Check (read-only)

```
make launch-check
```
- Calls only `describe`, `list`, `get`, `terraform state list`. Prints `key value` lines for
  distributions beyond the standing one, tagged distributions, functions, key-value stores,
  public keys, key groups, cache policies, OAC, log delivery source/destination/delivery,
  launch instances, volumes, spot requests, security group, IAM role, instance profile, cookie
  parameter, build bucket, log bucket and `dev_launch_state`.
- Expect: every value `0` and the final line `launch_check ok`, exit 0.
- Exit 1 and `launch_check FAILED` if any value is not 0 or is `error` (an unreadable value is
  never a zero). During a HOLD period it is expected to be red: build bucket, log bucket,
  distribution and so on are still up.
- Keep: the full output (also run it once more on Sunday and once on Monday).
- Stop if: any non-zero outside a HOLD window, or `error`.

### Step 7. Destroy (needs no shell state)

```
make launch-destroy
```
- Stage 1 here needs no terraform state: it terminates an instance tagged `Stack=dev-launch` directly
  and removes key directories a killed session left behind.
- Needed after any `HOLD=1` or `PREWARM=1` session, after a crash, or when `launch-check` is red.
  A session without those flags already ran it from the trap.
- Calls: stage 1 (terminate any launch instance directly, remove leftover `launch-*` key
  directories under `$XDG_RUNTIME_DIR`, `ssm delete-parameter`), `launch_init.sh`, `terraform destroy`
  (retry once with `-refresh=false`), then `launch_check.sh`.
- Expect: `STAGE 1`, `STAGE 2`, `destroy` output, the check lines all `0`, exit 0. Time: allow
  30 minutes (distribution delete duration unverified). Cost: stops billing; about $0.
- Keep: the log, and the final check output.
- Stop if: `DESTROY FAILED TWICE` or `LAUNCH EDGE NOT CLEANLY DESTROYED` (exit 1). Section 5.

### Step 8. Ledger and cost read

```
cat observability/launch/ledger.jsonl
python3 launch/ledger.py guard --next-usd 0
```
- Read the `record` and `correct` lines per run (estimate and corrected USD, GB).
  `guard --next-usd 0` prints `attributable: reported + ledger + next = total` against $25.
- Cost Explorer lags about 24 h, so today's real spend is not in `reported` yet. The ledger
  estimate is the figure that governs during the weekend (ADR Decision 12). Monday
  2026-11-30 and Tuesday 2026-12-01 reads confirm. They never trigger a stop.
- Keep: the ledger file and the guard output.

### Step 9. Saturday: PREWARM, then Runs B-D (`SCENARIO=bcd`) and probe P

PREWARM about 4 hours before the run (ADR Decision 13), so logs deliver reliably:
```
make launch-session SCENARIO=bcd PREWARM=1
```
- Applies the edge with the default (discarded) key, no instance, no cookies. Expect it
  to end with `PREWARM: no instance and no usable key; nothing to stop` and `THE EDGE IS
  STILL UP. Run by <UTC time>: make launch-destroy`. Est ledger: $1.20. `launch-check` is red
  until stage 2.
Then the live session, with `HOLD=1` so the logs can be collected:
```
make launch-session SCENARIO=bcd HOLD=1 MINUTES=90
```
- `MINUTES` 88 is the minimum and the default; 90 is a margin the owner chooses (the scripts
  refuse below 88). Probe P (1 client, the first 30 build chunks, through the signed edge, from
  this machine) starts automatically after the post-seed checks; there is no separate laptop
  step. Planned bytes: B 214.748 GB, C 112.760 GB, D 27.380 GB, P 2.013 GB; total 356.902 GB
  (limit 400). Release (T0) at +53 min after the instance apply.
- Time: about 88 min of run (est) and the edge create wait. Cost: $1.79 by the ledger (est;
  overlaps with Cost Explorer on purpose). Cloudfront free tier covers about 1 TB and 10M requests
  per month; the GB over it are counted in the ledger at $0.085/GB.
- Expect the same lines as Run A, then `the run finished`, `STAGE 1`, `THE EDGE IS STILL UP. Run
  by <time>: make launch-destroy`. Exit 0.
- Then, in this order: `make launch-collect RUN_ID=<run_id>` (repeat until the logs arrive,
  Step 4), the 100M exercise (Step 10), then `make launch-destroy` (Step 7) by Sunday noon IST
  (ADR) and always within the printed 24 h deadline, then `make launch-check`.
- Keep: per Run A, plus `run.json` `k6_requests_by_type`.
- Stop if: as Run A. If Run A showed the nftables quota, the signature check or the destroy
  not working, do NOT start bcd: the owner decides.

### Step 10. 100M-event telemetry exercise (Saturday)

```
make launch-exercise ARGS="--check"
make launch-exercise ARGS="--generate 100000000"
```
- Same calls as Step 5. The plan calls for it after B-D; the cut line is `--generate 10000000`
  (plan section 7). The plan expects 20-40 minutes for the Spark app at 100M (comment in
  `launch_exercise.sh`, unverified); timeout 5400 s. The guard estimate of $1.00 is a default
  made for a short run. Choose `--estimate-usd N` for a 100M run: `unknown` (the plan puts all
  exercises at $3-6, plan section 6). Test at 1M first (done Friday), then 10M if time allows.
- Run it after `launch-collect` so `downloads_cdn/` exists and the CDN marts build
  (`enable_downloads_cdn`).
- Keep, stop-if: as Step 5.

### Step 11. Sunday: pull the results (read-only)

After `launch-collect`, the 100M exercise and `launch-destroy` are done. Use the run ids you wrote
down: Run A id, bcd id and the 100M exercise id.
```
make launch-pull-results SESSION="<run A id> <bcd id>" EXERCISE=<100M id>
```
- Runs the five queries in `launch/queries/` over the gold downloads marts and writes
  `observability/launch/extracts/*.csv` and `manifest.json`. Athena uses the `cerberus-transform`
  profile (set inside `results_pull.py`): `cerberus-admin` cannot `StartQueryExecution`.
- Every id must match `[a-z0-9-]`. A query over 20,000 rows, a changed header or a value with a
  12-digit run is refused and nothing is written for it.
- Stop if: the pull refuses (read the line; do not edit the extracts by hand).

### Step 12. Monday: pull the cost, render, commit

```
make launch-pull-cost
make launch-results-render
```
- `launch-pull-cost` (read-only Cost Explorer, profile `cerberus-admin`) writes
  `observability/launch/extracts/cost.json`: the November Usage total and the daily cost by service.
  Cost Explorer lags about 24 h: run it Monday, and again Tuesday 2026-12-01 for the confirmation.
- `launch-results-render` needs no AWS. It writes `docs/launch-day-results.md` and
  `docs/img/launch/*.svg`; a number with no input reads `not measured`.
- Then commit (owner/`cerberus-git`): the extracts, the charts, `docs/launch-day-results.md` and
  the run records under `observability/launch/runs/`. `make verify` passes a 13-digit epoch in
  milliseconds (the scan refuses exactly 12 digits only).
- Fill section 6 from the rendered doc, never from memory.

## 4. Stop rules

| Rule | Limit | What happens | Source |
|---|---|---|---|
| Attributable spend | $25 | Stop and destroy. `launch-session` and `launch-exercise` refuse (guard exit 1) when reported + ledger + next-run estimate is above $25 or the baseline is absent. `launch-destroy` and `launch-collect` are never refused. | ADR Decision 12; `ledger.py` |
| Account total | $40 | Total November `Usage` (credits excluded) equals the Budget alert. Stop all runs. | ADR Decision 12 |
| Session bytes | 400 GB | `plan_bytes.py` refuses (exit 2). | ADR; `plan_bytes.py` |
| Month-to-date bytes | 900 GB | Same, month-to-date plus session. | same |
| Byte layers 3 and 4 | budget + 10% | Instance nftables drop; session polls `BytesDownloaded` each 60 s, stops above budget plus probe bytes x 1.10 (exit 3). Stops with a loud `BYTE BUDGET EXCEEDED`. Unreadable 5 minutes in a row stops too (exit 4). | `launch_session.sh` |
| A guard failure | any | Do not continue. No bypass flag exists; do not edit the ledger to pass. | ADR Decision 12 |
| An unreadable value | any `error` | `launch-check` fails; a failed read is never a zero. Stop and read it another way. | `launch_check.sh` |
| A leftover | any non-zero | Run `make launch-destroy`, then `make launch-check`. Stop new runs until all 0. | ADR Decision 2 |

- Attributable = November `Usage` (credits excluded, all services) minus the baseline
  through 2026-11-24, plus the ledger. Cost Explorer lags about 24 h, so on the day the
  ledger estimate governs; reported spend overlaps with it on purpose, so the rule errs
  toward refusing. Cost Explorer confirms on Monday and Tuesday; it is not the trigger.
- Expected total: $8-15 plan estimate (unverified). Free-tier overrun: about $8.50 per
  100 GB (US) or $10.90 (India) (plan F9).
- The 24 h hold: `HOLD=1` and `PREWARM=1` keep the edge and the log bucket up to 24 h
  at about $0 with no instance running. The session prints a deadline `now + 24 h`. It
  is a rule for the owner, not a timer: no automation runs stage 2. The owner runs `make
  launch-destroy` by that deadline (and by Sunday noon IST per the ADR). `launch-check`
  is red until then. The cookies and the private key are already gone after stage 1.

## 5. Recovery

First, always: run `make launch-check` (read-only) and read the counts.

- Interrupted session (Ctrl-C, closed terminal, SIGTERM): the EXIT trap runs stage 1
  (and stage 2 unless HOLD/PREWARM). Wait for it; Ctrl-C is ignored from there. A second
  look: `make launch-check`. If it prints `SESSION NOT CLEANLY ENDED`, run `make
  launch-destroy && make launch-check`.
- Lost shell (terminal gone, SIGKILL, power loss): the trap did not run. The instance
  shuts itself down at `MINUTES` plus 30 min (unverified margin) and terminates. Open a
  new shell and run `make launch-destroy`. It needs no shell state: it deletes the leftover
  cookie parameter, destroys the root, and checks. The private key lived only in tmpfs; a
  reboot removed it. If the machine did not reboot, delete the `launch-*` directory under
  `$XDG_RUNTIME_DIR` (`shred -u` the files first).
- Failed apply: the trap runs stage 1 then stage 2 (a failed PREWARM apply runs both stages).
  If terraform holds a state lock, it waits 120 s (`-lock-timeout`). Then run `make
  launch-destroy`. Do not retry the session until `launch-check` is all 0.
- Failed destroy: `launch-destroy` already retries once with `-refresh=false`. If
  `DESTROY FAILED TWICE`: run it once more; read the terraform error (it may name a bucket;
  do not paste it in public); check the console for CloudFront, EC2 instances and the log
  and build buckets. The distribution is disabled then deleted, which is slow (about 30
  min allowed). The `cerberus-admin-launch` policy must stay attached until the check is 0.
  Delete by hand only what `launch-check` names, and only after the owner agrees.
- Leftover report (`launch-check` non-zero): the key names the resource class. Run `make
  launch-destroy`, then `make launch-check`. A leftover instance: preflight of the next
  session also refuses (`launch instance(s) exist`). If an instance stays: it is tagged
  `Stack=dev-launch`; terminate it (owner, console or `aws ec2 terminate-instances`).
  A leftover `cookie_parameter`: `launch-destroy` stage 1 deletes it.
- Expired credentials: `STOP: no AWS identity` in preflight is safe (nothing created).
  Mid-session the trap's AWS calls fail and report loudly (`COOKIE PARAMETER DELETE
  FAILED`, `STAGE 1 APPLY FAILED`). Renew the credentials in a new shell, then `make
  launch-destroy && make launch-check`. The cookies expire at mint + `MINUTES` anyway.
- Owner laptop off: nothing keeps running except the instance and the edge. The instance
  stops itself (MINUTES + 30 min, unverified; a one-time Spot instance is expected to terminate on shutdown, unverified); its
  nftables quota caps the bytes; the cookies expire. The edge and buckets stay until you
  run `make launch-destroy`. Do that as soon as you are back, and no later than the 24 h
  deadline. Cost of waiting is about $0 per the ADR; the unverified part is the
  distribution and the buckets.
- Exercise failed or interrupted: the trap destroys `dev-compute` anyway. If it did not
  (`DESTROY FAILED`), run `make compute-destroy`, then check EKS, NAT, EIP and running
  instances are 0 (the script prints `after destroy:`).

## 6. Results table (fill in; leave blank until measured, never estimate)

| Item | Value |
|---|---|
| Run A run id | |
| Run A start and end (UTC) | |
| Run A bytes (CloudWatch `BytesDownloaded`) | |
| Run A requests (`k6_requests`, `curl_requests`) | |
| No cookie answers 403 | |
| Licence 403 before T0, then 200 | |
| Signature checked before the licence Function | |
| nftables quota stopped traffic at budget | |
| Stage 2 duration | |
| `launch-check` after Run A | |
| Log fields as delivered (Run A, HOLD only) | |
| Bronze CDN has no client IP, no account ID | |
| 1M exercise run id | |
| 1M events, bronze to silver count | |
| 1M rerun adds 0 | |
| 1M exercise cluster seconds, dbt exit, DQ exit | |
| PREWARM start (UTC) | |
| bcd run id, start and end (UTC) | |
| bcd bytes (B, C, D, P) | |
| bcd requests (`k6_requests_by_type`) | |
| Cache hit ratio, origin requests (Run D cold vs warm) | |
| TTFB p50 / p99, client and probe P (Bengaluru) | |
| `cdn_logs_complete` (log lines vs k6 counts, %) | |
| 100M run id, events, cluster seconds | |
| 100M dbt exit, DQ exit | |
| Scale ratio (measured peak / 33.03 Tbps, one region) | |
| Stage 2 done at (UTC); `launch-check` all 0 at | |
| Ledger total (sum of `usd` per run) | |
| Cost Explorer attributable on Mon 2026-11-30 | |
| Cost Explorer attributable on Tue 2026-12-01 | |
| Account November Usage total | |
| Budget alert returned to $20 on | |
| `cerberus-admin-launch` detached on | |

## 7. ADR 0030 Accepted evidence list

From `docs/adr-status.md` (acceptance record) and the ADR "Unverified". Only the owner marks
the ADR Accepted. Fill each from a kept file.

| Claim | Evidence to keep | Step |
|---|---|---|
| Admin permissions sufficient and valid | simulate output after the paste; Run A applies and destroys with no AccessDenied | 2, 3 |
| Generator deterministic; IDs unique within a run | 1M and 100M run records; DQ pass | 5, 10 |
| Byte guard refuses over budget | dry-run table; a refusal test is offline only (`make launch-test`) | 1 |
| nftables quota stops traffic | Run A results and CloudWatch `BytesDownloaded` vs `budget_bytes` | 3 |
| No cookie gives 403; licence 403 then 200 | Run A log lines `checks: ...`; k6 summaries | 3 |
| Signature checks run before the licence Function | Run A: a no-cookie `/license` after T0 (ADR Unverified); the code does not do this check, so it needs a manual `curl` after T0 or is `unknown` | 3 |
| Destroy leaves nothing; stage 2 time | `launch-check` all 0; stage 2 duration from the log | 3, 6, 7 |
| No client IP or account ID in bronze | `launch-collect` accepted; `cdn_fields.json`; a bronze listing | 4 |
| Silver load idempotent; a rerun adds nothing | 1M exercise promote line; a rerun (owner decision) | 5 |
| Spend under $25 attributable | ledger file; Cost Explorer Mon and Tue reads | 8 |
| Log field names, KVS propagation, nftables quota, 30 min shutdown margin, per-client DNS | Run A results and logs (README "Unverified") | 3 |

## 8. Contradictions and gaps found (not fixed)

Checked against `main` after #202-#204: the review findings F1-F3 are fixed and no item below
is one of them. Items 1-3 and 5 are unchanged; item 4 is still the owner's decision.

1. Plan section 6 (`docs/plans/2026-11-25-launch-day.md` L239-241) keeps a `BytesDownloaded`
   alarm at 450 GB and SNS; ADR Decision 12 (`docs/adr/0030-launch-day.md` L264-265)
   drops them. The ADR wins and the code has no alarm.
2. Plan section 7 (L253) lists a separate "laptop probe" on Saturday; the code runs probe
   P inside the session (`orchestration/launch_session.sh` L566-571, ADR L87-89). There is no
   separate probe command.
3. Allowance differs: `launch/ledger.py` L50 `ALLOWANCE_USD = 1.00` (session estimate) and
   `orchestration/launch_exercise.sh` L66 `ALLOWANCE_USD ... 0.25` (exercise correction). Both
   unverified. Not a stop-rule error, but the ledger mixes the two.
4. The plan and ADR do not say whether Run A uses `HOLD=1` (this runbook gives `HOLD=1` and the owner may
   drop it), yet Run A is the evidence for the
   CDN log fields (README "Unverified"). Without HOLD the log bucket is destroyed and no log
   is read.
5. No script or test checks "signature before the Function" with a no-cookie `/license`
   request after T0 (ADR L328 says Run A proves it). It needs a manual `curl`.
