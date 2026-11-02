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
| `status`, gold freshness | one Athena query: at most the 10 MB minimum (about $0.00005) plus one S3 PUT |

Caches bound it: the execution list for 30 s, the freshness result for 300 s.

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
