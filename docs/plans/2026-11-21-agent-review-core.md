# Plan 14.2: review core, tool registry, stdio MCP server

## Goal
Add `agents/cerberus_agents/`. It mirrors `console/` (plan 2026-11-08 step 1, L204). It holds:
- A model-free review core.
- A tool registry on the 9.3 command set.
- A stdlib stdio MCP server.

It runs offline, uses no AWS and no model, and stays $0 (ADR 0025 decisions 1, 4).

## Facts
- The 9.3 handlers return `(data, text)` (`console/cerberus_console/commands.py` L600-612). Grammar is a fixed allowlist: 7 commands, token regex, max 8 tokens (`grammar.py`). `sanitize.py` allows printable ASCII only, masks 12+ digit runs inside ARNs, and caps fields (200 chars), rows (50) and text (16 KiB) (`config.py`).
- `queries.py` loads the 17 named queries in `observability/queries/status.json` and lints them. The ADR 0021 amendment of 2026-11-12 says agents read queries by name only.
- `observability/status/series.py` has `end_series(record)` and `failed_step(record)`. They turn a run record into the AMP status values offline. The review core can reuse them, so it needs no AMP call and cannot drift from the alert inputs.
- 17 records in `observability/scale/runs/`. There are 2 FAILED:
  - `exercise-20261008T085728Z`: DQ errors 2, RunDbt 341 s, no RunServingQuery.
  - `exercise-20261009T101830Z`: DQ errors 0, RunDbt 381.5 s.
- Two things drive the cost rule:
  - `usd_per_million_events` spans 0.0037 to 34.3, so the baseline must be same-scale.
  - `exercise-20261012T075045Z` is a slow-step case: 538.5 s in RunDbt, against about 106-144 s for the 6k-event runs.
- `console/ruff.toml` adds `S` rules and bans subprocess and pickle. CI job `console-tests` runs `pytest console`. `orchestration/verify.sh` L38 runs the console tests, and `make verify` calls it.
- Unverified: whether `agents/` on `sys.path` can import `cerberus_console`. Check `console/conftest.py` and the `uv` invocations.

## Steps
**PR 1: review core (14.2a).** Files: `agents/cerberus_agents/{__init__,review,evidence,baselines}.py`, `agents/tests/`, `agents/ruff.toml` (extends `console/ruff.toml`), and the `verify.sh` and CI wiring.
- Input: one record, the others as baseline, and `series.end_series` values.
- Output: a review object `{execution, scale_class, findings[], evidence[]}`. Each finding has an `id`, a `rule` and an evidence id. Evidence holds allowlisted tokens (step names, rule names, check names) and numbers only. No free text from records goes through.
- Rules, each with a fixed threshold constant:
  1. `run_failed`: status is not SUCCEEDED, and `failed_step` (from `series.py`).
  2. `dq_errors`: `data_quality.errors > 0`, with the failing check names. Allowlist the names by pattern.
  3. `dq_missing`: no `data_quality` block (the suite was added in 8.4).
  4. `step_slow`: the step's seconds are over 1.5x the median of the same scale class. The scale class comes from `events_processed` buckets (about 6k, 1M, 9M, 100M). Skip when fewer than 3 peers exist.
  5. `cost_outlier`: `usd_per_million_events` over 2x the median of the same scale class.
  6. `athena_queue`: a step's `queue_seconds` is over a fixed limit.
  7. `headroom`: `bytes_scanned` at 80% or more of the cutoff (ADR 0023 values: dbt 25 GiB, DQ 20 GiB). Unverified: pull the constants from ADR 0023.
  8. `never_reported`: no run in the last N days, and `cost_missing`.
- The thresholds are proposals. The 14.3 eval scores them. The core is deterministic: same input, same bytes (sorted keys, no clock reads).
- Acceptance: golden JSON for all 17 records in `agents/tests/golden/`. A `--update` flag must be explicit. The run is repeatable, and the 2 FAILED records yield `run_failed`.

**PR 2: tool registry (14.2b-i).** Files: `agents/cerberus_agents/registry.py`, `tools.py`, tests.
- Tools: `status`, `runs`, `run`, `cost`, `dq`, `slo` (the `help` command is not a tool), `review` (takes a run id or `latest`), `queries_list` (names and meanings), and `query` (named). Each tool has a JSON-Schema input.
- Inputs are validated by `grammar._TOKEN` and the command allowlist, by reusing `parse_argv`.
- Query names are checked against the `queries.py` entry set. They are never free text.
- `query` runs only through an injected reader (Protocol). The default reader is "unavailable". The AMP reader needs the ops role and belongs to the IAM step (plan step 3), not here.
- Every output goes through `sanitize.clean_data` and `clean_text`. Add a response cap (`RESPONSE_BYTES`, 64 KiB), plus a per-tool token budget constant.
- Errors are one fixed text, as in the console.
- No new tool reaches the console API.
- Acceptance: the tool list is identical in-process and over MCP. A tool-input hostile corpus passes (see Tests).
- **Built 2026-11-21 (14.2b):** `registry.py` (Tool, Registry, `RESPONSE_BYTES` 65536, `CALL_BUDGET` 100) and `tools.py` (the 9 tools, `QueryReader` Protocol, default reader "unavailable"). Records are rebuilt from allowlisted fields before the console handlers run, so a check `detail` or other free text never reaches an output. Offline, `status` and `run` show their AWS sections as "unavailable"; `run` with an id not in the records gives the fixed unavailable text. Errors are the console's three fixed texts plus one fixed budget text.

