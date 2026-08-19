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
- **Architecture** — every phase closes with a Well-Architected pass over its
  own work plus an ADR. This is a real checkbox in each phase below, not an
  aspiration: architecture is built by repetition, so it is tracked like any
  other deliverable. Two parts are required to check a "Well-Architected pass
  + ADR" subtask off (3.8, 4.5, 5.5, 6.6, 7.4), not just the ADR: also save a
  new milestone on the `cerberus-platform` AWS Well-Architected Tool workload
  (`phase-N-<slug>-complete`). See [docs/plan.md](docs/plan.md)'s
  Architecture guiding principle and [checkpoint.md](checkpoint.md)'s
  Reference section / Notes for the method and current milestone state.
- **Cost + tagging** — resources are tagged when created, not retrofitted.
  Cost is reviewed as part of each phase's Well-Architected pass rather than
  batched into a cleanup phase.

## Phase 0 — Foundation (built by hand) ✅

- [x] 0.1 Repo scaffold
- [x] 0.2 AWS account hygiene + billing alarm
- [x] 0.3 Manual S3 bronze bucket
- [x] 0.4 Bash ingestion script on a systemd timer
- [x] 0.5 Manual Terraform state backend (S3 + DynamoDB lock)

_Predates the per-phase Well-Architected pass. Its deliberate shortcut —
`cerberus-admin` holding `AdministratorAccess` — is repaid by 7.3._

## Phase 1 — MVP: end-to-end lakehouse 🎯 ✅

- [x] 1.1 ADR: medallion layout (bronze/silver/gold conventions, partitioning)
- [x] 1.2 ADR: synthetic payments data model
- [x] 1.3 Synthetic payments generator landing raw records in bronze
- [x] 1.4 Terraform: S3 medallion module (bronze/silver/gold)
- [x] 1.5 Terraform: adopt the hand-built state backend as code
- [x] 1.6 Terraform: IAM module (least-privilege roles for the above)
- [x] 1.7 Minimal transform promoting bronze → silver → gold
- [x] 1.8 Glue Data Catalog schema registration
- [x] 1.9 dbt project + gold models
- [x] 1.10 Athena demo query against gold
- [x] 1.11 Verify `terraform apply` builds and `terraform destroy` tears down cleanly
- [x] 1.12 MVP architecture write-up (definition-of-done artifact)
- [x] 1.13 Well-Architected pass + ADR

## Phase 2 — Event-driven ingestion ✅

- [x] 2.1 Lambda ingestion function
- [x] 2.2 S3 event / EventBridge trigger
- [x] 2.3 IAM role for the Lambda
- [x] 2.4 ADR: push vs. pull ingestion
- [x] 2.5 Retire the Phase 0 systemd timer
- [x] 2.6 Well-Architected pass + ADR

## Phase 3 — Scalable compute ✅

- [x] 3.1 VPC design for the cluster (subnets, AZs, routing) + ADR
- [x] 3.2 EKS cluster module (spin-up/destroy pattern, not standing infra)
- [x] 3.3 Multi-AZ node group decision
- [x] 3.4 Spark Operator install
- [x] 3.5 Spark job manifest against S3
- [x] 3.6 Verify writes to silver/gold
- [x] 3.7 `terraform destroy` after each run (cost discipline)
- [x] 3.8 Well-Architected pass + ADR

## Phase 4 — Orchestration ⬜

- [x] 4.1 ADR: Step Functions vs. Airflow
- [x] 4.2 State machine definition as code
- [x] 4.3 Retries + visibility
- [ ] 4.4 Full ingest → transform → serve flow as one orchestrated run
- [ ] 4.5 Well-Architected pass + ADR

## Phase 5 — CI/CD ⬜

- [ ] 5.1 `terraform plan` on PR
- [ ] 5.2 `terraform apply` on merge
- [ ] 5.3 Pipeline code CI (lint/test)
- [ ] 5.4 Green build badge on README
- [ ] 5.5 Well-Architected pass + ADR

## Phase 6 — Observability & data quality ⬜

- [ ] 6.1 CloudWatch dashboards (pipeline health, data freshness)
- [ ] 6.2 CloudWatch alarms + slow-job alerting
- [ ] 6.3 dbt tests or Great Expectations suite
- [ ] 6.4 Lineage
- [ ] 6.5 SLO write-up
- [ ] 6.6 Well-Architected pass + ADR

## Phase 7 — End-to-end platform validation ⬜

- [ ] 7.1 Scaled-up synthetic payments workload
- [ ] 7.2 Full orchestrated run exercising every layer
- [ ] 7.3 Least-privilege IAM review (repay Phase 0's `AdministratorAccess`)
- [ ] 7.4 Self-run Well-Architected review across the whole platform
      (AWS Well-Architected Tool)
- [ ] 7.5 Cost + security summary
- [ ] 7.6 End-to-end demo (GIF or short video)

---

When every subtask in a phase is checked: mark that phase ✅ Complete here,
flip its status cell in [docs/plan.md](docs/plan.md)'s roadmap table,
record the completion in [checkpoint.md](checkpoint.md), and reconcile
[README.md](README.md)'s status badges and roadmap references —
`/end-day` keeps all four in sync together.
