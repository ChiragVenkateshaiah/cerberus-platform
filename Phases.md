# Phases

_Tracks phase and subtask completion status against
[docs/plan.md](docs/plan.md)'s roadmap. Phase goals, stack choices, and
"done when" criteria are defined there — this file only checks off progress
against that plan; it does not redefine it. Subtask breakdowns for phases
that haven't started yet are a reasonable first pass, not a fixed spec —
refine them once the phase actually starts. Session-to-session narrative and
the specific "what's next" live in [checkpoint.md](checkpoint.md)._

## Status legend

⬜ Planned · 🔨 In progress · ✅ Complete

## Cross-cutting (not phases)

- **IaC in Terraform** — every resource from Phase 1 onward is provisioned as
  code; each phase writes its own modules. No separate conversion phase.
- **Architecture** — each phase closes with a Well-Architected pass over its
  own work plus an ADR recording the reasoning.

## Phase 0 — Foundation (built by hand) ✅

- [x] 0.1 Repo scaffold
- [x] 0.2 AWS account hygiene + billing alarm
- [x] 0.3 Manual S3 bronze bucket
- [x] 0.4 Bash ingestion script on a systemd timer
- [x] 0.5 Manual Terraform state backend (S3 + DynamoDB lock)

## Phase 1 — MVP: end-to-end lakehouse 🎯 ⬜

- [ ] 1.1 ADR: medallion layout (bronze/silver/gold conventions, partitioning)
- [ ] 1.2 ADR: synthetic payments data model
- [ ] 1.3 Synthetic payments generator landing raw records in bronze
- [ ] 1.4 Terraform: S3 medallion module (bronze/silver/gold)
- [ ] 1.5 Terraform: adopt the hand-built state backend as code
- [ ] 1.6 Terraform: IAM module (least-privilege roles for the above)
- [ ] 1.7 Minimal transform promoting bronze → silver → gold
- [ ] 1.8 Glue Data Catalog schema registration
- [ ] 1.9 dbt project + gold models
- [ ] 1.10 Athena demo query against gold
- [ ] 1.11 Verify `terraform apply` builds and `terraform destroy` tears down cleanly
- [ ] 1.12 MVP architecture write-up (definition-of-done artifact)

## Phase 2 — Event-driven ingestion ⬜

- [ ] 2.1 Lambda ingestion function
- [ ] 2.2 S3 event / EventBridge trigger
- [ ] 2.3 IAM role for the Lambda
- [ ] 2.4 ADR: push vs. pull ingestion
- [ ] 2.5 Retire the Phase 0 systemd timer

## Phase 3 — Scalable compute ⬜

- [ ] 3.1 EKS cluster module (spin-up/destroy pattern, not standing infra)
- [ ] 3.2 Spark Operator install
- [ ] 3.3 Spark job manifest against S3
- [ ] 3.4 Verify writes to silver/gold
- [ ] 3.5 `terraform destroy` after each run (cost discipline)

## Phase 4 — Orchestration ⬜

- [ ] 4.1 ADR: Step Functions vs. Airflow
- [ ] 4.2 State machine definition as code
- [ ] 4.3 Retries + visibility
- [ ] 4.4 Full ingest → transform → serve flow as one orchestrated run

## Phase 5 — CI/CD ⬜

- [ ] 5.1 `terraform plan` on PR
- [ ] 5.2 `terraform apply` on merge
- [ ] 5.3 Pipeline code CI (lint/test)
- [ ] 5.4 Green build badge on README

## Phase 6 — Observability & data quality ⬜

- [ ] 6.1 CloudWatch dashboards (pipeline health, data freshness)
- [ ] 6.2 CloudWatch alarms + slow-job alerting
- [ ] 6.3 dbt tests or Great Expectations suite
- [ ] 6.4 Lineage
- [ ] 6.5 SLO write-up

## Phase 7 — End-to-end platform validation ⬜

- [ ] 7.1 Scaled-up synthetic payments workload
- [ ] 7.2 Full orchestrated run exercising every layer
- [ ] 7.3 Self-run Well-Architected review (AWS Well-Architected Tool)
- [ ] 7.4 Cost + security summary
- [ ] 7.5 End-to-end demo (GIF or short video)

---

When every subtask in a phase is checked: mark that phase ✅ Complete here,
flip its status cell in [docs/plan.md](docs/plan.md)'s roadmap table, and
record the completion in [checkpoint.md](checkpoint.md) — `/end-day` does
all three together.
