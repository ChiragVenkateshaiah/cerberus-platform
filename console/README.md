# Console command set (ADR 0024)

The read-only commands behind `cerberus` on the console site: `status`, `runs`,
`run <id>`, `cost`, `dq`, `slo` and `help`. One package, two entry points:

- The local CLI: `make cerberus CMD="status"` (also `CMD="--json run latest"`).
  It assumes `cerberus-console-cli` with your `cerberus-admin` profile and runs
  the same code as the Lambda. `make status` (10.5b) runs `status` through it (ADR 0021).
- `cerberus_console.api.lambda_handler`, for the console site's Lambda (step 7).

It is not a shell. It has no shell, no write and no free text: a request is
either exactly an allowed command or it is refused.

## Commands

| Command | Arguments | Reads |
|---|---|---|
| `help` | none, or one command name | nothing |
| `status` | none | the named status queries on AMP (Prometheus), Step Functions, one Athena query on gold, the newest record |
| `runs` | none (newest 50) | run records |
| `run <id>` | `latest` or a known id | run records; Step Functions detail if within 90 days |
| `cost [id]` | none, or a run-record id | run records |
| `dq [id]` | none, or a run-record id | run records |
| `slo` | none | run records |

A known id is an execution name in the run records (`observability/scale/runs/`)
or in the Step Functions list. Anything else answers `not_found`.
`cost` and `dq` accept only ids in the run records; only `run` also checks the Step Functions list.

## The grammar

Every token matches `[A-Za-z0-9][A-Za-z0-9-]{0,63}` (full match, ASCII). That
one rule rejects shell metacharacters, spaces, `/`, `..`, control characters,
non-ASCII lookalikes and bidi marks. At most 8 tokens; one leading `cerberus` is
dropped; the next token must be in the table above, in lowercase. The API body
is at most 2,048 bytes of JSON with exactly one key, `argv` (duplicates refused).
Rules: `cerberus_console/grammar.py`.

## The response

```json
{"ok": true,  "command": "status", "text": "...", "data": {}}
{"ok": false, "error": "refused",     "text": "Not an allowed command. Type help for the list."}
{"ok": false, "error": "not_found",   "text": "No run with that id. Type runs for the list."}
{"ok": false, "error": "unavailable", "text": "That command is not available right now. Try again later."}
```

HTTP status 200, 400, 404 and 503. The CLI exits 0, 2 (refused or not found) or
3 (unavailable). Output is printable ASCII only, a field is at most 200
characters, a table at most 50 rows, `text` at most 16 KiB and the response at
most 64 KiB. Account IDs inside ARNs are redacted. Step Functions `cause` text
is never read; only the failed state and the error code are shown. Any
exception becomes `unavailable`, logged by type name only.

## Cost per call

| Command | AWS cost |
|---|---|
| `help`, `runs`, `run` (record part), `cost`, `dq`, `slo` | $0 (git files; no Cost Explorer call) |
| Step Functions reads (`status`, `run <id>`) | $0 (the pricing page lists no charge for API reads; confirm in Cost Explorer after step 7) |
| `status`, gold freshness | one Athena query: at most the 10 MB minimum (about $0.00005) plus one S3 PUT; at most one billed query per 5 minutes across containers when Athena reuses the result (unverified for a zero charge) |

Caches bound it: the execution list for 30 s, the freshness result for 300 s. A failed freshness query is remembered for 60 s (negative cache), so a failing Athena is not asked again on each retry within one container.

## Run it

```
make cerberus CMD="help"
make cerberus CMD="status"
make cerberus CMD="--json slo"
make status
```

`make status` is read-only and owner-run. It runs `status` as `cerberus-console-cli`
(your `cerberus-admin` credentials assume the role). The first section, "Pipeline
status (from Prometheus)", reads the named queries in
`observability/queries/status.json` from AMP. It needs the workspace query URL:
pass `make status AMP_QUERY_URL=<workspace query URL>`, set
`CERBERUS_AMP_QUERY_URL`, or let the target read `terraform output
prometheus_endpoint`. Without a URL, or if AMP fails, that section prints
`unavailable` and the three sections below it still show. If AMP answers with no
data, it prints `no data yet`, never `failed`.

