---
description: Make a decision as a new ADR - Opus decides (plan and review), Sonnet writes, Haiku runs git
argument-hint: <the decision topic and any constraints>
---

When the user says "decision", the result is a new ADR (or an amendment) in
`docs/adr/`. This is the only place Opus is used. The main session routes
work between the project agents and talks to the user; it does not write the
plan or the ADR itself. (A subagent cannot start another subagent, so the
routing has to happen here.)

| Step | Agent | Model | Does |
|---|---|---|---|
| Plan | `cerberus-decision` | Opus | Plans the decision (once, fresh) |
| Write | `cerberus-executor` | Sonnet | Saves the plan file and writes the ADR |
| Review | `cerberus-decision` | Opus | Reviews the ADR (once, fresh, short) |
| Fix | `cerberus-executor` | Sonnet | Applies the findings |
| Ship | `cerberus-git` | Haiku | Branch, commit, push, draft PR |

Topic: $ARGUMENTS

Spend rules for this command:

- Start `cerberus-decision` fresh for the plan and fresh again for the
  review. Give each a one-page brief (below), not the conversation. Do not
  resume an Opus agent for a long thread: at most one `SendMessage` per
  Opus agent (the re-check), and if more is needed, start a new one with a
  handoff note.
- Do not send Opus anything the executor can do (formatting, reflowing,
  small wording fixes, counting). The main session or the executor applies
  those.
- Put the standing rules in the agent files, not in each brief.

Steps:

1. **Plan (Opus).** Brief = the topic, the user's words verbatim, the
   constraints they stated, and facts already measured (with sources), in
   about 15 lines. Ask for the plan in the shape its instructions define.
2. **Open questions.** If the plan lists open questions for the user, ask
   them with AskUserQuestion before anything is written. The answers go into
   the plan as "Owner answers" through the executor; they do not go back to
   Opus unless they change the recommendation.
3. **Write (Sonnet).** Start `cerberus-executor`. Tell it to save the plan to
   `docs/plans/YYYY-MM-DD-<slug>.md` and write the ADR from the plan's ADR
   outline, status `Proposed`. Changes beyond the ADR (code, Terraform) wait
   until the owner accepts the ADR, unless the owner said otherwise.
4. **Review (Opus).** Start `cerberus-decision` fresh in review mode with the
   plan path and the branch. If `CHANGES`, the executor applies the findings
   and the main session checks the result; send it back to Opus once only if
   a blocking finding was a design point. Then show the owner what is open.
5. **Ship (Haiku).** Start `cerberus-git` with the branch name
   (`decision-<slug>`), the exact paths to stage, the commit message file and
   the PR title and body file. It opens a draft PR.
6. **Report.** The PR link and the "How to review" block, the
   recommendation in two or three sentences, and the build steps that follow
   once the ADR is accepted.

If a project agent is not loaded in this session (agents load at session
start), use the `general-purpose` agent with the matching `model` override
(`opus`, `sonnet`, `haiku`) and put the agent file's instructions from
`.claude/agents/` at the top of the prompt.
