# Plan: 9.5 the terminal panel in the browser (amendment to ADR 0024)

Date: 2026-11-12. Planner: Opus. Mode: decision (an amendment to ADR 0024, Accepted 2026-11-12). Branch `9.5-terminal-adr` for PR A. Base: `origin/main`.

User decision (2026-11-12): option B, a plain DOM terminal. The terminal is not xterm.js. Option A stays in section 4 as the rejected alternative.

Line numbers refer to `origin/main`. `<cf>` stands for the CloudFront domain name.

## 1. Question

How to build the browser terminal on the standing edge with PKCE sign-in, a 60-minute session and a 15-minute idle drop, keeping the strict CSP, publishing without colliding with the landing-page rebuild, and keeping $0 idle.

Why now: steps 6 and 7 (#128, #130) and the landing publish (#142) are live. A3 proved the token flow by hand on 2026-11-09. Step 9 is next.

## 2. Facts

Edge (`terraform/modules/console_edge/main.tf`):

- F1 (verified). The CSP is built at L149-162: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' <cognito>; form-action 'self' <cognito>; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; upgrade-insecure-requests`. There is no `font-src` (it falls back to `default-src 'self'`). The policy sits on the default (S3) behaviour and on `/api/*` (L213-232), so it covers `/terminal/*`. The live header on `healthz.txt` matches (curl, 2026-11-12). The comment at L146 says "9.5 may relax style-src for the terminal."
- F2 (verified). `callback_url` is `https://<cf>/terminal/index.html` and `logout_url` is `https://<cf>/` (L32-33). The live client `cerberus-console-spa` has exactly these (describe-user-pool-client, 2026-11-12).
- F3 (verified). Access, ID and refresh token validity are 60 minutes (L313-322, `variables.tf` L63-67). The live values are 60/60/60. The client uses the code flow, the `openid` scope, `ALLOW_REFRESH_TOKEN_AUTH` only, revocation on, `auth_session_validity` 3 and no secret. The JWT authorizer (L340-355) rejects an expired access token, so the server already enforces the 60-minute token. The code exchange still returns a 60-minute refresh token.
- F4 (verified). `POST /api/command` needs a JWT with scope `openid`. The stage throttle is 1 rps, burst 3 (L367-374). There is no CORS (same-origin `/api`, L333).
- F5 (verified 2026-11-12). Cognito `/oauth2/token` returns `access-control-allow-origin: https://<cf>` to a POST with that Origin (an invalid code gives 400). The browser can exchange the code by `fetch` under the current `connect-src`.
- F6 (verified). `GET /terminal/index.html` returns 403 today (no key; the OAC has no ListBucket).
- F7 (verified). A3 (standing-edge plan section 8 and section 13) proved PKCE S256 through the classic hosted UI, the access token through CloudFront, `runs` (17 rows), `status`, and `status; id` refused, on 2026-11-09.
- F8 (verified from [the AWS docs](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html); the cookie details are unverified). `prompt=login` works only with managed login branding, not the classic hosted UI. The hosted UI session cookie lets a visitor sign in again without a password until it expires. Unverified: the cookie lifetime (believed 1 hour), and whether `/logout` clears the classic cookie. Live step 7 checks this.
- F9 (verified, same doc). An authorization code is valid for 5 minutes.

Command API (`console/cerberus_console/`):

- F10 (verified). The response is `{ok, command, text, data}` or `{ok: false, error, text}`, with status 200, 400, 404 or 503 (`api.py` L20-31, L45-55). The `text` is already sanitised (rule 4). The refusal text is "Not an allowed command. Type help for the list." (`grammar.py` L15). The limits are 8 tokens, 64 characters each, and a 2,048-byte body (`config.py` L29-31).

Landing and publish:

- F11 (verified). In `publish.py` L4-17, `MANAGED` matches only `site.*.css`, `favicon.*.svg` and `img/*.svg`. The docstring says anything under `terminal/` is never stale. `console/tests/test_landing_publish.py` L15-21 protects `terminal/index.html` and `terminal/app.0123456789.js`. `publish_site.sh` uploads only its own files and invalidates `/*` (L36-76).
- F12 (verified). `page.py` L27-29 has `TERMINAL_HREF: str | None = None` ("Step 9.5 sets this"). `content.toml` L74-77 holds the `[terminal]` text. Both belong to the rebuild session.
- F13 (verified). The workflow `console-site.yml` uses the concurrency group `console-site-publish`, builds before credentials, and reads `console_site_bucket_name`, `console_distribution_id` and `console_url`. `dev-standing/outputs.tf` has `console_client_id`, `console_auth_domain` and `console_callback_url` (L146-163).
- F14 (verified). The landing CSP scanner is `build.py` `csp_problems`. The preview server keeps a CSP copy at `serve.py` L15-19, pinned by `test_landing_csp.py` L108-114.
- F15 (verified). The repo has no JS toolchain (no `package.json`, no committed `.js`). The `console-tests` CI job is Python only (`code-ci.yml` L64-79), with `console/**` in its paths. Unverified: that `ubuntu-latest` ships Node.

xterm.js (npm, 2026-11-12):

- F16 (verified). `@xterm/xterm` 6.0.0 (2025-12-22), MIT, no dependencies.
- F17 (verified in the 6.0.0 source). xterm.js creates `<style>` elements at run time: `src/browser/Viewport.ts:79`, `src/browser/renderer/dom/DomRenderer.ts:138` and `:158`, `src/vs/base/browser/dom.ts:971`. Under `style-src 'self'` they are blocked. A static S3 origin cannot send a per-response nonce, and the content is dynamic, so a hash fails. xterm.js would need `style-src 'unsafe-inline'` on `/terminal/*`.
- F18 (verified from the repo). Rule 4 (`sanitize.py`) strips every ANSI and control sequence on the server, so xterm's escape-sequence renderer would get no input.

## 3. Constraints

- $0 idle: static files plus existing pay-per-request resources.
- CI applies `dev-standing` only. The CI role has `cognito-idp:UpdateUserPoolClient` (`github_oidc/main.tf` L718).
- ADR 0024 text: "The terminal is xterm.js in the browser" (the "not a shell" intro); rule 4 names xterm.js; "Sign-in and sessions" says "a 60-minute token with no refresh in the SPA, and a 15-minute idle drop in the page"; the 2026-11-02 amendment keeps the classic hosted UI.
- No collision with the landing rebuild. Do not edit `console/cerberus_landing/**`, `console/publish_site.sh` or `.github/workflows/console-site.yml`.
- The public repo holds no tokens, client IDs or emails. The client ID reaches the page at publish time from Terraform outputs.

## 4. Options

A. xterm.js 6.0.0 vendored, plus a `/terminal/*` CSP with `style-src 'unsafe-inline'`. Rejected. It gives up a weaker CSP on the one page that holds a token. It adds about 489 KB of third-party code with version bumps. Its mobile input is weak, and screen readers need `screenReaderMode`. Its ANSI engine has nothing to render (F18).

B. A plain DOM terminal (chosen): own `terminal.js` and `terminal.css`, an output `<div role="log">` and one `<input>`. Lines are added with `textContent` only. History is in memory on up and down. Tab completes the 7 command names. The font is a monospace system stack. About 10 KB (estimate). No CSP change. It needs an ADR 0024 amendment. It gives up the xterm.js name and cursor-addressed terminal behaviour, which are unused: there is no PTY, one request per line, and plain text out.

Pillars:

- Security: B keeps `style-src 'self'` everywhere and has no third-party code on the token page.
- Operational Excellence: B has no vendor bumps.
- Performance: about 10 KB against about 496 KB.
- Cost and Reliability: equal.
- Audience (hiring managers and non-engineers, some on phones): B works with native input and accessibility tools.

## 5. Decision (B) and session and token rules

- Sign-in: authorization code with PKCE S256 and a 16-byte random state. The verifier, the state and the creation time go in ONE `sessionStorage` key, during the redirect only. On return, read and delete that key first. Reject the callback if the state differs or the key is older than 5 minutes (F9). `history.replaceState` drops `?code=`.
- Tokens: the access token lives in memory only (a module variable). The ID and refresh tokens are discarded at once, never stored and never refreshed. A reload means a new sign-in. The token does not go in `sessionStorage`: that gives no gain against XSS and it outlives the tab session.
- Limits: the hard deadline is min(sign-in + 60 minutes, access-token `exp`). The `exp` is decoded for the timer only and is not trusted for auth; the server enforces the same 60 minutes (F3). The idle drop is 15 minutes without a keypress or command. Both are checked on wall-clock time: an interval, `visibilitychange` and focus events, and before each send. A status line shows the minutes left.
- Ending (idle or limit): clear the token and disable the input. Set `sessionStorage['cerberus-ended']` to `idle` or `limit`. Navigate to `<auth>/logout?client_id=...&logout_uri=<origin>/terminal/index.html`. On load, show "Session ended (15 minutes idle / 60-minute limit). Sign in again." The logout is required: otherwise the classic UI cookie signs the visitor back in without a password (F8). It needs one new registered logout URL (PR B). A "Sign out" button does the same.
- Commands: `POST /api/command` with `{"argv": input.trim().split(/\s+/)}`, a Bearer token, a 30 s `AbortController`, and one request in flight. There is no client-side filtering of hostile input: the server is the only judge. `maxlength` 519 (8*64+7) is for usability only. Render `body.text` with `textContent`. Local messages: 401 "Session expired. Sign in again."; 429 "Too many commands. Wait a second."; non-JSON or other "Not available right now." The only local command is `clear`; `help` goes to the server.
- Runtime config: `terminal/config.json` = `{"client_id", "auth_domain"}`, written by the publish script from Terraform outputs after the build (build before credentials; the client ID is not in git). Redirect and logout URIs come from `location.origin`. The JS validates `auth_domain` against `^https://[a-z0-9-]+\.auth\.us-east-1\.amazoncognito\.com$` and `client_id` against `^[a-z0-9]{1,128}$`. Otherwise it shows a fixed error.
- Publish: a separate package `console/cerberus_terminal/` builds to `console/terminal-dist/terminal/{index.html, terminal.<10hex>.js, terminal.<10hex>.css}`. `TERMINAL_MANAGED` is `^terminal/terminal\.[0-9a-f]{10}\.(js|css)$`. `index.html` and `config.json` never match (they are overwritten, never deleted). The landing `MANAGED` already ignores `terminal/` (F11), and a test proves the two patterns are disjoint. The terminal has its own workflow with its own concurrency group `console-terminal-publish` (sharing `console-site-publish` could drop a pending run). It invalidates `/terminal/*` only.
- Phases.md: 9.5 is checked off with the terminal alone. The Grafana clause moves to 9.2, which owns `envs/dev-console` and `make console-session` (the demo-console plan L289 maps step 10 to "9.2 and 9.4"). 9.5 reads "The terminal panel wired to the command set in the browser, with a session time limit (a 60-minute token and a 15-minute idle drop)". 9.2 gets "; the Grafana session self-terminates and is destroyed at its limit" appended.

## 6. ADR 0024 amendment (2026-11-12): a plain DOM terminal instead of xterm.js

Status Proposed in PR A (#149); accepted by the user 2026-11-12. Same form as the 2026-11-02 amendment. One pointer line in the Status block. No new ADR number.

- Context: F17 and F18. The token page is the most sensitive page. The audience is non-engineers, some on mobile.
- Decision: same-origin `terminal.js` and `terminal.css`, an output log (`textContent` only) and one input. The CSP stays unchanged. The amendment changes the text "The terminal is xterm.js in the browser" and rule 4's "into xterm.js" (now "into the page"), without rewriting the original Decision. Rule 4 itself stays. It states the section 5 session rules: a memory-only token, ID and refresh tokens discarded, Cognito `/logout` at the drop, and one more registered logout URL.
- Consequences. Good: a strict CSP on every page, no third-party code, about 10 KB, and mobile and screen readers work. Given up: the xterm.js name; no cursor-level terminal (unused); the idle drop is client-side only, so a copied token still works up to its 60-minute `exp` (it cannot be refreshed). Revisit if: the server ever sends styled or ANSI output, or a PTY returns. Also: if live step 7 shows the classic hosted UI cookie survives `/logout`, accept and document it (cookie about 1 hour), or wait for managed login with `prompt=login` (AWS provider 6.x, the 2026-11-02 amendment "Revisit if").

## 7. Build steps

PR A, docs (branch `9.5-terminal-adr`): this plan, the amendment, and the Phases.md 9.5 and 9.2 wording. Merging Phases.md republishes the landing page (harmless). Verify: Opus review; the user accepts; the status flips to Accepted.

PR B, Terraform `dev-standing`, CI-applied (branch `9.5-terminal-logout`). Merge before PR C.
- In `console_edge/main.tf`, add the local `logout_terminal_url = "https://${...domain_name}/terminal/index.html"` and set `logout_urls = [local.logout_url, local.logout_terminal_url]`.
- Update the L146 comment (no `style-src` relaxation now).
- Optional output `console_logout_terminal_url`.
- Verify: `terraform fmt`; the CI plan shows only an in-place update of `aws_cognito_user_pool_client.spa` (`logout_urls` +1) plus the Faker churn; after apply, describe-user-pool-client shows 2 LogoutURLs.

PR C, terminal page (branch `9.5-terminal-panel`):
- New package `console/cerberus_terminal/`: `__init__`; `__main__` with `build --out` and `stale --dir`; `build.py` (deterministic, 10-hex content hashes, a `cerberus-build` meta tag of 64 hex, its own CSP scanner); `publish.py` with `TERMINAL_MANAGED`, `local_keys`, `stale_keys`; `serve.py` (a 127.0.0.1 preview with the edge CSP).
- Static files: `index.html.tmpl`, `terminal.js`, `terminal.css`. In `terminal.js`, pure functions are exported behind `if (typeof module !== "undefined")`: `tokenise`, `base64url`, the PKCE challenge, `deadline()`, `idleExpired()` and `parseCallback()`. `start()` runs only when `document` exists.
- `console/publish_terminal.sh DIR BUCKET DIST URL CLIENT_ID AUTH_DOMAIN`:
  - Upload the JS (`text/javascript; charset=utf-8`) and CSS (`text/css; charset=utf-8`) as immutable.
  - Upload `config.json` (`application/json`, no-cache).
  - Upload `index.html` last (no-cache).
  - Invalidate `/terminal/*` and wait.
  - Delete stale keys via `python3 -m cerberus_terminal stale`.
  - Curl checks: index 200, CSP present, build meta matches, JS immutable with the JS content type, `config.json` 200.
  - Never echo the bucket name; never mirror or bulk-delete.
- `.github/workflows/console-terminal.yml`: a copy of `console-site.yml`; paths `console/cerberus_terminal/**`, `console/publish_terminal.sh` and itself; group `console-terminal-publish`; it also reads `console_client_id` and `console_auth_domain`.
- Append-only edits: `Makefile` (`console-terminal`, `console-terminal-preview`, `console-terminal-publish` [AWS WRITE]), `.gitignore` (`console/terminal-dist/`), `console/README.md` (a new section at the end), and `code-ci.yml` console-tests step `node --check ... && node --test console/tests/js/` using the runner's Node, with no npm and no setup-node (drop the step if there is no Node).
- Tests (`console/tests/test_terminal_*.py`):
  - The built `index.html` has no inline script, inline style, `on*` attribute, `style=` or `javascript:`.
  - Built keys match `TERMINAL_MANAGED`, except `index.html`.
  - `stale_keys` never returns `index.html`, `healthz.txt`, `live.json`, `terminal/index.html`, `terminal/config.json` or landing keys.
  - Landing `MANAGED` and `TERMINAL_MANAGED` are disjoint.
  - A static scan of `terminal.js` finds no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`, `localStorage`, `setAttribute("style"`, stored `refresh_token`, or `fetch` to anything other than `/api/command` and the token endpoint. `sessionStorage` is used only for the PKCE key and `cerberus-ended`.
  - Parity: `IDLE_MS` and `LIMIT_MS` against the ADR and `token_validity_minutes` in `variables.tf`; the command list against `grammar.COMMANDS`; `maxlength` against the config.
  - The build is deterministic.
  - The preview CSP equals the edge CSP minus `upgrade-insecure-requests`.
- `console/tests/js/terminal.test.js` (node:test): `tokenise`; `base64url` without padding; the RFC 7636 appendix B PKCE vector; a state mismatch; a callback older than 5 minutes; the deadline as min(60 minutes, `exp`); the idle cut-over at 15 minutes.
- Verify: pytest on `console`; ruff; the node step green; the local preview shows no CSP errors; after merge, the `console-terminal` workflow and its curl checks pass.

PR D, landing link: not part of 9.5. Tell the rebuild session that the target is `terminal/index.html` (`TERMINAL_HREF` and the `[terminal]` text). If the rebuild merged without it, a one-line follow-up PR.

PR E, docs: record the live check, check off 9.5, add the checkpoint note, and add a step 9 progress note to the demo-console plan.

Live check (the user, after PR B is applied and PR C is published). First enable `console-check` with `admin-enable-user` (a Cognito write, needs approval):

1. In a private window, open `https://<cf>/terminal/index.html`. Expect a Sign in button and no CSP violations in DevTools.
2. Sign in as `console-check` on the classic hosted UI. The page loads with no `?code=` and a status line of about 60 minutes.
3. In DevTools > Application, `sessionStorage` and `localStorage` are empty and there are no cookies on the CloudFront origin.
4. `help`, `status`, `runs`, `run <id from runs>`, `cost`, `dq` and `slo` each print text. Note how long `status` takes.
5. `status; id`, `$(id)`, a backtick `id`, `run ../../etc/passwd`, `<img src=x onerror=alert(1)>` and a 600-character paste each print exactly "Not an allowed command. Type help for the list.", with no alert and no rendered HTML.
6. Press Enter 6 times fast. At most "Wait a second" appears, and no error page.
7. Idle for 15 minutes. The page goes to the Cognito logout and returns with "Session ended (15 minutes idle)". Sign in again: the hosted UI must ask for the password. This proves the cookie was cleared (F8).
8. Optional, the 60-minute limit (one command every 10 minutes): a command after `exp` gets 401 in the access log.
9. Run `aws logs filter-log-events --log-group-name /aws/apigateway/cerberus-console-api --limit 50 | jq -r '.events[].message|fromjson|[.status,(.sub|length>0)]|@tsv'`. Expect 200 and 400 lines with `true`.
10. `admin-disable-user console-check` (a write, needs approval).

## 8. Cost

Idle $0; an estimated 20 KB of static objects. The cost per command is unchanged (about $0.000003, standing-edge plan section 10). Each terminal publish uses one invalidation path, inside the 1,000 free paths a month.

## 9. Risks

1. The hosted UI cookie survives `/logout` (F8, unverified). Then live step 7 fails and the limits are soft. Accept and document it (about 1 hour), or wait for managed login with `prompt=login` (provider 6.x).
2. Background-tab timers are slowed. Wall-clock checks run on `visibilitychange` and before each send, and the JS tests cover the deadline logic.
3. A wrong JS content type with `nosniff` blocks the script. The publish script sets the types explicitly and checks after upload.
4. The logout URI must exactly match a registered URL. PR B is applied before PR C publishes, and live step 7 tests it.
5. The throttle is 1 rps, burst 3. The page keeps one request in flight and shows a 429 message.
6. The idle drop is client-only. A copied token stays valid until `exp` (at most 60 minutes) and cannot be refreshed. The amendment accepts this.
7. Collision with the rebuild. Shared files are `Makefile`, `.gitignore`, `console/README.md` and `code-ci.yml` (all append-only). Tell the rebuild session that PR B touches `logout_urls`.
8. Node on the runner is unverified. Drop the node step if it is missing; the Python static checks still run.
