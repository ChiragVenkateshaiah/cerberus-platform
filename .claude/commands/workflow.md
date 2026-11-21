---
description: Run a task with the model split - Sonnet plans, executes and reviews, Haiku runs git; Opus only through /decision
argument-hint: <the task, e.g. a Phases.md subtask like "10.5">
---

The default way to do implementation work in cerberus-platform. The main
session routes work between the project agents and talks to the owner; it
does not plan or write the change itself. A decision (a new ADR or an
amendment) goes through `/decision`, which is the only place Opus is used.

| Step | Agent | Model |
|---|---|---|
| Plan | `cerberus-planner` | Sonnet |
| Execute | `cerberus-executor` | Sonnet |
| Review | `cerberus-reviewer` | Sonnet |
| Git and GitHub | `cerberus-git` | Haiku |
| Decision (ADR) | `cerberus-decision` | Opus, via `/decision` only |

Task: $ARGUMENTS

## Tiers: how much of the loop a change needs

| Tier | Change | Loop |
|---|---|---|
| T | Docs, comments, a test, a rename, a README or Phases.md line | executor, `make verify`, git. No planner, no reviewer. CI is the gate. |
| C | Code, tests with logic, dashboards, alert rules, scripts | planner (or a task card), executor, `make verify`, reviewer, git |
| D | A decision: new ADR, an amendment, a change to the security or cost model | `/decision` (Opus plans and reviews the ADR), then the Tier C loop for the build |
| S | IAM, trust or bucket/SNS/KMS policy, a public endpoint, credentials | Tier C, and the reviewer sets `escalate: opus-security`; the owner decides whether to spend an Opus review. Owner-run applies and pastes as before. |

The planner replies `NEEDS DECISION` when a task is really Tier D. The
reviewer sets `escalate: opus-design` when a change quietly changes an
Accepted ADR. Opus is never started on its own judgment: the owner agrees
to an escalation, or runs `/decision`.

## Steps

1. **Plan (Sonnet, Tier C).** A task card is enough when the work is
   already specified (a plan in `docs/plans/`, an ADR, a `Phases.md` line):
   goal, the files, the acceptance tests, about 10 lines. Otherwise start
   `cerberus-planner`. Show the owner the steps and the open questions only
   when there is a real decision; otherwise go on.
2. **Execute (Sonnet).** Start `cerberus-executor` with the plan path or the
   task card. The standing rules (no git, no AWS writes, no secrets,
   `make verify`, report format) live in the agent file. Do not repeat them.
   Anything that changes AWS is the owner's to run; the executor prepares it
   and writes the exact command.
3. **Review (Sonnet, Tier C and S).** Start `cerberus-reviewer` fresh on the
   branch. `CHANGES`: the executor applies the findings, the main session
   reads the result. One re-review at most. An `escalate:` line goes to the
   owner as one question with the reviewer's reason.
4. **Git (Haiku).** Start `cerberus-git` with the branch, the paths, the
   commit message file and the PR title and body files. The main session
   writes those files (short, and ending with the attribution lines the
   session provides). Merges only on the owner's "merge #N".
5. **Report.** The PR link with the "How to review" block, what was done in
   a few lines, and what the owner must run by hand.

## Spend rules (apply to every step)

- Start agents fresh. Do not resume a long agent thread. A re-check is one
  short message; for more, start a new agent with a one-page handoff.
- Briefs are short. Rules live in the agent files, checks in `make verify`.
- Reviews are about 400 words, plans about 900. Ask the executor for a
  25-line report.
- The main session does small edits itself (a wording fix, a README line, a
  count); it does not send them back through another agent.
- Run independent agents in the same turn. Poll CI once with
  `gh pr checks --watch`, not in loops.
- Large read-only sweeps (many files) go to a subagent that returns only the
  findings.
- Opus is for `/decision` only.

If a project agent is not loaded in this session, use `general-purpose`
with the matching `model` override and the agent file's instructions from
`.claude/agents/` at the top of the prompt.
