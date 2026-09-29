# 15. Phase 7 Well-Architected review (whole-platform)

Date: 2026-09-29

## Status

Proposed

## Context

Phase 7 — end-to-end platform validation — is the platform's last phase.
Three of its six subtasks are done so far:

- **7.1** — scaled the ingestion Lambda's synthetic payments workload 10x
  (`TRANSACTION_COUNT` 200 → 2000; `RETIRE_ON_OR_AFTER` bumped to
  2026-10-15, replacing the already-passed 2026-08-17 cap that had made
  the Lambda a pure no-op).
- **7.2** — a `dev-compute` exercise: 3 manually-started full orchestrated
  state-machine executions, all `SUCCEEDED` end to end (ingestion →
  Spark-on-EKS transform → dbt build → Athena serving query), every layer
  verified live including OpenLineage capture; `dev-compute` torn down and
  verified clean afterward.
- **7.3** — `cerberus-admin`'s `AdministratorAccess` replaced with 6
  scoped customer-managed policies (`iam/cerberus-admin/`), built from its
  complete real CloudTrail history (241 distinct operations across the
  whole project) rather than guessed, verified via
  `iam:simulate-custom-policy` and a live `terraform plan` across all
  three roots with `AdministratorAccess` fully detached.

7.4, 7.5, and 7.6 are not done — this review does not credit the platform
for work that hasn't happened yet.

**Unlike every prior Well-Architected pass in this project (ADR
0004/0006/0008/0010/0012/0014), this is not a per-phase diff review — it's
the full 57-question review across the whole platform**, per
`Phases.md`'s framing of 7.4. Milestone 6
(`phase-6-observability-and-data-quality-complete`) is still the baseline
diffed against, since nothing in 7.1–7.3 touches a pillar Milestone 6
didn't already cover. All 57 questions were re-answered honestly this
pass — not just the ones plausibly affected by 7.1–7.3 — matching this
project's standing practice (ADR 0014: "five more questions gained new
evidence... without crossing the Tool's internal threshold").

## What changed, and what honestly didn't

