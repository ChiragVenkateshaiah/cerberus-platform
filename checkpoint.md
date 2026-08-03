# Checkpoint

_State file for `/start-day` and `/end-day`. `/start-day` reads this to
resume work; `/end-day` writes it at the close of a session.
[Phases.md](Phases.md) is the authoritative phase/subtask checklist — this
file is the session-to-session narrative plus a concrete "what's next"
pointer._

## Current phase

Phase 1 — MVP: end-to-end lakehouse (⬜ planned, not yet started) — see
[Phases.md](Phases.md#phase-1--mvp-end-to-end-lakehouse--). Phase 0 —
Foundation is ✅ complete.

**Note:** the roadmap was re-scoped on 2026-08-03 from 9 phases (0–8) to
8 (0–7). The old "Phase 1 — IaC foundation" no longer exists as a phase;
Terraform is now cross-cutting and its work is absorbed into Phase 1's
subtasks. Session history entries before that date use the old numbering.

## Next up

Phase 1 opens with the two ADRs, since they settle the data model and storage
layout that every later subtask builds on:

- 1.1 ADR: medallion layout (bronze/silver/gold conventions, partitioning)
- 1.2 ADR: synthetic payments data model
- 1.3 Synthetic payments generator landing raw records in bronze
- 1.4 Terraform: S3 medallion module (bronze/silver/gold)
- 1.5 Terraform: adopt the hand-built state backend as code

## Session history

### 2026-07-30

- Scaffolded the repo: README, .gitignore, Makefile (with swappable
  `TF_BIN` for OpenTofu), LICENSE (MIT), docs/architecture.md, ADR 0001,
  and the terraform/ingestion/transform/data directory skeleton —
  completes subtask 0.1.
- Wrote and iterated an architecture diagram (Mermaid), reviewed twice by
  Opus 5 for fidelity to plan.md and GitHub-rendering quality. Final
  version groups nodes by function (foundation / pipeline /
  provisioning-access-delivery), color-codes by category, and covers the
  full stack: Terraform (BUSL 1.1, OpenTofu-swappable via `TF_BIN`), S3
  medallion + DynamoDB state lock, bash+systemd and Lambda ingestion,
  Spark on EKS, dbt, Athena, IAM, CI/CD. Embedded in both README.md and
  docs/architecture.md.
- Registered a local GitHub MCP server (`github-mcp-server`, built via
  `go install`, stdio transport, authenticated via the existing `gh`
  token) after the hosted OAuth endpoint rejected Claude Code's client
  (no dynamic client registration support).
- Initialized git, created the public GitHub repo
  `ChiragVenkateshaiah/cerberus-platform`, and pushed the initial commit
  plus two follow-up commits (diagram fixes, diagram redesign).
- Created Phases.md, this checkpoint.md, and the `/start-day` / `/end-day`
  commands (committed in 521c649).

### 2026-07-31

- **0.2 AWS account hygiene + billing alarm:** root MFA enabled, billing
  alerts preference turned on, IAM user `cerberus-admin` created
  (AdministratorAccess, MFA, CLI access key) as the working identity
  instead of root. Local CLI profile `cerberus-admin` configured (the
  pre-existing `cerberus` / `cerberus-admin` profile stubs were leftovers
  from a since-destroyed prior project, unrelated to `novapay-cli`).
  Billing alarm: SNS topic `cerberus-billing-alerts` with a confirmed
  email subscription, CloudWatch alarm `cerberus-billing-alarm-10usd`
  (threshold $10/month, `us-east-1`) — verified `OK` state after the
  billing alerts preference started publishing the `EstimatedCharges`
  metric.
- **0.3 Manual S3 bronze bucket:** created
  `cerberus-platform-bronze-131715059025` (`us-east-1`) — public access
  blocked, versioning enabled, SSE-S3 encryption, tagged
  (Project/Phase/Layer).
- **0.4 Bash ingestion script on a systemd timer:** `ingestion/scripts/ingest_weather.sh`
  pulls current weather for 5 fixed cities (New York, London, Tokyo,
  Bengaluru, Sydney) from the Open-Meteo API (no key required) and lands
  one Hive-partitioned JSON array per run at
  `s3://cerberus-platform-bronze-.../weather/dt=YYYY-MM-DD/`. Installed as
  a systemd `--user` service + hourly timer
  (`ingestion/systemd/cerberus-ingest.{service,timer}`, symlinked into
  `~/.config/systemd/user/`), enabled, and verified end-to-end with a
  manual trigger (object confirmed in S3, journal logs clean).
- **0.5 Manual Terraform state backend:** created
  `cerberus-platform-tfstate-131715059025` (S3, versioned, encrypted,
  public access blocked) and `cerberus-platform-tfstate-lock` (DynamoDB,
  `LockID` hash key, on-demand billing) via plain AWS CLI — no `terraform`
  command has run in this project yet; that starts in Phase 1 when a
  `backend "s3" {}` block first points at these two resources.
- **Phase 0 is now ✅ complete** — all 5 subtasks checked off in
  Phases.md, status flipped in docs/plan.md's roadmap table.
- Also hardened the `/end-day` command itself: it now reconciles stale
  VCS-status claims left in the previous checkpoint entry (this session's
  edit fixed the 2026-07-30 entry's "pending your review, not yet
  committed" line, which had gone stale the moment 521c649 was pushed),
  and going forward the dated history should describe durable content
  rather than transient commit/push status.

## Notes / blockers

- Systemd linger is still off for this user — `cerberus-ingest.timer` will
  stop firing once the current login session ends, until you run
  `sudo loginctl enable-linger $(whoami)` yourself (needs an interactive
  password, can't be run from here).
- The Phase 0 weather ingestion is now legacy. It stays in the repo as the
  Phase 0 artifact, but synthetic payments supersedes it as the pipeline's
  data source from Phase 1; the bronze bucket still holds weather objects
  under `weather/dt=*/`. Decide during Phase 1 whether to leave them as
  historical or clear them.
- The local working directory was wiped on 2026-08-03 and restored by
  cloning `origin/main` at 474296d. AWS resources were never affected.
