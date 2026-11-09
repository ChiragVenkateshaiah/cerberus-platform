# Plan: `/end-day` brings README.md up to date every day

Date: 2026-11-09. Planner: Opus. Base: `origin/main` (5c3550c when the worktree was made). Branch `tooling-end-day-readme`, worktree `/home/chirag/projects/cerberus-tooling-end-day-readme`. Tooling only: no ADR, no Phases.md subtask.

## 1. Question

How must `/end-day` step 4 change so that every call brings README.md up to date? The user asked for it on 2026-11-09 ("The audience should not have the stale update about the project"). Step 4 still describes the README from before PR #138, so today it checks sections that no longer exist.

## 2. Facts

- `.claude/commands/end-day.md` step 4 assumes the old README: a Status section with ✅/⬜ badges, a "Phases 0–N" reference, phase labels in the diagram, an ASCII layout tree at depth 2, a list of `.claude/commands/` files, and the rule "Touch only README's Status, Documentation, and Repository layout sections". Step 5 already requires "README checked, no drift found". The last paragraph forbids `git add`/`commit`/`push`.
- README.md after #138 and #107: badges, GIF, At a glance ("25 so far"), Headline result (Cost row is an estimate), Architecture (Mermaid), Tech stack, Scale ladder (the take row shows `not posted yet`), Observability for everyone, Data quality, Cost and security, Where Databricks fits, Roadmap table for Phases 0–14 (Phase, Theme, Status, Key ADRs), Run it yourself, Repository layout (bare fence, top-level dirs), Documentation, License.
- CI runs `ruff format --check .` (`.github/workflows/code-ci.yml`); ruff formats Markdown code blocks (`pyproject.toml`); ruff 0.16.4 is pinned in `requirements-dev.txt`.
- ADR count is 25 (`ls docs/adr/[0-9]*.md`).
- In billed run records, `cost.complete` is the posted signal; `estimated` stays true until the month closes (docs/scale-metrics.md, `collect_run_metrics.py`).
- PR #138 left out `.claude/commands`, `data/` (exists, holds `data/samples/`), `docs/courses-map-to-phases.md` and `article.md`.
- Checkpoint commits went straight to `main` (`a947c8a`, `48f6358`); `.claude/agents/cerberus-git.md` allows "a checkpoint commit when the caller says it comes from `/end-day`" on main. All other work uses sibling worktrees.
- `Phases.md` footer still says "reconcile README.md's status badges and roadmap references" (stale).
- `.claude/commands/start-day.md` has no README assumptions.

## 3. Constraints

No AWS change, no cost. No accepted ADR touched. `/end-day` still must not `git add`/`commit`/`push`. README and doc text in natural professional English.

## 4. Decision

Option B: `/end-day` edits in a worktree branch `end-day-YYYY-MM-DD`, and the change reaches `main` through a PR with CI green.

## 5. Replacement blocks

### 5a. `.claude/commands/end-day.md`: replace all of step 4 with

