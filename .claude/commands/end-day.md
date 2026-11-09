---
description: Checkpoint today's cerberus-platform progress for tomorrow's /start-day
---

Close out today's cerberus-platform session by recording progress so
`/start-day` can resume cleanly next time.

**Where to edit.** The main checkout stays on `main`, so make every edit
below in a worktree. Run `git -C /home/chirag/projects/cerberus fetch
origin`, then `git -C /home/chirag/projects/cerberus worktree add -b
end-day-YYYY-MM-DD /home/chirag/projects/cerberus-end-day-YYYY-MM-DD
origin/main` (today's date). If that worktree already exists from an
earlier `/end-day` today, reuse it instead. Edit Phases.md, checkpoint.md,
docs/plan.md and README.md only at their paths under
`/home/chirag/projects/cerberus-end-day-YYYY-MM-DD/`. The `@` references
in the steps below load the main checkout's copies for reading; never
write to those. Run step 1's `git status` in the main checkout and any
active worktrees to see the session's work.

1. Review what actually happened this session: recap the conversation, and
   run `git status`, `git diff --stat`, and `git log --oneline` (since the
   commit nearest the last checkpoint entry, if identifiable) to ground the
   summary in what changed, not just what was discussed.
   - Reconcile stale claims: scan checkpoint.md's most recent entry for any
     transient VCS-state claims ("pending review, not yet committed",
     "not yet pushed", etc.). If git log/status shows that state has since
     resolved (e.g. it's now committed), correct that line in place rather
     than leaving it to contradict the git history — don't just append a
     new entry on top of a stale one.
2. Update @Phases.md:
   - Check off any subtasks completed this session.
   - If every subtask in a phase is now checked, mark that phase's status
     ✅ Complete in its Phases.md heading, flip the matching row in
     docs/plan.md's roadmap table status column (only the status marker —
     leave plan.md's phase descriptions, stack, and "done when" text
     untouched), and note the completion in checkpoint.md's history.
3. Update @checkpoint.md:
   - Append a new dated entry (use today's actual date) summarizing what
     was completed, key decisions made, and anything left mid-flight.
   - Describe work by its durable content ("added X, Y, Z"), not by its
     transient VCS status ("not yet committed", "pending push"). Commit
     status is a snapshot that git log/status already answers authoritatively
     and will silently go stale the moment it changes outside this skill —
     don't duplicate it into the narrative as if it were a fixed fact. If a
     commit/push genuinely hasn't happened and is worth flagging, put it
     under "Notes / blockers" instead of the dated history, since blockers
     are expected to be revisited and cleared, not left as permanent record.
   - Rewrite "Current phase" and "Next up" to reflect reality after
     today's work. "Next up" should be concrete enough that `/start-day`
     can act on it without re-deriving context from the conversation.
   - **Preserve the reference sections verbatim.** Everything below the `---`
     separator near the end of checkpoint.md (currently
     `## Reference — Well-Architected method for ADRs`) is stable reference
     material, not session state. Never rewrite, summarise, trim, or drop it
     while updating the sections above it. Add new reference sections there
     only when the user explicitly asks for one.
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
5. Show the user a short summary of what changed in Phases.md,
   checkpoint.md, README.md, and (if a phase completed) docs/plan.md before
   finishing. Always include one README line: `README updated: <sections
   changed>` (for example `README updated: Roadmap, Scale ladder`), or
   `README checked, no drift found` when step 4 changed nothing. A clean
   check must look different from a skipped one.

Do not `git add`, `git commit`, or `git push` as part of this command, even
if a phase completed. The user reviews the changes first. Then the normal
workflow takes over: `cerberus-git` commits the changed files on
`end-day-YYYY-MM-DD`, pushes and opens a PR, and the user merges it with
`--merge`. README reaches `main` only through that PR, with CI green.
