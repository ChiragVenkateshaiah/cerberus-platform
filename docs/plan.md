# cerberus-platform — Build Plan

_Last updated: 2026-08-03 · Status: living document_

## Purpose

`cerberus-platform` is a portfolio project that demonstrates end-to-end
competence across three overlapping roles:

- **Data Platform Engineering** — a working lakehouse: ingestion, medallion
  storage, transformation, a queryable serving layer, data quality, and lineage.
- **Platform Engineering** — everything provisioned as code, with CI/CD,
  orchestration, observability, and reliability baked in rather than bolted on.
- **Cloud Engineering** — real AWS breadth (S3, IAM, Lambda, EKS, Athena,
  networking) designed against Well-Architected principles.

The goal is not a demo that runs once. It is a repository whose commit history,
ADRs, and phased deliverables read as evidence that the author can design,
build, automate, and operate a data platform.

## Guiding principles

1. **Ship a thin end-to-end slice first.** A minimal pipeline that ingests,
   stores, transforms, and serves data is worth more than a half-built
   ingestion layer. Get to "queryable" fast, then deepen.
2. **Everything as code.** After Phase 0, no resource is created by hand. If
   it isn't in Terraform, it doesn't exist.
3. **Build by hand once, then automate.** Each foundational piece is created
   manually first (to understand it), then re-created as code (to own it).
4. **Every phase is a portfolio artifact.** Each phase ends with something
   demonstrable: a module, an ADR, a screenshot, or a short write-up.
5. **Cost discipline is a feature.** Free tier wherever possible; non-free
   resources (notably EKS) are spun up per-exercise and destroyed immediately.
   `terraform destroy` is part of the workflow, not an afterthought.
6. **Decisions are recorded.** Every significant choice becomes a numbered ADR
   in `docs/adr/`.
7. **The build leads, courses follow.** Building this platform is the primary
   learning path; courses concrete concepts encountered while building and
   never gate a phase. See
   [courses-map-to-phases.md](courses-map-to-phases.md).
