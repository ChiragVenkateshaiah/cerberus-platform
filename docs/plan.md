

# cerberus-platform — Build Plan

_Last updated: 2026-07-30 · Status: living document_

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

## The MVP — Milestone 1

The MVP is the **thinnest lakehouse that works end to end**:

> Raw data is ingested and lands in S3 **bronze** → a minimal transform promotes
> it through **silver** to **gold** → the gold layer is queryable in **Athena** —
> and the entire stack is provisioned by `terraform apply`.

**Definition of done:**
- A reviewer runs a single Athena query against the gold table and gets a result.
- `terraform apply` builds the whole thing from nothing; `terraform destroy`
  removes it cleanly.
- The pipeline runs on a schedule without manual intervention.

The MVP spans **Phases 0–2**. Everything after Phase 2 is "greater engineering"
layered on top of a platform that already works.

## Roadmap overview

| Phase | Theme | Stack introduced | Course alignment | Status |
|------:|-------|------------------|------------------|--------|
| 0 | Manual foundation | Git, AWS CLI, S3, IAM, bash, systemd | DevOps prereq, Linux | 🔨 In progress |
| 1 | IaC foundation | Terraform | Terraform for Beginners | ⬜ Planned |
| 2 | **MVP: end-to-end lakehouse** | Athena, Glue Data Catalog, dbt | AWS fundamentals, S3 | ⬜ Planned |
| 3 | Event-driven ingestion | Lambda, S3 events / EventBridge | AWS Lambda | ⬜ Planned |
| 4 | Scalable compute | EKS, Spark Operator | AWS EKS | ⬜ Planned |
| 5 | Orchestration | Airflow (or Step Functions) | — | ⬜ Planned |
| 6 | CI/CD & GitOps | GitHub Actions / CodePipeline | AWS CodePipeline | ⬜ Planned |
| 7 | Observability & data quality | CloudWatch/Grafana, dbt tests | — | ⬜ Planned |
| 8 | Architecture hardening | VPC, secrets, cost, multi-AZ | AWS SAA | ⬜ Planned |

🎯 **MVP is complete at the end of Phase 2.**

## Phases in detail

### Phase 0 — Manual foundation
- **Goal:** Stand up the project skeleton and land raw data in S3 by hand.
- **Stack:** Git/GitHub, AWS CLI, S3, IAM, bash, systemd.
- **Tasks:** 0.1 repo scaffold · 0.2 AWS account hygiene + billing alarm ·
  0.3 manual S3 bronze bucket · 0.4 bash ingestion script on a systemd timer ·
  0.5 manual Terraform state backend (S3 + DynamoDB lock).
- **Done when:** raw data lands in `s3://.../bronze/` on a schedule, created
  entirely by hand.
- **Artifact:** the scaffolded public repo + a working ingestion script.

### Phase 1 — IaC foundation
- **Goal:** Re-create everything from Phase 0 as Terraform.
- **Stack:** Terraform (state backend module, S3 medallion module, IAM module).
- **Done when:** `terraform apply` reproducibly builds the storage + IAM
  foundation; `terraform destroy` tears it down; remote state is in S3 with
  DynamoDB locking.
- **Artifact:** reusable Terraform modules + ADR on the medallion layout.

### Phase 2 — MVP: end-to-end lakehouse 🎯
- **Goal:** Make data flow end to end and become queryable.
- **Stack:** a minimal transform (SQL/PySpark/dbt) promoting bronze → silver →
  gold, Glue Data Catalog for schema, Athena for query, dbt for the gold models.
- **Done when:** the MVP definition of done above is met.
- **Artifact:** a working, queryable lakehouse + a demo query + architecture
  write-up. **This is the first thing worth putting on a resume.**

### Phase 3 — Event-driven ingestion
- **Goal:** Replace the scheduled bash pull with event-driven ingestion.
- **Stack:** Lambda triggered by S3 events / EventBridge.
- **Done when:** dropping a file (or an upstream event) triggers ingestion
  automatically, no timer required.
- **Artifact:** Lambda function as code + ADR (push vs. pull ingestion).

