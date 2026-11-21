# 29. Platform-development traceability

Date: 2026-11-20

## Status

Accepted (2026-11-20). It extends the data contract of
[ADR 0027](0027-public-showcase.md) and
[ADR 0028](0028-databricks-free-edition.md) with `history.json`. It amends
nothing. The build steps and the facts behind this ADR are in
[the plan](../plans/2026-11-20-databricks-free-edition-showcase.md).

Amendment proposed 2026-11-21 (step 16.2): merged PRs are read from GitHub
merge commits in `git log --merges` (number, title, date), not
`gh pr list`; CI needs no token or API access. Squash or rebase merges would
not be seen; revisit if the merge method changes.

## Context

The owner asked for another one, for traceability of the platform
development. The owner answered on 2026-11-20 that this means a generated
record, not a decision log.

- Evidence for each piece of work is spread across Phases.md, the ADRs, the
  plans, the PRs, the run records and the Well-Architected milestones. The
  links between them are kept by hand.
- Portfolio readers ask how the platform was built, and why.
- The ADRs already are the decision log, so a second ADR list adds little.
  Requirements traceability (each "Done when" criterion to its evidence) can
  be one field in the record.

## Decision

1. **A generator.** A Python tool in `tools/traceability/`, with no AWS
   access, builds `history.json` and the `docs/traceability.md` table. It
   links each subtask to its ADR, plan, PR, merge commit, run record and
   dashboard panel, and to its Well-Architected milestone. Its sources are
   git, Phases.md, the ADR Status lines, the plan files, the run records and
   `gh pr list --state merged`. CI uses the read-only `GITHUB_TOKEN` with
   `pull-requests: read`.
2. **A CI check** fails on dangling links: a checked subtask with no PR, an
   ADR Accepted without a plan, or a run record that nothing references.
   The check applies only to subtasks checked and ADRs accepted on or
   after the date this ADR is accepted. Older items are listed with the
   link marked `none (before traceability)` and do not fail the check.
3. **Where it shows.** On the public site (step 15.3), and as a Databricks
   AI/BI dashboard, "how it was built" (steps 11.2c and 16.3).
4. **Public metadata only.** PR number, title and dates. No author emails.
   Titles go through the ADR 0027 redaction gate. A title that fails is
   shown as its PR number only.
5. **Phase 16.** The work is Phase 16, "Development traceability". It is
   git only, $0 and has no dependency. It runs right after Phase 10 (10.7),
   before 14.2.

## Consequences

**Good**

- Audit-style traceability, and a living timeline for readers.
- It catches bookkeeping drift between the files.

**Given up**

- A new CI job.
- History from before structured PR titles is partial.

**Revisit if**

- PR title conventions change.