The AMP reader (`aws.py`, `AwsAmpReader`) is called by query name only. It signs
a GET with SigV4 (service `aps`), waits at most 4 s per attempt with 2 attempts,
reads at most 256 KiB per reply and 100 series per query, and gives all the
queries of one `status` 5 s together. It keeps a reply 30 s and a failure 60 s.
It reads only the `step` and `execution` labels and the value. Every string is
cleaned and cut at 200 characters. The role needs `aps:QueryMetrics` on the
workspace (10.5c, Terraform, not built yet).

The Athena query runs in the `cerberus_platform_console` workgroup (enforced,
10 MB scan cutoff) and writes one result object under `console/` in the results
bucket, which expires after a day. The role can read nothing else in gold than
Iceberg metadata.

## Test and lint

No boto3, no AWS and no network are needed; the tests use fake clients.

```
uvx --with pytest==9.1.1 pytest console -q
uvx ruff@0.16.4 check . && uvx ruff@0.16.4 format --check .
```

`ruff.toml` turns on the bandit rules (`S`) and bans `subprocess`, `os.system`,
`pickle` and similar imports. `tests/test_banned_calls.py` also fails on
`eval`, `exec`, `compile` and `__import__`. `tests/test_real_records.py` renders
every command on the committed run records, so a new record that breaks a
command fails CI. The test fixtures contain no account ID; ARNs use
`<ACCOUNT_ID>` or a placeholder filled in at test time.

## Emergency levers

Three levers, from smallest to largest (ADR 0026). Use the smallest one that
works. `<USERNAME>` is a placeholder; read the pool and distribution IDs from
Terraform and never paste them into a file.

**(a) Disable one user.** A write, owner-run.

```
POOL=$(terraform -chdir=terraform/envs/dev-standing output -raw console_user_pool_id)
aws cognito-idp admin-disable-user --user-pool-id "$POOL" --username <USERNAME>
aws cognito-idp admin-user-global-sign-out --user-pool-id "$POOL" --username <USERNAME>
```

The sign-out revokes refresh tokens. An access token that was already issued
may keep working until its `exp` (60 minutes after sign-in). This is unverified:
plan
`docs/plans/2026-11-13-phase-9-well-architected-review.md` §7 step 5(c) checks it live. If it holds, use lever (b) or (c) when
60 minutes is too long.

**(b) Stop everyone.** Open a PR that sets the API stage throttle to zero in the
`module "console_edge"` block of `terraform/envs/dev-standing/main.tf`:

```
throttle_rate_limit  = 0
throttle_burst_limit = 0
```

(The module defaults are 1 and 3; the variables are in
`terraform/modules/console_edge/variables.tf`.) CI applies it on merge. To
restore, remove the two lines in a second PR. The static site keeps serving;
only `/api/command` is refused.

Zero rejecting every request with 429 comes from community reports and a
provider issue, not from the AWS documentation. It is unverified here. After
the CI apply, send one `POST /api/command` and confirm a 429 before you rely on
the lever.

**(c) Last resort.** Disable the CloudFront distribution. This takes the whole
site down, and it is a write, owner-run.

```
DIST=$(terraform -chdir=terraform/envs/dev-standing output -raw console_distribution_id)
aws cloudfront get-distribution-config --id "$DIST" > /tmp/dist.json
jq '.DistributionConfig | .Enabled = false' /tmp/dist.json > /tmp/dist-off.json
aws cloudfront update-distribution --id "$DIST" --if-match "$(jq -r .ETag /tmp/dist.json)" \
  --distribution-config file:///tmp/dist-off.json >/dev/null
rm /tmp/dist.json /tmp/dist-off.json
```

