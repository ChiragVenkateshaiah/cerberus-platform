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

## Phase 0 — Manual foundation 🔨

- [x] 0.1 Repo scaffold
- [ ] 0.2 AWS account hygiene + billing alarm
- [ ] 0.3 Manual S3 bronze bucket
- [ ] 0.4 Bash ingestion script on a systemd timer
- [ ] 0.5 Manual Terraform state backend (S3 + DynamoDB lock)

## Phase 1 — IaC foundation ⬜

- [ ] 1.1 Terraform state backend module (re-create 0.5 as code)
- [ ] 1.2 S3 medallion module (re-create 0.3 as code; bronze/silver/gold)
- [ ] 1.3 IAM module (least-privilege roles for the modules above)
- [ ] 1.4 ADR: medallion layout
- [ ] 1.5 Verify `terraform apply` builds and `terraform destroy` tears down cleanly

## Phase 2 — MVP: end-to-end lakehouse 🎯 ⬜

- [ ] 2.1 Minimal transform (SQL/PySpark/dbt) promoting bronze → silver → gold
- [ ] 2.2 Glue Data Catalog schema registration
- [ ] 2.3 dbt project + gold models
- [ ] 2.4 Athena demo query against gold
- [ ] 2.5 Architecture write-up (MVP definition-of-done artifact)

## Phase 3 — Event-driven ingestion ⬜

- [ ] 3.1 Lambda ingestion function
- [ ] 3.2 S3 event / EventBridge trigger
- [ ] 3.3 IAM role for the Lambda
- [ ] 3.4 ADR: push vs. pull ingestion
- [ ] 3.5 Retire the Phase 0 systemd timer

## Phase 4 — Scalable compute ⬜

- [ ] 4.1 EKS cluster module (spin-up/destroy pattern, not standing infra)
- [ ] 4.2 Spark Operator install
- [ ] 4.3 Spark job manifest against S3
- [ ] 4.4 Verify writes to silver/gold
- [ ] 4.5 `terraform destroy` after each run (cost discipline)

## Phase 5 — Orchestration ⬜

- [ ] 5.1 ADR: Airflow vs. Step Functions
- [ ] 5.2 DAG / state machine definition
- [ ] 5.3 Retries + visibility
- [ ] 5.4 Full ingest → transform → serve flow as one orchestrated run

## Phase 6 — CI/CD & GitOps ⬜

- [ ] 6.1 `terraform plan` on PR
- [ ] 6.2 `terraform apply` on merge
- [ ] 6.3 Pipeline code CI (lint/test)
- [ ] 6.4 Optional Argo CD for GitOps
- [ ] 6.5 Green build badge on README

## Phase 7 — Observability & data quality ⬜

- [ ] 7.1 CloudWatch or Prometheus/Grafana dashboards
- [ ] 7.2 dbt tests or Great Expectations suite
- [ ] 7.3 Pipeline health + slow-job alerting
- [ ] 7.4 Lineage
- [ ] 7.5 SLO write-up

## Phase 8 — Architecture hardening ⬜

- [ ] 8.1 VPC design
- [ ] 8.2 Least-privilege IAM review
- [ ] 8.3 Secrets management
- [ ] 8.4 Multi-AZ
- [ ] 8.5 Cost optimization + tagging
- [ ] 8.6 Self-run Well-Architected review write-up

---

When every subtask in a phase is checked: mark that phase ✅ Complete here,
flip its status cell in [docs/plan.md](docs/plan.md)'s roadmap table, and
record the completion in [checkpoint.md](checkpoint.md) — `/end-day` does
all three together.