```
4. Bring @README.md up to date. Do this on every `/end-day`, not only when a
   phase completes. README is the public portfolio page and the first thing
   a reader opens, so it must never describe the project as it stood last
   week. README describes what is merged on `main`: work that exists only on
   an open branch or draft PR stays out until it merges.
   - **Collect the sources mechanically, not from memory.** Let `<since>` be
     the date of checkpoint.md's most recent dated entry before today's.
     Read:
     - merged PRs: `gh pr list --state merged --search "merged:>=<since>"
       --limit 100 --json number,title,mergedAt,files`;
     - paths changed on main: `git log --first-parent --name-status
       --since=<since> origin/main`;
     - Phases.md and docs/plan.md after step 2, checkpoint.md after step 3;
     - the Status line of every ADR in `docs/adr/`;
     - the records in `observability/scale/runs/` and docs/scale-metrics.md.
   - **Roadmap.** One row per phase in docs/plan.md's roadmap table, with
     the same numbering and theme. Status is `Done` for a phase marked
     ✅ Complete in Phases.md; `In progress: <what is left>`, naming the open
     subtasks in a few words; or `Planned`, optionally with a short note
     such as `design accepted (ADR 00NN)`. Key ADRs: every linked file
     exists, the link text matches its number, and an ADR accepted since
     `<since>` is added to its phase's row. A Proposed ADR is labelled
     Proposed, never presented as accepted.
   - **Headline result and Scale ladder.** Change these when a new run
     record lands in `observability/scale/runs/` or a cited record gains a
     posted cost.
     - Every number comes from a committed file (a run record,
       docs/scale-metrics.md, a committed audit), and the section's
       "Sources:" line links it. A number that exists only in an
       uncommitted exercise log or a terminal stays out of README until it
       is written into docs/scale-metrics.md.
     - Recompute derived figures (events per second, SLO headroom, $/M
       events) from the record, at the rounding the table already uses.
     - Dashboard readings and pre-billing costs are labelled as estimates.
     - A billed figure appears only when the record has a `cost` section
       with `complete: true`, written by `collect_run_metrics.py
       --cost-only` (see "Collect `--cost-only` the day after" in
       docs/scale-metrics.md). Use `cost.run_usd`,
       `cost.usd_per_million_events` and the day's `cost.usd`, and name the
       Cost Explorer day. Until then the cell stays `not posted yet`.
     - A new ladder step adds a row. A run replaces the headline only when
       the user says so.
   - **At a glance and other counters.** The ADR count ("25 so far") equals
     `ls docs/adr/[0-9]*.md | wc -l`. Check every other count in the prose
     against its source: data-quality checks against the latest cited run
     record's `data_quality.checks`, dashboards against the titles in
     `observability/grafana/dashboards/*.json`, SLOs against docs/slo.md,
     admin policies against `iam/cerberus-admin/policies/`. Dated figures
     (for example the build cost "through 2026-10-02") keep their date;
     refresh them only from a newer committed source.
   - **Architecture and Tech stack.** Change these only when work merged
     since `<since>` changed the architecture: a service added or removed,
     a Step Functions state added or renamed, or a planned (dashed) edge
     made real, such as exercise lineage or alerting (ADR 0021) or the
     Phase 11 Databricks read. The diagram must stay true to the code on
     `main`: every solid node and edge maps to Terraform or code that exists
     now, and planned items stay dashed and labelled planned. Every ADR link
     in the Tech stack table points to the ADR whose title matches the
     layer.
   - **Documentation and Repository layout: a full state check, not only a
     delta check.** Check against the repo as it stands, so an older gap
     counts too.
     - Repository layout lists every non-hidden top-level directory, one
       line each, at its current granularity (top level only; no deeper
       tree).
     - Documentation lists `docs/plan.md`, `Phases.md`, `docs/adr/`,
       `articles/README.md` and every `docs/*.md` file, except the ones
       left out by design: `docs/courses-map-to-phases.md`. Internal working
       files are never listed: `checkpoint.md`, `article.md`, `.claude/`,
       `docs/plans/`, `docs/notes/`.
   - **Wording.** Natural, professional English (not the chat style).
     Absolute dates. The exercise runs "from no compute back to no
     compute", never "empty account". Databricks appears only as a
     complement and partner engine, never as something Cerberus beats or
     replaces.
   - **Hygiene checks.** Run from the root of the checkout you edited. Each
     check must print nothing, except the ruff line:
     - relative links resolve: `grep -oE '\]\(([^)#]+)(#[^)]*)?\)'
       README.md | sed -E 's/^\]\(//; s/\)$//; s/#.*//' | grep -vE
       '^https?://' | sort -u | while read -r p; do test -e "$p" || echo
       "MISSING $p"; done`;
     - no account IDs, ARNs, emails or local paths: `grep -nE
       '\b[0-9]{12}\b|arn:|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|/home/|\.env\b|exercises/'
       README.md`;
     - fences are bare, `bash` or `mermaid` only, because CI's `ruff format
       --check .` formats Python blocks in Markdown: `grep -n '^```'
       README.md | grep -vE '^[0-9]+:```(bash|mermaid)?$'`;
     - make targets exist: `grep -oE 'make [a-z-]+' README.md | awk '{print
       $2}' | sort -u | while read -r t; do grep -qE "^$t:" Makefile ||
       echo "NO TARGET $t"; done`;
     - banned wording: `grep -niE 'empty account|beats databricks|better
       than databricks|replace databricks' README.md`;
     - `ruff format --check README.md` reports "already formatted" (use the
       version pinned in requirements-dev.txt).
   - Leave everything else in README (tagline, GIF, Run it yourself,
     License) alone unless this session's merged work made it false.
