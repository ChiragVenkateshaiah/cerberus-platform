---
description: Make a decision as a new ADR - Opus plans, Sonnet writes, Opus reviews, Haiku runs git
argument-hint: <the decision topic and any constraints>
---

When the user says "decision", the result is a new ADR in `docs/adr/`.
Run it through the three project agents. The main session only routes work
between them and talks to the user; it does not write the plan or the ADR
itself. (A subagent cannot start another subagent, so the routing has to
happen here.)

| Step | Agent | Model | Does |
|---|---|---|---|
| Plan | `cerberus-planner` | Opus | Reads the repo, writes the plan |
| Write | `cerberus-executor` | Sonnet | Writes the plan file and the ADR |
| Review | `cerberus-planner` | Opus | Reviews the ADR against the plan |
| Fix | `cerberus-executor` | Sonnet | Applies blocking findings |
| Ship | `cerberus-git` | Haiku | Branch, commit, push, draft PR |

Topic: $ARGUMENTS

1. **Plan (Opus).** Start `cerberus-planner` in plan mode. Give it the
   topic, the user's words verbatim, every constraint the user stated in
   this conversation, and any facts already measured in this session (with
   their sources). Ask for the plan in the shape its instructions define.
2. **Open questions.** If the plan lists open questions for the user, ask
   them with AskUserQuestion before anything is written. Send the answers
   back to the planner (SendMessage) for a revised plan.
3. **Write (Sonnet).** Start `cerberus-executor`. Tell it to save the plan
   verbatim to `docs/plans/YYYY-MM-DD-<slug>.md` and then write the ADR from
   the plan's ADR outline, status `Proposed`. Changes beyond the ADR (code,
   Terraform) wait until the user accepts the ADR, unless the user said
   otherwise.
4. **Review (Opus).** Start `cerberus-planner` in review mode on the plan
   file and the ADR. If the verdict is `CHANGES`, send the findings to
   `cerberus-executor`, then review again. Stop after two review rounds and
   show the user what is still open.
5. **Ship (Haiku).** Start `cerberus-git`. Give it the branch name
   (`decision-<slug>`), the exact paths to stage, the commit message, and
   the PR title and body (summary, the recommendation, open points). It
   opens a draft PR.
6. **Report to the user.** The PR link and the "How to review" block from
   `cerberus-git`, the recommendation in two or three sentences, and the
   build steps that follow once the ADR is accepted.

If a project agent is not loaded in this session (agents load at session
start), use the `general-purpose` agent with the matching `model` override
(`opus`, `sonnet`, `haiku`) and put the agent file's instructions from
`.claude/agents/` at the top of the prompt.