8. **Phase work ships via PR, tagged at completion.** Starting Phase 2, each
   phase's implementation work (the actual code/infra/docs a subtask
   produces) happens on a branch and merges into `main` via a reviewed PR —
   one PR per phase by default, split into more if a phase's scope
   genuinely warrants it. Merges are regular merges, never squashed —
   history stays intact, not flattened. This is a followed **convention**,
   not GitHub branch protection: there's no CI check yet for a protection
   rule to gate on (that arrives in Phase 5's `terraform plan` on PR), so
   enforcing it in GitHub today would only police ceremony. Routine
   `/start-day`/`/end-day` checkpoint-only commits (`Phases.md`,
   `checkpoint.md`, no code) are exempt — they stay direct-to-`main`, as
   they always have, since there's no code in them to review. Every phase
   completion also gets an annotated git tag (`vN-<phase-name>`, e.g.
   `v1-mvp`) as a fixed, portfolio-referenceable milestone — Phases 0 and 1
   were tagged retroactively (`v0-foundation`, `v1-mvp`) since they predate
   this principle and already lived as direct-to-`main` history not worth
   rewriting.

## The data domain — synthetic payments

From Phase 1 onward the platform models **synthetic payments data**:
transactions, merchants, customers, settlement status. Chosen because it is
richer than a telemetry feed (joins, aggregations, late-arriving records,
status transitions all fall out naturally), it is a domain reviewers
immediately understand, and it forces real thinking about PII-shaped handling
even though every record is generated.

Phase 0's weather ingestion was a placeholder to prove the ingestion mechanism
end to end. It remains in the repository as the Phase 0 artifact; the payments
generator supersedes it as the pipeline's data source from Phase 1.

## Cross-cutting tracks

These are not phases — they run through every phase.

- **IaC in Terraform.** Every resource from Phase 1 onward is provisioned as
  code against the state backend hand-built in Phase 0. There is no separate
  "convert to Terraform" phase; each phase writes its own modules.
- **Architecture.** Every phase closes with a Well-Architected pass against
  its own work and an ADR recording the reasoning — tracked as a real subtask
  in [Phases.md](../Phases.md), not left as an aspiration. Architecture is
  built by repetition across phases, not deferred to a hardening phase at the
  end. Hardening concerns land where they belong: VPC design and multi-AZ with
  EKS in Phase 3, the least-privilege IAM review in Phase 7, tagging at
  creation time throughout.
- **Cost + tagging.** Resources are tagged when created, never retrofitted.
  Cost is reviewed in each phase's Well-Architected pass rather than batched
  into a cleanup phase.

## The MVP — Milestone 1

The MVP is the **thinnest lakehouse that works end to end**:

> Synthetic payments data is ingested and lands in S3 **bronze** → a minimal
> transform promotes it through **silver** to **gold** → the gold layer is
> queryable in **Athena** — and the entire stack is provisioned by
> `terraform apply`.

**Definition of done:**
- A reviewer runs a single Athena query against the gold table and gets a result.
- `terraform apply` builds the whole thing from nothing; `terraform destroy`
  removes it cleanly.
- The pipeline runs on a schedule without manual intervention.

The MVP spans **Phases 0–1**. Everything after Phase 1 is "greater engineering"
layered on top of a platform that already works.

## Roadmap overview

| Phase | Theme | Stack introduced | Course alignment | Status |
|------:|-------|------------------|------------------|--------|
| 0 | Foundation (built by hand) | Git, AWS CLI, S3, IAM, bash, systemd | DevOps prereq, Linux | ✅ Complete |
| 1 | **MVP: end-to-end lakehouse** | Terraform, Glue Data Catalog, Athena, dbt | AWS Cloud Practitioner, S3, IAM, Terraform | ✅ Complete |
| 2 | Event-driven ingestion | Lambda, S3 events / EventBridge | AWS Lambda | ⬜ Planned |
| 3 | Scalable compute | EKS, Spark Operator | AWS EKS | ⬜ Planned |
| 4 | Orchestration | AWS Step Functions | _(course gap — AWS workshop)_ | ⬜ Planned |
| 5 | CI/CD | AWS CodePipeline | AWS CodePipeline | ⬜ Planned |
| 6 | Observability & data quality | CloudWatch, dbt tests | AWS CloudWatch | ⬜ Planned |
| 7 | End-to-end platform validation | synthetic payments at scale, Well-Architected review | AWS SAA _(parallel track)_ | ⬜ Planned |

🎯 **MVP is complete at the end of Phase 1.**

## Phases in detail

### Phase 0 — Foundation (built by hand) ✅
- **Goal:** Stand up the project skeleton and land raw data in S3 by hand.
- **Stack:** Git/GitHub, AWS CLI, S3, IAM, bash, systemd.
- **Tasks:** 0.1 repo scaffold · 0.2 AWS account hygiene + billing alarm ·
  0.3 manual S3 bronze bucket · 0.4 bash ingestion script on a systemd timer ·
  0.5 manual Terraform state backend (S3 + DynamoDB lock).
- **Done when:** raw data lands in `s3://.../bronze/` on a schedule, created
  entirely by hand.
- **Artifact:** the scaffolded public repo + a working ingestion script.
- **Live resources:** see [Existing infrastructure](#existing-infrastructure).

### Phase 1 — MVP: end-to-end lakehouse 🎯 ✅
- **Goal:** Make synthetic payments data flow end to end and become queryable —
  provisioned entirely as Terraform.
- **Stack:** Terraform (medallion S3 module, IAM module, state backend as
  code), a synthetic payments generator, a minimal transform promoting
  bronze → silver → gold, Glue Data Catalog for schema, Athena for query,
  dbt for the gold models.
- **Done when:** the MVP definition of done above is met — `terraform apply`
  builds it, `terraform destroy` removes it, and an Athena query against gold
  returns a result.
- **Artifact:** reusable Terraform modules + a working, queryable lakehouse +
  a demo query + ADRs (medallion layout, synthetic data design) + an
  architecture write-up. **This is the first thing worth putting on a resume.**

### Phase 2 — Event-driven ingestion
- **Goal:** Replace the scheduled bash pull with event-driven ingestion.
- **Stack:** Lambda triggered by S3 events / EventBridge.
- **Done when:** dropping a file (or an upstream event) triggers ingestion
  automatically, no timer required; the Phase 0 systemd timer is retired.
- **Artifact:** Lambda function as code + ADR (push vs. pull ingestion).

### Phase 3 — Scalable compute
- **Goal:** Move the heavy transform onto distributed compute.
- **Stack:** Spark on EKS (via the Spark Operator), on a purpose-designed VPC.
- **Networking:** this is the one part of the platform that genuinely needs VPC
  design — subnets, AZ spread, routing — since the rest of the stack is
  serverless. Multi-AZ node groups are decided here too, not deferred.
- **Cost note:** EKS is **not** free-tier (~$0.10/hr control plane). Provision,
  run the job, `terraform destroy`. Treat as a spin-up/tear-down module.
- **Done when:** a Spark job runs on EKS against S3 and writes to silver/gold.
- **Artifact:** VPC + EKS + Spark manifests as code, an ADR on the network
  design; doubles as CKA-adjacent practice.

### Phase 4 — Orchestration
- **Goal:** Turn a sequence of jobs into a managed pipeline.
- **Stack:** AWS Step Functions — serverless, pay-per-transition, no standing
  scheduler to host or pay for.
- **Done when:** the full ingest → transform → serve flow runs as one
  orchestrated state machine with retries and visibility.
- **Artifact:** state machine definition as code + ADR (Step Functions vs.
  Airflow trade-off).

### Phase 5 — CI/CD
- **Goal:** No manual `apply`. Changes ship through a pipeline.
- **Stack:** AWS CodePipeline; `terraform plan` on PR, `apply` on merge.
- **Done when:** a merged PR safely updates infrastructure and pipeline code.
- **Artifact:** pipeline config + a green build badge on the README.

### Phase 6 — Observability & data quality
- **Goal:** Make the platform operable and trustworthy — the platform-
  engineering differentiator.
- **Stack:** CloudWatch dashboards, alarms and log insights for infrastructure
  health; dbt tests (or Great Expectations) for data quality; pipeline health
  and slow-job alerting; lineage.
- **Done when:** dashboards show pipeline health and data freshness, and bad
  data fails the pipeline loudly instead of landing silently.
- **Artifact:** dashboards + data-quality suite + an SLO write-up.

### Phase 7 — End-to-end platform validation
- **Goal:** Prove the whole platform works as one system under a realistic
  synthetic payments workload — the capstone.
- **Stack:** scaled-up synthetic payments generation exercising every layer;
  the AWS Well-Architected Tool for a formal platform-wide self-review.
- **Security debt:** this is where Phase 0's deliberate shortcut is repaid —
  `cerberus-admin` still holds `AdministratorAccess`, and the least-privilege
  review scopes it (and every per-phase role) down to what is actually used.
- **Done when:** a full run from generated payments through bronze/silver/gold
  to an Athena result completes orchestrated, monitored, and tested — and the
  platform survives a self-run Well-Architected review.
- **Artifact:** an end-to-end demo (GIF or short video), a Well-Architected
  review write-up, and a cost/security summary.

## Existing infrastructure

Live AWS resources, all created by hand during Phase 0 and reused from Phase 1
onward rather than rebuilt:

| Resource | Identifier | Purpose |
|---|---|---|
| S3 bucket | `cerberus-platform-bronze-131715059025` | Bronze (raw) layer |
| S3 bucket | `cerberus-platform-tfstate-131715059025` | Terraform remote state |
| DynamoDB table | `cerberus-platform-tfstate-lock` | Terraform state locking |
| CloudWatch alarm | `cerberus-billing-alarm-10usd` | Billing guard ($10/mo) |
| SNS topic | `cerberus-billing-alerts` | Billing alarm delivery |
| IAM user | `cerberus-admin` | Working (non-root) identity |

All in `us-east-1`. Silver and gold buckets do not exist yet — they arrive in
Phase 1 as Terraform.

## North-star architecture

```
                        ┌─────────────────────────────────────────────┐
                        │                Orchestration                 │  (Phase 4)
                        │             AWS Step Functions               │
                        └───────────────────┬─────────────────────────┘
                                            │ triggers
  source            ingestion              ▼           transform            serving
 ┌────────┐      ┌────────────┐      ┌────────────┐   ┌────────────┐     ┌──────────────┐
 │synthetic│────▶│ bash→Lambda│─────▶│  S3 bronze │──▶│ Spark/dbt  │────▶│ S3 silver/   │
 │payments │     │  (P0 / P2) │      │   (raw)    │   │ (P1 / P3)  │     │  gold        │
 └────────┘      └────────────┘      └────────────┘   └────────────┘     └──────┬───────┘
                                                                                 │
                                                        Glue Catalog ◀───────────┤
                                                                                 ▼
                                                                          ┌──────────────┐
                                                                          │   Athena     │  (query)
                                                                          │  + dbt (gold)│
                                                                          └──────────────┘

 Cross-cutting: Terraform (all infra) · IAM (least privilege) · CI/CD (P5)
                Observability + data quality (P6) · Well-Architected (every phase, P7 capstone)
```

## How this maps to the three roles

- **Data Platform Engineering:** Phases 1, 3, 4, 6 (lakehouse, distributed
  transform, orchestration, data quality/lineage).
- **Platform Engineering:** Phases 1, 5, 6 (IaC, CI/CD, observability,
  reliability).
- **Cloud Engineering:** Phases 0, 2, 3, 7 (AWS breadth, serverless,
  Kubernetes, Well-Architected).

A reviewer can enter from any of the three angles and find evidence.

## Portfolio multipliers (optional but high-leverage)

- One short write-up per milestone (README section or blog post): _what_ you
  built, _why_ that design, _what_ you'd do differently.
- An ADR for every non-obvious decision — the ADR log becomes the project's
  narrative.
- A short demo (GIF or 2-minute video) once the MVP is live.
