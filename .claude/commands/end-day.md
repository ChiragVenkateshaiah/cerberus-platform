---
description: Checkpoint today's cerberus-platform progress for tomorrow's /start-day
---

Close out today's cerberus-platform session by recording progress so
`/start-day` can resume cleanly next time.

1. Review what actually happened this session: recap the conversation, and
   run `git status`, `git diff --stat`, and `git log --oneline` (since the
   commit nearest the last checkpoint entry, if identifiable) to ground the
   summary in what changed, not just what was discussed.
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
   - Rewrite "Current phase" and "Next up" to reflect reality after
     today's work. "Next up" should be concrete enough that `/start-day`
     can act on it without re-deriving context from the conversation.
4. Show the user a short summary of what changed in Phases.md,
   checkpoint.md, and (if a phase completed) docs/plan.md before finishing.

Do not `git add`, `git commit`, or `git push` as part of this command, even
if a phase completed — committing is a separate, explicit step the user
takes after reviewing the checkpoint update.
