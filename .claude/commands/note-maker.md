---
description: Generate this session's textbook-style engineering notes (docs/notes/day-NN.md), theory alongside real code
---

Generate the next numbered learning note in `docs/notes/`, following the
format and rules below exactly — the same ones used to write
@docs/notes/day-01.md, which remains the canonical example. Read that file
first if you need a concrete reference for tone and density.

## 1. Determine the note's number and window

- List `docs/notes/day-*.md`, take the highest `NN`, and use `NN+1` as this
  note's number, zero-padded (`day-01.md`, `day-02.md`, ... `day-10.md`).
  If none exist, start at `day-01.md`.
- The window start is the previous note's `Date:` metadata line. If no
  previous note exists, use this repo's first commit date instead
  (`git log --reverse --format=%ad --date=short | head -1`). The window end
  is today.
- If `$ARGUMENTS` specifies an explicit date or range, use that instead and
  say so before proceeding.

## 2. Gather source material — grounded in git, not memory

Never reconstruct or paraphrase code from memory. Every code block in the
note must be copied verbatim from the real file or diff, the same
never-fabricate discipline @article.md uses for the weekly article.

- `git log --oneline --since=<start> --until=<end>` and
  `git log --name-status` over that same range, to enumerate every file
  touched.
- The matching dated entries in `checkpoint.md` for narrative context (what
  was decided and why), and any ADRs touched in the window.
- The actual current contents of every file the log touched — Terraform,
  Python, bash, systemd units, IAM policy JSON embedded in `jsonencode(...)`
  blocks, whatever the window contains.

If the window touched something you don't have a clear diff or file for,
say so rather than inventing plausible-sounding content.

## 3. Categorize by discipline, not chronology

Group the window's work the way an engineering curriculum would, not the
order it happened in. Typical categories (adapt to what the window actually
contains — don't force a category with nothing in it, and don't reuse a
previous note's categories just for consistency if this window covers
different ground):

- Governance (ADRs, decision records)
- Data Engineering (generators, transforms, data modeling)
- Systems Administration (systemd, scheduling, Linux tooling)
- Cloud Security (IAM, roles, trust policies, least privilege)
- Cloud Resources (the AWS service fundamentals a later section's code
  depends on — S3, Glue, Athena, etc.)
- Infrastructure as Code (Terraform patterns, HCL syntax, state/backend
  mechanics)
- Tooling / environment decisions (installing or switching tools, version
  pinning, CLI setup)

Order sections so foundational concepts a later section depends on come
first — e.g. a Cloud Resources section explaining what an IAM trust policy
*is* before the Cloud Security section that writes one, or an AWS S3
fundamentals section before the Terraform section that configures it.

## 4. Write `docs/notes/day-NN.md` in this exact structure

- `# Day NN — <short topic summary>` — a title describing the window's
  actual theme, not a generic placeholder.
- A metadata line:
  `_Date: <window end, or a range if the window spans multiple days> ·
  Project: cerberus-platform · Phase: <current phase, from
  checkpoint.md>_`
- A **Purpose of this document** paragraph, adapted from day-01's wording:
  this is a study note, not a status report — `checkpoint.md` already
  tracks that; the goal is capturing the *theory* behind each piece of code
  written in the window, with the actual code inline, organized by
  discipline. State it's meant to be read top to bottom once, then used as
  a reference later.
- A **Table of contents** — numbered, each entry linked to its section's
  anchor, the last entry always the Glossary.
- One `##` section per category from step 3. Each section contains:
  - A `### Theory` subsection **before** any code: explain the underlying
    concept — what it is, why it exists, what problem it solves — written
    for someone learning it for the first time, not someone who already
    knows it. This is the part that makes the note a textbook and not a
    changelog.
  - A code subsection (`### The code` or `### What changed`) with the real
    code inline in fenced blocks using the correct language tag, broken
    into digestible pieces — never one undifferentiated dump of an entire
    file. Prose between blocks must connect the theory above to the
    specific lines just shown, not just restate what the code obviously
    does.
  - An explicit callout wherever the window involved a real design
    decision — a fork that got resolved, a trade-off accepted, an
    alternative rejected and why. State what was chosen and why, the same
    way day-01's "Why this matters" and "The one real gotcha" asides do.
    Skip this where nothing was actually decided.
  - A horizontal rule (`---`) between top-level `##` sections.
- A closing `## N. Glossary`: a two-column table, one row per term
  introduced in this note, terse and precise — no repeated definitions
  from a previous day's note even if the term recurs.

## 5. Show the result

Show the user the finished note before considering the task done.

## Boundaries

This command only writes `docs/notes/day-NN.md`. It never modifies
`checkpoint.md`, `Phases.md`, `docs/plan.md`, or `README.md` — those are
status-tracking files with their own update path (`/end-day`); this note is
a separate learning artifact and must not duplicate or drift from what they
say. It also never runs `git add`, `git commit`, or `git push` — publishing
to git is a separate, explicit step the user takes after reviewing the
note, exactly as with every other command in this repo.
