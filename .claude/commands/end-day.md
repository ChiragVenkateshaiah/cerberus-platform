---
description: Checkpoint today's cerberus-platform progress for tomorrow's /start-day
---

Close out today's cerberus-platform session by recording progress so
`/start-day` can resume cleanly next time.

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
4. Reconcile @README.md against the rest of the project's status files and
   the repo's actual current layout. README is the entry point a reader
   hits first, so it must never lag behind what
   Phases.md/checkpoint.md/docs/plan.md now say, or behind what the
   filesystem actually contains:
   - **Find what changed mechanically, don't rely on memory.** Use step 1's
     `git status` output plus `git log --name-status` (since the commit
     nearest the last checkpoint entry) to enumerate every path added,
     renamed, or newly populated this session (including a directory that
     went from empty/placeholder to holding its first real file). Cross-check
     each one against README below — this is what catches drift like a new
     root file or command going unmentioned.
   - **Status section:** README's phase badges (✅/⬜) and "next" phase
     must match Phases.md's current phase status after step 2's updates.
   - **Roadmap phase count and diagram labels:** if docs/plan.md's phase
     count or numbering changed this session (a re-scope), confirm README's
     "Phases 0–N" reference matches, and confirm any phase-number labels
     inside the architecture diagram (e.g. "(Phase 2)" callouts on diagram
     nodes) match too. Only those labels are in scope — the diagram's
     topology and styling are not; leave them untouched.
   - **Documentation list / Repository layout — a full state check, not
     only a delta check.** Confirm README's "Documentation" section lists
     every root-level rules/reference file (e.g. article.md) and every file
     under `docs/` and `.claude/commands/` that a reader would need to find,
     and confirm the "Repository layout" ASCII tree includes every
     directory that exists at the depth the tree already shows (it
     currently shows depth-2 paths like `ingestion/scripts/` — match that
     granularity). Check this against the repo as it stands today, not only
     against this session's diff — pre-existing gaps (a file that went
     undocumented in an earlier session) count too and should be fixed now
     that they're noticed.
   - Touch only README's Status, Documentation, and Repository layout
     sections, plus in-diagram phase-number labels per above, for this
     reconciliation. Leave the rest of the architecture diagram and prose
     untouched unless this session's work specifically changed the
     architecture.
5. Show the user a short summary of what changed in Phases.md,
   checkpoint.md, README.md, and (if a phase completed) docs/plan.md before
   finishing. If step 4 found no drift, say so explicitly ("README checked,
   no drift found") rather than omitting it — a clean check should look
   different from a skipped one.

Do not `git add`, `git commit`, or `git push` as part of this command, even
if a phase completed — committing is a separate, explicit step the user
takes after reviewing the checkpoint update.
