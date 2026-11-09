# Plan: README refresh (portfolio-grade)

Date: 2026-11-09. Planner: Opus. Base: `main` at `ca48bfa`. Branch `docs-readme-refresh` in worktree `/home/chirag/projects/cerberus-docs-readme-refresh`. No ADR needed. No `Phases.md` change (cross-cutting README reconciliation in the `Phases.md` footer).

## 1. Question

Rewrite `README.md` so a hiring manager or engineer can see in two minutes what Cerberus is, what it proved at 100M events, and how it is built. Why now: the 100M take was recorded on 2026-11-08 (PR #136). The current README is a 14-phase changelog with wrong facts:
- The Mermaid diagram shows CodePipeline and a systemd timer.
- It calls ADR 0025 "proposed". It was accepted on 2026-11-08.
- It describes Phase 9 as "one start/stop EC2 instance". ADR 0024 replaced that design.

## 2. Facts (verified unless marked)

**The 100M take** (record `observability/scale/runs/demo-100m-20261108T135119Z.json`, on main):
- `status` SUCCEEDED, `run_seconds` 859.1, `events_processed` 100,001,897, `events_per_second` 116,409.
- Per-state seconds: InvokeIngestion 1.1, RunTransform 618.3, RunDbt 178.3, RunServingQuery 61.3.
- Silver 249,121,312 events, 81,745,183 transactions. 249,121,312 − 100,001,897 = 149,119,415 = silver in `rehearsal-1m-20261108T060517Z.json`.
- Data quality: passed, 26 checks, 0 errors, 1 warning (`token_digit_runs`, legacy hex tokens). `bronze_to_silver_count`: bronze 249121312, silver 249121312. Suite scanned 153.1 GB in 34.0 s.
- Prometheus peak 9,424 active series. Generator: 8 partitions, 1,180.8 s write, 84,687 events/s.
- No `cost` block yet (the `--cost-only` update waits until Cost Explorer has fully posted 2026-11-08).

**Take timings, verified only in the gitignored exercise log** `observability/scale/exercises/demo-100m-20261108T135119Z.log`:
- L1 start 13:51:19Z; L8 "spot executor nodes: 2"; L231 "apply took 790s"; L363 "generator took 1264s"; L365 "execution SUCCEEDED after 870s" (harness clock; Step Functions 859.1 s); L6641 "destroy took 807s"; L6642 "after destroy: EKS 0, NAT 0, EIP 0, running instances 0"; L6643 "cluster up for 3906s in total". 13:51:19 to 14:56:46 = 65 min 27 s.
- Take command: `docs/demo-recording.md` L449 (`--executor-nodes 2`).

**Dashboard readings from the take** (replayed from AMP/CloudWatch on 2026-11-09; user decision: record them, labelled):
- Dashboard 1 · Run Overview at Finished: cost estimate $2.20 (servers $1.25 + Athena $0.95), time since start 65 min, PASSED (26 checks, 0 errors, 1 warning), data read 50.9 GB.
- Dashboard 2 · Run Health: Spot executor nodes scaled from 2 to 4 during RunTransform (16 executors).

**Scale ladder** (run records, `docs/scale-metrics.md` L458-501):

| Step | Record | New events | Silver after | Run s | DQ | $/M events (run) |
|---|---|---|---|---|---|---|
| Baseline | `demo-7-8-take1-20261006T075445` | 39,222 | 39,222 | 363.4 | suite not built yet | 1.0699 |
| 10M | `exercise-20261009T074853Z` | 9,005,590 | 10,081,387 | 522.8 | passed | 0.0112 |
| 100M (8.9) | `exercise-20261013T055859Z` | 100,008,511 | 137,113,940 | 742.0 | passed | 0.0037 |
| 1M (clean, 8.10) | `exercise-20261015T145812Z` | 1,005,920 | 138,119,860 | 581.2 | passed | 0.2928 |
| 100M take | `demo-100m-20261108T135119Z` | 100,001,897 | 249,121,312 | 859.1 | passed | not posted |

- 8.9 billed: Cost Explorer day 2026-10-13 $1.78; state machine run $0.3657 (0.37 cents per million events); whole exercise 1.78 cents per million events.
- SLO (scale-metrics L503-516): 742 s against the 30-min SLO, 2.4x headroom. Take: 859 s = 48% of 30 min, about 2.1x (computed; label as computed).
- 8.8 Spot interruption: no failure, silver = bronze at 37,105,429. `--full` audit (`observability/scale/audits/dq-full-20261015.json`): 137,113,940 = 137,113,940.

**Architecture today** (from code; `docs/architecture.md` and the `docs/plan.md` north-star diagram are stale, do not copy):
- States (`orchestration/state_machine.asl.json.tftpl`): InvokeIngestion, RunTransform, RunDbt, RunServingQuery, then Succeed/Fail.
- RunTransform and RunDbt run on ECS Fargate (`orchestration/runner/`); RunTransform submits Spark to EKS (ADR 0019).
- Silver and gold are Iceberg with incremental MERGE (ADR 0017). Bulk bronze is JSON Lines (ADR 0018).
- `dev-compute`: On-Demand system group, Spot executor group, Cluster Autoscaler (ADR 0020).
- Prometheus agent → AMP; Grafana local in Docker Compose (ADR 0016, 0022; `make grafana-up`).
- OpenLineage → API Gateway + Lambda collector → Pages (ADR 0013).
- GitHub Actions with OIDC applies `dev-standing` only (ADR 0011).

**Dashboards** (`observability/grafana/dashboards/*.json`): "1 · Run Overview: progress, quality, cost" (`cerberus-run-story.json`), "2 · Run Health: compute and throughput" (`cerberus-run-live.json`), "3 · Spark and Cluster Diagnostics" (`spark-on-eks.json`).

**ADRs** 0001-0025 all Accepted. ADR 0023: HIGH risks 23 → 18.

**Phases** (`Phases.md`): 0-7 done; 8 in progress (8.10 write-up and video, 8.11 milestone); 9 ADR 0024 accepted, prerequisites #123/#124 done, 9.2-9.4 in draft PRs #126-#131; 10 ADR 0021 accepted; 11-13 planned; 14 planned, ADR 0025 accepted.

**Cost and security**: $5.74 gross through 2026-10-02, covered by credits (`docs/cost-security-summary.md` L33-35; dated). Budget $20/month, alerts at $15 and $20. Six least-privilege policies (`iam/cerberus-admin/`). Six SLOs (`docs/slo.md` L53-60).

**Makefile targets**: help, bootstrap-init/plan/apply, standing-init/plan/apply/destroy, compute-init/plan/apply/destroy, exercise, exercise-check, grafana-up/down/logs/token, demo-forward, fmt, clean. `exercise.sh` flags: --yes, --generate, --generator-executors, --executor-nodes, --interrupt-spot, --name, --keep, --no-annotate, --check. `AWS_PROFILE` defaults to `cerberus-admin`; `TF_BIN=tofu` swaps in OpenTofu.

**Portability caveat**: the backend bucket name in `terraform/envs/*/versions.tf` is account-specific; a fork must change it.

**CI** (`code-ci.yml`): ruff check, ruff format --check, pytest, dbt parse, sqlfluff. Four workflows with badges.

**Links**: Pages `https://chiragvenkateshaiah.github.io/cerberus-platform/` with `/dbt/` and `/lineage/`.

**Conflict**: draft PR #107 edits `README.md` and `docs/scale-metrics.md`. User decision: this PR merges first; #107 then drops its README hunks.

## 3. Constraints

- Natural professional English. Every number from a committed file; estimates labelled. No billed figure for the 100M take.
- No account IDs, ARNs, emails, secrets, local paths. Never link `observability/grafana/.env` or `observability/scale/exercises/`.
- Databricks is a complement, never a competitor.
- Code fences: bash, bare, or mermaid only. Never python.
- "Idle" wording exact: between runs nothing billed by the hour exists; the standing layer is pay-per-request plus S3 storage. Do not write "$0/month".
- Do not contradict ADR 0011 or ADR 0024.

## 4. Chosen option

A: rewrite the README as a portfolio page, and in the same PR add a short "8.10: the recorded 100M take" subsection to `docs/scale-metrics.md` so the README cites committed figures. Plus the replay GIF (user decision).

## 5. README outline

Target about 200-260 lines.

1. **Title + tagline + badges.** `# Cerberus`, "cerberus-platform" in the subtitle. Tagline: "A production-style AWS lakehouse, built and operated as code by one engineer. Compute exists only while a run needs it." Keep the four existing badge lines exactly.
2. **Demo GIF** (user decision): `docs/assets/cerberus-100m-run-overview.gif` directly under the badges, with alt text and a one-line caption: "The 100M take on dashboard 1 · Run Overview, replayed from the run's recorded metrics (2026-11-08): 100.0M events, 26 checks passed, cluster deleted, 65 min." Make the caption say plainly it is a replay of recorded metrics.
3. **At a glance** (3-4 sentences): synthetic payments data through an S3 medallion, Spark on EKS, dbt and Athena, on Apache Iceberg; orchestrated by Step Functions, provisioned by Terraform, observed with CloudWatch, Prometheus and Grafana; every non-obvious choice is an ADR (25 so far); each phase closes with a Well-Architected review.
4. **Headline result: 100 million events, empty account to empty account.** Small table: events 100,001,897; pipeline 859 s (14.3 min), about 116k events/s; DQ 26 checks passed, 0 errors, 1 known warning; bronze = silver = 249,121,312; whole exercise 65 min (apply 790 s, generator 1,264 s, pipeline 870 s harness clock, destroy 807 s); after destroy EKS 0, NAT 0, EIP 0, running instances 0; Spot executor nodes 2 → 4 (dashboard reading); cost estimate $2.20 (servers $1.25, Athena $0.95; dashboard estimate, billed figure posted later). Sources line: the run record and the new scale-metrics subsection. One sentence on the billed 8.9 100M run: "$0.37 for the run, 0.37 cents per million events, $1.78 for the whole day (Cost Explorer, 2026-10-13)".
5. **Architecture.** New Mermaid diagram (draft below), five-line walkthrough of the four states, links to ADRs 0002, 0009, 0017, 0019, 0020, 0022. Do not link `docs/architecture.md` here.
6. **Tech stack table** (layer, technology, ADR): Storage S3 + Iceberg + Glue (0002, 0017); Ingestion Lambda + Spark generator (0005, 0018); Compute Spark on EKS, Spot, Cluster Autoscaler (0007, 0020); Orchestration Step Functions + ECS Fargate (0009, 0019); Transform/serve dbt-athena, Athena; IaC/CI Terraform/OpenTofu, GitHub Actions OIDC (0011); Metrics Prometheus agent, AMP, Grafana (0016, 0022); Ops metrics CloudWatch, SNS; Lineage OpenLineage (0013). Verify each ADR number against its title before linking.
7. **Scale ladder.** The five-row table, two lines on why 1M costs more per event (fixed per-run overhead, run on 138M silver), bullets: 2.4x SLO headroom (8.9), Spot interruption absorbed (37,105,429 matched, 8.8), full audit 137,113,940 = 137,113,940. Link `docs/scale-metrics.md`.
8. **Observability for everyone.** The three dashboards with audiences (anyone incl. finance/product; engineering and operations; platform and Spark engineers). Grafana runs locally against AMP, no standing server (ADR 0022). CloudWatch dashboard, alarms to SNS, six SLOs (`docs/slo.md`), lineage (`docs/lineage.md`, Pages DAG and runtime graph).
9. **Data quality and reliability.** 26-check suite reconciles bronze → silver → gold on every exercise (`observability/scale/data_quality.py`); dbt tests gate `dbt build`; exercises tear down from an EXIT trap (`orchestration/exercise.sh`).
10. **Cost and security.** $20/month budget, alerts at $15 and $20; nothing billed by the hour between runs; CI without long-lived keys (OIDC); six least-privilege admin policies; HIGH risks 23 → 18 (ADR 0023); "$5.74 gross through 2026-10-02, covered by credits" with its date; link `docs/cost-security-summary.md`.
11. **Where Databricks fits.** Phase 11 planned: Databricks SQL reads Cerberus's Iceberg gold through Unity Catalog's AWS Glue federation, no copy, managed in Terraform; same workload measured on both engines; Cerberus stays the system of record and only writer (`docs/plan.md` Phase 11 "Not a migration"). Complement wording only.
12. **Roadmap.** Table for Phases 0-14: theme, status, key ADR. Phase 8 "In progress: results write-up, demo video, Well-Architected milestone"; Phase 9 "Planned: design accepted (ADR 0024), prerequisites built"; Phase 14 "Planned: ADR 0025 accepted 2026-11-08". Link `Phases.md`, `docs/plan.md`.
13. **Run it yourself.** Prerequisites (AWS account, Terraform or OpenTofu, AWS CLI with a `cerberus-admin` profile, Docker, uv); state-bucket caveat; warning that `make exercise` creates billable resources and destroys them on exit. bash fence with only:
    ```
    make help
    make bootstrap-init && make bootstrap-apply
    make standing-init && make standing-plan
    make exercise-check
    make exercise ARGS="--yes --generate 1000000"
    make grafana-up
    make compute-destroy   # failure path only
    ```
    Mention `TF_BIN=tofu`.
14. **Repository layout.** Top-level dirs, one line each: `terraform/`, `ingestion/`, `transform/`, `orchestration/`, `observability/`, `lineage/`, `serving/`, `iam/`, `docs/`, `articles/` (verify each exists).
15. **Documentation.** One line each: `docs/plan.md`, `Phases.md`, `docs/adr/`, `docs/scale-metrics.md`, `docs/slo.md`, `docs/lineage.md`, `docs/cost-security-summary.md`, `docs/demo-recording.md`, `docs/architecture.md` ("Phase 1 MVP architecture write-up"), `articles/README.md`.
16. **License.** `[MIT](LICENSE)`.

**Mermaid draft** (layout may change; every node and edge must stay true):
```
flowchart LR
    subgraph CI["Delivery"]
        GHA["GitHub Actions + OIDC"] -->|"plan on PR, apply on merge"| STAND["Terraform: dev-standing"]
        HUMAN["make exercise"] -->|"apply, run, destroy"| COMP["Terraform: dev-compute"]
    end
    subgraph RUN["AWS Step Functions run"]
        direction TB
        S1["InvokeIngestion"] --> S2["RunTransform<br/>ECS Fargate submits Spark"] --> S3["RunDbt<br/>ECS Fargate, dbt-athena"] --> S4["RunServingQuery"]
    end
    subgraph EKS["EKS, created per exercise, then destroyed"]
        GEN["Spark bulk generator"]
        SPARK["Spark job<br/>Spot executors, Cluster Autoscaler"]
        PROM["Prometheus agent"]
    end
    subgraph LAKE["S3 medallion, Glue Data Catalog"]
        BRZ[("Bronze<br/>JSON, JSON Lines")]
        SLV[("Silver<br/>Iceberg")]
        GLD[("Gold<br/>Iceberg marts")]
    end
    S1 --> LAMBDA["Ingestion Lambda"] --> BRZ
    GEN --> BRZ
    S2 --> SPARK
    BRZ -->|"new files only"| SPARK -->|"MERGE"| SLV
    S3 --> GLD
    SLV --> GLD
    S4 --> ATH{{"Athena"}}
    GLD --> ATH
    PROM --> AMP["Amazon Managed Prometheus"] --> GRAF["Local Grafana<br/>3 dashboards"]
    RUN --> CW["CloudWatch alarms"] --> SNS["SNS"]
    SPARK -. "OpenLineage" .-> OL["Lineage collector"] -.-> PAGES["GitHub Pages"]
    GLD -. "Phase 11, planned: Glue federation, no copy" .-> DBX["Databricks SQL"]
    COMP -.-> EKS
```

**Keep**: four badges, Pages URLs, MIT line, docs list and repo layout (condensed), synthetic payments statement, Phase 11 description, 8.8/8.9 facts (moved to the ladder).
**Drop**: changelog-style Status prose; the old Mermaid (CodePipeline, systemd); "Working across machines", `git config pull.rebase`, `/git-cleaner`, `.claude/commands` lines; "ADR 0025 is proposed"; Phase 9 "one start/stop EC2 instance"; the NovaPay-echo label.

## 6. Build steps

1. **GIF asset.** Copy `/home/chirag/.cache/tfspiketmp/cerberus-100m-run-overview.gif` (4.4 MB, 1280x720, 8 fps, 42.6 s loop of dashboard 1 over the whole take; every frame captioned "replay of recorded metrics"; no account ID or ARN visible) to `docs/assets/cerberus-100m-run-overview.gif`.
2. **Source the take figures** in `docs/scale-metrics.md`: add `### 8.10: the recorded 100M take` after "SLOs under load" and before `## Data-quality suite`. Content: execution name; command (demo-recording L449); apply 790 s; generator 1,264 s (write 1,180.8 s); execution 859.1 s (Step Functions) / 870 s (harness); destroy 807 s; cluster up 3,906 s; 13:51:19Z to 14:56:46Z (65 min); after destroy EKS 0, NAT 0, EIP 0, running instances 0; DQ 26 checks, 0 errors, 1 warning; bronze = silver = 249,121,312; peak series 9,424; the dashboard readings ($2.20 = $1.25 + $0.95 estimate; Spot 2 → 4, 16 executors) labelled "read from dashboards 1 and 2, replayed from the run's recorded metrics on 2026-11-09; estimate". Note the timings come from the exercise log, which is not committed. Note the billed figure follows with `--cost-only`.
3. **Rewrite `README.md`** to section 5.
4. **Static checks** (section 7), then review.
5. **Git agent**: commit, push, draft PR; PR body notes #107 must rebase and drop its README hunks.

Follow-up, not in this PR: refresh `docs/architecture.md` and the `docs/plan.md` north-star diagram.

## 7. Static checks (worktree root)

```
grep -oE '\]\(([^)#]+)(#[^)]*)?\)' README.md | sed -E 's/^\]\(//; s/\)$//; s/#.*//' | grep -v '^https\?://' | sort -u | while read -r p; do test -e "$p" || echo "MISSING $p"; done
grep -oE '\]\(#[^)]+\)' README.md
grep -nE '[0-9]{12}' README.md docs/scale-metrics.md
grep -n 'arn:' README.md
grep -nE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}' README.md
grep -nE '/home/|\.env\b|exercises/' README.md
grep -n '^```' README.md | grep -vE '^[0-9]+:```(bash|mermaid)?$'
$HOME/.cache/ruff0164/bin/ruff format --check README.md docs/scale-metrics.md
$HOME/.cache/ruff0164/bin/ruff check .
grep -oE 'make [a-z-]+' README.md | awk '{print $2}' | sort -u | while read -r t; do grep -qE "^$t:" Makefile || echo "NO TARGET $t"; done
grep -niE 'beats databricks|better than databricks|replace databricks' README.md
```

Mermaid render: after the push, open the branch README on GitHub and confirm the diagram and the GIF render.

## 8. User decisions (2026-11-09)

1. Dashboard-only figures: record them in `docs/scale-metrics.md` as labelled dashboard readings; the README cites them.
2. Demo media: add the 100M replay as a GIF at the top of the README for now, until later phases add new features to show.
3. Merge order: this PR first; #107 then drops its README hunks.