```

### 5b. Step 5: replace its last sentence ("If step 4 found no drift, ... skipped one.") with

```
   Always include one README line: `README updated: <sections changed>`
   (for example `README updated: Roadmap, Scale ladder`), or `README
   checked, no drift found` when step 4 changed nothing. A clean check must
   look different from a skipped one.
```

### 5c. Where to edit (option B)

Insert this paragraph after the intro paragraph, before step 1:

```
**Where to edit.** The main checkout stays on `main`, so make every edit
below in a worktree. Run `git -C /home/chirag/projects/cerberus fetch
origin`, then `git -C /home/chirag/projects/cerberus worktree add -b
end-day-YYYY-MM-DD /home/chirag/projects/cerberus-end-day-YYYY-MM-DD
origin/main` (today's date), and edit Phases.md, checkpoint.md,
docs/plan.md and README.md there. Run step 1's `git status` in the main
checkout and any active worktrees to see the session's work.
```

Replace the final paragraph ("Do not `git add`, ... checkpoint update.") with:

```
Do not `git add`, `git commit`, or `git push` as part of this command, even
if a phase completed. The user reviews the changes first. Then the normal
workflow takes over: `cerberus-git` commits the changed files on
`end-day-YYYY-MM-DD`, pushes and opens a PR, and the user merges it with
`--merge`. README reaches `main` only through that PR, with CI green.
```

In `.claude/agents/cerberus-git.md`, replace the rule "Never commit to `main`, except a checkpoint commit when the caller says it comes from `/end-day`." (match its exact current wording and list formatting) with:

```
- Work on a feature branch. Never commit to `main`. `/end-day` changes go
  on `end-day-YYYY-MM-DD` through a PR like any other change.
```

### 5d. `Phases.md` footer

Replace "reconcile [README.md](README.md)'s status badges and roadmap references —" with "update [README.md](README.md)'s Roadmap table —". (Match the exact current text; it may wrap across lines.)

### 5e. `start-day.md`

Change "Do not modify checkpoint.md, Phases.md, or docs/plan.md" to "Do not modify checkpoint.md, Phases.md, docs/plan.md, or README.md". (Match the exact current wording.)

## 6. Static checks (worktree root)

- `grep -nE 'Status section|ASCII|depth-2|Touch only README|Phases 0–N|✅/⬜' .claude/commands/end-day.md` prints nothing.
- `grep -c 'README updated:' .claude/commands/end-day.md` prints 1 or more.
- `grep -c 'no compute back to no compute' .claude/commands/end-day.md` prints 1.
- `grep -n 'end-day-YYYY-MM-DD' .claude/commands/end-day.md .claude/agents/cerberus-git.md` shows hits in both files; `grep -n 'except a checkpoint commit' .claude/agents/cerberus-git.md` prints nothing.
- `grep -n 'status badges' Phases.md` prints nothing.
- The 5a hygiene commands, run on the current README, all print nothing (except the ruff line).
- `$HOME/.cache/ruff0164/bin/ruff format --check .` and `ruff check .` pass.
- The diff touches only `.claude/commands/end-day.md`, `.claude/commands/start-day.md`, `.claude/agents/cerberus-git.md`, `Phases.md` and the plan file. README.md is not touched in this PR.

## 7. Build steps (one PR)

1. Worktree created from `origin/main`.
2. Executor: save this plan to `docs/plans/2026-11-09-end-day-readme-refresh.md`; apply 5a-5e.
3. Executor: run section 6.
4. Planner: review.
5. Git agent: commit, push, draft PR on `tooling-end-day-readme`. The user merges with `--merge`.
6. Verify: the next real `/end-day` prints a `README updated:` or `README checked, no drift found` line; the first run should add `data/` to Repository layout.

## 8. User decisions (2026-11-09)

1. Option B: worktree branch `end-day-YYYY-MM-DD` plus a daily PR.
2. `data/` is added to Repository layout on the first run (it is not on the left-out list).
3. `docs/courses-map-to-phases.md` stays out of the Documentation list by design.
4. README.md is added to `/start-day`'s "do not modify" list.
