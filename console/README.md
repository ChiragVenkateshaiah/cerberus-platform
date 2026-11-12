# Console command set (ADR 0024)

The read-only commands behind `cerberus` on the console site: `status`, `runs`,
`run <id>`, `cost`, `dq`, `slo` and `help`. One package, two entry points:

- The local CLI: `make cerberus CMD="status"` (also `CMD="--json run latest"`).
  It assumes `cerberus-console-cli` with your `cerberus-admin` profile and runs
  the same code as the Lambda. Phase 10's `make status` reuses it (ADR 0021).
- `cerberus_console.api.lambda_handler`, for the console site's Lambda (step 7).

It is not a shell. It has no shell, no write and no free text: a request is
either exactly an allowed command or it is refused.

## Commands

| Command | Arguments | Reads |
|---|---|---|
| `help` | none, or one command name | nothing |
| `status` | none | Step Functions, one Athena query on gold, the newest record |
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
```

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

## Landing page

`cerberus_landing/` builds the public landing page for the console site (ADR 0024,
step 8): one `index.html`, one stylesheet, a favicon, the hand-drawn architecture
diagram and, when they exist, the scale charts. It is stdlib Python and ships no
JavaScript, no inline style and no inline handler, so it passes the edge CSP as is.
It reads the run records through `cerberus_console.records`, so its "latest run"
is the same record as `cerberus run latest`. Phase status comes from `Phases.md`
and the plain-language text from `cerberus_landing/content.toml`.

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

**Publish.** `.github/workflows/console-site.yml` runs on a push to main that
changes the page's inputs (and on manual dispatch). It builds the site, assumes
`cerberus-ci-apply`, reads the bucket, distribution and URL from the
`envs/dev-standing` outputs and runs `publish_site.sh`. That script sets the
type and cache header per file class:

| Object | Content-Type | Cache-Control |
|---|---|---|
| `index.html` | `text/html; charset=utf-8` | `no-cache` |
| `site.*.css` | `text/css; charset=utf-8` | `public, max-age=31536000, immutable` |
| `favicon.*.svg`, `img/*.svg` | `image/svg+xml` | `public, max-age=31536000, immutable` |

It invalidates `/*` once, waits, then deletes only stale keys that match the
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
- A reader (the landing page's `live.js`) must hide the link when `ends` is in
  the past, when `schema` is not 1, when the file is missing (404) or does not
  parse. A dead trap leaves a stale file, and `ends` is the only guard.
- The file holds no secret. It is never written to the repo.
