# Plan: Phases.md 9.6, the safety and live check

Status: accepted 2026-11-13 (option A). Carries out ADR 0024 build step 12
(`docs/adr/0024-demo-console.md`); no new ADR.

## 1. Question

9.6 has three parts: escape and injection tests for the command set in CI,
a demo from a clean browser, and a teardown to $0. What is still missing?
The code goes first; the live steps run later, in the same session as the
step 10 PR F Grafana check.

## 2. Facts (repo at 019925f)

**Grammar and API.**
- `console/tests/test_grammar.py` has 9 bad bodies (bad JSON, non-object,
  extra key, duplicate `argv`, more than 2048 bytes, None, int), bad base64,
  base64 of invalid UTF-8, JSON nested 1500 deep, and 37 bad argv cases
  (shell characters, space, `\n`, `\r`, NUL, `../`, `/etc/passwd`, upper
  case, fullwidth, RLO, zero-width, `-h`, `--json`, type confusion, more
  than 8 tokens, a 65-character token, wrong argument counts). Every
  refusal is byte-identical to `REFUSED`, and a probe token is never echoed.
- `grammar.py`: `_TOKEN` is an ASCII `fullmatch`, so all non-ASCII input is
  refused. No Unicode normalisation, which is correct (NFKC would turn
  fullwidth `ｓｔａｔｕｓ` into `status`). Run ids are looked up by exact
  dict key only; no path or query is built from them.
- `test_api.py` covers a hostile run record end to end, hostile Step
  Functions and Athena values, failures that do not leak exception text,
  and a non-dict event.
- The refusal JSON is 87 bytes; the 9.5 access log shows "400, 87 bytes"
  (`docs/plans/2026-11-12-terminal-panel.md` §7a).

**Sanitize.** `test_sanitize.py` has 10 hostile strings (CSI, OSC 52, OSC 8,
C1 `\x9b`, DEL, RLO, U+2028/2029, NUL, zero-width, 10k characters), the
caps, tab to space, the recursion and list cap in `clean_data`, and ARN
account redaction.

**Output size.** `len(to_json()) <= RESPONSE_BYTES` is checked only on real
records (`test_real_records.py`). No synthetic oversized `data` exercises
the cut-down branch in `api.py:_finish`.

**Terminal JS.** `test_terminal_js_scan.py` bans 21 APIs (`innerHTML`,
`outerHTML`, `insertAdjacentHTML`, `eval`, `localStorage`, `.style`, …);
output is written through `textContent` only. The two `location.assign`
targets are not pinned.

**CSP and headers.** The preview CSP is checked against the CSP string in
`terraform/modules/console_edge/main.tf`. Nothing pins the other headers
(HSTS, `nosniff`, `DENY`, `no-referrer`, `Permissions-Policy`) or that both
cache behaviours use the security policy.

**API, Cognito and IAM config.** No test pins: the single route
`POST /api/command` with JWT auth and `authorization_scopes = ["openid"]`,
the SPA client as audience, the throttle defaults 1 and 3, the timeout 25;
the Cognito client (`generate_secret = false`, flows `["code"]`, scopes
`["openid"]`, refresh-only `explicit_auth_flows`, admin-create-only); the
write grants of `cerberus-console-cli` (`athena:StartQueryExecution`,
`StopQueryExecution`, `s3:PutObject` and `AbortMultipartUpload` on the
results prefix only); the Lambda inline policy (logs only).

**Grafana module.** Annotation and home-dashboard escaping is tested for
`<script>`, `onerror`, markdown links, `javascript:` and newlines.
`md_escape` lets C0/C1 controls, bidi and zero-width characters through
(code reading, untested). `grafana_ini._BAD_VALUE` is a denylist.

**Tools.** `hypothesis` is not installed (`requirements-dev.txt`: ruff,
sqlfluff, pytest). `grafana-console-tests` runs Python 3.9 with pytest 8.

**Plan scope.** Plan step 12 (`docs/plans/2026-10-27-demo-console.md`)
lists `;`, `$( )`, backticks, newline, NUL, `../`, Unicode, long input,
type confusion, ANSI/OSC 52 — all already covered — plus an IAM deny check,
a clean-browser demo, teardown to $0 and a recorded short video.

## 3. Constraints

- No new standing resources; all new tests are offline (no AWS, no
  `terraform` binary). The edge is not changed.
- Consistent with ADR 0024 and its amendments (throttle 1/3, openid scope,
  DOM terminal with no client-side filter).
- The Grafana module tests stay Python 3.9 and stdlib + pytest 8.

## 4. Gaps

| # | Gap | Severity |
|---|---|---|
| G1 | No shared hostile corpus. Missing: lone surrogate (JSON escape and raw), BOM, `NaN`/`1e999`, combining marks, Kelvin sign and `ſ`, Cyrillic `ѕ`, Arabic-Indic digits, NEL U+0085, VT/FF, CRLF in a token, `%3B`, SQL `' OR 1=1--`, HTML; the multibyte >2048-byte branch and the exact 2048/2049 boundary. | real |
| G2 | No property or fuzz test. | real |
| G3 | No test of the response-size bound on huge synthetic `data`, or that deeply nested `data` becomes the fixed 503. | real |
| G4 | No test pins the edge headers, API, authorizer, throttle or Cognito client in Terraform. | real |
| G5 | The plan's IAM deny check has no static form. | real |
| G6 | The JS scan does not ban `srcdoc`, `DOMParser`, `createContextualFragment`, `window.open`, `postMessage`, `.href =`; `location.assign` targets are not pinned. | minor |
| G7 | `md_escape` lets controls and bidi through; the ini check is a denylist. Both inputs are owner-controlled. | minor |

