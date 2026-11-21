# Showcase snapshot

The sanitised numbers that the public page and the Databricks Free Edition
tables read (ADR 0027 Decisions 3 and 4, ADR 0028). Built by step 11.2a.

Every value here is public data that is already in git: the run records in
`observability/scale/runs/`, the named query set, and `docs/slo.md`. Nothing is
read from AWS, and the builder has no credentials.

The site build does **not** publish these files yet. `console-site.yml` only
lists `observability/showcase/**` in its paths filter, so a change here starts
the site build. Publishing to the standing edge happens in step 15.2.

## Files

Each file has `schema_version` (1), `generated_from` (repo-relative paths and
git blob SHAs, computed as `git hash-object` does) and `generated_at`. There is
no clock in the build: `generated_at` is the newest run `end` (UTC), so two
builds of the same inputs give the same bytes.

| File | What it holds |
|---|---|
| `runs.json` | One entry per run record, newest first, and a `dropped` count with fixed reasons. |
| `status.json` | The values of the 17 entries of `observability/queries/status.json` for the newest run, with each entry's `label`. |
| `slo.json` | Objective 1 of `docs/slo.md` (pipeline success) over the newest 20 terminal runs: share succeeded and `error_budget_used`. |
| `comparison.json` | Only when `comparison-input.json` exists (see below). |

`runs.json` fields: `execution`, `kind` (`exercise`, `demo` or `rehearsal`),
`status`, `start`, `end`, `run_seconds`, `events_processed`, `events_per_second`,
`dq_passed`, `dq_errors`, `dq_warnings`, `cost_usd`, `cost_usd_per_million_events`,
`cost_estimated`, and `steps` (`state` and `seconds` for the four fixed states of
`console/cerberus_landing/runs.py`). A value that is unknown is `null`. A cost is
`null` when the record says the cost is not final.

A record is dropped, and counted, when its execution name does not match the
console grammar token, holds a 12-digit run, has an unknown kind, status or
timestamp, repeats an execution, has a field of the wrong type, or lies past the
file cap of `console/cerberus_console/config.py` (`over_file_cap`). The file name
and the text of a dropped record are never written.

`status.json` is made by `observability/status/series.py`, the same code that
`publish.py` uses to write the status series. The 30-day and 90-day windows end
at the newest run end, not at the clock. `observability/status/test_e2e.py`
checks that these values equal the query results from a local Prometheus
(`make status-e2e`, offline).

`error_budget_used` is a multiple of the budget (1.0 = exactly used, above 1.0 =
overspent); the page must show the window and the context, not only the number.

The 30-day and 90-day windows end at the newest run's end, so "90 days" means
"90 days up to `generated_at`". A live AMP query moves with the clock and
diverges from this file as time passes. A page or a dashboard that shows these
values must label the window, for example "90 days to 8 Nov 2026".

A run record exists only after a run has ended. While a run is in progress, AMP
already shows it (its start series is written at the start) and this snapshot
does not. That is a real difference, not a fault.

## Redaction gate (fail-closed)

Before any file is written, every output string must match its field allowlist
(an enum or a token pattern). No string may hold `arn:`, `s3://`,
`amazonaws.com`, `cloudfront.net`, `@`, or a run of 12 digits. Numbers are JSON
numbers, so byte counts do not trip the 12-digit rule. The one exception is the
`generated_from[n].sha` field, which must be exactly 40 hex characters. A failure names the file,
the rule and the path (never the value), exits 1, and leaves the previous files
as they were. The files are written to a temporary name and renamed.

`scan_text(text, account_id=None)` in `console/cerberus_landing/showcase.py`
reports the forbidden fragments and, when an account ID is given, an exact match
of it. CI or the publish script can call it. No AWS call is made here.

## Optional comparison input

`comparison.json` needs a measured record from step 11.5, so the builder omits it
until `observability/showcase/comparison-input.json` exists (or
`--comparison-input FILE` is given). No file is committed now, and nothing is
invented. The input is one JSON object with exactly these fields, and the output
copies them:

- `step`: one of the Task state names in the state machine.
- `input`: `run_id` (a grammar token) and `events` (a whole number).
- `measured_on`: a date, `YYYY-MM-DD`.
- `trial`: `true`.
- `engines`: `cerberus` and `databricks`, each with `run_seconds`, `usd`,
  `usd_per_million_events` (numbers), `cost_source` (`run_record` or
  `databricks_billing`) and `estimated` (true or false).
- `caveats`: a list of fixed IDs, lower case with underscores, for the page text.

The engine layout is this step's reading of ADR 0027 Decision 7. Step 11.5 may
amend it. If the input is removed, the next build removes `comparison.json`.

## Regenerate

```
make showcase-snapshot   # write the files
make showcase-check      # fail if the committed files are stale
```

Run `make showcase-snapshot` after a new run record is merged, and commit the
result.
