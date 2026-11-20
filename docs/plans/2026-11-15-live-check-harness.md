# Plan: a live-check harness (script + read-only verifier agent) for 9.6 §7 and PR F

Save as `docs/plans/2026-11-15-live-check-harness.md`. This is tooling for existing subtasks, not a decision. No ADR is needed, and it contradicts no ADR (see Constraints).

## 1. Question

How do we run the owner-run live checks with a script, so nothing depends on catching a URL that is printed once? The checks are 9.6 §7 D1–D3, PR F E1–E6, `live.json` during and after the session, and the ADR 0026 build-step-5 reads. A Claude agent then does the read-only follow-ups and drafts the 9.6c / PR F record.

Why now: the 2026-11-14 session proved the infrastructure. But E1–E6 are still untested because the owner missed the URL. D3 also lost the fullwidth and zero-width characters in a manual paste. PR F and 9.6 both block 9.2, 9.6 and Milestone 9 (ADR 0026 plan §8.1).

## 2. Facts

**2026-11-14 live run (from the caller, from the owner's run; not yet in the repo).** Record these in the plan file and in the docs step (build step 1, item 8).
- D1: all six headers matched `EDGE_HEADERS` exactly. POST with no token gave 401, `Bearer x` gave 401, and GET gave 404.
- D2: no CSP errors.
- D3: the 7 commands worked and the hostile lines were refused. Two gaps:
  - The manual paste lost the fullwidth and zero-width characters, so those two cases are untested.
  - The 520-character line was cut by the input `maxlength`. This is by design. `max_input_length()` = `MAX_TOKENS * MAX_TOKEN_CHARS + MAX_TOKENS - 1` = 8·64+7 = 519 (`console/cerberus_terminal/build.py` L37-39, `console/cerberus_console/config.py` L30-31). `test_terminal_build.py` L109-112 pins it. The 9.6 plan's 519-character line is the right case.
- First session (`MINUTES=30`), from CloudTrail:
  - NAT 14:09:47Z, instance 14:11:21Z, VPC origin 14:11:39Z, Cognito client 14:22:44Z. That is about 13 min of wake, inside the spike's 12–15 min (Phases.md 9.2).
  - The destroy started 14:54:05Z and the NAT was deleted 15:05:06Z, about 11 min.
  - All 20 resources were created, so the probe passed and `live.json` was written. The auto teardown removed 20/20, and `console_check` was ok.
- E1–E6: untested.

**Repo facts.**
- `live.json` sits at the root of the standing site bucket. It holds `{schema:1, url:"https://<session-cf>/", home:"/d/cerberus-runs", started, ends}` with `no-cache` (`terraform/envs/dev-console/session.tf` L128-141). The public file already holds the session URL, so a script can read the URL there. Nobody needs to copy it from the terminal.
- `console_session.sh` prints the URL once (L229-230). It then redraws `time left` every 10 s with `\r` (L232-238). There is no bell and no reprint.
- `console_url` is `https://<standing-cf>` with no trailing slash (`terraform/envs/dev-standing/outputs.tf` L126-129). The Makefile already reads it with `terraform output -raw` (Makefile L117-121).
- `EDGE_HEADERS` (6 keys) is in `console/tests/test_edge_config.py` L27-48. That module imports `pytest` at top level. `console/tests/hostile.py` holds `ARGV` with `"fullwidth"`, `"zero width"`, `"command substitution"`, `"backtick"`, `"html img"`, `"run with a path"`, `"rtl override"`, `"SQL"`. `BODIES["shell"]` is `status; id`. It imports only `base64` and `json`.
- `grammar.REFUSED_TEXT` = "Not an allowed command. Type help for the list." and `COMMANDS` = help, status, runs, run(1 arg), cost, dq, slo (`console/cerberus_console/grammar.py` L15, L23-31). `run latest` is valid (`commands.py` L38, L240).
- The terminal DOM is `#status`, `#log` (`.line` children), `#cmd-form`, `#cmd-input` (maxlength), `#sign-in` and `#sign-out` (`static/index.html.tmpl` L15-26). After sign-in the status reads "Signed in. N min left…" (`terminal.js` L211). A 429 prints "Too many commands. Wait a second." (L111). `tokenise` splits on `/\s+/` (L34-36).
- Throttling: rate 1, burst 3 (`test_edge_config.py` L51-52). The Lambda timeout is 25 s.
- Grafana (`observability/grafana/console/grafana.ini.tmpl`):
  - `disable_login_form = true`, `auto_login = true`, role fixed `'Viewer'` with `role_attribute_strict`, `signout_redirect_url` set.
  - `[explore] enabled = false` is marked "unverified key name".
  - Grafana 13.2.3 has not run these keys yet (header comment).
- Dashboards:
  - Home uid `cerberus-runs`, title "0 · Recorded runs". It is one markdown text panel with links `[YYYY-MM-DD HH:MM UTC · <execution>](/d/cerberus-run-story?from=..&to=..)` (`observability/grafana/console/dashboards.py` L21-23, L240-261, L264-300).
  - Story tiles are titled "Now", "Data quality result" and "Clean-up result". "Pipeline journey" is panel id 4 (`observability/grafana/dashboards/cerberus-run-story.json`; `dashboards.py` L27).
- The access log group is `/aws/apigateway/cerberus-console-api`. Its fields are requestId, requestTime, routeKey, status, authError, sub, integrationStatus, integrationLatency, responseLength and edgeIp (`terraform/modules/console_edge/main.tf` L388-424).
- `cerberus-admin` has the permissions the follow-ups need:
  - `logs:FilterLogEvents` on `/aws/apigateway/cerberus-*` (`iam/cerberus-admin/policies/cerberus-admin-orchestration.json`).
  - `iam:SimulatePrincipalPolicy` on `*` and `cloudtrail:LookupEvents` (`cerberus-admin-iam-and-governance.json` L60, L170).
- Both distributions use `cloudfront_default_certificate = true` (`console_edge/main.tf` L263, `dev-console/edge.tf` L155). The TLS floor is "reportedly TLSv1", unverified (ADR 0026 L202-206; plan step 5a).
- ADR 0026 plan build step 5 (owner, during PR F):
  - (a) openssl TLS1.0/1.1 on both distributions.
  - (b) Viewer `/api/frontend/settings` and `/api/datasources`.
  - (c) disabled-user token test, which is a Cognito write.
  - (d) Grafana CSP.
  - (e) 504s on the 100M windows.
- `console-check` is a Cognito user outside Terraform. The owner enables it before a check and disables it after (`admin-enable-user` / `admin-disable-user`, both writes; `docs/plans/2026-11-12-terminal-panel.md` L127, L138, §7a).
- **The console lint bans `subprocess`, `os.system` and the like for everything under `console/`** (`console/ruff.toml`, ADR 0024 rule 5), and CI runs `ruff check .` from the root. `test_banned_calls.py` scans only `cerberus_console/`. So a harness under `console/` must not shell out. It cannot call openssl or terraform.
- The Lambda zip takes only `cerberus_console/` and `runs/` (`console_edge/main.tf` comment above section 5). A new sibling package is never deployed.
- CI runs `pytest console` with `requirements-dev.txt` only (`code-ci.yml` L91-106). The paths filter includes `console/**`.
- Playwright: uv has `playwright-1.65.1` cached (`~/.cache/uv/archive-v0/.../playwright-1.65.1.dist-info`). The browser cache has `chromium-1248` and `chromium_headless_shell-1248`. `record_terminal_demo.py` L94 launches with `executable_path=` set to the headless shell. Unverified: that 1.65.1 drives build 1248 without warnings (the demo script suggests it does).
- Makefile convention: `uv run --no-project --python 3.12 --with <pin> python -m <pkg>` (L108). Local `openssl` is 3.5.5 and supports `-tls1` and `-tls1_1`. `aws` and `jq` are installed.
- Existing agent format: frontmatter `name`, `description`, `tools`, `model` (`.claude/agents/cerberus-*.md`). No `.claude/settings.json` is committed. `/workflow` already says: if a project agent is not loaded, use `general-purpose` with the agent file's text (`.claude/commands/workflow.md` last paragraph).

**Unverified (the harness records these, it does not assume them).**
- Grafana 13.2.3 `grafanaBootData` keys: `user.orgRole`, `user.isGrafanaAdmin`, `settings.disableLoginForm`, `settings.exploreEnabled`, and the `navTree` ids `explore` / `cfg` / `admin`.
- The `data-testid Panel header <title>` selector.
- The `?inspect=<id>&inspectTab=query` URL parameter.
- The classic hosted-UI selectors `input[name=username]` and `input[name=password]` (the page has two forms, so use `:visible`).
- Whether CDP `insertText` respects `maxlength`.
- ~~Whether uv's bundled OpenSSL can offer TLS 1.0 at `SECLEVEL=0`.~~ Resolved by the 2026-11-15 smoke run: the probe returned accepted (TLSv1).
- ~~The status of a missing `live.json` through CloudFront (403 or 404).~~ Resolved by the 2026-11-15 smoke run: 403.

## 3. Constraints

- **Cost:** $0 new. No new AWS resource. The checks run inside a session the owner already starts. The 7 commands run small Athena queries in the console workgroup (10 GiB cutoff), the same as the manual check.
- `dev-compute` destroy contract and CI `dev-standing` apply: not touched.
- **Claude never runs `terraform apply` and never holds the test password.** The password comes from `getpass` in the owner's terminal, or from `CERBERUS_CHECK_PASSWORD` set in the owner's own shell. It is never written to file, log, trace, HAR, video or chat. Claude runs only the no-sign-in half.
- Reports redact the standing and session CloudFront hosts, the account ID, the pool ID, client IDs, tokens, OAuth `code` / `state`, and `sub` UUIDs. Reports go to a gitignored path.
- **Read-only.** It signs in as `console-check` only. It sends no Cognito or IAM writes. ADR 0026 step 5(c) stays owner-manual.
- No new line in `requirements-dev.txt`. CI must not import Playwright.
- ADR 0024 rule 5: no program execution under `console/`. Ruff enforces it. ADR 0025 (Bedrock product agents) is unrelated to a Claude Code dev agent. Nothing to amend.

## 4. Options

**A. Script + `general-purpose` with a prompt file (`docs/runbooks/live-verify.md`).**
- Idle $0. Effort: small.
- Works in this session.
- Gives up a tool restriction: `general-purpose` has Write and Edit. It does not follow the repo's agent pattern.

**B. Script + project agent `.claude/agents/cerberus-live-verifier.md` (tools: Read, Grep, Glob, Bash; model sonnet).**
- Idle $0. Effort: the same as A, plus one markdown file.
- Write and Edit are removed. The agent can be reused for the 90-minute session and for later sessions.
- Gives up: it loads only at the next session start. This session uses the `/workflow` fallback, which is already documented.

**C. Script only. The main session reads the report.**
- Lowest effort.
- Gives up: the five AWS follow-ups and the record draft fill the main context. It also ignores the explicit ask for an agent.

**D. Script does everything, including the AWS follow-ups (boto3 or CLI in code).**
- Most deterministic.
- Gives up: shelling out is banned under `console/`. boto3 is allowed, but it would need `cerberus-admin`-level reads inside console code, which blurs the read-only package boundary. It is also more code for interpretive steps (the CloudTrail timeline).

Pillar tensions:
- **Security** (password and redaction) against **Operational Excellence** (one-command runs). Solution: split the harness into a public half that Claude may run and a sign-in half that only the owner runs.
- **Reliability** of DOM selectors on an unrun Grafana version. Solution: prefer bootData, API and network-response checks. DOM results are "record", backed by screenshots that the agent reads (Read can view PNG).

## 5. Recommendation

**B.**
- A stdlib + Playwright package `console/cerberus_live_check/` with no subprocess. HTTP uses `urllib`, TLS uses the `ssl` module, and the browser uses Playwright via `uv run --with`.
- Three make targets: `console-wait` (Claude), `console-verify-public` (Claude) and `console-verify` (owner).
- A small `console_session.sh` reminder.
- One read-only agent file.

The agent runs the follow-ups as exact CLI commands from its own file, not from code. This keeps console code free of admin reads (against D). It also beats A on tool restriction at the same cost.

Small deviation from the caller: use `uv run --no-project --python 3.12 --with playwright==1.65.1 --with pytest==9.1.1` instead of `uvx --with playwright`. This matches Makefile L108. `pytest` is added only because `test_edge_config.py` imports it, so `EDGE_HEADERS` is reused, not copied. TLS uses Python `ssl`, not `openssl s_client`, because of the subprocess ban. The agent may also run `openssl s_client` as a cross-check while the session is live.

## 6. ADR outline

None. This is tooling under 9.2 PR F and 9.6. No decision changes.

## 7. Build steps (one PR: `9.6-live-check-harness`)

**Files**

1. `console/cerberus_live_check/__init__.py`, `__main__.py`: argparse with subcommands `watch` and `verify`. No Playwright import at module top anywhere.

2. `console/cerberus_live_check/redact.py` (pure):
   - `redact(text, hosts)` replaces:
     - the given standing and session hosts → `<standing-cf>` / `<session-cf>`;
     - `\b\d{12}\b` → `<ACCOUNT_ID>`;
     - `[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+` → `<POOL_ID>`;
     - `eyJ[\w-]+\.[\w-]+\.[\w-]*` → `<TOKEN>`;
     - UUIDs → `<UUID>`;
     - the values of `code=`, `state=`, `client_id=`, `redirect_uri=` → `<redacted>`.
   - It is idempotent. It must leave the public `COGNITO_URL` and the `EDGE_HEADERS` values unchanged.

3. `console/cerberus_live_check/report.py` (pure):
   - A `Check(id, status in pass|fail|record|skip, expected, observed, note)` record.
   - `compare_headers(observed, EDGE_HEADERS)`: names are case-insensitive, values must match exactly, extra headers are ignored, and a diff goes in `observed`.
   - `parse_live(json_text, now)`: ready only if schema == 1, `url` is https, and `ends` is in the future. A stale file is not ready (console-session plan risk 5).
   - `typed_lines()`, built from the shared sources:
     - `json.loads(hostile.BODIES["shell"])["argv"][0]` (`status; id`);
     - `" ".join(hostile.ARGV[n])` for the 8 names in §2;
     - `"a" * max_input_length()` (519);
     - `"a" * (max_input_length() + 1)` (expect it clamped to 519).
   - `commands()` from `grammar.COMMANDS`: zero-arg names as-is, `run` → `run latest`.
   - `write(dir, checks, secret)`:
     - Runs `redact()` over the full JSON and markdown.
     - Refuses to write, and exits 2, if `secret` occurs in either.
     - Writes `report.json` and `report.md`.
     - Exit 0 when nothing failed, 1 when any check failed.

4. `console/cerberus_live_check/http.py` (stdlib):
   - `fetch()` allows https only.
   - The TLS probe sets `ssl.SSLContext` min = max = TLSv1, TLSv1_1 and TLSv1_2, with `set_ciphers("DEFAULT:@SECLEVEL=0")`. It classifies each as accepted, refused (an alert from the server) or untestable-locally (the client cannot offer it).
   - `# noqa` with a reason on S310 and S502/S503 only.

5. `console/cerberus_live_check/watch.py`:
   - Polls `<standing>/live.json?t=<epoch>` every 15 s.
   - When ready: print "READY live.json 200; ends HH:MMZ (N min left); URL hidden", ring a bell (`\a`), exit 0.
   - `--gone` waits until the status is not 200, then exits 0.
   - `--timeout-min 30` exits 3. `--show-url` prints the URL (owner terminal only).
   - It never prints the URL by default.

6. `console/cerberus_live_check/browser.py` (Playwright imported inside functions):
   - `executable_path` comes from `--chromium`, else `$CERBERUS_CHROMIUM`, else the newest `~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell`.
   - No tracing, video or HAR. A new context for each part, so every part starts from a clean profile.
   - Collects CSP violations from `console` messages on every page.
   - A `dialog` handler marks a fail and dismisses.
   - Never takes a screenshot on a Cognito page.

7. `verify` runs in this order. It reads `live.json` first and waits up to 30 min, so the owner can start it right after the y/N.

   **Public checks (no password):**
   - L1 `live.json` 200, with minutes left.
   - D1a headers on `/terminal/index.html` against `EDGE_HEADERS`.
   - D1b POST `/api/command` with no token → 401. D1c `Bearer x` → 401. D1d GET → record (2026-11-14: 404).
   - D2 CSP violations on `/` and on `/terminal/index.html` before sign-in = 0.
   - T1 TLS 1.0/1.1/1.2 on both hosts (record).
   - S1 the session `/` response security headers (record; for ADR 0026 5d).

   **Sign-in checks.** Skipped with "skip: no password" when `--no-sign-in` is set, or when there is no TTY and no env var.
   - D3a: sign in at `#sign-in` through the hosted UI as `console-check`. `#status` starts with "Signed in."
   - D3b: the 7 commands. Each prints a new `.line` that is not `REFUSED_TEXT` and not "Not available right now.". Leave at least 1.5 s between commands. Wait up to 30 s per command.
   - D3c: each typed line goes in with `keyboard.insert_text`.
     - Record whether `input.value == line`, which proves exact Unicode reached the page, or `len == 519` for the long line.
     - The output must equal `REFUSED_TEXT`.
     - There must be no dialog and no `<img>` in `#log`.
   - D3d: sign out.
   - E1:
     - No `input[type=password]` on the session origin. The only password field is on `*.amazoncognito.com`.
     - From `window.grafanaBootData`, record and check: `orgRole == "Viewer"`, `isGrafanaAdmin == false`, `disableLoginForm == true`, and no `cfg` / `admin` / `explore` ids in `navTree`.
   - E2: read `/api/dashboards/uid/cerberus-runs`. Use a regex to find the links labelled `2026-10-13` and `2026-11-08 14:26`. Open each, wait for network idle (60 s max), then record:
     - `/api/ds/query` counts by status, and how many returned non-empty frames;
     - the `/api/annotations` item count (step regions; it must be > 0);
     - for the tiles "Now", "Data quality result" and "Clean-up result", whether "No data" shows (DOM; "record" if the selector misses);
     - a full-page screenshot.
   - E3:
     - Open the story dashboard with `?inspect=4&inspectTab=query`. Record whether the drawer is visible and take a screenshot.
     - Explore: record `exploreEnabled`, the navTree, and the status and final URL of `/explore`.
   - E4: run in-page `fetch`:
     - `GET /api/user`, `/api/frontend/settings`, `/api/datasources`: record the status. Fail if a body holds `\d{12}` or `arn:aws`.
     - `POST /api/ds/query` with datasource uid `cloudwatch`: must not be 2xx (PR F item 4).
   - E5: go to `/logout`. Record that `/login` appeared in the chain. Opening the session URL again must land on Cognito with a visible password input.
   - E6: 504 count and the slowest `ds/query` per E2 window.

   **Output.** Write `console/live-check-reports/<UTC stamp>/` with `report.json`, `report.md` and `*.png`. Print the path and ring the bell.

8. `console/tests/test_live_check.py` (no network, no Playwright):
   - Redaction cases, one for each pattern, plus idempotence and the COGNITO_URL kept.
   - `compare_headers` cases: match, wrong value, missing key, upper-case name, extra header.
   - Every `typed_lines()` entry tokenised like `terminal.js` (`re.split(r"\s+", line.strip())`) raises `grammar.Refused`.
   - The long-line lengths are 519 and 520.
   - `commands()` all parse.
   - `parse_live` cases: future, past, missing key, http url.
   - `write()` refuses when the secret is present.
   - Importing the package leaves `"playwright" not in sys.modules`.

9. `Makefile`, three `.PHONY` targets. Each reads the standing URL with the `@` prefix: `--standing "$$($(TF_BIN) -chdir=$(TF_STANDING_DIR) output -raw console_url)"`.
   - `console-wait`: `## READ-ONLY, no password: wait for live.json 200 and ring the bell (ARGS=--gone waits for it to go)`. Stdlib, no `--with`.
   - `console-verify-public`: `## READ-ONLY, no password, Claude-safe: headers, 401/404, CSP, TLS, live.json`. Uses `--no-sign-in`.
   - `console-verify`: `## READ-ONLY, owner-run in your own terminal: public checks plus the console-check sign-in checks; asks for the password`.

10. `.gitignore`: add `console/live-check-reports/` with a comment.

11. `orchestration/console_session.sh`:
    - Ring the bell when the URL first prints.
    - Add the line "In another terminal: make console-verify".
    - In the loop, keep `next=$((SECONDS+300))`. When it is due, run `printf '\a\n'`, then `log "session URL: $url ($((left/60)) min left)"`, then `next+=300`.
    - Update the header comment (the URL still goes to the terminal only).

12. `.claude/agents/cerberus-live-verifier.md`: frontmatter `tools: Read, Grep, Glob, Bash`, `model: sonnet`.

    Rules:
    - Read-only.
    - May run `make console-wait`, `make console-verify-public` and `make console-check`.
    - Never runs `make console-verify`.
    - Never reads, asks for or echoes the password or `CERBERUS_CHECK_PASSWORD`.
    - No `terraform apply`, no Cognito `admin-*`, no `put`, `delete` or git writes.
    - Redact in every output with the same rules as `redact.py`.

    Input: a report dir path.

    Steps, each with exact commands:
    1. Read `report.json`, `report.md` and the PNGs. Judge the "record" tiles and the inspect drawer from the screenshots.
    2. `aws logs filter-log-events --log-group-name /aws/apigateway/cerberus-console-api --start-time/--end-time` (from the report window) piped to `jq`. Build a table of status, routeKey, responseLength, authError and `sub` present (bool), plus counts by status. The expectation is 400s at 87 bytes, each with a sub (9.6 §7.4).
    3. `aws iam get-role --role-name cerberus-console-cli`. Then run `simulate-principal-policy` for the 9.6 §7.6 action list. Take the resources from the dev-standing outputs `bucket_arns` and `athena_results_bucket_name`, and the results prefix from `aws athena get-work-group` on `console_workgroup_name`. Expected: every action `implicitDeny`, and `s3:PutObject` on the results prefix `allowed`.
    4. While the session is live: `openssl s_client -connect <host>:443 -servername <host> -tls1` and `-tls1_1`, with `-cipher 'DEFAULT:@SECLEVEL=0'`, as a cross-check of T1.
    5. Take the CloudTrail timeline: `aws cloudtrail lookup-events` for the event names behind the 2026-11-14 timeline, over the session window.
    6. After `make console-wait ARGS=--gone`: `make console-check`, all 0.

    Output: a draft "9.6c record" and a "PR F Outcome" in the 9.6 §7 record shape, with no account ID, hosts, tokens or subs. It returns the draft in its final message and writes no files.

13. `console/README.md`: a "Live check harness" section. It covers the run order, which targets Claude may run, the owner's Cognito enable/disable, and the report path.

14. Record the 2026-11-14 partial result:
    - In `docs/plans/2026-11-13-safety-and-live-check.md`, add a new §7a "Live result 2026-11-14 (partial)" with the facts in §2.
    - In `docs/plans/2026-11-12-console-session.md` §6 PR F, add a one-line progress note: first session infra passed; E1–E6 untested.

**Verify (in the PR, by the executor)**
- `cd console && pytest` passes, including the new tests.
- `ruff check . && ruff format --check .` from the repo root (this covers the subprocess ban).
- `bash -n orchestration/console_session.sh`, and `shellcheck` if installed.
- `make console-wait` with no session: it times out with exit 3, or Ctrl-C after one poll shows "not ready". This is read-only, so Claude may run it.
- `make console-verify-public` with no session: L1 waits. Optionally add `--no-wait`, which records L1 as fail and runs D1/D2/T1 on the standing edge only. This proves the HTTP, TLS and browser launch paths with no password and no session.

**Live run (next session; owner and Claude)**
1. Owner: `aws cognito-idp admin-enable-user ... console-check` (a write).
2. Owner, terminal 1: `make console-session MINUTES=30`.
3. Claude: `make console-wait` in the background, which announces readiness. Then `make console-verify-public`.
4. Owner, terminal 2: `make console-verify` (getpass). Steps 3 and 4 can overlap. A second run of the public half is harmless.
5. Claude: start `cerberus-live-verifier` with the newest report dir, or `general-purpose` with the file's text if the agent is not loaded yet. Run its steps 1–5 while the session is live.
6. After the destroy: `make console-wait ARGS=--gone`, then agent step 6.
7. Owner: `admin-disable-user console-check`.
8. The executor writes the agent's draft into the 9.6 / console-session plans. Cost Explorer the next day.

**Phases.md:** no new subtask. Add a progress note under 9.6 (and 9.2 PR F) when the PR merges.

## 8. Owner answers (2026-11-15)

1. Claude may run `make console-verify-public` itself during a live session.
2. Screenshots stay on by default. They go to the gitignored `console/live-check-reports/` and are never taken on a Cognito page.

Key paths:
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/orchestration/console_session.sh
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/terraform/envs/dev-console/session.tf
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/console/tests/test_edge_config.py
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/console/tests/hostile.py
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/console/ruff.toml
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/console/cerberus_terminal/build.py
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/observability/grafana/console/grafana.ini.tmpl
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/observability/grafana/console/dashboards.py
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/docs/plans/2026-11-13-safety-and-live-check.md
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/docs/plans/2026-11-12-console-session.md
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/docs/plans/2026-11-13-phase-9-well-architected-review.md
- /home/chirag/projects/cerberus/.claude/agents/ (existing agent format)