## 5. Options

- **A (chosen): a seeded stdlib fuzz and a shared corpus.** No new
  dependency, deterministic, under 2 s, Python 3.9-compatible. Gives up
  hypothesis's shrinking and search; the grammar is a closed allowlist, so
  a hostile alphabet finds the same faults.
- B: add `hypothesis`. Better search, but a new pinned dependency, and a
  second pin for the 3.9 job.
- C: nothing more in code. Gives up G3–G5, which make the CI claim credible.

## 6. Build steps

**PR 9.6a + 9.6b: the safety suite and Grafana module hardening.**
- `console/tests/hostile.py`: `BODIES`, `ARGV`, `DATA_STRINGS` (the
  existing cases plus G1); `test_grammar.py` and `test_sanitize.py` import
  from it.
- `console/tests/test_hostile_corpus.py`: every corpus item through
  `parse_body` → `handle_body` → `lambda_handler` (full v2 event): status
  400, body bytes equal to the compact `REFUSED` JSON (87 bytes), headers
  exactly `content-type` and `cache-control: no-store`; `NOT_FOUND` and
  `UNAVAILABLE` fixed and input-free.
- `console/tests/test_fuzz.py`: `random.Random(96)`, about 3000 argv and
  1000 body cases from a hostile alphabet. Grammar: only `Refused` is
  raised; accepted commands are in `COMMANDS` with ASCII tokens; statuses
  in {200, 400, 404, 503}; every 400 is byte-identical. Sanitize: output in
  `[\x20-\x7e\n]*`, within the caps, idempotent. G3: `_finish` with 10k keys
  and long text stays within `RESPONSE_BYTES`; `data` nested 5000 deep
  gives the fixed 503.
- `console/tests/test_edge_config.py` (G4, G5): parses the Terraform text;
  expected values in one constant dict, shared with the live `curl -sI`
  check. Headers, CSP (no `unsafe`, `frame-ancestors 'none'`,
  `object-src 'none'`, `base-uri 'none'`), viewer protocols, the single JWT
  route with `openid`, no CORS, throttle 1/3 and timeout 25, the Cognito
  client, the `cerberus-console-cli` write set exactly
  {`athena:StartQueryExecution`, `athena:StopQueryExecution`,
  `s3:PutObject`, `s3:AbortMultipartUpload`} with `s3:PutObject` only on
  the results prefix, and the Lambda policy logs-only.
- `test_terminal_js_scan.py` (G6): ban the 6 patterns; pin
  `location.assign` targets.
- `observability/grafana/console/` (G7): `md_escape` replaces non-printable
  ASCII with `?`; `grafana_ini` checks values against an allowlist; tests.
- Verify: `pytest console`, `pytest observability/grafana/console` (3.9),
  ruff; the real dashboards build output is unchanged; local mutation
  spot-checks (not committed), each must fail the new tests: `fullmatch`
  → `match`; remove `frame_options`; add `s3:DeleteObject` to
  `console_roles`; echo `argv[0]` in `REFUSED`; remove the `_finish` try.

**PR 9.6c: the record (after the live run, docs only).** The Outcome
section here, the Phases.md 9.6 tick, a progress note under plan step 12.

## 7. Live check (owner-run, during the step 10 PR F session)

1. `make console-check` (all 0); `make console-session MINUTES=30`.
2. A private window with no extensions. Landing page loads without sign-in
   and with no CSP violations. `curl -sI https://<cf>/terminal/index.html`
   matches the `test_edge_config.py` constants.
3. `curl` `/api/command` with no token and with `Bearer x`: 401 for both.
   `curl -X GET` the same path: record the status (expected 404,
   unverified).
4. Terminal: sign in, run the 7 commands, paste `status; id`, `$(id)`,
   `<img src=x onerror=alert(1)>`, `ｓｔａｔｕｓ`, `sta​tus` (zero-width), a
   519-character line. Fixed refusal, no alert; access log `400` at 87
   bytes with a `sub` for each.
5. Grafana: PR F steps 1–7 (`docs/plans/2026-11-12-console-session.md` §6).
6. IAM deny check (read-only): `aws iam simulate-principal-policy` on
   `role/cerberus-console-cli` for `s3:PutObject` (gold),
   `s3:DeleteObject`, `glue:UpdateTable`, `states:StartExecution`,
   `athena:CreateWorkGroup`, `iam:PassRole`: all `implicitDeny`;
   `s3:PutObject` on the results prefix `allowed`.
7. Sign out of both; wait for the destroy; `make console-check` all 0;
   `live.json` gone.
8. Cost Explorer the next day.

**Record (9.6c):** date and build ids; the `console-tests` run with counts,
corpus size and fuzz seed; the header block and 401/404 results; access log
counts; the simulate table; `console-check` before and after; destroy
time; session cost and the next-day figure. No account ID or tokens
(redact ARNs to `<ACCOUNT_ID>`).

## 8. Open questions for the owner

1. Tick 9.6 after the PR F session on the current landing page, with a
   short clean-browser landing check added to 9.4's own verify? (suggested)
2. Keep the "recorded short video" of plan step 12, or replace it with the
   written record and screenshots?
