# 12. Phase 5 Well-Architected review

Date: 2026-08-24

## Status

Accepted

## Context

Phase 5 — CI/CD — is built and verified live (5.1–5.4 done): ADR 0011
chose GitHub Actions authenticating via OIDC federation over AWS
CodePipeline, split `envs/dev` into `dev-standing` (CI-managed) and
`dev-compute` (human-run only), and added a new `github_oidc` module with
two IAM roles (`cerberus-ci-plan` read-only/any-PR, `cerberus-ci-apply`
write-scoped/`main`-only). `terraform plan` now runs on every PR and
`terraform apply` runs unattended on every merge to `main`, both proven
live after closing 9 real IAM permission gaps across three live-apply
attempts; a `code-ci.yml` workflow lints Python (ruff) and validates the
dbt project (`dbt parse` + sqlfluff) on every PR; three build-status
badges on the README make all of it visible.

Per `Phases.md`'s cross-cutting rule, every phase closes with a
Well-Architected pass plus an ADR. Following the diff-based pattern ADR
0004 set up and ADR 0006/0008/0010 continued: milestone 4
(`phase-4-orchestration-complete`) is the baseline, and this ADR only
touches the questions Phase 5's actual work changed the honest answer to
or added genuine new evidence for.

## What Phase 5 actually changed, pillar by pillar

Five questions were re-answered against the `cerberus-platform` workload
in the Well-Architected Tool. Two gained a genuinely new selected choice;
three gained real new evidence recorded in their notes without crossing a
risk bucket. All five verified live via `aws wellarchitected update-answer`.

