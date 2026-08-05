---
description: Generate this week's cerberus-platform engineering article per article.md's rules
---

Generate the weekly cerberus-platform article, following the rules in
@article.md exactly — read that file first, since it is the authoritative
rule set and may have been updated since this command was last touched.

1. Determine the article's window and target date:
   - List files in `articles/` matching `YYYY-MM-DD.md` — explicitly
     excluding `README.md` and anything else — and take the latest date as
     the window start. If none exist, use the date of this repo's first
     commit (`git log --reverse --format=%ad --date=short | head -1`) as
     the window start.
   - The window end, and the article's target date, is today — unless
     today is not a Wednesday. In that case tell the user and confirm
     before continuing which case applies: (a) a normal run happening on
     the wrong day, or (b) an intentional catch-up for a missed Wednesday.
     For a catch-up, set the target date to the most recent Wednesday that
     is after the window start and on or before today, and use *that* date
     as the window end and as the article's filename date — not today's
     date.
   - The window is `(window start, window end]` per article.md's Cadence
     section.
2. Gather source material per article.md's "Sourcing" section, using the
   window from step 1: `git log --oneline --since=<window start>
   --until=<window end>`, a diff of that range against `terraform/`,
   `ingestion/`, `transform/`, and `docs/adr/`, the matching
   `checkpoint.md` session entries, `Phases.md` deltas, and ADR changes
   within the window.
3. Apply article.md's "shippable work" definition (in "Sourcing") to what
   step 2 found. If the window has no shippable work, do not fabricate
   content — write the one-line skip entry described in article.md's
   "Publishing" section to `articles/README.md` and stop; still show the
   user that index update before finishing.
4. Draft the article to satisfy every point in article.md's "Required
   content" and "Shape" sections: engineering narrative of cloud actions,
   the actual code pulled from the window's diffs (never reconstructed or
   invented — if a week had no code, say so instead of fabricating an
   example), an explanation of each major code block referencing its
   provider(s) where applicable, and grounding strictly in what step 2
   gathered.
5. Check article.md's "Escalation" section against the current phase (see
   Phases.md). If the phase has moved into engineering territory (Lambda,
   Kubernetes, orchestration, CI/CD, observability, etc.) that article.md's
   "Required content" doesn't yet cover, propose the specific wording to
   fold in as a new "Required content" bullet and get the user's
   confirmation before editing article.md — this command must never
   rewrite its own rules file silently. Apply the confirmed addition to
   this article's draft too; if the user declines, draft without it.
6. Write the article to `articles/YYYY-MM-DD.md`, using the target date
   from step 1 (today, or the missed Wednesday for a catch-up run), and add
   an entry to `articles/README.md`'s index in the format article.md
   specifies.
7. Show the user the drafted article and the index update before
   finishing, whether or not step 3's skip path was taken.

Do not `git add`, `git commit`, or `git push` as part of this command —
publishing to git is a separate, explicit step the user takes after
reviewing the draft.
