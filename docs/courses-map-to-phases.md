# Courses mapped to Cerberus phases

_Companion to the build — **not a prerequisite for it**. Building Cerberus is
the primary learning path; courses exist to concrete concepts encountered
while building, not to gate the next phase. Nothing here should stall a phase:
skim ahead when a topic is unfamiliar, come back for depth once the hands-on
work has raised real questions. Primary source is KodeKloud (paid access);
AWS Skill Builder and other free resources fill the gaps where KodeKloud has
no coverage._

_Last updated: 2026-08-03_

## Phase numbering

✅ **Reconciled on 2026-08-03.** [plan.md](plan.md), [../Phases.md](../Phases.md),
[../checkpoint.md](../checkpoint.md) and this document all now use the same
0–7 numbering. Phase 0 (foundation, built by hand) is complete; Phase 1 is the
MVP lakehouse.

The previous roadmap ran 0–8. Two of its phases became cross-cutting tracks
rather than disappearing: the old "Phase 1 — IaC foundation" is now Terraform
work absorbed into every phase, and the old "Phase 8 — Architecture hardening"
is now a per-phase Well-Architected pass with the formal review as the Phase 7
capstone. Anything written before 2026-08-03 (early checkpoint.md history,
commit messages) uses the old numbering.

## Cross-cutting tracks (not a phase — every phase)

### Terraform / IaC

**Confirmed: the whole platform is built as IaC in Terraform.** The old Phase 1
was a dedicated "re-create Phase 0 as Terraform" phase; in the re-scoped
structure there is no such phase, so IaC becomes cross-cutting instead —
every phase provisions its own resources as code rather than deferring it to
a catch-up phase. This holds plan.md's guiding principle #2 ("after Phase 0,
no resource is created by hand") and puts the state backend already built by
hand in subtask 0.5 to work from Phase 1 onward.

Terraform is learned alongside the build, not before it — but it is the one
topic worth a head start, since every phase depends on it.

| Course | Source | Duration | When |
|---|---|---|---|
| Terraform for Beginners | KodeKloud | 4h 45m | Head start before Phase 1 — the one course worth front-loading |
| AWS Workshop with Terraform | KodeKloud | — | Alongside the build; project-shaped practice (state, modules, workspaces, CI/CD) |
| HashiCorp Terraform Associate (003/004) | KodeKloud | — | Optional; only if you want the certification |

### Architecture skill (the deliberate focus)

Architecture is a habit built by repetition, not a course you finish once.
The recommended loop: read the Well-Architected pillars early, then re-review
your own build against them at the end of **every** phase — writing an ADR
each time. That is what turns "I built it" into "I can defend why."

| Resource | Source | Cost | Notes |
|---|---|---|---|
| **AWS Well-Architected Foundations** | AWS Skill Builder | **Free** | ~1.5h, fundamental level. Covers all pillars: operational excellence, security, reliability, performance efficiency, cost optimization, sustainability. **Start here — do this before Phase 1.** |
| AWS Well-Architected Labs | wellarchitectedlabs.com | **Free** | Hands-on labs per pillar. Use as the "apply it" half after the course above. |
| AWS Well-Architected for Enterprises | AWS Skill Builder | **Free** | Newer, scale/business-alignment angle. Good second pass, not a starting point. |
| AWS Architecture Center | aws.amazon.com/architecture | **Free** | Reference architectures + diagrams. Use as a pattern library when designing each phase. |
| AWS Well-Architected Tool | AWS console | **Free** | Run an actual review against your own workload. Ideal capstone for Phase 7. |
| AWS Certified Solutions Architect – Associate | KodeKloud | 48h 15m | The deep architecture course. Long — treat as a parallel long-run track, not a phase blocker. |

## Phase-by-phase mapping

### Phase 1 — MVP lakehouse

_Synthetic payments data through bronze → silver → gold, Glue Data Catalog,
Athena queryable — all provisioned as Terraform._

| Course | Source | Duration | Priority |
|---|---|---|---|
| AWS Cloud Practitioner Certification | KodeKloud | 10h 30m | Core |
| AWS S3 | KodeKloud | 3h 45m | Core — storage classes, versioning, lifecycle, encryption, replication; directly informs the medallion layout |
| AWS IAM | KodeKloud | 2h | Core — STS, access control, least privilege |
| Terraform for Beginners | KodeKloud | 4h 45m | Core (see cross-cutting) |
| AWS Well-Architected Foundations | Skill Builder | ~1.5h free | Core (see cross-cutting) |

**Gap — no dedicated KodeKloud coverage:**
- **Glue Data Catalog** — only a ~5 min module inside the SAA course.
- **Athena** — only ~5 min + a ~7 min demo inside SAA / Developer Associate.
- **dbt** — nothing at all.