Two questions gained genuine new evidence and a new selected choice.
**Neither crossed a risk bucket** — consistent with ADR 0014's own
prediction that "7.3's least-privilege review is the next real candidate,
and only for Security," which turned out right in kind (Security moved)
but not in degree (it didn't cross).

**Security / `permissions`** ("How do you manage permissions for people
and machines?", MEDIUM) — added **"Establish emergency access process"**.
7.3 is direct, first-class evidence for the already-selected "reduce
permissions continuously" choice (the whole review *is* that continuous
reduction, done once with real usage data instead of guesswork) — but
that choice was already selected, so it reinforces rather than moves
anything. The genuinely new choice is the emergency-access one:
`cerberus-admin` cannot manage its own IAM policies (deliberately, to
avoid the same self-escalation risk `iam:PassRole` warns about, applied
symmetrically to policy management) — confirmed live twice this session,
when a bug in the first policy draft required root-console intervention
(MFA sign-in, CloudShell) to push the fix. That root-console path is now
a documented, real emergency access process (`iam/cerberus-admin/README.md`'s
"What's deliberately NOT granted"), not an improvised one-off. **Stayed
MEDIUM** — one more real choice, not enough to cross.

**Reliability / `testing-resiliency`** ("How do you test reliability?",
HIGH) — added **"Test scalability and performance requirements"**. 7.1's
10x volume bump and 7.2's three successful full-pipeline executions at
that volume are a genuine, verified scalability test — not a synthetic
load test against defined breaking-point thresholds, but real evidence
the pipeline holds at materially higher volume, which is what this choice
asks about. **Stayed HIGH** — chaos engineering, game days, and
post-incident analysis were already selected from earlier phases; this
adds a fourth real choice without crossing.

**Everything else stayed exactly as milestone 6 left it, honestly, not by
default.** The full 57 were reviewed, not skipped:

- **Security / `identities`** (HIGH) — considered adding "Audit and rotate
  credentials periodically", since 7.3's CloudTrail-based review is real
  auditing. Declined: the choice conflates auditing *and* rotation, and
  credential rotation for `cerberus-admin`'s long-lived access keys still
  hasn't happened. Selecting it would overstate what's true, the same
  discipline ADR 0014 used declining "automate responses" for
  `monitor-aws-resources`.
- **Security / `securely-operate`** (HIGH) — 7.3 is real evidence for two
  *already-selected* choices ("reduce security management scope",
  "identify and validate control objectives" — the whole
  test-then-swap methodology is validating a control objective). Reinforcement,
  not a new choice, so no bucket movement to claim.
- **Security / `detect-investigate-events`** (MEDIUM) — still no
  CloudTrail trail exists in this account (confirmed directly this
  session, not assumed — `aws cloudtrail describe-trails` returns empty).
  `cerberus-admin`'s new ability to query the default 90-day Event History
  ad hoc is not the same as "capture logs, findings, and metrics in
  standardized locations." Stays honestly unchanged; see Consequences.
- **Operational Excellence / `ready-to-support`, `event-response`** (both
  HIGH) — 7.2's three successful runs are real operational evidence but
  not a *formal, repeatable* operational-readiness review process, and
  nothing broke during 7.2 to exercise incident handling (the one real
  operational event this session — 7.2's dev-compute teardown hitting the
  documented NAT-before-node-group gotcha — was resolved via an existing
  documented fix, which is "use runbooks" (already selected), not a new
  formal event/incident/problem process).
- **Cost Optimization** (all 11 questions) — 7.1's config change and
  7.3's policy work are real, but neither is a new cost-governance
  *practice* (no cost modeling exercise was re-run, no new pricing-model
  decision was made). No Cost question's answer changed.
- **The three organisational Operational Excellence HIGHs**
  (`priorities`, `ops-model`, `org-culture`) — re-checked, not assumed.
  Unchanged, as ADR 0014 predicted: they measure a team, business
  stakeholders, and a support structure this solo project doesn't have,
  and nothing in 7.1–7.3 changes that.
- **Sustainability** (all 6 questions) — unchanged, unrelated to 7.1–7.3's
  scope.

## Overall

Milestone 6 (`phase-6-observability-and-data-quality-complete`,
2026-09-07) → milestone 7 (`phase-7-end-to-end-validation-complete`,
2026-09-29):

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 6 | 23 | 19 | 10 | 5 |
| Milestone 7 | 23 | 19 | 10 | 5 |

No bucket moved. Two questions (`permissions`, `testing-resiliency`)
gained genuinely new, notes-recorded evidence without crossing. This is
the honest outcome for a phase whose three completed subtasks so far are
a config change (7.1), a verification exercise (7.2), and an identity's
own permission scope (7.3) — none of them is the kind of structural,
pillar-defining work Phase 6's observability build was. It does not mean
the work didn't matter; it means Well-Architected risk buckets are a
coarse instrument, and 7.1–7.3's real value (verified scale, verified
end-to-end reliability, a demonstrably least-privilege operator identity)
shows up in this project's own audit trail — checkpoint.md, `docs/slo.md`'s
first real run-history sample, `iam/cerberus-admin/`'s methodology — more
than in this Tool's checkboxes.

## Consequences

- **This is the platform-wide review, not a diff pass** — but it landed
  on the same baseline milestone 6 already established, because nothing
  in 7.1–7.3 opened new pillar territory the way Phase 6's build did.
  7.5's cost + security summary and 7.6's demo are what remain before
  Phase 7 — and by extension this project — is done.
- **ADR 0013's unauthenticated OpenLineage collector endpoint is still
  open.** It was explicitly deferred out of 7.3's scope (scoped to
  `cerberus-admin` only, not a broader auth sweep) and this review did not
  address it either — no phase currently owns it. It's the most concrete
  candidate for 7.5's security summary to either close or explicitly
  accept as a residual, documented risk.
- **No CloudTrail trail exists in this account** — confirmed directly
  this session (not assumed from a stale note). `detect-investigate-events`
  stays MEDIUM honestly because of this; a trail with S3 delivery would be
  the concrete next step if this question is ever meant to move, and
  would also unlock IAM Access Analyzer's automatic CloudTrail-based
  policy generation for any future least-privilege work (7.3 had to build
  its policies from the default 90-day Event History instead, precisely
  because no trail existed).
- **`cerberus-admin`'s own emergency-access process is now a real,
  documented thing, not an improvised one-off** — see
  `iam/cerberus-admin/README.md`. Future changes to any of the 6 policies
  go through the same root-console path used this session, by design.
- **The three organisational Operational Excellence HIGHs remain the
  standing, expected gap** — ADR 0014 predicted they'd likely outlast
  Phase 7 entirely, and nothing here changes that prediction. 7.5's
  write-up is the natural place to name this honestly rather than let it
  read as an oversight.
