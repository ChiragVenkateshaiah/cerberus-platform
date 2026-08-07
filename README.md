# cerberus-platform

A portfolio project that builds a working AWS lakehouse end to end — ingestion,
medallion storage, transformation, a queryable serving layer, orchestration,
observability, and IaC — demonstrating Data Platform, Platform, and Cloud
Engineering competence in one repository.

## Status

✅ Phase 0 (foundation, built by hand) — complete.
🔨 Phase 1 (MVP: end-to-end lakehouse) — in progress.

See [docs/plan.md](docs/plan.md) for the full phased roadmap (Phases 0–7)
and [Phases.md](Phases.md) for subtask-level progress.

The platform models **synthetic payments data** from Phase 1 onward.

## Architecture

```mermaid
flowchart TB
    subgraph FOUND["Foundation & tooling"]
        direction LR
        GIT["Git + GitHub<br/>public repo"]
        ADR["Markdown ADRs"]
        MK["Makefile<br/>TF_BIN swappable"]
    end

    subgraph PIPE["Lakehouse pipeline"]
        direction LR
        SAMPLE["Sample data<br/>payments-shaped<br/>(NovaPay-echo)"]
        ING1["Bash + AWS CLI<br/>systemd timer (Phase 0)"]
        ING2["AWS Lambda<br/>event-driven (Phase 2)"]
        BRZ[("S3 Bronze<br/>raw")]
        SPARK["Apache Spark on EKS<br/>spin-up / destroy"]
        SLV[("S3 Silver<br/>cleaned")]
        DBT["dbt models<br/>silver to gold"]
        GLD[("S3 Gold<br/>curated")]
        ATH{{"Amazon Athena<br/>serverless SQL"}}

        SAMPLE --> ING1 --> BRZ
        SAMPLE -.-> ING2 -.-> BRZ
        BRZ --> SPARK --> SLV --> DBT --> GLD --> ATH
    end

    subgraph GOV["Provisioning, access and delivery - cross-cutting"]
        direction LR
        TF["Terraform BUSL 1.1<br/>OpenTofu-swappable via TF_BIN"]
        TFSTATE[("Terraform state<br/>S3 bucket + DynamoDB lock")]
        IAM["AWS IAM<br/>least privilege per component"]
        CICD["CI/CD - Phase 5<br/>AWS CodePipeline"]
        TF --- TFSTATE
        CICD -. plan / apply .-> TF
    end

    GIT -. git push .-> CICD
    TF -. provisions .-> PIPE
    IAM -. least-privilege .-> PIPE

    classDef storage fill:#dbeafe,stroke:#1e3a8a,color:#1e3a8a
    classDef compute fill:#dcfce7,stroke:#14532d,color:#14532d
    classDef provisioning fill:#fef3c7,stroke:#78350f,color:#78350f
    classDef tooling fill:#f3e8ff,stroke:#4c1d95,color:#4c1d95
    classDef query fill:#fee2e2,stroke:#7f1d1d,color:#7f1d1d

    class BRZ,SLV,GLD,TFSTATE storage
    class SPARK,ING1,ING2 compute
    class TF,IAM,CICD provisioning
    class GIT,ADR,MK tooling
    class DBT,ATH query
    class SAMPLE tooling
```

This is the target end-state, not current state (see [Status](#status)
above). For current-state notes, the full stack table, and the governing
constraints behind this diagram, see
[docs/architecture.md](docs/architecture.md).

## Repository layout

```
.
├── docs/                 # plan, architecture notes, ADRs
├── terraform/
│   ├── bootstrap/        # one-time state backend (S3 + DynamoDB lock)
│   ├── modules/          # reusable modules (storage, IAM, ...)
│   └── envs/dev/         # dev environment root module
├── ingestion/scripts/    # ingestion scripts: synthetic payments generator
│                         #   (Python, Phase 1); ingest_weather.sh (Phase 0,
│                         #   unscheduled — retired as the active feed)
├── ingestion/systemd/    # systemd --user service + timer for the
│                         #   payments generator (daily)
├── transform/dbt/        # dbt project: bronze → silver → gold
└── data/samples/         # small sample datasets for local testing
```

## Getting started

This project is being built incrementally; see [docs/plan.md](docs/plan.md)
for what's done and what's next. Common tasks are wired up in the
[Makefile](Makefile).

## Documentation

- [docs/plan.md](docs/plan.md) — the build plan and phased roadmap
- [docs/architecture.md](docs/architecture.md) — architecture overview
- [docs/adr/](docs/adr/) — architecture decision records
- [docs/courses-map-to-phases.md](docs/courses-map-to-phases.md) — which
  courses (if any) map to each phase, and where no course exists
- [article.md](article.md) — rules for the weekly engineering write-up,
  generated via `/write-article`; published articles land in `articles/`
  once the first one exists

## License

[MIT](LICENSE)