Fill with: AWS Skill Builder free digital courses on Glue and Athena, the
[AWS Glue](https://docs.aws.amazon.com/glue/) and
[Athena](https://docs.aws.amazon.com/athena/) docs, and
[dbt Fundamentals](https://learn.getdbt.com) (free, vendor-provided).

### Phase 2 — Event-driven ingestion

_Lambda replaces the Phase 0 systemd timer; S3 events / EventBridge._

| Course | Source | Duration | Priority |
|---|---|---|---|
| AWS Lambda | KodeKloud | 2h 15m | Core — event sources, permissions, concurrency, networking, containers |

Good coverage; no significant gap. EventBridge is touched in the KodeKloud
CloudWatch course (see Phase 6) if you want it earlier.

### Phase 3 — Scalable compute

_Spark on EKS via the Spark Operator._

| Course | Source | Duration | Priority |
|---|---|---|---|
| AWS EKS | KodeKloud | 4h 16m | Core — EKS networking, storage, load balancers, scaling, Karpenter, cluster access |

**Gap — no KodeKloud coverage of Spark or the Spark Operator.**
Fill with: the [Spark Operator docs](https://www.kubeflow.org/docs/components/spark-operator/),
AWS's EMR on EKS material on Skill Builder, and the Apache Spark docs.

⚠️ **Cost:** EKS is not free tier (~$0.10/hr control plane). Provision, run,
`terraform destroy` — same discipline as plan.md's Phase 4 note.

### Phase 4 — Orchestration (Step Functions)

_Full ingest → transform → serve as one orchestrated run, with retries._

**Gap — no dedicated KodeKloud Step Functions course.** Only a ~12 min
module inside SAA and a Step Functions demo in the course notes.

Fill with:
- AWS Skill Builder free Step Functions digital course
- [AWS Step Functions Workshop](https://catalog.workshops.aws) — free, hands-on
- [Step Functions docs](https://docs.aws.amazon.com/step-functions/)

This is the thinnest course coverage of any phase — budget extra self-directed
time here.

### Phase 5 — CI/CD

_`terraform plan` on PR, `apply` on merge._

| Course | Source | Duration | Priority |
|---|---|---|---|
| AWS CodePipeline | KodeKloud | 3h 30m | Core — CI/CD integration, security, cost, monitoring, CodeCommit, CodeBuild |

Good coverage. Note the course is CodePipeline-specific; if you choose GitHub
Actions instead, the concepts transfer but the tooling won't.

### Phase 6 — Observability & data quality

_Pipeline health, data freshness, alerting — plus bad data failing loudly._

| Course | Source | Duration | Priority |
|---|---|---|---|
| **AWS CloudWatch** | KodeKloud | — | Core — alarms, dashboards, logs, EventBridge, Insights, X-Ray. Dedicated course, not a module. |

**Partial gap — data quality is not covered.** CloudWatch handles the
infrastructure half of this phase; data-quality testing does not appear in the
KodeKloud catalog at all. Fill with dbt tests (dbt Fundamentals, above) or
[Great Expectations docs](https://docs.greatexpectations.io).

### Phase 7 — End-to-end test with synthetic payments data

_Full platform exercise: generate synthetic payments data, run it through
every layer, verify the whole thing works._

No course maps cleanly here — this phase is the exam, not the lesson. It
exercises everything already learned.

Recommended companions:
- **AWS Well-Architected Tool** (free, in console) — run a real review of the
  finished platform. This is the natural capstone artifact.
- **AWS Certified Solutions Architect – Associate** (KodeKloud, 48h 15m) — if
  the long track was run in parallel, this is where it pays off.

Note: payments data implies thinking about PII/PCI-shaped concerns even when
synthetic. Worth an ADR on why synthetic data was chosen and what the
data-handling posture would be with real data.

## Recommended sequencing

The build sets the pace. Courses slot in around it.

**Worth doing up front (short, high-leverage — ~6h total):**

1. AWS Well-Architected Foundations _(free, ~1.5h)_ — frames how you judge
   every design decision that follows; cheapest possible investment
2. Terraform for Beginners _(4h 45m)_ — the one place where going in cold
   costs more time than the course takes, since every phase provisions as code

**Reach for while building, when the phase raises the question:** AWS S3 and
AWS IAM during Phase 1, Lambda during Phase 2, EKS during Phase 3, Step
Functions self-study during Phase 4, CodePipeline during Phase 5, CloudWatch
during Phase 6. Start the phase, hit the unknown, then take the course — the
material lands better against a concrete problem than in the abstract.

**Long-running in the background:** AWS Cloud Practitioner (10h 30m, broad and
non-blocking), SAA (48h 15m), and the Well-Architected labs. These are breadth
tracks — never block a phase on them.

## Courses in the KodeKloud Cloud Engineer path that Cerberus does not use

The path is multi-cloud; Cerberus is AWS-only. These reinforce nothing in this
project — take them for career-path completion on their own schedule:
GCP Digital Cloud Leader, AZ-900, AZ-104, DP-900, AZ-305, AZ-500, Azure
Kubernetes Service, Google Kubernetes Engine, AWS ECS, Amazon EC2, AWS RDS.

Also noted: KodeKloud's **Data Engineering Fundamentals** course (ingestion,
storage, transformation, serving) would be the single best fit for Phase 1,
but as of 2026-08-03 it is **not yet released** — the page only offers a
notify-me form. Worth checking again when Phase 1 starts.
