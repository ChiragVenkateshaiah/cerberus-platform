---
description: Resume cerberus-platform work from the last checkpoint
---

Resume work on cerberus-platform for a new session, picking up exactly
where the last `/end-day` left off.

1. Read @checkpoint.md in full — it holds the current phase, the last
   session's summary, and the specific "Next up" items.
2. Read @Phases.md to confirm phase/subtask checkbox status agrees with
   what checkpoint.md claims. If they disagree, say so explicitly rather
   than silently trusting one — checkpoint.md's dated history should be
   the more current source, but a mismatch usually means the last
   `/end-day` was interrupted partway through.
3. Run `git log --oneline -15` and `git status` to check whether the repo
   has changed since checkpoint.md was last updated (e.g. commits or edits
   made outside a Claude Code session) in a way the checkpoint doesn't
   reflect.
4. Report back concisely: current phase, what was completed last session,
   and the proposed next actions drawn from "Next up." Ask the user to
   confirm or redirect before starting any implementation work — do not
   start a subtask until they've confirmed today's plan.
5. checkpoint.md ends with a `## Reference — Well-Architected method for ADRs`
   section. If any item in "Next up" is ADR work (or the user asks for it),
   render that section **in full and verbatim** — the whole pillar table, the
   tensions, the Nygard-template guidance, and the Well-Architected Tool
   notes — after the report in step 4. It is the working method for writing
   ADRs, so it needs to be on screen before that work starts, not summarised
   or linked. If no ADR work is upcoming, mention in one line that the
   reference is there rather than rendering it.

Do not modify checkpoint.md, Phases.md, or docs/plan.md, and do not commit
or push anything as part of this command — `/start-day` is read-only
orientation. Only `/end-day` writes the checkpoint.