The `rm` matters: the config holds the bucket domain, which contains the
account ID. Or use **Disable** on the distribution in the CloudFront console
(unverified). This is
drift from Terraform: the next CI apply of `dev-standing` sets `enabled` back
and brings the site up again. To bring it back at once, re-enable it the same
way, or run that apply. Do not merge an unrelated `dev-standing` change while
the site must stay down.

## Invite lifecycle

The pool is invite-only: self sign-up is off, and users are created by hand,
outside Terraform (ADR 0024). No email, password or token goes into the repo.

1. **Create.** Owner-run write. The user gets a temporary password that is
   valid for 7 days (`temporary_password_validity_days` in
   `terraform/modules/console_edge/main.tf`). Type the password at the hidden
   `read -rs` prompt, so it never reaches the screen, the shell history or a
   file. Send it to the visitor by a channel that is not the repo.

   ```
   read -rs TMPPW && aws cognito-idp admin-create-user --user-pool-id "$POOL" --username <USERNAME> \
     --temporary-password "$TMPPW" --message-action SUPPRESS >/dev/null; unset TMPPW
   ```

   `console-check`, the account the live check uses, is kept disabled between
   checks (see "Live check harness").
2. **Demo.** The visitor signs in on the terminal page and sets a new password.
   A sign-in lasts at most 60 minutes.
3. **Disable within 7 days** of the invite, even when the visitor never signed in:
   `admin-disable-user` and `admin-user-global-sign-out` as in lever (a).
4. **Catch a forgotten user.** `make console-check` prints an informational
   `enabled_users N` line. It never fails the check, and `/start-day` runs it
   and reports any non-zero value. `enabled_users unknown` means the read
   failed. Disable the user. `console-check` is enabled only during a live check.

## Landing page

`cerberus_landing/` builds the public landing page for the console site (ADR 0024,
step 8): one `index.html`, one stylesheet, one script, a favicon, the hand-drawn
architecture diagram and, when they exist, the scale charts. It is stdlib Python
and ships no inline script, no inline style and no inline handler, so it passes
the edge CSP as is. The page links to the terminal (`terminal/index.html`, invite
only). It reads the run records through `cerberus_console.records`, so its
"latest run" is the same record as `cerberus run latest`. Phase status comes from
`Phases.md` and the plain-language text from `cerberus_landing/content.toml`.

**The script** (`static/site.js`, step 9.4a, plan
`docs/plans/2026-11-28-landing-showcase.md`) does one thing: it shows the link to
the live Grafana dashboard while a session runs. It reads `live.json` from this
site with no cache, at load and every 60 seconds, and follows the rules in
"Live session link" below. The link is hidden in the HTML, so without
JavaScript the page shows nothing dead. The builder allows exactly one empty,
relative `<script src ... defer>` on the page, and none in an SVG.

```
make console-site            # build into console/site-dist/ (no AWS)
make console-site-preview    # serve it at http://127.0.0.1:8088/ with the edge CSP
```

The preview sends the edge's `Content-Security-Policy` (without
`upgrade-insecure-requests` and the Cognito host), so a violation shows in the
browser's DevTools console. The charts come from `docs/img/scale/` (override with
`--charts-dir`); until that folder exists the page shows a placeholder. The build
is deterministic: two builds of the same inputs are byte-identical, and asset
names carry a hash of their content.

Tests (`tests/test_landing_*.py`) cover determinism, links, the CSP scan (with
negative fixtures), the `Phases.md` parser, the run cards (including the hostile
record), the placeholder, accessibility basics and the stylesheet's contrast.
`tests/test_landing_js_scan.py` scans `site.js` and checks its fields against
`envs/dev-console`; `tests/js/landing.test.js` (`node --test`) covers when the
live link shows and hides.

**Publish.** `.github/workflows/console-site.yml` runs on a push to main that
changes the page's inputs (and on manual dispatch). It builds the site, assumes
`cerberus-ci-apply`, reads the bucket, distribution and URL from the
`envs/dev-standing` outputs and runs `publish_site.sh`. That script sets the
type and cache header per file class:

| Object | Content-Type | Cache-Control |
|---|---|---|
| `index.html` | `text/html; charset=utf-8` | `no-cache` |
| `site.*.css` | `text/css; charset=utf-8` | `public, max-age=31536000, immutable` |
| `site.*.js` | `text/javascript; charset=utf-8` | `public, max-age=31536000, immutable` |
| `favicon.*.svg`, `img/*.svg` | `image/svg+xml` | `public, max-age=31536000, immutable` |

The stylesheet, the script and the images are uploaded before `index.html`. It
invalidates `/*` once, waits, then deletes only stale keys that match the
builder's hashed names (`cerberus_landing/publish.py`). `healthz.txt`,
`live.json` and anything under `terminal/` can never match, so they are never
deleted. It then checks the live URL. The owner fallback is
`make console-site-publish`; it writes to AWS, so it needs approval.

## Terminal (9.5)

The browser terminal at `/terminal/index.html` (ADR 0024 amendment, 2026-11-12;
plan `docs/plans/2026-11-12-terminal-panel.md`). It is a plain DOM terminal, not
xterm.js: `terminal.js`, `terminal.css`, an output log (`role="log"`, lines added
with `textContent` only) and one input. The CSP does not change.

- **Sign-in.** Authorization code with PKCE S256 on the Cognito hosted UI. The
  verifier, the state and the time live in one `sessionStorage` key during the
  redirect, at most 5 minutes. The access token lives in a module variable only.
  The ID and refresh tokens are discarded. A reload means a new sign-in.
- **Limits.** The hard limit is min(sign-in + 60 minutes, the token `exp`). The idle
  drop is 15 minutes. Both are checked on wall-clock time (every 15 seconds, on
  visibility and focus, and before each send). At a limit, or on Sign out, the page
  clears the token and goes to the Cognito `/logout`, so the hosted UI cookie does
  not sign the visitor back in. The idle drop is client-side only; the server
  enforces the 60 minutes through the JWT authorizer.
- **Commands.** `POST /api/command` with `{"argv": [...]}`. No client-side
  filtering: the server judges every line. `clear` is the only local command.
- **Config.** `terminal/config.json` (`client_id`, `auth_domain`) is written by the
  publish script from the `envs/dev-standing` outputs. It is not built and not in git.

```
make console-terminal            # build into console/terminal-dist (no AWS)
make console-terminal-preview    # http://127.0.0.1:8089/terminal/index.html, edge CSP
make console-terminal-publish    # AWS WRITE, needs approval (owner fallback)
node --check console/cerberus_terminal/static/terminal.js
node --check console/cerberus_landing/static/site.js
node --test console/tests/js/*.test.js
```

The preview shows "The terminal is not configured" unless you place your own
`config.json` in `console/terminal-dist/terminal/` (never commit one). A local
origin is not a registered callback URL, so a real sign-in works only live.

**Publish.** `.github/workflows/console-terminal.yml` runs on a push to main that
changes `console/cerberus_terminal/**`, `publish_terminal.sh` or itself. It has its
own concurrency group (`console-terminal-publish`). `publish_terminal.sh` uploads
under `terminal/` only:

| Object | Content-Type | Cache-Control |
|---|---|---|
| `terminal/index.html` | `text/html; charset=utf-8` | `no-cache` |
| `terminal/config.json` | `application/json` | `no-cache` |
| `terminal/terminal.<hash>.js` | `text/javascript; charset=utf-8` | `public, max-age=31536000, immutable` |
| `terminal/terminal.<hash>.css` | `text/css; charset=utf-8` | `public, max-age=31536000, immutable` |

It invalidates `/terminal/*` once, waits, then deletes only stale keys that match
`TERMINAL_MANAGED` (`cerberus_terminal/publish.py`), one by one. `index.html` and
`config.json` never match, so they are overwritten and never deleted. A test shows
the landing `MANAGED` and `TERMINAL_MANAGED` patterns do not overlap.