**PR 3: MCP stdio server (14.2b-ii).** Files: `agents/cerberus_agents/mcp_server.py`, `__main__.py`, `Makefile` target `mcp`, tests.
- Stdlib JSON-RPC 2.0, newline-delimited, over stdin and stdout. Methods: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`.
- Unknown method returns -32601. A bad request returns -32600 or -32602 with fixed text. Cap one line at 64 KiB. No echo of input.
- Logs go to stderr only.
- `make mcp` runs `python -m cerberus_agents.mcp_server --runs-dir ...`. Offline is the default: it reads `observability/scale/runs/*.json` through `records.load`. The `observability/showcase/*.json` files are derived from those records, so the server does not read them.
- AWS (`status`, `run` detail) works only with `--aws`, and the owner runs that. It assumes `cerberus-console-cli` through `aws.assumed_session`. Until the ops role exists, the server offers no new AWS tool.
- Acceptance: a scripted handshake test drives `initialize`, `tools/list` and `tools/call` through a subprocess pipe. Ruff `S` bans subprocess in the package, so run that test from `agents/tests` with a per-file ignore, or call `serve(stdin, stdout)` directly. Recommend the direct call.

## Tests
- Hostile corpus: reuse `console/tests/hostile.py` as tool-argument cases (`ARGV` and `DATA_STRINGS`). Every case must give the fixed refusal or sanitised ASCII.
- Add injection strings to run-record fixtures (an instruction in a check `detail`). The review output must hold none of the text.
- Fuzz the tool arguments as `test_fuzz.py` does, with a deterministic seed.
- The ARN and account-number scan covers every golden file.
- Add `test_banned_calls`-style checks for `agents/`.

## Verify
`make verify` after wiring `agents/tests` into `orchestration/verify.sh` and the `console-tests` CI job. Also run `ruff check` and `ruff format --check`, then `python -m cerberus_agents.mcp_server` against a scripted stdin.

## Plugs into later steps
- 14.3 (eval) feeds the same review objects to the scorer. Labelled incident fixtures use `evidence ids`, so cited-claim validity is checkable. The core gives the "found / not found" label for the generator-commit case: no finding means "not found".
- 14.4 consumes `review()` plus the registry in the Converse loop and the validator. It writes `observability/scale/reviews/<id>.json` and `.md`, posts the `cerberus-ai` annotation, and fills the AI panel. 14.2 builds none of these.

## Owner steps
None for 14.2. The IAM step, Bedrock model access and the first apply come later (plan steps 3 to 4).

## Risks and unverified
- Thresholds, scale buckets and headroom constants are proposals until 14.3.
- Python 3.12 with `sys.path` across `agents/` and `console/` is unverified.
- Small baselines: only 17 records, 6 at about 6k events.
- The 2 untracked rehearsal records in the ADR 0025 text are now tracked. The count there (16) is out of date.
- MCP spec revision and client compatibility are unverified. Check one real client (Claude Code) by hand.
- **Known limit (review of 2026-11-21):** the output allowlist accepts any token that matches its pattern. A check named `ignore_all_previous_instructions` (64 characters or fewer) or an execution named `IGNORE-ALL-PREVIOUS-INSTRUCTIONS` would pass. Before 14.4 feeds a review to a model, restrict check names to a list of known names.
- **Narrowed 2026-11-21 (review of 14.2b):** execution names in any output must match the committed shape (kind exercise, demo or rehearsal, up to 3 segments of 1 to 8 characters, then the UTC stamp) and check names must be in `KNOWN_CHECKS` in `evidence.py` (else `unknown_check` in the tools, skipped in the review core). A new check name must be added to that constant. Cost service keys must start with Amazon or AWS or be in `_OTHER_SERVICES` in `tools.py`; hidden keys show as a count. Residual: short tokens within the shape can still carry words. This is accepted, because the tools take named input only, the role is read-only and a human approves each action (ADR 0025).
- **Built 2026-11-21 (14.2a):** the `headroom` rule was dropped (a record holds bytes summed over all queries of a step, so a successful 100M run would trigger it) and `never_reported` was dropped (it needs a clock). `record_invalid` was added. `ATHENA_QUEUE_LIMIT_SECONDS`, the scale-class bounds and the two factors are proposals that 14.3 scores.

## Owner answers (2026-11-21)
1. MCP implementation: stdlib, no SDK, as recommended.
2. Package location: `agents/cerberus_agents/`, with its own `ruff.toml` that extends `console/ruff.toml`, as recommended.
3. `help` is not a tool, as recommended.

Decision text (Accepted): `docs/adr/0025-ai-operations-agents.md`, `docs/plans/2026-11-08-ai-operations-agents.md`.
