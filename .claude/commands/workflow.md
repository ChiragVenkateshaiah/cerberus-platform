---
description: Run a task with the model split - Opus plans and reviews, Sonnet executes, Haiku runs git
argument-hint: <the task, e.g. a Phases.md subtask like "9.2">
---

The default way to do implementation work in cerberus-platform. The main
session routes work between the three project agents and talks to the
user; it does not plan or write the change itself. For a decision (a new
ADR), use `/decision` instead.

| Step | Agent | Model |
|---|---|---|
| Plan | `cerberus-planner` | Opus |
| Execute | `cerberus-executor` | Sonnet |
| Review | `cerberus-planner` | Opus |
| Git and GitHub | `cerberus-git` | Haiku |

Task: $ARGUMENTS

1. **Plan (Opus).** Start `cerberus-planner` in plan mode with the task,
   the matching `Phases.md` subtask, and the user's constraints. Skip the
   ADR outline section unless the task needs an ADR amendment.
2. **Confirm.** Show the user the plan's build steps and open questions.
   Do not start execution until the user confirms. Save the confirmed plan
   with `cerberus-executor` to `docs/plans/YYYY-MM-DD-<slug>.md`.
3. **Execute (Sonnet).** Start `cerberus-executor` on the plan. Anything
   that changes AWS (`terraform apply`, `make exercise`) is the user's to
   run; the executor prepares it and says the exact command.
4. **Review (Opus).** Start `cerberus-planner` in review mode. Loop
   executor fixes and review at most twice; then show the user what is
   still open.
5. **Git (Haiku).** Start `cerberus-git` to branch, commit and open a
   draft PR. Merges happen only after the user approves, and only with
   `--merge`.
6. **Report.** The PR link with the "How to review" block, what was done,
   and what the user must run by hand.

If a project agent is not loaded in this session, use `general-purpose`
with the matching `model` override and the agent file's instructions from
`.claude/agents/` at the top of the prompt.