Tests: `tests/test_terminal_*.py` (build, determinism, CSP scan with negative
fixtures, stale-key safety, a static scan of `terminal.js`, parity with the ADR,
Terraform and the grammar) and `tests/js/terminal.test.js` (`node --test`:
tokenise, base64url, the RFC 7636 PKCE vector, state and age checks, the deadline
and the idle cut-over).

## Live session link: `live.json`

While a Grafana session runs, `terraform/envs/dev-console` writes `live.json` at
the root of the site bucket (not under a published prefix, so the page publish
never deletes it). `make console-session` creates it after the readiness probe
passes, and destroy deletes it first.

```json
{"schema":1,"url":"https://<session-distribution>/","home":"/d/cerberus-runs","started":"2026-11-12T10:00:00Z","ends":"2026-11-12T11:30:00Z"}
```

- `url` is the session's Grafana; `home` is the path of the recorded-runs
  dashboard on that host; `started` and `ends` are UTC, RFC 3339.
- Served with `Cache-Control: no-cache, max-age=0`.
- A reader (the landing page's `site.js`) must hide the link when `ends` is in
  the past, when `schema` is not 1, when the file is missing (403 through CloudFront, seen 2026-11-15;
  treat any non-200 as missing) or does not
  parse. A dead trap leaves a stale file, and `ends` is the only guard.
- `site.js` also requires `url` to be https and `home` to start with exactly one
  `/`. It labels the link "invited sign-in".
- The file holds no secret. It is never written to the repo.

## Live check harness

`cerberus_live_check/` runs the owner-run live checks (9.6 section 7 and 9.2 PR F)
with a script (plan `docs/plans/2026-11-15-live-check-harness.md`). It is
read-only, it is never deployed (the Lambda zip takes only `cerberus_console/`
and `runs/`), and it runs no program (ADR 0024 rule 5). It reads the expected
headers from `tests/test_edge_config.py` and the hostile lines from
`tests/hostile.py`. CI does not import Playwright.

Run order, with a session live:

1. Owner: enable `console-check` in Cognito (a write):
   `aws cognito-idp admin-enable-user ...`.
2. Owner, terminal 1: `make console-session MINUTES=30`. It rings the bell and
   reprints the URL every 5 minutes.
3. Claude or owner: `make console-wait` (waits for `live.json`, rings the bell,
   hides the URL), then `make console-verify-public` (no password).
4. Owner, terminal 2: `make console-verify`. It asks for the password with
   `getpass`, or reads `CERBERUS_CHECK_PASSWORD` from your own shell.
5. Claude: the `cerberus-live-verifier` agent reads the newest report and runs
   the read-only AWS and TLS follow-ups.
6. After the destroy: `make console-wait ARGS=--gone`, then `make console-check`.
7. Owner: disable `console-check` (`aws cognito-idp admin-disable-user ...`).

Who runs what:

| target | password | who |
|---|---|---|
| `make console-wait` | no | Claude or owner |
| `make console-verify-public` | no | Claude or owner |
| `make console-verify` | yes | owner only |

`make console-verify-public ARGS=--no-wait` skips the wait for a session. It
records `L1` as a fail when no session is live, and runs the header, 401/404,
CSP and TLS checks on the standing edge only.

Reports go to `console/live-check-reports/<UTC stamp>/` (gitignored):
`report.json` and `report.md` are redacted (hosts, account ID, pool ID, tokens,
UUIDs, OAuth values); the `*.png` screenshots are not redacted, and the harness
never takes one on a Cognito page. The harness refuses to write a report, and
exits 2 ("No report was written; the screenshots never show a Cognito page"),
if the password appears in it. There is no tracing, video or HAR.

Playwright 1.65.1 drives the headless shell found in `~/.cache/ms-playwright`
(`--chromium PATH` or `CERBERUS_CHROMIUM` overrides it).