### Phase 4 — Scalable compute
- **Goal:** Move the heavy transform onto distributed compute.
- **Stack:** Spark on EKS (via the Spark Operator).
- **Cost note:** EKS is **not** free-tier (~$0.10/hr control plane). Provision,
  run the job, `terraform destroy`. Treat as a spin-up/tear-down module.
- **Done when:** a Spark job runs on EKS against S3 and writes to silver/gold.
- **Artifact:** EKS + Spark manifests as code; doubles as CKA-adjacent practice.

### Phase 5 — Orchestration
- **Goal:** Turn a sequence of jobs into a managed pipeline.
- **Stack:** Airflow (on EKS) or AWS Step Functions for a serverless-cheap path.
- **Done when:** the full ingest → transform → serve flow runs as one
  orchestrated DAG with retries and visibility.
- **Artifact:** DAG definition + ADR (Airflow vs. Step Functions trade-off).

### Phase 6 — CI/CD & GitOps
- **Goal:** No manual `apply`. Changes ship through a pipeline.
- **Stack:** GitHub Actions or CodePipeline; `terraform plan` on PR,
  `apply` on merge; optional Argo CD for GitOps.
- **Done when:** a merged PR safely updates infrastructure and pipeline code.
- **Artifact:** pipeline config + a green build badge on the README.

### Phase 7 — Observability & data quality
- **Goal:** Make the platform operable and trustworthy — the platform-
  engineering differentiator.
- **Stack:** CloudWatch or Prometheus/Grafana dashboards; dbt tests or Great
  Expectations for data quality; pipeline health + slow-job alerting; lineage.
- **Done when:** dashboards show pipeline health and data freshness, and bad
  data fails the pipeline loudly instead of landing silently.
- **Artifact:** dashboards + data-quality suite + an SLO write-up.

### Phase 8 — Architecture hardening
- **Goal:** Refactor against the Well-Architected pillars — the SAA capstone.
- **Stack:** proper VPC design, least-privilege IAM review, secrets management,
  multi-AZ, cost optimization, tagging.
- **Done when:** the platform survives a self-run Well-Architected review.
- **Artifact:** a hardening ADR set + a cost/security summary.

## North-star architecture

```
                        ┌─────────────────────────────────────────────┐
                        │                Orchestration                 │  (Phase 5)
                        │            Airflow / Step Functions          │
                        └───────────────────┬─────────────────────────┘
                                            │ triggers
  source(s)        ingestion               ▼           transform            serving
 ┌────────┐      ┌────────────┐      ┌────────────┐   ┌────────────┐     ┌──────────────┐
 │ files  │─────▶│ bash→Lambda│─────▶│  S3 bronze │──▶│ Spark/dbt  │────▶│ S3 silver/   │
 │ RDS/API│      │  (P0 / P3) │      │   (raw)    │   │ (P2 / P4)  │     │  gold        │
 └────────┘      └────────────┘      └────────────┘   └────────────┘     └──────┬───────┘
                                                                                 │
                                                        Glue Catalog ◀───────────┤
                                                                                 ▼
                                                                          ┌──────────────┐
                                                                          │   Athena     │  (query)
                                                                          │  + dbt (gold)│
                                                                          └──────────────┘

 Cross-cutting: Terraform (all infra) · IAM (least privilege) · CI/CD (P6)
                Observability + data quality (P7) · Well-Architected (P8)
```

## How this maps to the three roles

- **Data Platform Engineering:** Phases 2, 4, 5, 7 (lakehouse, distributed
  transform, orchestration, data quality/lineage).
- **Platform Engineering:** Phases 1, 6, 7 (IaC, CI/CD, observability,
  reliability).
- **Cloud Engineering:** Phases 0, 3, 4, 8 (AWS breadth, serverless, Kubernetes,
  Well-Architected).

A reviewer can enter from any of the three angles and find evidence.

## Portfolio multipliers (optional but high-leverage)

- One short write-up per milestone (README section or blog post): _what_ you
  built, _why_ that design, _what_ you'd do differently.
- An ADR for every non-obvious decision — the ADR log becomes the project's
  narrative.
- A short demo (GIF or 2-minute video) once the MVP is live.