**Operational Excellence / `dev-integ`** ("How do you reduce defects, ease
remediation, and improve flow into production?") — milestone 4's own notes
named this pass's exact target in advance: *"No CI/CD build system yet
(Phase 5) and no linting -- real gaps."* Added **"Use build and deployment
management systems"**: GitHub Actions (`terraform-plan.yml`,
`terraform-apply.yml`, `code-ci.yml`) is now a real build/deployment
management system, not a gap conceded and deferred. **Stayed MEDIUM** — 6
of 10 choices selected now, up from 5, not enough to cross the bucket.
Deliberately did **not** select "Fully automate integration and
deployment": `envs/dev-compute` (EKS/Spark) stays human-run-only by
design (ADR 0007/0009's spin-up/destroy cost discipline), so "fully"
would overstate what's actually automated — the same discipline ADR 0010
used declining `event-response`.

**Security / `permissions`** (already this project's strongest Security
area — "Define access requirements," "Grant least privilege access,"
"Reduce permissions continuously," "Analyze public and cross account
access" all selected) — added **"Share resources securely with a third
party"**: `cerberus-ci-plan`/`cerberus-ci-apply` are the first AWS access
this project has ever granted to something outside the AWS account
itself. The grant is real evidence for this exact choice, not a stretch:
OIDC federation (no static key ever leaves AWS), a name-prefix-scoped
write policy, and a deliberate self-escalation guard (`cerberus-ci-apply`
cannot modify its own policy, the OIDC provider, or `cerberus-ci-plan`'s
policy — only a human running `terraform apply` as `cerberus-admin` can).
**Stayed MEDIUM** — 5 of 9 choices now, up from 4.

**Security / `identities`** (HIGH; "Use strong sign-in mechanisms," "Use
temporary credentials," "Store and use secrets securely" already
selected) — no new checkbox, but real new evidence for the already-selected
"temporary credentials": Phase 5 extends it to a machine identity outside
AWS entirely. GitHub Actions authenticates via OIDC, minting short-lived
STS credentials per workflow run, scoped by the token's `repository`/`ref`
claims — no AWS access key is stored in GitHub for CI or anything else.
**Stayed HIGH**, same as ADR 0010's `mitigate-interaction-failure`
pattern: real reinforcement, not a new box.

**Operational Excellence / `mit-deploy-risks`** (MEDIUM; "Plan for
unsuccessful changes," "Test deployments," "Employ safe deployment
strategies" already selected) — "Test deployments" was previously a
manual habit (run `terraform plan` by hand before applying); Phase 5 made
it an enforced, automatic gate — `terraform-plan.yml` posts the plan diff
as a PR comment on every PR, `code-ci.yml` lints/validates Python and dbt
code the same way. Considered but did **not** select "Automate testing
and rollback": rollback stays entirely manual — Phase 5 added automated
testing, not automated rollback, and the choice requires both. **Stayed
MEDIUM.**

**Reliability / `tracking-change-management`** (MEDIUM; "Deploy changes
with automation" already selected) — milestone 4's notes claimed this on
the strength of `terraform apply` always running through Terraform rather
than the console, but every actual apply through Phase 4 was still a
human running that command from a terminal. Phase 5 makes the claim
strictly true rather than aspirational: `terraform-apply.yml` runs
`terraform apply` unattended in CI on every merge to `main`. **Stayed
MEDIUM** — real evidence recorded, no new checkbox available on this
question for it.

**Overall risk-count movement: none** — worth stating plainly, the same
way ADR 0010 did. ADR 0010's own Consequences section predicted the
opposite for this phase specifically: *"Phases whose work is more
orthogonal to what's already been credited (e.g. Phase 5's CI/CD, which
opens entirely new Operational Excellence and Security ground) are more
likely to move buckets."* That prediction didn't hold. Phase 5's evidence
is real and genuinely new (two new checkboxes, three reinforced
questions), but it landed in questions that already had partial credit
from Phase 1's IAM design (1.6) and Phase 1's Terraform-first discipline
(1.5/1.11) — the same shape of outcome ADR 0010 found for Phase 4, for a
different underlying reason.

## Considered, not changed

- **Security / `detect-investigate-events`** (MEDIUM, only "Configure
  service and application logging" selected) — the 2026-08-21 OIDC
  trust-policy bug was found by reading CloudTrail's actual rejected
  `AssumeRoleWithWebIdentity` calls. Tempting to credit "Capture logs,
  findings, and metrics in standardized locations," but that one
  CloudTrail query was ad hoc manual investigation during debugging, not
  a standing log-aggregation or alerting capability — the honest answer
  stays unchanged, real Phase 6 territory.
- **Security / `securely-operate`** (HIGH, 5 of 8 already selected,
  including "Automate deployment of standard security controls" from
  every IAM policy being Terraform code) — the two new CI roles are
  exactly more of this already-credited practice, not new ground.
- **Cost Optimization** — Phase 5's `dev-standing`/`dev-compute` split
  IS a cost decision (ADR 0011's Context), but it's a decision about
  which resources CI is even allowed to touch, not a new service-selection
  or demand-management practice on top of what Phase 1–4 already chose.
  No Cost Optimization question's answer changed.

## Overall

Milestone 4 (`phase-4-orchestration-complete`, 2026-08-20) → milestone 5
(`phase-5-cicd-complete`, 2026-08-24):

| | HIGH | MEDIUM | NONE | N/A |
|---|---|---|---|---|
| Milestone 4 | 25 | 18 | 9 | 5 |
| Milestone 5 | 25 | 18 | 9 | 5 |

No question moved buckets this pass. Two questions gained a genuinely new
selected choice (`dev-integ`'s build/deployment management system,
`permissions`'s third-party sharing), and three gained real, specific,
live-verified new evidence in their notes (`identities`, `mit-deploy-risks`,
`tracking-change-management`) without crossing the Tool's internal risk
threshold. Consistent with ADR 0010's precedent: worth recording honestly
rather than padding the diff with a bucket change the evidence doesn't
support.

## Consequences

- Phase 5 is now fully closed — 5.1–5.5 all done.
- ADR 0010's prediction that Phase 5 would be more likely to move buckets
  than Phase 4 (because it opens new ground) did not hold in practice —
  worth remembering for Phase 6/7's own predictions: "opens new ground"
  and "moves a risk bucket" are not the same claim, and this project has
  now seen two consecutive phases confirm that.
- The two genuinely new checkboxes this pass (`dev-integ`'s build system,
  `permissions`'s third-party sharing) are both direct, unambiguous
  consequences of ADR 0011's OIDC design — a clean example of an ADR's
  decision showing up as concrete Well-Architected evidence rather than
  a coincidence.
- Milestone 5 becomes the baseline 6.6's pass diffs against, continuing
  the chain ADR 0004 started.
