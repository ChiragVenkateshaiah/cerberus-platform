# Cost and security summary

_Phase 7.5. What this platform has actually cost, where its security
posture stands at the end of the build, and the residual risks it carries
deliberately. Written against live account state on 2026-10-02 rather than
the Terraform code alone. Its companion is
[ADR 0015](adr/0015-phase-7-well-architected-review.md), the platform-wide
Well-Architected review. That ADR scores the platform; this document names
the money and the open doors._

---

## Cost

### What was spent

From Cost Explorer (unblended cost, queried 2026-10-02), split by region.
The platform lives entirely in `us-east-1`. Spend in other regions comes
from resources this project never created.

| Month | Platform (`us-east-1`) | Not the platform (`ap-south-2`) | Credits applied | Out of pocket |
|---|---|---|---|---|
| 2026-05 | — | $0.43 | −$0.43 | $0.00 |
| 2026-06 | — | $2.52 | −$2.52 | $0.00 |
| 2026-07 | $0.00 | $2.18 | −$2.19 | $0.00 |
| 2026-08 | $4.06 | $0.73 | −$4.79 | $0.00 |
| 2026-09 | $1.68 | $0.73 | −$2.41 | $0.00 |
| 2026-10 (to date) | $0.00 | $0.005 | −$0.006 | $0.00 |

**The platform cost $5.74 gross over the whole build, and nothing out of
pocket**: AWS credits absorbed every dollar of usage, every month. Even
without credits, no month came within half of the `$10/month` budget, and
the `cerberus-billing-alarm-10usd` alarm (Phase 0) never fired.

July shows $0.00 for the platform because Phases 0–1 (S3, Glue, Athena,
Lambda, the state backend) all sit inside free-tier or sub-cent usage.
Real spend starts with Phase 3's first EKS spin-up on 2026-08-18.

### Where it went

The $5.74 splits into three buckets:

| Bucket | Cost | Share | Line items |
|---|---|---|---|
| **An orphaned Elastic IP** | $2.26 | 39% | `PublicIPv4:IdleAddress`, 2026-08-19 → 2026-09-07 |
| **`dev-compute` exercises** | $3.20 | 56% | EC2 nodes `m7i-flex.large` $0.95, NAT Gateway hours $0.90 + bytes $0.40, EKS control plane $0.59, regional data transfer $0.26, in-use public IPv4 $0.09 |
| **Everything standing** | $0.28 | 5% | S3 requests + storage, Fargate task-seconds, ECR storage, the rest under a cent each |

The orphaned Elastic IP was the most expensive item in the platform's
history, more than the EKS control plane and every NAT Gateway hour
combined. CloudTrail tells the story. A partial-apply crash on 2026-08-19,
during Phase 4's live pass (see checkpoint.md's 2026-08-20 entry), issued
two `AllocateAddress` calls 13 minutes apart. Terraform state recorded
only the second. The first (`eipalloc-09f39f00f2dfd06cd`) sat outside
state and unattached for about 450 hours. It was found by hand and
released during the next `dev-compute` exercise on 2026-09-07 (PR #34's
session).

The lesson is about *verification*, not design. The 2026-08-20 cleanup
reconciled the crash's orphans against what was visibly wrong (a duplicate
VPC, IAM roles, log groups), and an unattached EIP isn't visibly wrong. The
cheap safeguard is to make every teardown's "0 EIP" check account-wide
(`aws ec2 describe-addresses`, empty) rather than state-relative. A
partial-apply crash creates exactly the resources state doesn't know
about.

The `dev-compute` exercises themselves were efficient. Four exercises
over two months cost $3.20 in total, which is the dormant-by-default
design (ADR 0007) working as intended. Standing infrastructure cost
**$0.28 across three months**.

**Not the platform:** a stopped `t3.micro` in `ap-south-2` (Hyderabad),
`sre-lab` (`i-0b65d9fb63ede2e26`), launched 2026-06-29, predating this
project. It accounts for all spend in May–July, and its EBS volume kept
billing about $0.73/month while stopped, which made it the account's only
ongoing cost. It was never a cerberus-platform resource. 7.5 surfaced it,
and the account owner terminated it on 2026-10-02, from root CloudShell
(`cerberus-admin` has no `ec2:TerminateInstances`). Its root volume had
`DeleteOnTermination = true`, so that cost stops entirely. The account
now has no ongoing spend outside the platform.

