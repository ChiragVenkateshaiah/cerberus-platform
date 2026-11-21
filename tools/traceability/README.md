# Platform-development traceability (ADR 0029, step 16.2)

A generator that links each subtask in [Phases.md](../../Phases.md) to its ADR,
plan, PR and run record, and a CI check that fails on a dangling link. Python
standard library only. No AWS, no network, no GitHub API, no token.

```
python tools/traceability/generate.py                   # write the outputs
python tools/traceability/generate.py --check           # CI: stale or dangling fails
python tools/traceability/generate.py --write-baseline  # once, at the cut-off
make traceability / make traceability-check
```

## Outputs

| File | What |
| --- | --- |
| `observability/showcase/history.json` | `schema_version` 1: `phases`, `subtasks`, `adrs`, `prs` |
| `docs/traceability.md` | the human table, phase by phase, with the legend and the cut-off note |
| `observability/showcase/traceability-baseline.json` | the cut-off baseline (below) |

`history.json` goes in `observability/showcase/` as ADR 0029 asks (the site and
dashboard steps 15.3 and 16.3 read it there). Both generated files are
deterministic: the same inputs give the same bytes. `generated_at` is an ISO-8601
UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`, like the 11.2a files) taken from the commit
time of the newest **merged** PR row. PR rows carry `number`, `title`, `date`
(UTC) and `merge`; a PR that is named but not merged is `{"number": N, "pending": true}`.

`history.json` is the contract for Phase 15 (the public site) and the Databricks
"how it was built" dashboard (11.2c, 16.3). Change its shape only with
`schema_version`.

`observability/showcase/` is shared with PR #177 (11.2a). After both merge, the
11.2a README in that directory must list `history.json` and
`traceability-baseline.json`.

## Where each link comes from

- **PR**: GitHub's merge commit. This depends on the merge method: squash or
  rebase merges leave no `Merge pull request #N` commit, so those PRs are
  invisible (they would stay pending). Revisit if the merge method changes. `git log --merges` gives
  `Merge pull request #N from <owner>/<branch>`, and the PR title in the body.
  Only the number, title, date and short merge hash are kept; the owner and
  branch never leave the parser. Other merge commits are ignored.
- **Subtask title**: the first line, plus wrapped lines until a sentence ends or a
  note starts (a bullet, `ADR NNNN Accepted`, `Done`, `Progress`, `Plan`, a date, or
  `(#`); capped at 140 characters at a word boundary.
- **Subtask links**: read from the subtask line and its indented notes in
  Phases.md: `#NNN` PR numbers, `ADR NNNN` (and `docs/adr/NNNN-...`), `docs/plans/...md`
  paths, and run-record `execution` names that match a file in
  `observability/scale/runs/`.
- **ADR**: number and title from the file, status and accepted date from the
  Status line. The ADR's plan is the `docs/plans/` file that **the ADR itself** links.
  A plan that only mentions the ADR does not count (that guessed wrong facts). A new
  ADR must link its plan; an old one with no link shows `none (before traceability)`.
- Not extracted: dashboard panels (no stable text in the notes to read them
  from) and Well-Architected milestones. A run record that no note names is
  counted in a report-only line; it does not fail.

## The cut-off (ADR 0029 Decision 2)

The dangling-link check applies only to subtasks checked, and ADRs accepted, on
or after the date ADR 0029 was accepted (read from its Status line,
2026-11-20). To know which items were done before, without parsing history, the
generator uses a committed baseline: `traceability-baseline.json` lists the
subtasks checked and the ADRs accepted at that date. Items in it are `legacy`:
they show `none (before traceability)` for a missing link and never fail.
Guards: `--write-baseline` refuses if the file exists (there is no force flag; delete
the file by hand if it must ever be redone); the file's SHA-256 is pinned as
`BASELINE_SHA256` in `generate.py`, so an edit shows as a code change in review; and
`--check` fails if the baseline `cutoff` differs from the ADR 0029 acceptance date.

**A new subtask checked (`[x]`) after the baseline must cite at least one PR
number (`#NNN`; a PR that is not merged yet counts).** Name an ADR or a plan if it has one. A new Accepted ADR
needs a plan link. Do not regenerate the baseline to silence a failure.

## The checks (named messages, no secrets)

- `subtask N.M: checked after the baseline with no PR reference`
- `subtask N.M: ADR NNNN has no file in docs/adr`
- `subtask N.M: plan docs/plans/... does not exist`
- `ADR NNNN: accepted after the baseline with no plan link`
- `<file> is stale: run `make traceability` and commit it`

The reference checks run on checked subtasks that are not in the baseline.
Unchecked subtasks may name future ADRs and plans.

## Staleness: why a merge does not turn CI red

A PR merge adds a merge commit to history. If the committed files listed every
merge, each merge would make them stale. So:

- The outputs contain **only the PRs that Phases.md names by number**. A merge that
  no note names changes nothing.
- A named number with no merge commit is **pending**, never an error. A subtask
  can cite its own PR before it merges (the number is known from the open PR).
- `--check` reads the numbers that the committed `history.json` has as pending and
  keeps them pending even if they are merged now. `generated_at` comes from merged
  rows only. So a merge after the files were written never makes them stale.
- `make traceability` (run at `/end-day`) resolves pending rows: title, date and
  merge hash appear, and the files are committed in the next PR.
- A report-only note lists pending numbers lower than the newest merged PR (an open
  or stacked PR, or a squash merge that this tool cannot see).

Tradeoff: PRs nobody wrote into Phases.md are not in the record (it is a
traceability record, not a merge log), and pending rows show no title until the
next refresh. CI needs `fetch-depth: 0` so `git log` sees the merge commits. A
shallow clone sees none, so every named PR looks pending and `--check` reports the
files stale; the smoke test skips.

## Public metadata and the redaction gate

Public fields only: PR number, title, date, merge short hash; ADR and subtask
titles. No author names or emails and no branch names. A title that contains
`arn:`, `s3://`, `amazonaws.com`, `cloudfront.net`, `@` or a run of 12 digits
is replaced by `PR #N` (`ADR NNNN`, `Subtask N.M`) and counted in the summary.
The gate is self-contained; it follows the field-allowlist idea of
ADR 0027 section 5.2 but imports nothing.

## Tests

`pytest tools/traceability` (stdlib and pytest). The git log is passed in as a
string, so only the last test touches the real repository. CI runs the tests and
the check in the `traceability` job of `.github/workflows/code-ci.yml`.
