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
8. **Work ships via PR-per-push, tagged at phase completion.** Superseded
   2026-08-12 — the original branch-per-phase/PR-per-phase shape (below)
   lasted one day before being dropped in favor of visible daily activity;
   the replacement pins that down properly instead of leaving it inferred
   from inconsistent practice. Each unit of work — a subtask, a fix, a
   review finding, not necessarily a whole phase — ships on its own branch
   and merges into `main` via a PR, same-day rather than batched to the end
   of a phase. Merges are regular merges, never squashed — history stays
   intact, not flattened. This is a followed **convention**, not GitHub
   branch protection: there's no CI check yet for a protection rule to gate
   on (that arrives in Phase 5's `terraform plan` on PR), so enforcing it in
   GitHub today would only police ceremony. Routine `/start-day`/`/end-day`
   checkpoint-only commits (`Phases.md`, `checkpoint.md`, no code) are
   exempt — they stay direct-to-`main`, as they always have, since there's
   no code in them to review. Every phase completion also gets an annotated
   git tag (`vN-<phase-name>`, e.g. `v1-mvp`) as a fixed,
   portfolio-referenceable milestone — Phases 0 and 1 were tagged
   retroactively (`v0-foundation`, `v1-mvp`) since they predate this
   principle and already lived as direct-to-`main` history not worth
   rewriting.

   _Superseded shape (2026-08-10 to 2026-08-11):_ phase implementation work
   happened on a branch and merged via one PR per phase by default, split
   into more only if a phase's scope genuinely warranted it. Abandoned after
   one day (2026-08-11) because batching a whole phase into a single PR
   read as less active than daily commits — but the replacement wasn't
   actually written down until now, so 2026-08-11's work shipped
   inconsistently (one phase-batched PR, one direct-to-`main` push) under a
   policy that no longer matched practice.

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
  creation time throughout. Each pass has **two required parts, not one**:
  the ADR, and saving a new milestone on the `cerberus-platform` AWS
  Well-Architected Tool workload (named `phase-N-<slug>-complete`) — the
  subtask isn't done until both exist, not just the ADR. checkpoint.md's
  Reference section has the method (read the pillars as a design lens
  continuously; the Tool review only after a phase's work actually exists)
  and the workload's current tracked milestone state.
- **Cost + tagging.** Resources are tagged when created, never retrofitted.
  Cost is reviewed in each phase's Well-Architected pass rather than batched
  into a cleanup phase.
- **AWS Agent Toolkit** (`aws-core@claude-plugins-official`, installed
  2026-08-11, user scope) is in scope for the rest of the build. Two
  capabilities: its MCP doc-search/read tools, always available and the
  fallback for anything no packaged skill covers — notably Terraform, since
  no `aws-terraform` skill exists at all — and its 20 packaged skills, used
  where they map to a remaining phase: `aws-compute` (4.1, Step Functions),
  `aws-observability` (Phase 6), `aws-iam` (7.3), `aws-sdk-python-usage`
  (boto3 pattern-checking, already caught one real bug in Phase 2).
  `aws-containers` is named for ECS/Fargate/ECR, not EKS specifically, so
  its actual usefulness for Phase 3 is unconfirmed — worth checking at 3.2.

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
| 2 | Event-driven ingestion | Lambda, S3 events / EventBridge | AWS Lambda | ✅ Complete |
| 3 | Scalable compute | EKS, Spark Operator | AWS EKS | ✅ Complete |
| 4 | Orchestration | AWS Step Functions | _(course gap — AWS workshop)_ | ✅ Complete |
| 5 | CI/CD | AWS CodePipeline | AWS CodePipeline | ✅ Complete |
| 6 | Observability & data quality | CloudWatch, dbt tests | AWS CloudWatch | ✅ Complete |
| 7 | End-to-end platform validation | synthetic payments at scale, Well-Architected review, Prometheus metrics for EKS/Spark | AWS SAA _(parallel track)_ | ✅ Complete |
| 8 | Scale validation | Apache Iceberg, incremental processing, Spark tuning, node autoscaling + Spot, AWS Budgets | _(course gap — Iceberg and Spark docs)_ | 🔨 In progress |
| 9 | Pipeline status & alerting | Prometheus exporter for the batch pipeline, PromQL, Grafana dashboards as code, Alertmanager, SLO burn-rate alerts, a terminal status view | _(Prometheus and Grafana docs; Google SRE Workbook, alerting on SLOs)_ | ⬜ Planned |
| 10 | Databricks interoperability | Unity Catalog federation to AWS Glue (Cerberus's Iceberg tables, no copy), Databricks Terraform provider, serverless SQL and jobs, Lakeflow | _(Databricks Academy; Databricks docs)_ | ⬜ Planned |
| 11 | Platform tooling in Go | Go, AWS SDK for Go v2, `cerberusctl` CLI | _(Go docs, AWS SDK for Go v2 examples)_ | ⬜ Planned |
| 12 | Streaming ingestion | Apache Kafka (KRaft, one start/stop EC2 instance), Go producer and consumer | _(Kafka docs; KodeKloud Kafka if available)_ | ⬜ Planned |

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

### Phase 2 — Event-driven ingestion ✅
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
- **Scope addition (2026-10-02): Prometheus for the EKS/Spark layer.**
  Phase 6's CloudWatch observability covers everything serverless/managed
  (Lambda, Step Functions, Fargate, Athena), because those publish to
  CloudWatch natively. The ephemeral EKS cluster and the Spark jobs on it
  (driver/executor, Spark Operator, pod/node metrics) are the one layer it
  doesn't see. Prometheus is the native tool there. The central tension is
  that Prometheus expects a standing server while `dev-compute` is torn down
  after every exercise (ADR 0007), so where metrics live and how they are
  viewed is an ADR decision (ADR 0016), not settled here. The candidates are
  in-cluster only, an in-cluster agent writing to Amazon Managed Service for
  Prometheus, and CloudWatch Container Insights. The constraint is the one
  every ADR since 0005 has held: no new idle cost. Added inside Phase 7
  rather than as a new phase so the closing demo can show it.
- **Done when:** a full run from generated payments through bronze/silver/gold
  to an Athena result completes orchestrated, monitored, and tested — and the
  platform survives a self-run Well-Architected review.
- **Artifact:** an end-to-end demo (GIF or short video) that includes the
  Prometheus/Grafana view of the run, a Well-Architected review write-up, and
  a cost/security summary.

### Phase 8 — Scale validation
- **Goal:** Prove the platform by putting real load on it. Take the same
  pipeline from today's ~40k events to 100M events in three 10x steps
  (about 1M, 10M, 100M), find the bottleneck at each step, and fix it in
  the data layer or the infrastructure, whichever it lives in.
- **Thesis:** platform engineering and data engineering are tested
  together. The data work applies the load; the platform work answers what
  the load breaks. Infrastructure is added only when a measurement shows
  it is needed.
- **Stack:** Apache Iceberg tables in the Glue Data Catalog with
  incremental `MERGE` processing (ADR 0017); a Spark-based synthetic
  generator for large volumes (the ingestion Lambda's 15-minute limit
  cannot produce 100M events); Spark tuning (partition sizing, compaction,
  AQE, skew); node autoscaling and Spot for `dev-compute` (its own ADR);
  AWS Budgets.
- **Measured at every step:** run time, events per second, bytes read and
  written per run, cost per million events, Prometheus series count, and
  the data-quality suite (bronze → silver → gold reconciliation must stay
  clean).
- **Budget:** $20/month on a pay-as-you-go account, about $30 over the
  phase. Budgets alerts at $15 and $20 are in place before the first large
  exercise; the Phase 0 `$10` billing alarm stays as an early warning. Cost
  is checked after each step before climbing to the next one.
- **Timeline:** six weeks (from 2026-10-06).
- **Known risks:** new 7.3 permission gaps for Iceberg, Spot and
  autoscaling calls (expect root-console policy updates). Checked and
  cleared in 8.2 (2026-10-06): the Spot and on-demand vCPU quotas are 32
  each, and the account is on the Paid plan (`freetier
  get-account-plan-state`: `PAID`, `ACTIVE`, run as root because
  `cerberus-admin` can't read it), so the Free-plan EC2 restriction seen
  on 2026-08-18 no longer applies. $147.55 in credits remained, more than
  the whole phase budget; the Budget measures gross cost, so its alerts
  still fire while credits apply.
- **Known need before 100M (found 2026-10-09):** the data-quality suite's
  bronze checks scan all of bronze on every run. At 10M events bronze was
  4.36 GB, five checks passed the workgroup's 1 GiB cutoff and were
  cancelled (`exercise-20261009T074853Z`), so the suite moved to its own
  workgroup with a 10 GiB cutoff. That is a stopgap: each run scans about
  22 GB (about $0.11), and at 100M (about 45 GB of bronze) the same checks
  would cost more than $1 a run and pass any sensible cutoff. Before 8.9,
  the bronze checks must get cheaper -- for example, counting bronze from
  the generator manifests and the Lambda's own files, or checking only the
  runs since the last passing suite.
- **Out of scope:** streaming (Kafka) and Airflow, now Phase 12 (on one
  start/stop EC2 instance, about $70/month if left running, so it follows
  the `dev-compute` spin-up/tear-down pattern); Delta Lake (ADR 0017); any
  language change -- 8.6–8.11 stay in Python, Spark and SQL, so the
  Phase 8 numbers show where the real limits are before Go is introduced
  (Phases 11 and 12).
- **Done when:** a 100M-event run completes orchestrated, with the
  data-quality suite clean, and run time and cost per million events are
  recorded for the 1M, 10M and 100M steps.
- **Artifact:** a results write-up with the per-step numbers and charts, a
  demo video, ADRs for each decision, and Well-Architected milestone 8.

### Phase 9 — Pipeline status & alerting
_Added 2026-10-09, to follow Phase 8 directly._

- **Goal:** Make the result of every pipeline run visible at a glance --
  succeeded or failed, which step failed, how long each step took, how
  many events it processed, and whether the data-quality suite passed --
  on a Grafana dashboard and in the terminal, with an alert when a run
  fails or the data goes stale.
- **Gap it closes:** today a run's outcome is spread across the Step
  Functions console, CloudWatch, the exercise log and the JSON run record
  in `observability/scale/runs/`. The Prometheus agent and Grafana from
  7.7 (ADR 0016) see only the EKS/Spark layer, and only while
  `dev-compute` is up -- they are gone when the question "did last
  night's run pass?" is asked.
- **Why this skill set:** Prometheus, PromQL and Grafana are the
  open-source default for metrics in platform and SRE roles, and the
  skills that set an engineer apart are the layers on top: writing an
  exporter, alert rules and dashboards kept as code and tested in CI,
  and alerting on SLOs and error budgets rather than raw thresholds. This
  phase builds those on the six SLOs from 6.5, so it extends the existing
  stack instead of adding a second one.
- **Stack:** a small Prometheus exporter for the batch pipeline (Python
  `prometheus_client`, reusing what `collect_run_metrics.py` already reads
  from Step Functions and the data-quality suite), following the
  Prometheus batch-job pattern -- last-run status and a last-success
  timestamp per step, not a scrape of a process that has already exited;
  Grafana with provisioned, version-controlled dashboards; Prometheus
  alerting rules with Alertmanager, unit-tested with `promtool test
  rules` in `code-ci.yml`; multi-window, multi-burn-rate SLO alerts; a
  terminal view (`make status`) that runs the same PromQL queries as the
  dashboard, so both always show the same numbers.
- **The central decision (its own ADR):** where pipeline status lives
  while `dev-compute` is down, with no new idle cost -- the rule every ADR
  since 0005 has held. Candidates: a local Docker Compose stack
  (Prometheus, Grafana, Alertmanager, the exporter) that reads AWS on
  demand; the exporter's series written to the standing Amazon Managed
  Service for Prometheus workspace from 7.7 (a few hundred series, cents
  per month) with Grafana run locally or in-cluster; or Grafana Cloud's
  free tier. The ADR also decides dashboard tooling (provisioned JSON as
  in 7.7, or Grafonnet/Jsonnet) and whether the exporter uses the
  OpenTelemetry metrics SDK.
- **Out of scope:** log aggregation (Loki) -- the exercise already saves
  the Spark logs; a Go rewrite of the exporter or the terminal view --
  `cerberusctl status` belongs to Phase 11.
- **Done when:** after a successful run and a deliberately failed one,
  the dashboard and `make status` show each run's status, failed step,
  step timings, events and data-quality result; the failed run fires an
  alert; the alert rules pass `promtool test rules` in CI; and the stack
  costs $0 when idle.
- **Artifact:** a short video of the dashboard and terminal view across
  one passing and one failing run, the ADR, and Well-Architected
  milestone 9.

### Phase 10 — Databricks interoperability
_Added 2026-10-09, after Phase 9 and before the Go tooling. Feature and
cost facts below were checked against the Databricks docs on that date;
re-check them in the phase's ADR._

- **Goal:** Show where Databricks fits in a platform like Cerberus. Read
  Cerberus's Iceberg tables from Databricks with no copy, manage the
  Databricks side as code, and run the same workload on both engines with
  measured run time and cost per million events.
- **Why:** the target roles are platform engineering at companies that
  run Databricks, and solutions-architect or platform roles at Databricks.
  Both meet at one question -- how Databricks fits into the rest of a
  company's platform, and what it costs. Cerberus answers the first half
  from first principles; this phase answers the second half with real
  numbers instead of a feature list.
- **Not a migration:** Cerberus stays the system of record and the only
  writer. Databricks is a second engine reading through the catalog --
  the same "pluggable through the Glue catalog" stance ADR 0002 takes for
  Redshift.
- **Stack:**
  - **Unity Catalog federation to AWS Glue** (GA since March 2025): the
    Glue catalog is mounted as a foreign catalog. Iceberg reads are
    supported; the foreign catalog needs its own `storage_root`.
    Databricks reaches Glue through an IAM role registered as a service
    credential, and S3 through an external location over the
    silver/gold paths.
  - **Databricks Terraform provider** for the Databricks side: the
    connection, service credential, external location, foreign catalog,
    grants and jobs. The IAM role it assumes lives in `dev-standing`.
  - **Serverless SQL warehouse and serverless jobs** only -- no classic
    compute, so no EC2 in the Cerberus account.
  - **Lakeflow Jobs / Lakeflow Declarative Pipelines** with expectations
    for the comparison port of one pipeline step, beside dbt and the
    data-quality suite.
- **Two environments, each for what it allows:**
  - **Free Edition** (no cost, no end date): serverless only, one
    workspace and one metastore, no account console or account-level
    APIs, outbound internet limited to trusted domains, at most 5
    concurrent job tasks, one 2X-Small SQL warehouse, compute shut down
    for the day when the quota is exceeded, non-commercial use only. Use
    it to build and rehearse the port at no cost.
  - **14-day free trial**: usage credits valid for 14 days (the AWS
    Marketplace listing caps them at $400); personal-email trials are
    capped (one SQL warehouse at 50 DBU/h, limited external network
    access). Needed for what Free Edition can't show: federation with
    Cerberus's own IAM role and S3, and account-level configuration.
    **Cost guardrail:** a Marketplace signup or a saved card switches the
    account to pay-as-you-go when the trial ends, so sign up without a
    payment method, keep the cancellation steps (terminate compute,
    remove the card, cancel the plan) in the runbook, and start the
    14-day clock only when the Terraform and the runbook are ready.
- **Measured:** the same input on both engines (the Phase 8 data), run
  time and cost per million events (Cerberus from its run records,
  Databricks from its billing data), plus the code, configuration and
  operational steps each one needs.
- **Open questions for the ADR:** the Glue federation docs require the
  service credential's AWS Lake Formation permissions to stay available,
  while Cerberus grants Glue access through IAM only -- check what that
  means here; whether Free Edition can reach Cerberus's S3 at all, given
  its restricted outbound access; and which provider resources work on a
  Free Edition workspace with no account-level API.
- **Out of scope:** migrating Cerberus to Databricks; Delta Lake as the
  storage format (ADR 0017); writes from Databricks into Cerberus's
  tables; classic compute in the Cerberus VPC; ML and AI features.
- **Done when:** a Databricks SQL query reads Cerberus gold through the
  federated Glue catalog with no copy, under Unity Catalog grants defined
  in Terraform; one pipeline step runs on Databricks with its run time
  and cost recorded beside Cerberus's numbers; and the trial is cancelled
  with $0 of Databricks charges after it.
- **Artifact:** a comparison page (each Cerberus component beside its
  Databricks counterpart, with the measured numbers and what each gives
  up), the ADR, a short demo, and Well-Architected milestone 10.

### Phase 11 — Platform tooling in Go
- **Goal:** Replace the platform's operational scripts with one Go
  command-line tool, `cerberusctl`, that runs an exercise, collects its
  metrics and runs the data-quality suite -- with real concurrency and
  stronger failure handling than Bash.
- **Why Go here:** the work is many independent AWS calls (Athena queries,
  S3 listings, Step Functions and EKS polling, Cost Explorer), which
  goroutines run in parallel; one static binary has no Python environment
  to set up (the workstation's `.venv` drift and `uv` workarounds go away);
  and signal handling (Ctrl-C, SIGTERM, a dead pipe) is explicit code, not
  Bash traps -- the 2026-10-07 SIGPIPE bug that could skip the destroy is
  exactly what Bash makes easy to get wrong.
- **Why after Phase 8:** Phase 8's tools (`exercise.sh`,
  `collect_run_metrics.py`, `data_quality.py`) define the behaviour to
  match, and their run records are the regression test: `cerberusctl`
  must produce the same record for the same run.
- **Stack:** Go (current stable), AWS SDK for Go v2, a small CLI framework
  (standard library `flag`, or Cobra if subcommands warrant it), the
  existing Terraform via `os/exec` for plan/apply/destroy.
- **Scope:** `cerberusctl exercise` (preflight, apply, optional generator,
  execution, collect, guaranteed teardown, account check), `cerberusctl
  collect` (the metric record, `--cost-only`, `--dq-only`), `cerberusctl
  dq` (the 17 checks, all queries in flight at once, fail-closed),
  `cerberusctl status` (Phase 9's terminal view, same PromQL). The SQL
  of the checks stays in one place that both tools read until the Python
  versions are retired.
- **Engineering bar:** unit tests with fakes for the AWS clients, a
  `golangci-lint` + `go test` job in `code-ci.yml`, release binaries built
  in CI, and an ADR for the language and layout decision.
- **Done when:** a full exercise runs through `cerberusctl` with the same
  record and data-quality result as the Python tools, Ctrl-C at any stage
  still ends in the account check, and the Python and Bash versions are
  retired.

### Phase 12 — Streaming ingestion
- **Goal:** Add a streaming path next to the batch one: payment events
  flow through Apache Kafka into bronze continuously, and the Phase 8
  incremental silver job picks them up on its next run.
- **Why Go here:** a high-throughput producer and consumer is where Go's
  goroutines and channels pay off -- many partitions in flight, batching
  and back-pressure as plain code, a small memory footprint, and one
  binary per service in a container. Both are new components written in Go
  from day one, not rewrites.
- **Stack:** Apache Kafka (KRaft mode, one broker) on one start/stop EC2
  instance, following the `dev-compute` spin-up/tear-down pattern; a Go
  producer (synthetic payment events, same schema as ADR 0003) and a Go
  consumer that writes JSON Lines into bronze (a new prefix, decided by
  ADR, next to `payments/` and `payments_bulk/`); Airflow as planned
  earlier, if the phase's ADR still finds a job for it.
- **Measured:** events per second end to end, consumer lag, producer and
  consumer memory and CPU, delivery guarantees (at-least-once, with the
  silver job's insert-only merge on `(transaction_id, event_type)` as the
  deduplication), and cost per hour of the streaming stack.
- **Done when:** a sustained stream lands in bronze, the silver job
  ingests it incrementally with the data-quality suite clean (bronze →
  silver reconciles the new prefix too), and the stack tears down to $0.

## Planned later work (no phase number yet)

_Agreed in discussion and kept here until each one is scheduled -- either
folded into a phase or given its own. Nothing here is built yet._

### Realistic time spread for the synthetic data

_Proposed 2026-10-08, from 8.6's first measurements._

- **Problem:** both producers put every event in the last 7–8 days (the
  ingestion Lambda's 7-day creation window; the bulk generator's same
  window). So every new batch touches the same few days that hold almost
  all of silver, and day pruning -- correct and in place since 8.6 --
  saves almost nothing (13.33 → 12.61 MB read in the local test). Real
  payment data spans months and years, with a busy recent edge and a long,
  quieter history.
- **Plan:** give the bulk generator a configurable history -- events spread
  across days, weeks, months and years, with realistic shapes (weekday and
  hour-of-day patterns, month-end peaks, growth over time) -- and keep each
  new batch landing mostly in the recent days, as real ingestion does. Same
  schema, lifecycle rules and determinism as ADR 0018.
- **What it unlocks:** measurements that mean what they would in
  production -- partition pruning (a batch touches a few of hundreds of day
  partitions), broadcast and hash-join choices (a small batch against a
  large, spread-out history), the size of the anti-join shuffle against a
  realistic silver, file counts and compaction per partition, and
  Athena's pruning on time-filtered gold queries. It also makes the 10M and
  100M steps a realistic larger load, not a denser copy of one week.
- **Where it fits:** best before the 10M step of Phase 8, so 8.6's
  before/after numbers are taken on the realistic shape; otherwise as the
  first item of whichever phase picks it up.

### Spark 4 and Java 17 for the Spark jobs

_Proposed 2026-10-08, from 8.6's bucketing test._

- **Why:** two limits found on `apache/spark:3.5.9` (Java 11). Iceberg
  1.11+ is built for Java 17, so the platform is pinned to Iceberg 1.10.2.
  And Spark 3.5 has no one-side storage-partitioned join
  (`spark.sql.sources.v2.bucketing.shuffle.enabled` arrived in Spark 4.0):
  a bucketed silver can avoid shuffling its keys only when both join sides
  are bucketed tables, so an incoming batch can't use it.
- **Scope:** move the transform and generator to Spark 4 on Java 17; with
  it, Scala 2.13 artifacts, a matching `hadoop-aws`, the OpenLineage
  listener, the Iceberg runtime (1.12+), and the Spark Operator's support
  for Spark 4. Then re-test bucketed silver with one-side SPJ against the
  8.6 baseline.
- **Done when:** the orchestrated run, the generator and the data-quality
  suite pass on the new stack, and the silver anti-join's shuffle is
  measured with and without one-side SPJ.
- **Its own unit of work:** every Spark dependency changes at once, so it
  is planned and tested on its own, not mixed into a scale step.

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
| AWS Budget | `My Monthly Cost Budget` | Gross monthly cost (credits and refunds excluded), whole account. Raised from $10 to $20 for Phase 8 (8.2, 2026-10-06), with email alerts at 75% actual ($15), 100% actual ($20) and 100% forecast. Kept out of Terraform on purpose, like the billing alarm: a CI-applied role should not be able to raise the account's own spending cap. |
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