### Why it stays this cheap

The cost profile is a design outcome, not luck. Three decisions carry it:

- **Dormant by default.** The only billed-by-the-hour infrastructure (the
  EKS control plane, its nodes, and the NAT Gateway) lives in
  `envs/dev-compute` and is destroyed after every exercise (ADR 0007,
  3.7). `pipeline_active = false` keeps the daily schedule `DISABLED`
  between exercises (ADR 0011, amended 2026-09-01), so nothing burns
  Fargate starts against a cluster that isn't there.
- **Pay-per-request everywhere standing.** Lambda, Step Functions, ECS
  Fargate, Athena, the HTTP API, and EventBridge Scheduler all cost
  nothing while idle. The ADRs that picked them (0005, 0009, 0011, 0013)
  each named cost as the deciding pillar.
- **Scan-cost discipline in the data layout.** Parquet + partitioning
  from silver on (ADR 0002), so an Athena query against gold scans
  kilobytes, not the whole lake.

### Tagging

Every Terraform root sets `default_tags { Project = "cerberus-platform" }`
at the provider, so every taggable resource has been tagged since creation
(the cross-cutting rule in [Phases.md](../Phases.md)), with per-module
`Phase`/`Component` tags on top.

**Verified live** via the Resource Groups Tagging API: **41 of the 43**
tagged resources in `us-east-1` carry `Project=cerberus-platform`. The two
exceptions are both expected:

- `cerberus-billing-alarm-10usd`, hand-built in Phase 0 before IaC.
- A billing payment instrument, which is not a platform resource.

That API only lists resources that support tagging, and IAM roles are
under-represented in its output. So "41/43" describes the taggable
inventory, not every IAM entity.

**Tagging wasn't connected to billing until 7.5.** Through Phase 7.4,
`Project` (like every user-defined tag here) was `Inactive` as a
cost-allocation tag. The tags worked as an inventory, but Cost Explorer
couldn't group spend by them. That's why the attribution above had to be
done by region and usage type rather than by `Project`, which only worked
because the one non-platform resource happened to sit in another region.
The account owner activated `Project` from the root console on 2026-10-02
(`cerberus-admin` deliberately lacks `ce:UpdateCostAllocationTagsStatus`).
Verified `Active` via `ce:ListCostAllocationTags`. From here on, Cost
Explorer and Budgets can scope spend to `Project=cerberus-platform`
directly. Data appears within about 24 hours, and the build months only
show it if a backfill is requested.

---

## Security

### Identity: how every caller authenticates

| Caller | Mechanism | Since |
|---|---|---|
| Human operator | IAM user `cerberus-admin`, SigV4 via CLI profile, **6 customer-managed least-privilege policies** built from its full CloudTrail history; `AdministratorAccess` removed | 7.3 |
| CI (GitHub Actions) | OIDC federation, no stored AWS keys. `cerberus-ci-plan` (AWS `ReadOnlyAccess` plus state-lock writes) for PRs; `cerberus-ci-apply` trusted only for `refs/heads/main` | ADR 0011 |
| Ingestion / probe / collector Lambdas | Per-function execution roles | Phases 2, 6 |
| Orchestration | Per-task ECS task roles + a separate execution role; Step Functions role | Phase 4 |
| Spark on EKS | IRSA (pod-level role), not node-role inheritance | Phase 3 |
| OpenLineage producers → collector | **Unauthenticated, exercise windows only.** See residual risk 1 | ADR 0013, 7.5 |

There are no long-lived secrets in this stack apart from `cerberus-admin`'s
own access key. No API keys, no database passwords, no Secrets Manager
entries. That was a deliberate constraint from the 2026-08-03 re-scope.

### Data protection

- **Encryption at rest:** all four S3 bucket groups the code creates
  (medallion, Athena results, lineage events, Terraform state) use SSE-S3
  (`AES256`) with bucket keys. No customer-managed KMS keys anywhere in
  the stack: SSE-S3 is sufficient for synthetic data, and each CMK adds a
  monthly per-key cost. EKS Secrets aren't envelope-encrypted with a CMK
  either, since the cluster holds no application secrets.
- **No public buckets:** every bucket has all four S3 Block Public Access
  settings on and `BucketOwnerEnforced` object ownership.
