# Weekly Article Rules

_Rules for generating cerberus-platform's weekly engineering article. Invoked
by `/write-article`
([.claude/commands/write-article.md](.claude/commands/write-article.md)).
This file is the authoritative rule set — the command reads it fresh each
run rather than hard-coding its own copy. It is a living document: update it
as the project's engineering surface grows (see "Escalation" below)._

## Cadence

- One article per week, published **every Wednesday**, covering the window
  `(last article's date, today]` — exclusive of the last article's date,
  inclusive of today, so no day is double-counted or dropped.
- If there is no previous article, the window starts at this repo's first
  commit.
- If a week produced no shippable work (see "Sourcing" for the definition),
  skip it explicitly rather than padding — a one-line note in the article
  index is enough (see "Publishing" below).
- A catch-up run (today isn't the Wednesday the article covers) is dated to
  the missed Wednesday it covers, not to the day it was actually generated —
  see the command's step 1 for how that date is chosen.

## Purpose

Each article is a portfolio artifact: a technical write-up of what was
actually built on cerberus-platform that week, aimed at a reader who
understands cloud/IaC concepts and wants to see engineering judgment, not a
changelog.

## Shape

- **Title:** `# Week of <window start date>–<window end date>: <short
  theme>`.
- **Length:** roughly 800–1500 words — enough room for real code and real
  explanation, not padded prose.
- **Section order:** brief context (what phase, what was the goal this
  week) → engineering narrative of the cloud actions taken → the actual
  code, each block followed immediately by its explanation → what's next /
  open questions.
- **Voice:** first person, technical peer-to-peer register — the target
  reader already knows what an IAM role or a state backend is.

## Required content

Every article must include:

1. **Cloud actions, told as engineering narrative.** What was provisioned,
   ingested, transformed, or torn down on AWS this week — framed as
   decisions with reasoning (why this resource, why this shape), not a
   bullet list of nouns. Read like an engineer explaining their week to
   another engineer.
2. **The actual code written this week, in whatever form it took.** Once
   Phase 1 gives `terraform/` real content, this means real HCL
   (resource/module/data/provider blocks) pulled from that week's diff. In
   any week where `terraform/` had no diff — including all of Phase 0 —
   reproduce whatever infrastructure-relevant code was actually written
   instead (bash, systemd units, SQL, CI YAML, etc.), pulled from the
   actual diff. **Never invent illustrative code that wasn't actually
   written.** If a week genuinely produced no code, say so plainly rather
   than filling the gap with a hypothetical example.
3. **Explanation of each major code block included.** When the block is
   Terraform, reference the specific provider(s) involved (e.g.
   `hashicorp/aws`, `hashicorp/random`) and why that resource/provider was
   the right tool — not what the syntax means, but why the design is
   correct (state handling, IAM scoping, naming/tagging, blast radius,
   etc.). When the block isn't Terraform, explain the analogous design
   decisions instead (e.g. why systemd over cron, why this IAM policy
   shape) — don't force a provider reference that doesn't apply.
4. **Grounding in source material, not invention.** Pull only from what
   "Sourcing" below turns up for the article's window. Do not describe work
   that didn't happen.

## Escalation — rules grow with the project

These rules are a floor, not a ceiling. They're expected to be edited as
the project's engineering surface expands. As later phases introduce new
domains, fold the matching bullet below into "Required content" above as a
first-class rule (not left here as a forward note) so articles keep pace
with what's actually being engineered. The command must confirm any such
edit with the user before making it — this file is not silently
self-modifying.

- **Phase 1–2:** Terraform/HCL, S3/IAM resource design, Glue Data Catalog
  schema registration, SQL/dbt transforms, Athena queries.
- **Phase 3:** Lambda function code + event source mappings; explain
  trigger design, not just "a Lambda was added."
- **Phase 4:** Kubernetes manifests / Spark Operator CRDs; explain resource
  requests, job configuration, and cost/teardown discipline.
- **Phase 5:** DAG / state machine definitions; explain retry and
  failure-handling design.
- **Phase 6:** CI/CD pipeline YAML; explain the plan/apply gating strategy.
- **Phase 7:** dashboard/alerting config and data-quality test definitions;
  explain what SLO or failure mode each one guards against.
- **Phase 8:** VPC/networking diagrams, IAM policy documents, cost/tagging
  reports.

When starting a new phase, review this list and fold its bullet into
"Required content" before that week's article is drafted.

## Sourcing

Given the article's window (from "Cadence"), gather:

- `git log --oneline --since=<window start> --until=<window end>`, and a
  diff of that same range against `terraform/` (once it has real content)
  and any other infrastructure-relevant paths (`ingestion/`, `transform/`,
  `docs/adr/`).
- `checkpoint.md`'s session-history entries that fall within the window.
- `Phases.md` — which subtasks flipped from ⬜/🔨 to ✅ within the window.
- Any ADRs added or changed in `docs/adr/` within the window.

**Definition of "shippable work"** (for the Cadence skip rule): the window
contains at least one commit touching a code or infrastructure path
(`terraform/`, `ingestion/`, `transform/`, `docs/adr/`, or similar).
Commits that only touch `checkpoint.md`, `Phases.md`, or other
session-tracking files don't count on their own.

## Publishing

- Articles live in `articles/`, one file per week:
  `articles/YYYY-MM-DD.md`, dated per "Cadence" above.
- Maintain `articles/README.md` as an index, newest first. Create both the
  directory and this file if they don't exist yet. Format:

  ```
  - [YYYY-MM-DD](YYYY-MM-DD.md) — <one-line summary of the week>
  ```

  or, for a skipped week:

  ```
  - YYYY-MM-DD — skipped: <reason>
  ```

- Writing the file is the command's job; committing and pushing is a
  separate, explicit step the user takes afterward — consistent with how
  `/end-day` handles checkpoint updates. The command must never `git
  add`/`commit`/`push` on its own.