- **Immutable bronze:** append-only and versioned, so silver and gold can
  always be rebuilt (ADR 0002). This is the platform's recovery story.
- **Synthetic data only.** No real PII or card data ever enters the
  platform (ADR 0003). That bounds the impact of every residual risk
  below.

### Changes made in 7.5

- **The lineage collector is no longer unauthenticated around the clock.**
  The route's `authorization_type` now follows `pipeline_active`: `NONE`
  during a compute exercise, `AWS_IAM` otherwise. No identity in the
  account holds `execute-api:Invoke` on it, so outside an exercise every
  request is rejected `403` at API Gateway, before the Lambda runs.
  `collector_url` stays stable, so the ECS task definitions that embed it
  don't change.
- **`cerberus-admin` gained read-only cost and tag visibility**
  (`ce:GetCostAndUsage`, `ce:GetCostForecast`, `ce:ListCostAllocationTags`,
  `tag:GetResources`), applied through 7.3's root-only path. The
  write-side neighbours (`ce:UpdateCostAllocationTagsStatus`,
  `tag:TagResources`) stay denied, verified via `iam:simulate-custom-policy`.
- **`Project` activated as a cost-allocation tag** (root console). See
  Tagging above.
- **The non-platform `sre-lab` instance in `ap-south-2` was terminated**
  (root CloudShell), ending the account's only ongoing non-platform cost.
  See "Where it went" above.

---

## Residual risks, accepted deliberately

Each of these is a known gap, chosen rather than overlooked. Each records
what would change the decision.

### 1. The lineage collector is unauthenticated during exercises

**State:** `POST /api/v1/lineage` accepts anonymous requests while
`pipeline_active = true`, throttled to 10 req/s steady and 20 burst
(verified live 2026-10-02).

**Why accepted:** ADR 0013's three grounds still hold. The endpoint's
whole capability is writing one JSON object to a private, 90-day-expiring
prefix. `openlineage-spark` has no SigV4 transport. A shared key would
introduce the stack's first real secret. 7.5 narrows the exposure from
24/7 to the few hours per month an exercise runs.

**Would change if:** the platform ever handled real data, or an exercise
window became a standing deployment. Then the answer is a SigV4 sidecar
or a custom transport, not an API key.

### 2. No CloudTrail trail

**State:** confirmed absent (`describe-trails` empty, 2026-10-02). Only
the default 90-day management-event Event History exists.

**Why accepted:** the Event History was enough for 7.3's policy
generation. A trail would also need `cloudtrail:*` grants pushed through
the root-only path, plus a new module and bucket, for an account that
holds only synthetic data. It keeps the Well-Architected question
`detect-investigate-events` at MEDIUM, honestly.

**Would change if:** audit history past 90 days became necessary, or a
future least-privilege pass wanted IAM Access Analyzer's automatic,
trail-based policy generation. A management-events trail to a
lifecycle-expiring bucket is the concrete next step: the first trail is
free, and storage costs cents.

### 3. `cerberus-admin`'s own permission changes require root

**State:** `cerberus-admin` cannot modify its own policies, by design
([iam/cerberus-admin/README.md](../iam/cerberus-admin/README.md)). 7.5's
policy change went through the root console. A standing IAM user with
policy-edit keys was considered and rejected, because it would re-create
`AdministratorAccess` one API call away.

**Trade-off:** every policy change needs a human at the root console.
That friction is the control. An MFA-gated, policy-edit-only role
assumable by `cerberus-admin` is the documented middle ground if changes
ever become frequent.

### 4. Three organisational Operational Excellence HIGHs

`priorities`, `ops-model`, and `org-culture` stay HIGH in the
Well-Architected Tool. They ask about team structures, business
stakeholders, and organisational culture, which a single-person
portfolio project doesn't have to evidence. ADR 0014 and ADR 0015 both
predicted they would outlast Phase 7. They're named here as a standing,
expected gap, not an oversight.

### 5. Carried operational debt (not security, recorded for completeness)

- **`null_resource.build_and_push`** can't run on a CI runner, so
  runner-image changes need a local apply first. The fix (a CI
  build/push job) widens CI's blast radius to ECR pushes, so it remains
  its own deferred decision.
- **Faker Lambda-layer hash churn:** a cosmetic 1-add/1-change/1-destroy
  on every `dev-standing` apply.
