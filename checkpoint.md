# Checkpoint

_State file for `/start-day` and `/end-day`. `/start-day` reads this to
resume work; `/end-day` writes it at the close of a session.
[Phases.md](Phases.md) is the authoritative phase/subtask checklist — this
file is the session-to-session narrative plus a concrete "what's next"
pointer._

## Current phase

**Phases 1–7 are all ✅ complete**, which closes the original roadmap (see
[Phases.md](Phases.md) for the subtask checklist and the per-phase ADRs):

- **Phase 1 — MVP lakehouse** (1.1–1.13): medallion S3, IAM, a Python
  bronze→silver→gold transform, Glue catalog, a dbt fact/dimension layer,
  an Athena demo query, `apply`/`destroy` verified live. ADR 0002/0003 +
  0004 (milestone 1).
- **Phase 2 — Event-driven ingestion** (2.1–2.6): the ingestion Lambda +
  EventBridge Scheduler replacing the systemd timer. ADR 0005 + 0006
  (milestone 2).
- **Phase 3 — Scalable compute** (3.1–3.8): VPC + EKS + Spark Operator,
  spin-up/destroy per exercise, a real Spark job on EKS. ADR 0007 + 0008
  (milestone 3).
- **Phase 4 — Orchestration** (4.1–4.5): Step Functions state machine
  (Lambda → ECS Fargate transform/dbt → Athena), retries + X-Ray. ADR
  0009 + 0010 (milestone 4).
- **Phase 5 — CI/CD** (5.1–5.5): GitHub Actions + OIDC over CodePipeline;
  `envs/dev` split into `dev-standing` (CI-applied) / `dev-compute`
  (human-run); `terraform-plan.yml` / `terraform-apply.yml` / `code-ci.yml`.
  ADR 0011 + 0012 (milestone 5).
- **Phase 6 — Observability & data quality** (6.1–6.6): CloudWatch
  dashboard + freshness probe, seven alarms, dbt tests in `dbt build`,
  OpenLineage lineage (ADR 0013) on GitHub Pages, six SLOs. ADR 0014
  (milestone 6, the first bucket movement: 25→23 HIGH).
- **Phase 7 — End-to-end platform validation** (7.1–7.8): 2,000-transaction
  workload, full orchestrated run, `cerberus-admin`'s `AdministratorAccess`
  replaced by six CloudTrail-derived policies, the full Well-Architected
  review (ADR 0015, milestone 7, no bucket moved), the cost + security
  summary, ADR 0016 (Prometheus agent → AMP + in-cluster Grafana), and on
  2026-10-06: **7.7 verified live** (remote-write 0 failed samples, peak
  4,349 active series vs the ~10k estimate) and **7.8 recorded**
  (`demo-7-8-take1-20261006T075445`, SUCCEEDED in ~6 min). PRs #48–#52.

**Note:** the roadmap was re-scoped on 2026-08-03 from 9 phases (0–8) to
8 (0–7). Session history entries before that date use the old numbering.
Phase 8 below is a *new* phase added on 2026-10-06, not the pre-re-scope
Phase 8.

**Phase 8 — Scale validation is now 🔨 in progress** (see
[Phases.md](Phases.md#phase-8--scale-validation-) and
[docs/plan.md](docs/plan.md#phase-8--scale-validation)). Thesis: prove the
platform by putting real load on it. Take the same pipeline from ~40k
events to 100M in 10x steps (1M, 10M, 100M), fix each bottleneck in the
data layer or the infrastructure, and record run time and cost per
million events per step. $20/month, six weeks from 2026-10-06.

- **8.1** — ADR 0017 **Accepted**: Apache Iceberg in the Glue catalog for
  silver and gold. Silver `MERGE INTO` on `(transaction_id, event_type)`
  with the bronze watermark committed as an Iceberg snapshot property;
  gold `fct_transactions` as dbt-athena `incremental` + `merge` on
  `transaction_id`; compaction + snapshot expiry as a step;
  `cerberus-spark` gets scoped Glue write. Delta Lake ruled out (Athena
  can't write it). PR #53.
- **8.2** — cost guardrails: the hand-made `My Monthly Cost Budget`
  raised $10 → $20 with alerts at 75% / 100% actual and 100% forecast
  (gross cost; kept out of Terraform on purpose); Spot and on-demand vCPU
  quotas both 32; account plan `PAID` / `ACTIVE` with $147.55 credits.
  PR #54.
- **8.3** — the scale harness, done 2026-10-07 (PRs #55–#60):
  - **ADR 0018 Accepted:** bulk events land in bronze as **JSON Lines**
    under a sibling prefix,
    `payments_bulk/run_id=<id>/dt=YYYY-MM-DD/part-*.json`. Bronze
    `payments/` (the Lambda's JSON arrays) is unchanged.
  - **Generator** (`transform/spark/generate_bulk_payments.py`,
    `generate_bulk.sh`, `spark-application-generate.yaml`): deterministic
    by (`run_id`, row id), so a re-run replaces only its own run.
    `cerberus-spark` gained Get/Put/Delete/AbortMultipartUpload on
    `bronze/payments_bulk` and `payments_bulk/*` (the bare key too: S3A
    probes it). Verified live: 1,000,029 events in 117 s.
  - **Metric set** ([docs/scale-metrics.md](docs/scale-metrics.md)) and
    collector (`observability/scale/collect_run_metrics.py`, one JSON
    record per run in `observability/scale/runs/`). Cost is scoped by
    us-east-1, not the `Project` tag (node instances are untagged).
  - **Baseline** from the five existing runs (median 363 s at about 39k
    events, $1.07 per million events), plus today's exercise.
  - **`make exercise`** (`orchestration/exercise.sh`): preflight → plan +
    apply → optional generator → one execution → collect → destroy from an
    EXIT trap → account-wide check. Cluster time fell from 2.10 h to 42 min.
- **8.4** — the data-quality suite as code, done 2026-10-07 (PRs #61, #62):
  `observability/scale/data_quality.py`, 17 Athena checks run as
  `cerberus-transform` with no cluster, all started at once. Bronze →
  silver count and key reconciliation (ADR 0017), silver → gold
  reconciliation and status, silver lifecycle and value rules, a `warn`
  for 97 legacy digit-run tokens, and `payments_bulk/` duplicate and
  per-run manifest checks. A check that can't run fails the suite. The
  collector runs it on every collection (`record.data_quality`, exit 3 on
  failure) and records the generator manifest (`--generator-log`); new
  `--dq-only`. Bronze is read through two unpartitioned Glue tables,
  `bronze_payments_raw` and `bronze_payments_bulk` (own output, so
  `cerberus-serving`'s grant didn't widen). First full run on the
  2026-10-07 exercise: **passed**, bronze 45,304 = silver 45,304, generator
  1,000,029 = manifest.

- **8.5** — 1M events on Iceberg, done 2026-10-08 (PRs #63–#70):
  - **Silver** (`promote_payments_spark.py`): incremental Iceberg table
    `payments_events` (format v2, `days(event_timestamp)`,
    `silver/iceberg/`), Iceberg **1.10.2** (1.11+ needs Java 17; the image
    runs 11). Each run globs only bronze files newer than the watermark
    under both prefixes, reads them once, anti-joins on
    `(transaction_id, event_type)` and appends with the watermark as a
    snapshot property in the same commit; then compaction and snapshot
    expiry. New `loaded_at` column. The Hive table was retired by Terraform.
  - **Gold** (dbt): all three models Iceberg (`schema_table_unique`);
    `fct_transactions` incremental + merge on `transaction_id`, recomputing
    only transactions with silver events newer than its `silver_loaded_at`.
  - **Live:** silver 1,063,625 events / 349,000 transactions; the latest
    run appended 6,094 events and merged exactly 2,000 gold rows, in 340 s
    with data quality passing.
  - **Also:** CI apply refuses commits that aren't `main`'s head (#65);
    `Makefile` defaults `AWS_PROFILE` to `cerberus-admin` (#68); the
    collector flags a partly posted Cost Explorer day (#63).

- **8.6** — 🔨 in progress (2026-10-08, second session): measured before
  changing anything. Of RunTransform's 178 s, data work is 28 s and
  maintenance 10 s; the rest is fixed overhead (ECS task start/stop ~50 s,
  Spark image pulls on fresh nodes ~20 s, Ivy ~8 s, JVM/executor start-up,
  catalog + listing 16 s). The anti-join was tuned locally: day pruning
  kept (branch `phase-8-6-prune-anti-join`, small gain on today's data);
  broadcast, bucketing/SPJ and a hash-key join measured and rejected.
  `make exercise` now saves the Spark operator/driver logs (#74).

## Next up

Start with `git switch main && git pull`. Run `make exercise` **in your
own terminal** (a `!` command in Claude Code has no keyboard for the
`[y/N]` question; there use `make exercise ARGS="--yes"`).

1. **Open PRs to review and merge first:**
   - **#72** — ADR 0002 amendment: serving stays on Athena; Redshift
     Serverless is pluggable through the Glue catalog (not adopted, for
     cost and maintenance). Docs only.
   - **#73** — plan: Phase 9 (Go `cerberusctl`), Phase 10 (Kafka streaming
     with a Go producer/consumer), and "Planned later work": a realistic
     time spread for the synthetic data, and Spark 4 / Java 17. Updates
     `Phases.md`, `docs/plan.md`, `README.md`. Docs only.
2. **8.6 — cut RunTransform's fixed overhead, in measured steps** (numbers
   in today's entry):
   - **Pre-pull the Spark image** while `dev-compute` is created (a small
     DaemonSet in `eks_observability` or `spark_operator`), so driver and
     executor don't each pull `apache/spark:3.5.9` (~10 s each) at run
     time. Expected: ~20 s per run. `dev-compute` only, so no runner-image
     rebuild.
   - **ADR first, then maybe build:** submit and watch the Spark job from
     Step Functions' native EKS integration instead of the ECS Fargate
     wrapper (~25 s start + ~24 s stop per run, and RunDbt pays the start
     too). The trade-offs: kubectl/RBAC from Step Functions, the
     `entrypoint_transform.sh` logic, retries.
   - The day-pruning branch `phase-8-6-prune-anti-join` joins whichever
     change next rebuilds the runner image (one `make standing-apply`).
3. **Then the 10M step:** `make exercise ARGS="--generate 9000000"` —
   check executor sizing first (2 × 1 core × 2 GB on two m7i-flex.large).
   Consider the realistic time spread (in #73's plan) before it, so the
   10M numbers reflect a production-like shape.
4. **Costs, once days have fully posted:** `--cost-only` for
   `exercise-20261007T145442Z` and the four 2026-10-08 runs
   (`…T085728Z`, `…T095905Z`, `…T115807Z`, `…T160759Z`); commit only
   without the "not fully posted" warning.
5. **Small follow-ups:** `use_lockfile`; orphaned Hive data
   (`silver/payments/`, `gold/fct_transactions/`, `gold/dim_*/`).

**Deadline:** the ingestion Lambda's `RETIRE_ON_OR_AFTER` is
**2026-10-30** (PR #45). The scale generator does not depend on it, but
the daily orchestrated path does.

**Carried-over, not blocking (see Notes / blockers):**

- **`build_and_push` CI landmine:** still deferred.
- **Faker Lambda-layer hash churn:** still cosmetic, still present.
- **Follow-ups recorded in ADR 0016, not adopted:** private EKS endpoint
  access, and a Pushgateway.
- **Lineage page on GitHub Pages** doesn't include the 2026-10-06/07 runs
  yet: re-render with the `dbt docs (lineage)` workflow's
  `workflow_dispatch` when wanted.
- **Well-Architected milestone 8** belongs to 8.11 (it will also cover
  7.7's Prometheus evidence).
- **New 2026-10-07:** untagged EKS node instances (8.7/8.8), stale Spark
  labels on pod-IP reuse (Grafana driver panels), and
  `RunServingQuery`'s ~55 s Step Functions polling floor (a latency fix
  for SLO 3, worth only about $0.006 per run).
- **New 2026-10-08:** the Spark job's poll limit in
  `entrypoint_transform.sh` is 20 minutes, which the 100M step (8.9) will
  likely need raised; and the transform task definition still receives
  OpenLineage env only.
- **Later phase, recorded in plan.md:** Kafka + Airflow on one start/stop
  EC2 instance.

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

### 2026-08-03

_No Phase 1 subtasks started — the session went to roadmap design, recovery,
and reference capture._

- **Course mapping.** Reviewed the KodeKloud Cloud Engineer learning path
  against the build and created `docs/courses-map-to-phases.md`: per-phase
  course mapping, a free architecture track (AWS Well-Architected Foundations
  on Skill Builder, Well-Architected Labs, Architecture Center), and explicit
  gaps where no course exists (Step Functions has only a ~12 min module inside
  SAA; Glue and Athena ~5 min each; Spark, dbt and data quality nothing at
  all). KodeKloud's Data Engineering Fundamentals course would fit Phase 1
  best but is unreleased as of today.
- **Learning philosophy settled:** building Cerberus is the primary learning
  path; courses are reached for just-in-time during a phase and never gate
  one. Only Terraform is worth a head start. Recorded as guiding principle #7
  in plan.md.
- **Roadmap re-scoped** from 9 phases (0–8) to 8 (0–7) — commit 67e5479.
  Phase 1 is now the MVP lakehouse; the old "IaC foundation" phase is gone,
  with Terraform cross-cutting instead. Data domain confirmed as **synthetic
  payments from Phase 1 onward** (the README's diagram had always said
  "payments-shaped"; Phase 0's weather feed was only ever a mechanism proof).
  MVP boundary moved to the close of Phase 1. Data quality joined observability
  in Phase 6. plan.md gained an "Existing infrastructure" inventory of the six
  live hand-built AWS resources. Numbering reconciled across plan.md,
  Phases.md, checkpoint.md, README.md, architecture.md and the courses doc.
- **Architecture hardening distributed** rather than restored as a Phase 8 —
  commit a526fe0. Reviewed against the actual stack, its subtasks were mostly
  duplicated, misplaced or empty: VPC design and multi-AZ moved to Phase 3
  (EKS is the only component that needs them), the least-privilege IAM review
  became 7.3, cost/tagging became continuous, secrets management was dropped
  (no secret exists in this stack), and the review write-up already existed as
  Phase 7. Each phase now closes with a tracked "Well-Architected pass + ADR"
  subtask — seven enforced touchpoints instead of one end-loaded phase.
- **Repo destroyed and restored.** The local working directory was
  intentionally wiped to restart the project; on realising Phase 0's work was
  worth keeping, it was restored by cloning `origin/main` at 474296d and
  merging in place so the uncommitted courses doc survived. AWS resources were
  never touched and were verified intact.
- **Well-Architected reference captured** in this file below the `---`, with
  `/start-day` set to render it in full whenever ADR work is next, and
  `/end-day` instructed to preserve it verbatim.

### 2026-08-05

- **Weekly article mechanism added.** Created `article.md` (rules: cadence
  every Wednesday, required content — engineering narrative of cloud
  actions, actual code pulled from that week's diff with never-fabricate
  guardrails, per-block explanation referencing the provider(s) involved,
  an escalation table mapping future phases to new required content) and
  `.claude/commands/write-article.md` (the `/write-article` command that
  executes those rules). Reviewed twice by Opus 5; fixes applied both
  passes — date-range anchoring off the latest `articles/YYYY-MM-DD.md`
  filename instead of directory mtime, an objective "shippable work"
  definition for the skip-week path, required user confirmation before the
  command edits article.md's own Escalation rules, explicit catch-up-run
  dating, a concrete `articles/README.md` index schema, and a new "Shape"
  section (title/length/section-order/voice) that hadn't existed at all.
- **Pushed into a diverged remote.** The push was rejected: `origin/main`
  had 3 commits from a 2026-08-03 session not yet pulled locally (a
  roadmap re-scope from 9 phases to 8, and a full repo restore after an
  intentional wipe). Merged cleanly, then fixed article.md's Escalation
  section, which had been drafted against the old phase numbers before the
  merge — realigned it to the current Phase 1–7 structure (Phase 1 now
  absorbs what used to be two phases; Phase 7 is validation, not a
  separate hardening phase).
- **README drift closed, then automated.** Found README's Documentation
  list didn't mention the new article.md/write-article.md; fixed it, then
  (at request) baked a permanent check into `/end-day` itself (new step 4)
  so this class of drift gets caught at every session close instead of by
  manual review. Opus 5 review caught the first draft relying on
  conversation memory rather than git output to detect "what's new," being
  scoped to root-level files only (missing `docs/`), a contradiction
  between "check diagram labels" and "leave the diagram untouched," and
  being delta-only so it could never clear pre-existing gaps — all fixed.
  Also fixed two gaps the new check would have caught: `ingestion/systemd/`
  was missing from README's Repository layout tree, and
  `docs/courses-map-to-phases.md` was missing from its Documentation list.
  Phases.md's closing note now names README as a fourth file `/end-day`
  keeps in sync (previously said "all three").
- **Drafted `docs/adr/0002-medallion-layout.md`** (1.1), using the
  pillar-as-question-generator method from the reference section below.
  Decided: three buckets (existing bronze + new silver/gold, same
  `cerberus-platform-<layer>-<account-id>` naming, bronze adopted via
  `terraform import` rather than recreated); daily `dt=YYYY-MM-DD`
  partitioning with payments under their own `payments/` prefix, separate
  from the legacy `weather/` prefix already in bronze; raw JSON in bronze,
  Parquet+Snappy from silver onward; bronze immutable/append-only
  (versioning as backstop, not primary mechanism); a 30-day
  Standard-IA lifecycle transition on bronze exposed as a Terraform
  variable. IAM policy specifics were explicitly left to 1.6. Status was
  `Proposed` at the time (committed same day in ea2a04b; accepted 2026-08-07).
- Confirmed the ADR strategy going in: draft each Phase 1 ADR using the
  pillars as a design lens (per the reference section), *not* by running
  drafts through the AWS Well-Architected Tool — the Tool audits an
  existing workload's implementation via checkboxes, not documents, and at
  this point in Phase 1 almost nothing is built yet. The Tool-based review
  stays deferred to 1.13's Well-Architected pass, after 1.1–1.12 are
  actually built.

### 2026-08-06

_Reconstructed from git history — this session's `/end-day` did not run, so
this entry was missing until the 2026-08-07 gap was caught and backfilled._

- **Drafted `docs/adr/0003-synthetic-payments-data-model.md`** (1.2),
  building on 0002's container decisions. Decided: a single denormalized
  "payment event" entity (merchant/customer embedded inline, not
  referenced) rather than separate entity prefixes at bronze —
  normalization deferred to 1.7/1.9; status modeled as append-only events
  keyed on `(transaction_id, event_timestamp)` rather than in-place
  updates, to stay consistent with bronze's immutability from 0002;
  `payment_method`, names, and emails generated pre-masked so no
  unmasked PII-shaped data ever exists in the pipeline. Status
  `Proposed`, committed in 348604a.

### 2026-08-07

- **Accepted ADR 0002 and ADR 0003.** User reviewed both; flipped Status to
  `Accepted` on each, checked off 1.1 and 1.2 in Phases.md. Also caught and
  backfilled the 2026-08-06 gap above — that session's `/end-day` never ran,
  so checkpoint.md's "Next up" was a full session stale (still said "draft
  1.2 next" when 1.2 had already been drafted and committed).
- **Built 1.3, the synthetic payments generator**
  (`ingestion/scripts/generate_payments.py`, Python + Faker, pinned in the
  new `ingestion/requirements.txt`, run from a local `.venv`). Implements
  ADR 0003 directly: a deterministic 15-merchant/75-customer roster (seeded,
  stable across runs, so joins are meaningful); each transaction lifecycle
  generated as append-only events (`created` → `authorized` →
  `settled`/`failed`, plus a small refund chance) with realistic time
  deltas between steps; events grouped by the UTC day they actually
  occurred and uploaded as one JSON array per touched `payments/dt=.../`
  partition — a single run legitimately spans multiple day partitions
  (e.g. `created` today, `settled` up to 3 days later), which is ADR 0003's
  example made concrete. `payment_method` is pre-masked at generation
  (token + last4, never a real-looking PAN); names/emails are
  realistic-but-fake via Faker, emails pinned to `@example.com` (IANA's
  reserved documentation domain) regardless of Faker's default. Verified
  with a manual run (200 transactions → 603 events across 8 partitions,
  confirmed via `aws s3 ls`) and via systemd (`status=0/SUCCESS`).
- **Wired a daily `cerberus-payments.timer`** (`OnCalendar=daily`, per
  explicit request — not hourly like the weather timer, since a daily
  batch is the right cadence for this generator) mirroring Phase 0's
  service+timer pattern.
- **Found and fixed a stale-checkout split.** `cerberus-ingest.timer` was
  actually still running fine (resolves the old "timer state unverified"
  blocker below) — but out of `/home/chira/cerberus`, a second local clone
  pinned at commit `4861440` (2026-08-03), not this session's
  `/home/chira/projects/cerberus`. Repointed `cerberus-ingest.service`'s
  `ExecStart` and both new units at `/home/chira/projects/cerberus`,
  relinked all four `~/.config/systemd/user/` symlinks accordingly, and
  verified both services with a manual `systemctl --user start`.
  `/home/chira/cerberus` is now orphaned — nothing points at it anymore;
  left in place rather than deleted since removing another checkout wasn't
  asked for.
- **Retired weather ingestion at user request**, scoped explicitly to the
  timer/service, the systemd unit files, and the S3 data. Disabled and
  unlinked `cerberus-ingest.timer`/`.service`, deleted
  `ingestion/systemd/cerberus-ingest.{service,timer}` from the repo, and
  permanently purged all 40 weather objects (every version, not just
  current) under `weather/dt=*/` in bronze. `ingest_weather.sh` itself,
  and Phase 0's historical record of building it, were left untouched —
  out of scope for this cleanup. Payments is now bronze's only live feed.
- **Capped the payments timer to a 10-day window, cost/data-volume
  control.** Added `ingestion/scripts/run_payments_scheduled.sh`, a
  wrapper now sitting between `cerberus-payments.service` and
  `generate_payments.py`: it runs the generator normally through
  2026-08-16, then on/after 2026-08-17 it disables
  `cerberus-payments.timer` instead of generating (self-retiring, not
  self-deleting — the timer/service files and the generator itself all
  stay on disk and runnable). The retirement date lives in the wrapper,
  not the generator, so `generate_payments.py` stays a plain,
  always-available script for manual runs at any time — the plan is to
  trigger it by hand once 1.4–1.13 are far enough along to need more
  data. Verified both branches of the date check in isolation and the
  run branch through an actual `systemctl --user start`.
- **Built 1.4, the Terraform S3 medallion module**
  (`terraform/modules/s3_medallion/`, instantiated from
  `terraform/envs/dev/`) — three buckets via `for_each` over a locals map
  (bronze `Phase=0`, silver/gold `Phase=1`, matching when each was
  actually created), each with versioning, SSE-S3, public access block,
  and `BucketOwnerEnforced` ownership controls; bronze alone also gets the
  30-day Standard-IA lifecycle rule from ADR 0002
  (`bronze_ia_transition_days` variable, default 30). `envs/dev` backend
  points at the Phase 0 state bucket/lock table by name (using them, not
  yet managing them as code — that's 1.5). Bronze was adopted via
  `terraform import` of all 5 of its resources (bucket, versioning,
  encryption, public-access-block, ownership-controls); the resulting
  plan was 11 to add / 0 to change / 0 to destroy — confirming the
  import matched the real bucket exactly, no drift. Applied; verified
  both new buckets and bronze's lifecycle rule via `aws s3api`, and a
  follow-up `plan` showed "No changes."
- **Switched from OpenTofu to Terraform mid-task, at user request** (they
  want to build Terraform muscle memory specifically, having just taken a
  beginner course). Installed `terraform` 1.15.8 via HashiCorp's apt repo
  (the user ran the `sudo` steps themselves in their own terminal — this
  session can't supply an interactive sudo password). The `.tf` files
  needed no changes (HCL is identical between the two); the real fallout
  was in *state*: the bronze imports had been done with `tofu import`
  first, and OpenTofu defaults to `registry.opentofu.org` as the implicit
  provider source rather than `registry.terraform.io` — so state had
  those 5 resources tagged to a different provider than
  `envs/dev/versions.tf` declares. Fixed by `terraform state rm`-ing all
  5 (state-only, touches nothing in AWS) and re-running the imports with
  `terraform import` instead; confirmed via `terraform state pull` that
  every resource now uniformly references
  `registry.terraform.io/hashicorp/aws`. Per explicit user decision, the
  Makefile's `TF_BIN` swappability and the OpenTofu mentions in
  README/architecture.md/plan.md stay as-is — only the hands-on tool
  changed, not the project's documented flexibility.
- **Wrote `docs/notes/day-01.md`**, a textbook-style learning note covering
  everything built today — organized by discipline (ADR governance, the
  payments generator's design, systemd scheduling, S3 fundamentals, a full
  Terraform code walkthrough, the Terraform-vs-OpenTofu fix), not
  chronology, with theory explained alongside the actual code and a closing
  glossary. Written at explicit request as a reference/study artifact,
  separate from this file's session narrative.

### 2026-08-08

- **Built 1.5, adopting the hand-built state backend as code**
  (`terraform/bootstrap/`, previously empty). Same adoption pattern as
  1.4: the S3 state bucket (`cerberus-platform-tfstate-131715059025`,
  5 resources — bucket, versioning, encryption, public-access-block,
  ownership-controls) and the DynamoDB lock table
  (`cerberus-platform-tfstate-lock`, on-demand billing, `LockID` hash
  key) were both inspected via `aws s3api`/`aws dynamodb describe-table`
  first to match their real config exactly, then imported — 6 resources,
  0 created. `terraform plan` came back **"No changes"** immediately
  after import, with no `apply` step needed at all (cleaner than 1.4,
  where silver/gold still had to be created). This directory deliberately
  has **no `backend "s3" {}` block** — it's the one directory in this
  project that can't point its own state at the resources it's
  describing, so it uses plain local state
  (`terraform/bootstrap/terraform.tfstate`, gitignored), the standard
  Terraform bootstrap pattern.
- **Confirmed the `dynamodb_table` vs `use_lockfile` decision explicitly**
  (see below) before starting: keep the DynamoDB table as-is, since it's
  already built and effectively free, and revisit only after the MVP
  (Phase 1) is done and there's real signal on whether it's worth the
  extra moving part.
- **Built 1.6, the Terraform IAM module** (`terraform/modules/iam/`,
  instantiated as `module.iam` from `envs/dev`). Unlike 1.4/1.5, nothing
  existed to adopt — this was a from-scratch design decision, resolved by
  asking: build the three roles ADR 0002 forward-pointed to (ingestion,
  transform, serving) as genuinely assumable IAM roles now, even though no
  automated compute exists yet to assume them (that's Phase 2's Lambda at
  the earliest) — or just the bare policy documents, inert until later.
  Went with real roles: each trusts `cerberus-admin` (the only identity in
  this account) via `sts:AssumeRole`, with an inline policy scoped
  per-layer — `cerberus-ingestion` gets `s3:PutObject` on
  `bronze/payments/*` only; `cerberus-transform` gets read on
  `bronze/payments/*` plus read+write on `silver`/`gold` (with
  `s3:ListBucket` correctly scoped via an `s3:prefix` condition on bronze,
  not the whole bucket); `cerberus-serving` gets read-only `gold` (S3 only
  for now — Glue/Athena permissions land once 1.8–1.10 actually build
  those). `terraform plan` came back 6 to add / 0 to change / 0 to
  destroy, no drift on existing S3 resources. Applied, then **verified the
  scoping actually works, not just that it was declared**: assumed
  `cerberus-ingestion` via `aws sts assume-role` and confirmed all four
  boundaries live — allowed to `PutObject` under `payments/`, denied
  `PutObject` elsewhere in bronze, denied `ListBucket` entirely, denied
  reading `gold`. Test object cleaned up afterward. This is a deliberate
  head start on repaying Phase 0's `AdministratorAccess` shortcut
  (formally closed out at 7.3) rather than a placeholder — the roles are
  real and usable today, nothing currently assumes them automatically.
- **Built 1.7, the bronze → silver → gold transform**
  (`transform/scripts/promote_payments.py`, boto3 + pandas + pyarrow, new
  `transform/requirements.txt`, installed into the shared `.venv`). Unlike
  1.4-1.6, plan.md's stack line just said "a minimal transform" with no
  compute specified — resolved by ruling out Spark (Phase 3's addition,
  not Phase 1's) and going with plain Python. Design settled on: full
  rebuild every run (reprocesses all of bronze, no watermark/incremental
  tracking — simplest correct option at this data volume, trivially
  idempotent); silver gets the complete flattened event history as
  Parquet+Snappy, one file per day partition at a deterministic key
  (`payments/dt=.../events.parquet`, overwritten on rebuild — silver is
  derived and reprocessable, unlike bronze's append-only accumulation);
  gold gets a current-state table, one row per `transaction_id` via
  latest-event-wins resolved on `event_timestamp`
  (`payments_current/current_state.parquet`), still denormalized on
  purpose — per ADR 0003 the fact/dimension split is 1.9's job, not this
  script's. First real use of the `cerberus-transform` role from 1.6: the
  script assumes it via STS rather than running as `cerberus-admin`
  directly. Ran clean on the first try against all 37 bronze objects
  (2,451 events) — 9 silver day-partitions written, gold resolved to 805
  distinct transactions (729 settled / 40 failed / 36 refunded). Verified
  by reading both outputs back with pandas: silver's schema is properly
  typed (`datetime64[ns, UTC]` etc.), and gold's row count matched its
  unique `transaction_id` count exactly, confirming the dedup was correct.
- **Built 1.8, Glue Data Catalog schema registration**
  (`terraform/modules/glue_catalog/`: one database `cerberus_platform`,
  two tables — `payments_events` (silver, `dt=` partitioned) and
  `payments_current` (gold, unpartitioned), explicit column schema
  matching the exact Parquet types 1.7 already writes. Decided against a
  Glue Crawler: the schema is fully known and owned end-to-end, so
  hand-declaring it in Terraform is more accurate and reviewable than
  paying to have AWS re-derive something already certain. Partitions are
  explicitly *not* Terraform-managed — they're data, not infrastructure,
  and grow every run — so `promote_payments.py` was extended to register
  each day partition it writes via `glue:BatchCreatePartition` directly
  (idempotent: re-running reports "0 new, N already existed" rather than
  erroring), using a `PARQUET_COLUMNS` constant kept in sync with the
  Terraform module's column list by hand (no shared schema source between
  HCL and Python today). Also extended the 1.6 IAM roles to close the
  "S3-only for now" forward pointer: `cerberus-transform` gained scoped
  Glue permissions (`GetTable`/`BatchCreatePartition`/`GetPartitions`) on
  `payments_events` only; `cerberus-serving` gained catalog read
  (`GetDatabase`/`GetTable`/`GetTables`/`GetPartitions`) on both tables.
  `terraform plan` came back 3 to add / 2 to change (both IAM policies,
  in-place, no role recreation) / 0 to destroy. Applied, then re-ran the
  transform to populate all 9 existing partitions, verified via
  `aws glue get-table`/`get-partitions` that the catalog's schema and
  partition list are exactly right, and confirmed a second transform run
  is idempotent (0 new partitions, no errors).
- **Wrote `docs/notes/day-02.md`** (1.5-1.8: the Terraform bootstrap
  pattern, IAM roles/trust policies/least privilege, the transform's
  Parquet/latest-event-wins design, and the Glue Data Catalog), same
  textbook format as day-01. Also created **`/note-maker`**
  (`.claude/commands/note-maker.md`) at explicit request — codifies
  day-01's format as a reusable command (window detection from the
  previous note's date, discipline-based categorization, theory-then-code
  structure, never-fabricate grounding in git history, a glossary that
  doesn't repeat prior notes' terms) so future sessions don't need the
  format re-derived by hand each time.

### 2026-08-10

_Phase 1 finished today — 1.9 through 1.13 all landed in one session, plus
the first learning note and the first published article._

- **Built 1.9, the dbt project + gold fact/dimension models**
  (`transform/dbt/`: `dbt_project.yml`, `profiles.yml`, `models/sources.yml`,
  `models/marts/{dim_merchants,dim_customers,fct_transactions}.sql`).
  Implements ADR 0003's deferred fact/dimension split: `dim_merchants`/
  `dim_customers` are plain `SELECT DISTINCT`s off the fixed roster (no
  latest-wins needed, roster values never change); `fct_transactions`
  resolves latest-event-wins via a `ROW_NUMBER() OVER (PARTITION BY
  transaction_id ORDER BY event_timestamp DESC)` window function, emitting
  `merchant_id`/`customer_id` as foreign keys instead of embedding names
  inline. Runs as `cerberus-transform`, authenticated via a new named AWS
  CLI profile (`role_arn` + `source_profile` chaining in `~/.aws/config`)
  rather than in-code STS, since dbt is a CLI tool this project doesn't
  control.
  Pulled 1.10's minimal Athena plumbing forward as a prerequisite —
  dbt-athena can't run at all without a query-results bucket and a
  workgroup (`terraform/modules/athena/`). Hit and fixed three real gaps
  live: missing `s3:GetBucketLocation` and `glue:GetDatabases` (both
  surfaced by actual `AccessDeniedException`s, not predicted from docs),
  and a workgroup with `enforce_workgroup_configuration = true` that
  silently misrouted every dbt table's data into the results bucket
  instead of gold — dbt-athena omits a table's `external_location` when
  the workgroup enforces its own output location. Fixed by turning
  enforcement off (the `bytes_scanned_cutoff_per_query` cost guardrail
  still applies as a default either way).
- **Built 1.10, the Athena demo query + `cerberus-serving` permissions**
  (`serving/queries/demo_query.sql`, `serving/scripts/run_demo_query.sh`).
  Extended `cerberus-serving` with read-only Athena query execution and
  Glue read on the new `fct_*`/`dim_*` tables (not Terraform-managed, so
  absent from its original grant). The demo query joins
  `fct_transactions`+`dim_merchants` for settled revenue by merchant —
  deliberately not a trivial count, since it exercises the actual
  normalization 1.9 did. Verified end to end via a new `cerberus-serving`
  AWS CLI profile, same role-chaining pattern as `cerberus-transform`.
- **Built 1.11, live `terraform destroy`/`apply` verification.** Not a
  dry-run: backed up bronze's raw data locally (the only non-reproducible
  layer — silver/gold/marts are all derived and reprocessable), emptied
  all four buckets of every object version, then actually destroyed and
  rebuilt the full 31-resource stack. The Athena workgroup failed to
  destroy once (`WorkGroup is not empty` — its query-execution history
  needs `force_destroy`); fixing it surfaced a real Terraform gotcha —
  `terraform destroy` uses the resource's last-*applied* state for its
  delete call, not just the current `.tf` config, so the new
  `force_destroy = true` had to be applied to state first via
  `terraform apply -target=` before a destroy would honor it. Confirmed
  deleting the Glue database cascade-deletes every table inside it,
  Terraform-managed or not (the dbt tables included). Restored bronze and
  re-ran the transform + dbt to reconstruct silver/gold/marts — which
  incidentally caught and fixed a real pre-existing bug: silver/gold
  hadn't picked up 4 bronze partitions since 2026-08-08, silently stale
  until this rebuild forced a fresh full-reprocess. The payments timer was
  stopped for the duration of the test and restarted afterward — no
  schedule change, still self-retires 2026-08-17.
- **Built 1.12, rewrote `docs/architecture.md`'s "Current state" section**
  for the actually-built Phase 1 MVP — it had been stale since Phase 0
  ("Phase 0 complete, Phase 1 next") despite 1.1–1.11 landing. New
  build-specific Mermaid diagram (not the aspirational 7-phase one), a
  stage-by-stage narrative, and a "Verified" section citing the real demo
  query output and 1.11's results. Resolved the data-layout table's
  "TBD — see ADR" placeholders per ADR 0002/0003 and expanded Decisions to
  list ADR 0002/0003 (previously only ADR 0001 was mentioned). The old
  7-phase diagram was relabeled post-MVP rather than removed.
- **Built 1.13, the first AWS Well-Architected Tool review**
  (`docs/adr/0004-phase-1-well-architected-review.md`). Created the
  `cerberus-platform` workload (Framework lens, `us-east-1`) via the
  `aws wellarchitected` CLI/API — scripted rather than clicked through the
  console, which is what made a genuine 57-question review tractable in
  one sitting. Answered every question honestly against what's actually
  built: **26 HIGH / 19 MEDIUM / 7 NONE / 5 NOT_APPLICABLE**. Sustainability
  came back cleanest (0 HIGH); Operational Excellence and Reliability
  scored hardest, mostly because those pillars assume an organization and
  standing compute this solo, serverless-only project doesn't have yet.
  Hit one real gotcha: leaving `--selected-choices` empty on a genuinely
  "nothing applies yet" question left it `UNANSWERED` rather than
  "answered, at risk" — fixed by explicitly selecting each question's
  `"None of these"` choice instead. Saved milestone 1
  (`phase-1-mvp-complete`) as the baseline every future phase's pass diffs
  against. ADR 0004 documents it pillar-by-pillar (the shape a *review*
  ADR takes, vs. 0002/0003's decision-record shape), mapping every real
  gap to the phase that already owns it rather than treating it as a new
  backlog.
- **Phase 1 flipped to ✅ Complete** across `Phases.md`, `docs/plan.md`'s
  roadmap table (which had drifted — never actually updated off "⬜
  Planned" this whole time, a pre-existing gap only caught now), and
  README's status line.
- **Wrote `docs/notes/day-03.md`** (1.9–1.13: Athena workgroup fundamentals,
  AWS CLI role-chaining and the empirically-discovered IAM permissions,
  dbt's source/materialization model and window functions, the
  `force_destroy` state-vs-config gotcha, the Well-Architected Tool's
  CLI-driven review), same textbook format as day-01/day-02. Window was
  effectively just today — 2026-08-09 had no commits.
- **Published the first article** (`articles/2026-08-10.md`,
  `articles/README.md` created as its index). No prior article existed, so
  this was a one-off Phase 1 completion retrospective rather than a strict
  weekly-cadence run — dated today (Phase 1's actual completion day)
  rather than the mechanical catch-up date (2026-08-05, the last
  Wednesday), which would have cut the story off before 1.5–1.13 even
  happened. Confirmed with the user before deviating from `article.md`'s
  literal dating rule. Covers the full Phase 1 arc with real code pulled
  from the actual files.
- **Adopted a tagging + PR-per-phase workflow, retroactively tagged
  Phase 0/1.** Created annotated git tags `v0-foundation` (→ `474296d`,
  Phase 0's completion commit) and `v1-mvp` (→ `3283781`, Phase 1's), both
  pushed to origin. Added guiding principle 8 to `docs/plan.md`: starting
  Phase 2, phase implementation work ships via branch + PR — one per phase
  by default, more if a phase's scope genuinely warrants it — merged with
  **regular merges only, never squashed**, per explicit user instruction
  (full commit history stays intact, not flattened). Convention only, not
  GitHub branch protection, since there's no CI check yet for a protection
  rule to gate on (that's Phase 5's `terraform plan` on PR); routine
  `/start-day`/`/end-day` checkpoint-only commits stay direct-to-`main` as
  before. Phases 0/1 were tagged rather than retrofitted with PRs, since
  rewriting already-merged history isn't worth it for a settled record.

### 2026-08-11

_Phase 1 review + fixes, ADR 0005 (drafted, reviewed, revised, accepted), 2.1–2.4
built and verified live, a workflow-policy change mid-flight, and a first look
at AWS's Agent Toolkit for Claude Code._

- **`/code-review high` against `v0-foundation..v1-mvp`** (the whole of Phase
  1), at the user's request to sanity-check the MVP before starting Phase 2.
  10 findings, all verified against the actual files (not taken on trust) —
  the top 4 were fixed the same session:
  - **Gold/dbt latest-event-wins had no tiebreak** on equal
    `event_timestamp`s (`promote_payments.py`'s `sort_values().tail(1)` and
    `fct_transactions.sql`'s `row_number()`) — `generate_payments.py` clamps
    every event to `min(ts, now)`, so a settled event and a later refund can
    land on an identical timestamp. Confirmed **live in production data**:
    15 transactions were mislabeled `settled` instead of `refunded`. Fixed
    with a fixed lifecycle-order rank (`created < authorized <
    settled/failed < refunded`) as the tiebreak in both places; re-ran the
    transform and dbt and confirmed all 5 sampled mislabeled transactions
    now correctly resolve to `refunded`.
  - **`generate_payments.py` ran as the full `cerberus-admin` profile**
    instead of the least-privilege `cerberus-ingestion` role built for it in
    1.6. Fixed by adding a role-chained `cerberus-ingestion` CLI profile
    (same `role_arn`/`source_profile` pattern as `cerberus-transform`/
    `cerberus-serving`) and switching to it; verified with a real run.
  - **Upload failures had no retry and could abort the rest of a run** —
    fixed with a per-partition retry loop (later replaced, see below).
  - Fixed findings committed in `3bc73d0`. Six lower-severity findings
    (an unchunked Glue `BatchCreatePartition` call past 100 partitions, no
    noncurrent-version expiration on silver/gold, two already-known/accepted
    tradeoffs, two simplification items) were reported but left as tracked,
    not-yet-actioned findings — not fixed this session.
- **Drafted, reviewed, revised, and accepted ADR 0005** (`docs/adr/0005-push-vs-pull-ingestion.md`,
  2.4) on a new branch, `phase-2-event-driven-ingestion` — the first work
  under the (now-superseded, see below) branch-per-phase convention.
  Decision: **EventBridge Scheduler**, not an S3 event notification —
  `generate_payments.py` produces its own data rather than consuming an
  externally-dropped file, so there's no genuine upstream write for a push
  trigger to react to; "event-driven" here is about replacing systemd's
  login-session-dependent scheduling with managed infrastructure, not
  introducing reactivity that doesn't structurally exist yet.
  - **An Opus review of the draft ADR found real problems, not style
    nits**: a fabricated claim that a systemd catch-up bug had already
    fired (it hadn't — replaced with the actual, verified evidence: the
    timer skipped 2026-08-09 entirely and ran late on 08-10/08-11); a
    Decision that named "EventBridge scheduled rule" but argued using
    EventBridge Scheduler's capabilities (now explicitly committed to
    Scheduler, with the timezone fixed to UTC to avoid silently shifting
    which `dt=` partition a run lands in); a Security row claiming a
    1-vs-2 trust-relationship asymmetry that doesn't hold up (fixed to
    "roughly neutral"); and a Consequences section that conceded no real
    cost at all — most notably missing that EventBridge's at-least-once
    retries against the generator's intentionally unseeded RNG risk
    appending duplicate, non-reconciled data into append-only bronze.
  - **Before finalizing, priced out the 2.5 retirement-cap question with
    real numbers** rather than guessing: running the EventBridge/Lambda
    path for 10 vs. 30 days, against this project's actual measured data
    rate (~283 KB / 8 S3 PUTs per daily `count=200` run), costs
    ~$0.0004 vs. ~$0.0014 total — negligible against the existing
    $10/month billing alarm. Decided to **keep the 10-day cap anyway, on
    data-volume/manageability grounds, not cost** — 1.3's original
    "cost/data-volume control" framing turns out to only ever really have
    been about the data-volume half. Where that cap's logic lives once the
    systemd wrapper is retired (in the Lambda's own code vs. an
    infrastructure-level schedule toggle) is still open — see Next up.
  - Revised ADR committed (`40dfa6c`), then flipped to `Accepted` and 2.4
    checked off (`796bcd7`).
- **Built 2.1–2.3 together** (`caa1bed`) — the Lambda ingestion function,
  its EventBridge Scheduler trigger, and its IAM role, since they're
  interdependent and were designed/tested as one unit:
  - Extracted the roster/event-generation/upload core out of
    `generate_payments.py` into new `ingestion/scripts/payments_lib.py`,
    shared between the CLI script (now a thinner wrapper) and the new
    Lambda handler (`ingestion/lambda/handler.py`) — the two differ only in
    trigger, auth, and logging, not generation logic.
  - Lambda handler reads `BRONZE_BUCKET`/`RETIRE_ON_OR_AFTER`/
    `TRANSACTION_COUNT` from its environment, no-ops past the retirement
    date rather than trying to disable its own schedule (would need
    `scheduler:*` permissions the role deliberately doesn't have), and
    raises on partial failure only to surface it in CloudWatch, not to
    trigger a retry.
  - `terraform/modules/iam`: added a 4th role, `cerberus-ingestion-lambda`
    — same `s3:PutObject` scope as `cerberus-ingestion`, but trusted by
    `lambda.amazonaws.com` instead of a human principal (the first of the
    four roles actually assumed by compute, not by hand). Uses the
    AWS-managed `AWSLambdaBasicExecutionRole` for CloudWatch Logs — the one
    deliberate exception to this module's inline-only-policy convention,
    since it's runtime boilerplate, not a project-specific grant.
  - New `terraform/modules/lambda_ingestion`: the function (Faker packaged
    as a layer, pip-installed at `terraform apply` time via
    `null_resource`/`local-exec` — boto3/botocore deliberately excluded
    from the layer since the Lambda runtime ships both already), and an
    `aws_scheduler_schedule` — daily, UTC, `MaximumRetryAttempts = 0` (an
    invocation-level retry would regenerate a different, unseeded dataset
    and duplicate data into bronze — payments_lib's client-level retry,
    see below, is the only retry layer).
  - Applied (9 resources, 0 drift) and **verified live, not just planned**:
    manually invoked the Lambda and confirmed a real object landed in
    bronze; confirmed via `iam simulate-principal-policy` that the
    scheduler's role can actually invoke the function and that the
    execution role's boundaries match `cerberus-ingestion`'s (allowed on
    `bronze/payments/*`, denied elsewhere in bronze, denied on gold).
- **Workflow changed mid-session, at explicit user request**: dropped the
  one-day-old branch-per-phase/PR-per-phase convention in favor of pushing
  to `main` continuously — stated reason: daily visible activity reads
  better to recruiters than work batched into one PR per phase. Opened and
  merged PR #1 (`phase-2-event-driven-ingestion` → `main`, regular merge,
  `c30e1f1`) covering 2.1–2.4's work *while Phase 2 was still incomplete* —
  a deliberate trunk-based-development choice, not an oversight. The exact
  new shape (still PR-per-push vs. fully direct-to-`main`) was never
  pinned down, though — see Next up, this needs a real decision and a
  `docs/plan.md` principle-8 rewrite next session.
- **Installed AWS's Agent Toolkit for Claude Code** (`aws-core@claude-plugins-official`
  v1.1.0, user scope) to evaluate it against this project. Findings, not
  just marketing claims: it's genuinely CDK/CloudFormation-flavored (no
  `aws-terraform` skill exists at all) — a real gap for a Terraform-first
  project; `aws-containers` names ECS/Fargate/ECR, not EKS specifically,
  so Phase 3 coverage is uncertain; ~5,005 tokens are added to every
  session just for having it installed, always-on, before any skill even
  fires. Mapped the 20 skills against the actual remaining roadmap and
  found real matches (`aws-compute` explicitly covers Step Functions —
  4.1's open ADR; `aws-observability` maps to Phase 6; `aws-iam` to 7.3;
  `aws-sdk-python-usage` for boto3 pattern-checking) and clear non-matches
  (`aws-database`, `amazon-bedrock`/`aws-ai-ml`, `aws-secrets-manager` —
  this project explicitly decided secrets management doesn't apply,
  `aws-blocks` — confirmed via research to be an unrelated TypeScript
  full-stack framework).
  - **Discovered a real mechanical limitation**: a plugin installed
    mid-session doesn't hot-load into that session's skill registry — the
    `Skill` tool returned "Unknown skill" for `aws-sdk-python-usage` even
    though the plugin was correctly installed and enabled on disk. Skills
    from a freshly-installed plugin only actually become invocable
    starting the *next* new session.
  - Worked around it by reading the skill's packaged reference content
    directly from `~/.claude/plugins/cache/.../aws-sdk-python-usage/` and
    applying it by hand — genuinely useful anyway: it flagged that
    `payments_lib.upload_day`'s hand-rolled retry loop retried on *any*
    `ClientError`, including non-retryable ones (`AccessDenied`,
    `NoSuchBucket`) that can never succeed no matter how many attempts — a
    real bug, not style, and costly inside a Lambda with a 60s timeout
    budget. Fixed by replacing the manual loop with botocore's own
    `Config(retries={"total_max_attempts": 3, "mode": "standard"})`
    applied once at client construction — exponential backoff, and only
    genuinely retryable errors, for free. `upload_day` simplified to a
    single `try`/`except`. Verified live: reran the CLI generator,
    redeployed the Lambda (new code hash picked up automatically), and
    reinvoked it — both still land real objects in bronze. Pushed directly
    to `main` (`2917bbd`), no PR — see the workflow-policy note above.
  - Also correctly **declined to create a cloud-scheduled routine** for
    tomorrow's unattended-fire check (user asked to "check back tomorrow")
    — a cloud agent has no access to the local `~/.aws/config`
    `cerberus-admin` profile and no AWS MCP connector is set up, so it
    would have silently failed. Left as a `checkpoint.md`-tracked
    follow-up instead (see Next up), consistent with how this project
    already handles session-to-session continuity.

### 2026-08-12

_Phase 2 closed — 2.5, 2.6, the workflow-policy rewrite, and ADR 0006 all
landed; day-04 learning notes written._

- **Confirmed the EventBridge Scheduler → Lambda path fires unattended.**
  Checked `/aws/lambda/cerberus-ingest-payments`'s CloudWatch Logs and the
  day's S3 partition from the local machine (`cerberus-admin` profile): a
  clean invocation at `2026-08-12T00:00:09Z`, 8 partitions written, no
  manual trigger. Also caught systemd's `Persistent=true` firing an
  unprompted catch-up run at `04:41:09 UTC` the same morning (this
  session's login restarting the `--user` systemd instance) — live,
  observed confirmation of the login-session dependency ADR 0005 already
  cited as motivation for the move.
- **Retired `cerberus-payments.timer`, completing 2.5.**
  `systemctl --user disable --now` on the timer, then a second explicit
  removal of the service's own symlink (`disable` only unregisters the
  *timer* from `timers.target.wants/`, not the separate `.service` symlink
  it points at), `daemon-reload`, then deleted both unit files from
  `ingestion/systemd/` in the repo. `generate_payments.py`,
  `payments_lib.py`, and `run_payments_scheduled.sh` all left in place,
  unscheduled — mirrors weather ingestion's 2026-08-07 retirement shape.
  Bronze now has exactly one ingestion mechanism. (Auto mode's classifier
  initially blocked the `systemctl` state-change commands outright; the
  user switched to manual mode to proceed.)
- **Resolved the workflow-policy decision flagged 2026-08-11: PR-per-push,
  not PR-per-phase, and not fully direct-to-`main` either.** Every unit of
  work — a subtask, a fix, a review finding — now ships on its own branch,
  merged same-day via a regular (non-squash) merge; routine
  `/start-day`/`/end-day` checkpoint-only commits stay direct-to-`main` as
  before. Rewrote `docs/plan.md`'s guiding principle 8 to state this
  explicitly, keeping the one-day-lived branch-per-phase shape inline as a
  dated, superseded note rather than deleting it (PR #2, `f4e63e5`).
- **Ran the second Well-Architected Tool pass and wrote ADR 0006, completing
  2.6 — Phase 2 done.** Diffed milestone 1 (`phase-1-mvp-complete`) against
  a new milestone 2 (`phase-2-event-driven-ingestion-complete`) rather than
  re-answering all 57 questions — the diff-based pattern 1.13/ADR 0004
  explicitly set up for later phases. Three questions re-answered with
  concrete new evidence: `observability` (the Lambda's CloudWatch
  application telemetry, used live this session to confirm the unattended
  fire above), `fault-isolation` (removing the systemd timer's
  login-session dependency — the 04:41 catch-up fire as live evidence), and
  `select-service` (ADR 0005's real 10-vs-30-day cost analysis — the one
  question that actually moved a risk bucket, MEDIUM → NONE). Two IAM
  questions (`permissions`, `identities`) were considered but left
  unchanged: the new `cerberus-ingestion-lambda` role is genuine new
  evidence but fits a choice the Tool already credits, not a new one — noted
  in the ADR rather than forcing an edit the evidence doesn't support.
  Flipped Phase 2 to ✅ complete across `Phases.md`, `docs/plan.md`'s
  roadmap table, and README's status line (PR #3, `7ffd3c9`) — then caught
  and fixed ADR 0006's own status field, drafted as `Proposed` by mistake
  (mirroring the decision-ADR pattern of 0002/0003/0005) when review-type
  ADRs go straight to `Accepted`, per ADR 0004's actual precedent — they
  document a review already performed, not a decision awaiting buy-in
  (PR #4, `891a352`).
- **Wrote `docs/notes/day-04.md`** (ADR 0005's push-vs-pull decision and
  review arc, Lambda/EventBridge Scheduler fundamentals, human-vs-service-
  principal IAM trust policies, the `payments_lib.py` extraction plus two
  real production bug fixes carried over from 2026-08-11 — gold/dbt's
  tiebreak and the retryable-error `Config` fix — the `lambda_ingestion`
  Terraform module's `archive_file`/`null_resource` mechanics, retiring the
  systemd timer, and this session's process changes), same textbook format
  as day-01 through day-03. Window ran from right after day-03's own
  cutoff (2026-08-10 morning) through today, to avoid re-covering ground
  day-03 already wrote up.
- **Drafted ADR 0007** (`docs/adr/0007-vpc-network-design.md`, opens Phase
  3/3.1), later the same day — after this date's own `/end-day` had already
  run and recorded the entry above, which is why this bullet was missing
  until the 2026-08-14 session caught and backfilled it (see that entry).
  Working through the Well-Architected pillars for a VPC/EKS network:
  dedicated `10.0.0.0/16` VPC (distinct from the account's default
  `172.31.0.0/16`), two AZs (`us-east-1a`/`us-east-1b`) with one
  public/private subnet pair each, private subnets sized `/20` for VPC CNI
  per-pod IP headroom, a single NAT Gateway rather than one per AZ (Cost
  over Reliability, deliberately — this VPC is spun up and destroyed per
  job, so an idle-time AZ-level NAT outage isn't the failure mode that
  matters), a free S3 Gateway VPC endpoint taking Spark's bronze/silver/gold
  traffic off NAT's billed path, and a public EKS API endpoint (accepted
  gap, same shape as Phase 0's `AdministratorAccess` shortcut — no
  bastion/VPN in a solo project). Folded in 3.3 per `docs/plan.md`: a single
  EKS-managed node group spanning both private subnets (not one per AZ),
  on-demand instances rather than Spot. Committed on branch
  `adr-0007-vpc-network-design` (`3b72db6`) and merged via PR #5
  (`ef1226a`). Status left `Proposed` — not yet reviewed/accepted, so 3.1
  stays unchecked in Phases.md.

### 2026-08-14

_Started as orientation-only, then grew into the session that actually
opened Phase 3's build: ADR 0007 accepted (3.1/3.3 complete), the
Well-Architected Tool's per-phase-milestone requirement made durable, and
3.2's VPC + EKS Terraform modules written and plan-verified (not yet
applied)._

- **Ran `/start-day`**, which cross-checked checkpoint.md/Phases.md against
  `git log` and caught a real mismatch: both files still said Phase 3 "has
  not started," but ADR 0007 had already been drafted and merged on
  2026-08-12 (PR #5) — after that day's own `/end-day` commit
  (`f711a0c`, 11:40 UTC), so the ADR work (`3b72db6`/`ef1226a`, 11:46–17:17
  UTC the same day) was never recorded. Same shape as the 2026-08-06 gap
  caught on 2026-08-07: a session's `/end-day` ran before the session's
  work actually finished.
- **Backfilled the 2026-08-12 entry above** with ADR 0007's content rather
  than filing it as a new dated section, since it happened on that date.
  Flipped Phase 3's status marker in Phases.md from ⬜ to 🔨.
- **Verified the AWS Well-Architected Tool's actual state via the
  `aws wellarchitected` CLI** rather than trusting checkpoint.md's claims:
  confirmed the `cerberus-platform` workload and both milestones (1
  `phase-1-mvp-complete`, 2 `phase-2-event-driven-ingestion-complete`)
  genuinely exist as described. Read the AWS Well-Architected Framework's
  six pillar design-principle pages and the Data Analytics Lens live from
  `docs.aws.amazon.com` — three of the six core pillar pages
  (Operational Excellence, Security, Sustainability) failed to render body
  content through the fetch tool and were supplemented from stable public
  AWS documentation instead, flagged as such rather than blended in
  silently. Pulled the four Data Analytics Lens design principles most
  relevant to Phase 3 (DP5 infrastructure access control, DP6 workload
  resilience, DP8 compute selection, DP11 cost-effective compute/storage by
  usage pattern) and tied each to ADR 0007's existing reasoning.
- **Registered a durable requirement, since the review surfaced a real
  gap**: nothing previously forced a future "Well-Architected pass + ADR"
  subtask (3.8, 4.5, 5.5, 6.6, 7.4) to actually save a Tool milestone,
  only to write the ADR — a future session could check the box having done
  half the work. Fixed in `docs/plan.md`'s Architecture guiding principle
  and Phases.md's cross-cutting Architecture bullet: both now state the
  pass has two required parts. checkpoint.md's Notes/blockers gained a
  tracked-state entry (workload ID, milestones so far, next one due at
  3.8) so this doesn't need rediscovering via CLI each time. Committed
  directly to `main` (`1f13564`), consistent with routine
  session-bookkeeping commits.
- **Accepted ADR 0007** (user reviewed it independently) — flipped
  `Status` to `Accepted`, checked off **3.1** and **3.3** together in
  Phases.md, since the ADR's Decision section resolves both the VPC/subnet
  layout and the multi-AZ node-group shape. Committed directly to `main`
  (`ac13085`).
- **Built 3.2 — VPC + EKS cluster Terraform modules** implementing ADR
  0007's design exactly: `terraform/modules/vpc/` (dedicated `10.0.0.0/16`
  VPC, 2 AZs, one public/private subnet pair each, single NAT Gateway in
  `public-a`, free S3 Gateway endpoint on the private route table) and
  `terraform/modules/eks/` (cluster + IAM roles, a single managed node
  group spanning both private subnets per 3.3 — on-demand, fixed size 2 —
  cluster-admin access for `cerberus-admin` via
  `bootstrap_cluster_creator_admin_permissions` rather than a hand-built
  access entry, and an OIDC provider so 3.4/3.5 can give Spark its own
  IRSA-scoped S3 role instead of overloading the broad node role). Added
  the `hashicorp/tls` provider (needed for the OIDC thumbprint) to
  `envs/dev/versions.tf`. `terraform fmt`/`validate` clean;
  `terraform plan` came back **24 to add, 0 to change, 0 to destroy** —
  matches the design exactly (15 VPC resources + 9 EKS resources).
  **Deliberately not applied**: the EKS control plane and NAT Gateway both
  bill on `apply` regardless of load, and ADR 0007's whole design is
  spin-up/destroy, so this stops at a verified-clean plan. Apply is
  deferred until 3.4/3.5 (Spark Operator, job manifest) are also ready, so
  one `apply` exercises the whole stack instead of leaving a paid idle
  cluster with nothing running on it — confirmed as the explicit plan with
  the user before writing any code. **3.2 stays unchecked in Phases.md**
  until that live apply and verification actually happens. Shipped on
  branch `eks-cluster-module`, merged via PR #6 (`b284e46`/`d6781f6`).

### 2026-08-17

_3.4 and 3.5 built, both plan-only like 3.2 — Phase 3's whole compute
stack is now written and plan-verified, nothing applied yet._

- **Built 3.4 — the Spark Operator Helm install**
  (`terraform/modules/spark_operator/`). Installs `kubeflow/spark-operator`
  (the actively maintained successor to the archived
  `GoogleCloudPlatform/spark-on-k8s-operator`) into its own `spark-operator`
  namespace, configured via `spark.jobNamespaces` to watch a separate
  `spark-jobs` namespace rather than the chart's own default of `default`.
  No chart version pinned — checked three different live sources for the
  current version and got inconsistent/unreliable answers, so left unset
  (Helm installs latest) rather than hardcode a guess, same treatment
  already given to the eks module's `kubernetes_version`. Wired
  `kubernetes`/`helm` providers into `envs/dev`, authenticated via
  `data.aws_eks_cluster_auth` against the not-yet-created cluster's
  outputs — confirmed live that `terraform plan` resolves cleanly even
  though the provider config depends on resources that don't exist yet (a
  known real-world Terraform+EKS+Helm rough edge that turned out not to
  bite here). `depends_on = [module.eks]` on the module so the operator's
  pods aren't scheduled before a node exists. `terraform plan`: 27 to add,
  0 to change, 0 to destroy. Shipped on branch `spark-operator-install`,
  merged via PR #7 (`c19720f`/`e6203f5`).
- **Built 3.5 — the Spark job manifest against S3.** Scope confirmed with
  the user before writing code: the job replaces only 1.7's bronze→silver
  flatten/parse step, writing to the exact same silver location and
  15-column schema `promote_payments.py` already produces; gold's
  latest-event-wins rollup and dbt's marts stay Python/dbt, untouched by
  which tool wrote silver. Container-image strategy also confirmed first:
  off-the-shelf `apache/spark` image + script fetched from S3 at submit
  time, no custom build/ECR repo.
  - `transform/spark/promote_payments_spark.py`: PySpark rewrite of that
    one step. Explicit bronze schema (not inferred), `multiLine` JSON
    read (bronze files are JSON arrays, not one-object-per-line),
    `mode("overwrite")` + `partitionBy("dt")` matching 1.7's own
    full-rebuild-every-run semantics. Deliberately does **not** register
    Glue partitions itself — the off-the-shelf image has no boto3 —
    `submit_job.sh` runs `MSCK REPAIR TABLE` afterward instead, reusing
    `cerberus-transform`'s existing Glue/Athena grant. On reflection this
    isn't a workaround, it's the standard Glue/Athena mechanism for "new
    partition directories appeared in S3."
  - `terraform/modules/iam`: a 5th role, `cerberus-spark` — the first in
    this project assumed via IRSA (OIDC federation from an EKS service
    account) rather than `sts:AssumeRole` or a service principal, scoped
    via `sts:AssumeRoleWithWebIdentity`'s `sub`/`aud` conditions to
    exactly `system:serviceaccount:spark-jobs:cerberus-spark`. S3 only —
    read `bronze/payments/*`, read+write `silver/*` — no Glue permissions
    at all, since it doesn't need any.
  - `terraform/modules/spark_job`: just the Kubernetes service account
    carrying the `eks.amazonaws.com/role-arn` annotation. The
    SparkApplication CR itself
    (`transform/spark/spark-application.yaml`) is a plain, manually-applied
    manifest, not Terraform-managed — submitting a job run is a workload
    action, not infrastructure provisioning, the same distinction this
    project already draws between Terraform-managed IAM roles and the
    plain scripts that assume them.
  - `transform/spark/submit_job.sh`: uploads the script to
    `silver/_spark_jobs/`, points `kubectl` at the cluster, applies the
    manifest, polls for completion, then runs the `MSCK REPAIR TABLE`
    step — three separate least-privilege credentials throughout
    (`cerberus-transform` for the S3/Athena steps, `cerberus-admin` for
    `kubectl`, `cerberus-spark` for the job itself).
  - `terraform plan`: 30 to add, 0 to change, 0 to destroy.
  - **Version uncertainty flagged, not fabricated, then explicitly
    deferred.** `spark-application.yaml`'s `apache/spark` image tag and
    its paired `hadoop-aws` version couldn't be verified live — a Docker
    Hub tags-API fetch came back three years stale even with explicit
    `ordering=-last_updated`, the second unreliable result for this exact
    question this session. Presented the user two options (verify by hand
    now, or defer to 3.6 since the version only matters at actual apply
    time); **user chose to defer**. Also caught mid-discussion that the
    boto3/MSCK-REPAIR split isn't actually a residual gap — it's a
    resolved design decision, not a stopgap, corrected after initially
    describing it as an open risk.
  - Caught and fixed a branch-hygiene mistake before pushing: kept
    committing 3.5's work on the already-merged `spark-operator-install`
    branch instead of cutting a fresh one off updated `main`. Fixed by
    resetting that branch back to its merged tip and cherry-picking the
    3.5 commit onto a new `spark-job-manifest` branch — verified
    `terraform plan` still came back identical (30/0/0) after the
    cherry-pick before pushing. Shipped via PR #8 (`756365d`/`a308490`).
  - **3.2, 3.4, and 3.5 all stay unchecked in Phases.md** — same
    discipline as 3.2 alone previously: written and plan-verified isn't
    the same as applied and verified live.

### 2026-08-18

_The live apply → install → submit → verify → destroy pass (3.6/3.7) —
Phase 3's full compute stack ran for real on EKS, three real bugs found and
fixed live, a near-miss full-stack `terraform destroy` caught and avoided,
and a real destroy-order gotcha discovered and worked around. 3.2–3.7 all
complete; only 3.8 remains to close Phase 3._

- **Verified `spark-application.yaml`'s image/hadoop-aws versions live**,
  clearing the deferred blocker from 2026-08-17. Docker Hub's tags API
  silently ignores its own `ordering=-last_updated` param on this endpoint
  — paging to the *last* page (not trusting page 1 under the requested
  ordering) surfaced real current data: `apache/spark:3.5.9` (pushed
  2026-07-24) is the latest patch on the already-targeted 3.5.x line
  (`4.2.0` also exists but is a major-version jump with unverified
  Spark-Operator/API compatibility — user chose to stay on 3.5.x). Read
  Spark v3.5.9's own `pom.xml` to confirm `hadoop-aws:3.3.4` was already
  the correct pairing, not a guess. Bumped the manifest's image, sparkVersion,
  and driver/executor labels; the header comment now records the
  verification instead of flagging it as open.
- **Ran the live `terraform apply` against the full 30-resource Phase 3
  stack.** First attempt failed: the EKS node group's `m5.large` launch
  was rejected — this AWS account (18 days old) is still under AWS's
  new-account Free-Tier-only EC2 restriction
  (`InvalidParameterCombination`), not an EC2 quota issue (32 vCPU quota,
  healthy). Switched `terraform/modules/eks`'s `node_instance_types`
  default to `m7i-flex.large` (Free-Tier-eligible, same 2 vCPU/8 GiB spec
  as `m5.large`) — re-planned (5 to add: the replacement node group plus
  the Spark Operator/namespace resources that never got attempted; 1 to
  destroy: the failed node group) and applied clean. Full stack came up:
  VPC, EKS with 2 healthy nodes, Spark Operator's controller/webhook pods
  running, `cerberus-spark` service account correctly IRSA-annotated.
- **Submitted the job via `submit_job.sh` (3.5) — hit and fixed two real
  bugs before it ran clean:**
  - First submission failed in ~7 seconds, before any driver pod existed:
    the Spark Operator's controller resolves `deps.packages` (the
    `hadoop-aws` Maven coordinate) locally via Ivy *inside its own pod*,
    and that pod's `$HOME` is `/nonexistent` (a hardened non-root
    container), so Ivy's default `$HOME/.ivy2` cache write failed
    outright. Fixed by adding `spark.jars.ivy: "/tmp/.ivy2"` to the
    manifest's `sparkConf` — not a version/config mismatch, a submit-time
    container-hardening interaction.
  - Second attempt got a driver pod running, but it crashed:
    `cerberus-spark`'s IRSA role only ever had **S3** permissions (from
    1.6/3.5's IAM design) — the Spark-on-Kubernetes scheduler backend
    running inside the driver also needs **Kubernetes RBAC** to `GET` its
    own pod and create/watch/delete executor pods directly against the
    K8s API, which it had zero grant for at all. Added a `kubernetes_role`
    + `kubernetes_role_binding` to `terraform/modules/spark_job` (pods,
    services, configmaps, persistentvolumeclaims — matching the upstream
    Spark-on-Kubernetes docs' reference RBAC) — applied (2 to add), then
    found `deletecollection` was still missing as a separate verb from
    `delete` (post-job configmap/PVC cleanup uses label-selector bulk
    delete), fixed in two more small applies. Final rerun: `submit_job.sh`
    exit 0, zero errors/exceptions anywhere in the driver log.
- **Completed 3.6's verification, both parts:**
  - **Data:** silver has 61 real Parquet objects across every `dt=`
    partition (885 KB), 17 Glue partitions registered via the script's
    `MSCK REPAIR TABLE` step, and Athena queries `payments_events`
    successfully (8,723 rows) — the full data path works end-to-end, not
    just "the job exited 0."
  - **S3-via-Gateway-endpoint claim (ADR 0007):** confirmed definitively
    via the private route table itself, not inferred from traffic volume
    — it has a specific route for the S3 prefix list (`pl-63a5400a`) to
    the VPC endpoint, which AWS always prefers over the `0.0.0.0/0` NAT
    route for S3-destined traffic (more specific route wins,
    deterministically). NAT Gateway did show traffic during the run, but
    that's fully explained by non-S3 traffic with no endpoint coverage —
    pulling `apache/spark:3.5.9` from Docker Hub and EKS system images
    from ECR.
- **3.7's `terraform destroy` — caught a near-miss, then a real dependency-
  graph bug, then a real destroy-order gotcha, before it actually
  finished clean:**
  - The first `terraform plan -destroy` (no `-target`) came back **72 to
    destroy** — the entire root module, including bronze/silver/gold, the
    Glue catalog, and the Lambda ingestion function. Caught before
    applying anything. Correct scope is `-target=module.spark_job
    -target=module.spark_operator -target=module.eks -target=module.vpc`.
  - That scoped plan still pulled in Phase 2's
    `module.lambda_ingestion.aws_lambda_function.ingest_payments` (35 to
    destroy) — traced to a real Terraform dependency-graph artifact:
    `module.iam`'s `role_arns` output is a single map literal built from
    all 5 roles, so *any* consumer reading one key creates a graph edge to
    the whole expression, which depends on all 5 underlying role
    resources — including `spark`, which is genuinely downstream of the
    EKS OIDC provider. Fixed at the root: added a standalone
    `ingestion_lambda_role_arn` output to `terraform/modules/iam` and
    switched `lambda_ingestion`'s module call to read it instead of
    `role_arns["ingestion_lambda"]` — verified zero resource impact (`No
    changes`) before relying on it. One further gotcha: the fix didn't
    take effect until an actual `apply` ran — Terraform's stored
    `depends_on` metadata per resource is only refreshed on `apply`, not
    read-only `plan`, so a no-diff `terraform apply` was needed to
    propagate the graph change into state. Re-planned clean at 32 to
    destroy (exactly Phase 3's own resources, correctly including
    `iam.aws_iam_role.spark`).
  - The apply itself stalled ~5 minutes into destroying the
    `spark-operator` namespace (`context deadline exceeded`): both nodes
    had gone `NotReady`, because this cluster's public-only EKS API
    endpoint (ADR 0007) means nodes reach the control plane via NAT, and
    Terraform had already destroyed the NAT Gateway in parallel with the
    Kubernetes cleanup — so kubelet could never confirm pod termination
    back to the API server. Force-deleted the two stuck pods
    (`--grace-period=0 --force`), which cleared the namespace immediately;
    re-planned and applied the remaining 12 resources (EKS cluster, node
    group, OIDC provider, EKS IAM roles, VPC, private subnets) clean.
    Documented as an expected recurring gotcha for this design in Notes /
    blockers, not a one-off bug.
  - **Verified the teardown was both complete and correctly scoped**,
    independently of Terraform's own state: `terraform state list` shows
    zero Phase 3 resources remaining; AWS CLI confirms no EKS clusters, no
    `cerberus-platform` VPC, no NAT gateways, `cerberus-spark` role gone —
    and separately, that bronze/silver/gold (61 silver objects intact),
    the Glue catalog (5 tables), and `cerberus-ingest-payments`
    (Lambda `Active`, EventBridge schedule `ENABLED`) were all completely
    undisturbed.
- **3.2, 3.4, 3.5, 3.6, and 3.7 all checked off in Phases.md** — the first
  time any of Phase 3's compute subtasks have been marked complete, since
  all of it is now genuinely applied and verified live, not just planned.
  Only 3.8 (Well-Architected pass + ADR + Tool milestone) remains to close
  the phase.
- **Ran 3.8, closing Phase 3.** Diffed milestone 2
  (`phase-2-event-driven-ingestion-complete`) against a new milestone 3
  (`phase-3-scalable-compute-complete`), same pattern as ADR 0004/0006.
  Three questions re-answered with concrete new evidence, all from this
  session's actual live pass, not re-labeled old evidence:
  `fault-isolation` (Reliability) fully resolved, HIGH → NONE — the EKS
  node group's live-confirmed multi-AZ placement (two `Ready` nodes on
  different subnets/AZs) is the compute layer's first genuine multi-AZ
  deployment; `ready-to-support` (Operational Excellence) gained "use
  playbooks" — the Ivy-cache, RBAC, and NAT/destroy-order fixes are
  genuine investigate-diagnose-fix playbooks, not routine runbooks, now
  written up reusably in this file's Notes / blockers; `manage-service-limits`
  (Reliability) moved off "None of these" — the Free-Tier EC2 restriction
  was investigated and durably documented, honest partial credit for a
  reactive discovery, not proactive quota management. Two items
  considered and explicitly not forced: `identities` (Security) — IRSA is
  a genuinely new mechanism but the Tool's matching checkbox is scoped to
  workforce identity, not workload identity; `sus_hardware`
  (Sustainability) — `m7i-flex.large` is more efficient than `m5.large`,
  but the switch was driven by the Free-Tier constraint, not an
  energy-efficiency evaluation. Overall: HIGH 26→25, NONE 8→9. Wrote
  `docs/adr/0008-phase-3-well-architected-review.md` documenting all of
  this pillar-by-pillar, matching ADR 0004/0006's review-ADR shape.
  **Phase 3 flipped to ✅ Complete** across `Phases.md`, `docs/plan.md`'s
  roadmap table, and README's status line.
- **Shipped on branch `phase-3-well-architected-review`, merged into `main`
  via PR #9** (`f2156c5`/`7ddee36`) — covers both this entry's live pass
  (`a4cb040`) and ADR 0008 (`f2156c5`) as one PR, since they closed the same
  phase in one continuous session. Independently re-verified post-merge,
  not just trusted from the commit messages: milestone 3
  (`phase-3-scalable-compute-complete`) genuinely exists via
  `aws wellarchitected list-milestones`, silver genuinely holds the Spark
  job's multi-part `.snappy.parquet` output, and live AWS confirms zero
  VPCs/EKS clusters/NAT Gateways/instances remain — the destroy really was
  clean, not just reported as clean.

### 2026-08-20

_Phase 4 opened and driven all the way to ✅ complete across two sessions
today: 4.1–4.4 landed first (started 2026-08-19, ran past midnight) — ADR
0009 (Step Functions vs. Airflow), the state machine built and tuned, then
a long, genuinely hard live-verification pass — two separate partial-apply
crashes' worth of orphaned AWS resources cleaned up, six real bugs found
and fixed live, a full orchestrated execution actually succeeded end to
end, and a scoped destroy that surfaced and fixed a real Terraform
dependency-graph bug along the way. A separate same-day session (different
machine — see below) added cross-machine sync tooling. A third same-day
session then closed 4.5 (ADR 0010, milestone 4), completing Phase 4._

- **4.1 — ADR 0009: AWS Step Functions over Airflow.** Deciding pillar was
  cost/standing-infrastructure: Airflow (MWAA or self-hosted) would be the
  first non-serverless standing service in this stack, breaking the
  serverless/spin-up-destroy pattern held since Phase 1; Step Functions +
  ECS Fargate keeps that pattern intact since neither has idle cost.
  Conceded up front that Step Functions has no native Spark-on-EKS
  integration, so 4.2 would need to wrap `submit_job.sh`'s logic in a
  container. Merged via PR #10 (`818e80c`).
- **4.2 — state machine definition as code (plan-only).** New
  `orchestration/runner/` container image (Dockerfile, `entrypoint_transform.sh`
  adapted from `submit_job.sh`, `entrypoint_dbt.sh`) and the ASL definition
  (`orchestration/state_machine.asl.json.tftpl`): `InvokeIngestion` (native
  Lambda integration) → `RunTransform`/`RunDbt` (ECS Fargate via
  `ecs:runTask.sync`) → `RunServingQuery` (native Athena integration, no
  container needed). New `orchestration_runner` and `step_functions`
  Terraform modules; four new least-privilege IAM roles. A `code-review
  high` pass on the container files caught and fixed five real issues
  before anything ran live: unbounded poll loops, a `curl` missing `-f`,
  gitignored dbt build artifacts leaking into the image (new
  `.dockerignore`), an unpinned AWS CLI version, and a hand-duplicated dbt
  profile (now derived via `sed` from the committed original instead of
  hand-synced). Verified via `terraform validate`/`plan` only — no live
  apply this session, deliberately (see Scope boundary in the PR). Merged
  via PR #11 (`2e6b7a1`).
- **4.3 — retries + visibility.** Re-reading 4.2's baseline while tuning it
  surfaced a real bug, not just tuning debt: `InvokeIngestion`'s Retry
  block reintroduced the exact duplicate-unseeded-data risk ADR 0005
  eliminated at the EventBridge Scheduler layer — removed. `RunTransform`/
  `RunDbt` retries raised 1→2 attempts instead, since both are fully
  idempotent end to end (documented per-state in the ASL). Added
  CloudWatch Logs (`ALL`, full execution data) + X-Ray tracing to the
  state machine. Retargeted EventBridge Scheduler from invoking the
  ingestion Lambda directly to starting the state machine instead (ADR
  0009's item left open for this subtask) — moved via `moved` blocks, not
  destroyed/recreated, preserving the live Phase 2 schedule's identity;
  its `retry_policy` stays at 0 attempts, carrying ADR 0005's reasoning
  forward one level (a scheduler retry now means starting a new execution,
  same regenerate-and-duplicate risk). Merged via PR #12 (`8b3b21a`).
- **4.4 — the live pass.** By far the longest and most consequential
  subtask this phase — `terraform apply` against the full stack for the
  first time, exercising code that had only ever been plan-validated.
  - **Environment blocker first:** this sandbox (and, initially, the
    user's own terminal) had no docker, needed for the runner image's
    `docker build`/`push` step. Resolved by the user installing Docker
    Engine directly (`get-docker.sh`) and adding themselves to the
    `docker` group — needed a full WSL2 restart (`wsl --shutdown`) before
    group membership actually took effect, `newgrp docker` alone wasn't
    enough. Once unblocked, `!`-prefixed commands (running in the user's
    real terminal, not this session's own sandbox) became the mechanism
    for everything requiring docker.
  - **First `terraform apply` attempt got killed mid-run** (hit a harness
    timeout while waiting on user confirmation, since `-input=false`
    without `-auto-approve` doesn't behave as "refuse silently" in this
    version) — left a stale DynamoDB state lock and, worse, several
    resources created for real in AWS with **no state written for them at
    all** (state persistence didn't reach that point before the kill).
    Cleared the stale lock via `terraform force-unlock -force`, then spent
    real effort reconciling: a genuinely orphaned duplicate VPC (with its
    own NAT Gateway, IGW, route table — all deleted by hand, in dependency
    order), EKS's own cluster/node IAM roles, and the four new
    orchestration IAM roles + ECR repo + 3 CloudWatch log groups, all
    hand-verified against AWS and deleted before a clean re-apply was
    possible.
  - **Six real bugs found and fixed live, none catchable by `plan`/`validate`:**
    1. `aws_security_group.runner`'s description had an apostrophe
       ("runner's Fargate tasks") — AWS's SG description charset excludes
       it.
    2. The runner image's `local-exec` provisioner used `set -o pipefail`,
       unsupported by `/bin/sh` (dash) — added an explicit
       `interpreter = ["/bin/bash", "-c"]`.
    3. The ASL used `arn:aws:states:::ecs:runTask.sync2` — not a real AWS
       resource ARN. Correct: `arn:aws:states:::ecs:runTask.sync`, no
       version suffix (verified against AWS's own docs after guessing
       wrong twice, including a `.sync:2` attempt).
    4. The retargeted EventBridge Scheduler used
       `aws-sdk:states:startExecution` as its universal-target service
       name — AWS's actual abbreviation is `sfn`, not `states`.
    5. `cerberus-orchestration-transform` was missing `glue:GetDatabase`
       (needed by `MSCK REPAIR TABLE` to resolve the database before the
       table) and silver bucket read/list entirely — `cerberus-transform`,
       the role this one's policy shape was copied from, only avoided both
       gaps because its own broader statements happened to cover the same
       resources incidentally.
    6. `cerberus-orchestration-dbt` never got read access to
       `payments_events`, the dbt *source* table its models `SELECT FROM`
       — its policy only covered the `fct_*`/`dim_*` tables it creates.
  - **A real state machine execution succeeded end to end** after all six
    fixes: `InvokeIngestion` → `RunTransform` (an actual Spark job
    completing on EKS, not a mock) → `RunDbt` → `RunServingQuery`, all
    `SUCCEEDED`. Re-ran `serving/scripts/run_demo_query.sh` directly and
    got real settled-revenue-by-merchant data back — the MVP's original
    "one Athena query against gold" criterion, now proven through the
    fully automated pipeline rather than the manual path.
  - **Committed the fixes** (PR #13, `ec98d87`) and checked off 4.4.
  - **The scoped destroy surfaced a seventh bug**, a real one, not a
    live-environment fluke: `module.iam`'s `role_arns` output is a single
    map expression, so any consumer reading even one key gets a graph
    edge to *all 9* roles — the exact same class of bug
    `ingestion_lambda_role_arn`'s standalone output was already built to
    fix during 3.7, reproduced here because 4.2 didn't check for the
    precedent. `terraform destroy -target=module.iam.aws_iam_role.spark`
    pulled in `orchestration_runner`'s task definitions and the entire
    `step_functions` state machine as false dependents. Fixed with four
    more standalone role-ARN outputs (PR #14, `89200ae`) — confirmed via
    `terraform state pull` that the *stored* dependency metadata on
    already-applied resources doesn't update from a config edit alone; a
    no-op `terraform apply` was needed to recompute and rewrite it before
    the fix actually took effect on a destroy plan.
  - **Final destroy, correctly scoped**: EKS (cluster, node group, OIDC
    provider), the Spark stack, and the NAT Gateway + EIP — 26 resources,
    verified gone via real AWS API calls (`describe-cluster`
    `ResourceNotFoundException`, `describe-nat-gateways` empty). Left
    standing, deliberately: the VPC itself, subnets, IGW, public route
    table (all free), and the entire orchestration layer — ECR, ECS task
    definitions, the state machine, the scheduler — proving ADR 0009's
    central bet true in practice, not just in theory. Hit the same
    NAT/pod-termination destroy-order gotcha 3.7 already documented
    (`spark-operator` namespace stuck `Terminating`, `context deadline
    exceeded`) — same fix worked (`kubectl delete pod --grace-period=0
    --force`, then re-run destroy for the remainder).
- **4.1–4.4 all checked off in Phases.md**; Phase 4's own heading marker
  flipped ⬜→🔨 (same precedent as Phase 3's 2026-08-14 flip), and
  `docs/plan.md`'s roadmap row updated to "🔨 In progress" to match — not
  yet ✅, since 4.5 remains.
- **Cross-machine sync tooling added, from a separate same-day session on
  the other machine** (commits authored between this session's own work,
  never previously recorded here — same gap shape as the 2026-08-06 and
  2026-08-12 entries above, caught and backfilled now): `.gitattributes`
  (`* text=auto eol=lf`, normalizing line endings between the workstation
  and the WSL2 laptop this project now runs on); `.gitignore` gained
  `get-docker.sh` (the Docker Engine install script 4.4's environment
  blocker required, local-only, not project source); and a new
  `/git-cleaner` command (`.claude/commands/git-cleaner.md`) — the
  two-machine sync ritual: checks both `cerberus` and `tessera` repos for
  uncommitted changes, rebases from origin, prunes stale remote-tracking
  branches, and reminds about `terraform init` if providers are missing
  (gitignored, don't travel between machines). README gained a new
  "Working across machines" section documenting the two-machine workflow,
  the `pull.rebase = true` config, and the push-before-switching golden
  rule. A follow-up fix corrected the command's own hardcoded repo path
  (`cerberus-platform` → `cerberus`, matching this machine's actual clone
  directory name).
- **Ran 4.5, closing Phase 4.** Diffed milestone 3
  (`phase-3-scalable-compute-complete`) against a new milestone 4
  (`phase-4-orchestration-complete`), same pattern as ADR 0004/0006/0008.
  Three questions re-answered with concrete new evidence from this
  phase's actual live pass: `mitigate-interaction-failure` (Reliability)
  gained "Set client timeouts" — every ASL Task state carries an explicit
  `TimeoutSeconds` tuned to its own downstream's real behavior (120s
  Lambda invoke, 2100s Spark-on-EKS transform, 900s dbt, 300s Athena
  query); `monitor-aws-resources` (Reliability) and `observability`
  (Operational Excellence) both gained tracing-related choices from the
  same underlying evidence — 4.3's X-Ray instrumentation on the state
  machine, the orchestration layer's first real distributed trace across
  Lambda → ECS Fargate → ECS Fargate → Athena. **None of the three moved
  a risk bucket** — overall workload risk counts are unchanged from
  milestone 3 (25 HIGH / 18 MEDIUM / 9 NONE / 5 N/A) — recorded honestly
  in ADR 0010 rather than glossed over, same discipline as ADR 0008's
  `ready-to-support`/`manage-service-limits` partial credit. Considered
  but not forced: Cost Optimization's `select-service`/
  `manage-demand-resources` (ADR 0009's zero-idle-cost bet, confirmed by
  4.4's scoped destroy leaving the orchestration layer standing, but
  already fully credited from Phase 1–3's own service decisions);
  Security's `permissions` (the two live-discovered IAM grant gaps
  reinforce already-selected "reduce permissions continuously," no new
  checkbox); Operational Excellence's `event-response` (the six live-pass
  bugs were fixed ad hoc, not through a formal incident process — stayed
  honestly at "None of these"). Wrote
  `docs/adr/0010-phase-4-well-architected-review.md`. **Phase 4 flipped
  to ✅ Complete** across `Phases.md`, `docs/plan.md`'s roadmap table, and
  `README.md`'s status section. Shipped on branch
  `phase-4-well-architected-review`, merged via PR #15 (regular merge,
  not squash, per the established workflow).

### 2026-08-21

_Opened Phase 5 (CI/CD) and landed its foundational decision in one day:
ADR 0011, the `envs/dev` state split, the live migration, and the OIDC
trust-policy/CI-bug fixes it immediately surfaced. Merged as PR #16._

- **Wrote ADR 0011 (Proposed at the time — see 2026-08-24 for
  acceptance).** Two decisions bundled together because designing the
  second one forced the first:
  - **Tool choice, GitHub Actions over the inherited AWS CodePipeline
    line:** investigating "what actually runs `terraform plan` on a PR"
    surfaced that CodePipeline is a merge/branch-triggered delivery tool,
    not built around reacting to a GitHub `pull_request` event the way
    5.1 describes — the same "make the inherited stack line a reasoned
    decision" pattern as ADR 0005/0009.
  - **The bigger problem:** `envs/dev` was one root/one state mixing the
    always-cheap standing resources (S3, IAM, Glue, Athena, the Lambda,
    the orchestration layer) with the resources ADR 0007/0009 deliberately
    keep destroyed between exercises (VPC's NAT Gateway, EKS, Spark
    Operator, `cerberus-spark`). A naive CI `apply` on every merge would
    recreate the whole EKS/NAT/Spark stack from scratch each time — a
    portfolio project's commit cadence turned into a standing bill.
    Resolved by splitting into `envs/dev-standing` (CI-managed) and
    `envs/dev-compute` (human-run only, per exercise, never CI) — carving
    `vpc_nat` out of `vpc` and `iam_spark` out of `iam` along the same
    boundary.
  - **Two IAM roles, not one, because the repo is public:**
    `cerberus-ci-plan` (read-only, trusted for any PR including forks —
    `terraform plan` has to check every PR to be useful) and
    `cerberus-ci-apply` (write-scoped, name-prefix-limited, trusted only
    for `ref:refs/heads/main` — a fork's PR can never get write access).
    `cerberus-ci-plan`'s ARN stored as a repo Variable, `cerberus-ci-apply`'s
    as a Secret — Secrets aren't exposed to a fork's `pull_request` run, so
    keeping `ci-plan`'s ARN plaintext is what keeps the one check that has
    to work for forks actually working.
- **Live migration, run the same day:** `terraform state mv` moved all 8
  previously-applied `envs/dev` modules (56 resources) into
  `envs/dev-standing`'s new state, address-for-address, zero recreation,
  then applied `github_oidc`'s new resources. `envs/dev-standing` plan came
  back clean afterward; `envs/dev-compute` planned a clean fresh
  23-resource spin-up (not applied — that's a real exercise start, left for
  later). Picked up the private route table, its subnet associations, and
  the S3 gateway endpoint as newly-permanent — ADR 0007's original `vpc`
  module coupled them to the NAT Gateway via an inline route, so prior
  destroy cycles (3.7, 4.4) tore them down alongside NAT even though
  they're free; the new `vpc`/`vpc_nat` split (a standalone `aws_route`
  instead of an inline route block) means they now survive a compute
  teardown. `AWS_CI_PLAN_ROLE_ARN`/`AWS_CI_APPLY_ROLE_ARN` set in GitHub
  from `dev-standing`'s outputs.
- **OIDC trust-policy fix**, found via live testing: this GitHub org embeds
  immutable numeric IDs into the `sub` claim
  (`repo:OWNER@12345/REPO@67890:pull_request`, not the plain
  `repo:OWNER/REPO:...` shape most docs assume) — a `StringLike` condition
  on `sub` never matched, confirmed via CloudTrail's actual rejected
  `AssumeRoleWithWebIdentity` calls. Fixed by matching the token's
  dedicated `repository`/`ref` claims instead, which are immune to
  whatever shape `sub` takes. Separately, AWS IAM rejects any GitHub-OIDC
  trust policy that doesn't evaluate `sub`/`job_workflow_ref` at all
  (`MalformedPolicyDocument`) regardless of other conditions — added a
  loose `sub` condition just to satisfy that.
- **Three real CI-tooling bugs from the first live plan run:**
  `terraform plan | tee` masked `terraform`'s real exit code (`tee`'s,
  almost always 0, wins) — a real plan failure would have silently
  reported as a green run; added `set -o pipefail`.
  `module.lambda_ingestion`'s `archive_file` data source needs a real,
  populated build/layer/python directory that's gitignored and doesn't
  exist on a fresh checkout (the same problem 2026-08-20's cross-machine
  sync already hit by hand) — added a setup-python + `pip install` step to
  both workflows. `cerberus-ci-plan`'s hand-enumerated read-only action
  list was missing routine AWS-provider refresh permissions.
- Merged as PR #16.

### 2026-08-22

_The first live `terraform-apply.yml` run — triggered by PR #16's merge —
failed during refresh with `AccessDenied` on seven distinct AWS API calls,
confirming ADR 0011's own prediction ("expect real `AccessDenied` fixes
during the first live apply run")._

- Root-caused each of the 7 gaps: the Athena query-results bucket (outside
  `bucket_arns`' bronze/silver/gold), the Athena workgroup name (policy
  pattern used a hyphen, the real workgroup is `cerberus_platform` with an
  underscore), the Faker Lambda layer's separate ARN namespace, three
  `logs:ListTagsForResource` calls (the policy's `/cerberus/*` pattern
  never matched the real log-group prefixes,
  `/ecs/cerberus-orchestration-*` and
  `/aws/vendedlogs/states/cerberus-platform-orchestration*`),
  `iam:GetRole` on the EventBridge Scheduler's own execution role, and no
  EC2 permissions at all (`ec2:DescribeVpcs` failing first).
- **Found the live AWS policy had already been hand-patched** for every one
  of these gaps (state modified 4 minutes after the failed run) — evidently
  from an earlier local session that debugged this live against AWS but
  never committed the fix. Rewrote the committed HCL to match what was
  already proven live rather than guessing a fresh, divergent fix,
  including its more precisely-scoped two-statement EC2 split
  (`ManageVpcCore` on resource-type ARNs, `DescribeVpcCore` on `"*"`, since
  EC2's action matrix structurally requires `"*"` for `Describe*` actions).
  Verified via `terraform plan`: zero diff against the live policy. Shipped
  as PR #17 (`b19dd17`), merged the next morning.

### 2026-08-23

_PR #17 landed, and the second live apply run it triggered hit two more EC2
gaps neither the original policy nor the live-AWS-matched fix had covered —
closed same day as PR #18._

- `terraform-apply.yml` reran after PR #17's merge, got past all 7 original
  gaps, then failed on `ec2:DescribeSecurityGroups`
  (`orchestration_runner`'s security group) and `ec2:DescribePrefixLists`
  (the S3 gateway endpoint's AWS-managed prefix-list lookup) — neither
  reachable by `ManageVpcCore`'s resource-type-scoped actions, same
  `Resource: "*"` requirement as the other `Describe*` actions already in
  `DescribeVpcCore`. Added both. Shipped and merged as PR #18 (`f7bd953`).

### 2026-08-24

_A long day that closed out the rest of Phase 5 end to end: 5.1/5.2 first
(the bootstrap-loop fix and live verification below), then 5.3 (pipeline
code CI), 5.4 (README build badges), and 5.5 (the Well-Architected pass) —
Phase 5 is now fully ✅ complete._

- **CI's rerun after PR #18's merge hit the *same* two `Describe*` errors
  again**, despite the fix being merged — root-caused as a genuine
  structural bootstrap loop, not a flaky run: `terraform apply` refreshes
  every resource in state before computing or executing anything, so a
  refresh failure on the EC2 permissions blocks the apply that would
  otherwise grant them; separately, `cerberus-ci-apply`'s own policy is
  deliberately excluded from what `cerberus-ci-apply` itself can ever
  modify (the self-escalation guard ADR 0011 documents by design), so
  CI's own apply could never have applied this fix to itself regardless.
- **Broke the loop with a targeted local apply**: ran
  `terraform apply -target=module.github_oidc.aws_iam_role_policy.ci_apply`
  as `cerberus-admin` — a real AWS mutation, but scoped to exactly one IAM
  policy resource, done with explicit user confirmation first. Reran the
  same CI workflow (no new commit needed, since the committed HCL already
  matched) and **`terraform-apply.yml` completed successfully** — the
  first real end-to-end green run of Phase 5's apply pipeline.
- **Verified against ADR 0011's own stated completion bar for 5.1/5.2**:
  `terraform plan` on `dev-standing` came back with only the pre-existing,
  unrelated Faker Lambda-layer hash churn (see Notes/blockers — the layer
  is rebuilt via `pip install` at every apply, producing a different
  `source_code_hash` each time regardless of any real change, so it always
  shows a 1-add/1-change/1-destroy diff); `dev-compute` came back with a
  clean 23-resource fresh-apply plan, no errors. No IAM/`github_oidc`
  drift either way.
- **ADR 0011 flipped `Proposed` → `Accepted`**; **5.1 and 5.2 checked off**
  in Phases.md. Phase 5's own heading marker flipped ⬜→🔨 (same precedent
  as Phase 3/4's partial-completion flips), `docs/plan.md`'s roadmap row
  updated to "🔨 In progress" to match (its `AWS CodePipeline` stack-label
  text is now stale per ADR 0011's own tool-choice reversal, but left
  untouched here — that's a stack-description edit, out of `/end-day`'s
  scope, not a status marker), and `README.md`'s Status section gained a
  Phase 5 line.
- **5.3 — pipeline code CI.** New `code-ci.yml` workflow (`ruff check` +
  `ruff format --check` for Python; `dbt parse` + `sqlfluff lint` for the
  dbt project), path-filtered to `ingestion/**`/`transform/**`, separate
  from the two Terraform workflows. Turning Ruff on for the first time
  surfaced 8 real findings, all fixed: a genuine bugbear (B023)
  late-binding-closure bug in `payments_lib.generate_events` (a nested
  `event()` closure captured loop variables by reference, not value —
  harmless today since it's only ever called synchronously within the same
  iteration, but fixed properly via default-argument binding rather than a
  `noqa`), unsorted imports, a stale `datetime.now(timezone.utc)` instead
  of the 3.11+ `UTC` alias, and several over-100-char log lines. Ran
  `ruff format` once to normalize the whole tree (`docs/notes/*.md`
  excluded — those are dated code snapshots via `/note-maker`, not source
  to reformat). For dbt: confirmed live that `dbt parse` never opens a
  warehouse connection (runs clean against a committed dummy profile,
  `transform/dbt/ci_profiles/`, no real AWS profile behind it), but
  sqlfluff's own `dbt` templater unexpectedly *does* — it calls
  `sts:GetCallerIdentity` to build a relations cache even just to lint,
  confirmed by watching it fail with `NoCredentialsError` locally. Switched
  `.sqlfluff` to the plain `jinja` templater instead (with
  `apply_dbt_builtins`), which lints the same 3 mart models clean with zero
  AWS access needed. New root `pyproject.toml` (line-length 100,
  `E/F/I/B/UP`) and `requirements-dev.txt` (ruff, sqlfluff, pinned).
  Shipped as PR #20; both `python-lint` and `dbt-validate` ran green on the
  PR itself, confirmed via `gh pr checks` before checking off 5.3 — same
  "written and plan-verified isn't done" bar 5.1/5.2 used.
- **5.4 — green build badge on README.** Three badges, one per workflow
  (`terraform plan`, `terraform apply`, `code CI`) rather than picking one
  — there's no single "the build" across a Terraform-plus-lint pipeline.
  Confirmed live by curling each badge's SVG endpoint directly: all three
  render `"... - passing"`, including the two PR-only-triggered workflows
  that never run directly on `main` (a real worry going in — GitHub's
  badge behavior for non-push-triggered workflows isn't obviously
  documented — but it resolved correctly). Shipped as PR #21, a doc-only
  change with no CI to wait on.
- **5.5 — Well-Architected pass, closing Phase 5.** Wrote
  `docs/adr/0012-phase-5-well-architected-review.md`, diffing milestone 4
  against a new milestone 5 (`phase-5-cicd-complete`), same pattern as
  ADR 0004/0006/0008/0010. Queried the live Tool first (`aws
  wellarchitected list-answers`/`get-answer`) rather than guessing which
  questions Phase 5 touched — found `dev-integ`'s own milestone-4 notes
  had already named the exact gap Phase 5 closes ("No CI/CD build system
  yet"). Two questions gained a genuinely new selected choice, both
  applied live via `aws wellarchitected update-answer`: **OE `dev-integ`**
  — "Use build and deployment management systems" (GitHub Actions is now
  a real one); **Security `permissions`** — "Share resources securely with
  a third party" (`cerberus-ci-plan`/`cerberus-ci-apply`, federated to
  GitHub Actions via OIDC, are the first AWS access this project has ever
  granted outside the AWS account itself — a third party by the Tool's own
  framing). Three more questions (`identities`, `mit-deploy-risks`,
  `tracking-change-management`) gained real, specific new evidence
  recorded in their notes without a new checkbox — e.g.
  `tracking-change-management`'s "Deploy changes with automation" was
  already selected on the strength of Terraform-not-console, but every
  actual apply through Phase 4 was still a human running `terraform
  apply` from a terminal; Phase 5 makes that claim strictly true
  (`terraform-apply.yml` runs it unattended in CI). Deliberately did
  *not* select `dev-integ`'s "Fully automate integration and deployment"
  (`envs/dev-compute` stays human-run-only by design) or
  `mit-deploy-risks`'s "Automate testing and rollback" (rollback is still
  entirely manual) — same honesty discipline ADR 0010 used declining
  `event-response`. **Milestone 5 saved live**
  (`aws wellarchitected create-milestone`, confirmed via
  `list-milestones`); overall risk counts came back unchanged from
  milestone 4 (25 HIGH / 18 MEDIUM / 9 NONE / 5 N/A, confirmed via
  `get-lens-review`) — recorded plainly, including that ADR 0010's own
  prediction ("Phase 5... opens entirely new ground, more likely to move
  buckets") did not hold in practice. Shipped as PR #22. **Phase 5 flipped
  to ✅ Complete** across `Phases.md`, `docs/plan.md`'s roadmap table
  (status marker only, its stale `AWS CodePipeline` stack text still left
  as-is per the same out-of-scope reasoning as 5.1/5.2's session entry
  above), and `README.md`'s Status section.

### 2026-08-27

_Built and shipped 6.1 (CloudWatch dashboards + data-freshness probe),
opening Phase 6. Two PRs: #23 (the module) and #24 (a CI-permissions fix
its failed apply forced). The probe immediately surfaced a real
pre-existing failure — the daily pipeline has been red for a week._

- **Design decision, made with the user before building:** for the
  "data freshness" half of 6.1, use a **scheduled probe Lambda**, not a
  pipeline-emitted metric. Reason: CloudWatch has no native "time since
  last write" metric and CloudWatch dashboard metric math has no `now()`,
  so a "seconds stale" number can't be derived from the pipeline's own
  emitted metrics — it needs an external observer on its own clock. The
  probe also keeps working when the pipeline stops running (the failure
  mode that matters most), and 6.2's alarms get a real metric to
  threshold.
- **Built `terraform/modules/observability`** (instantiated from
  `envs/dev-standing`, per ADR 0011's no-idle-cost placement — same
  reasoning as the orchestration layer):
  - `aws_cloudwatch_dashboard "cerberus-platform-pipeline"` — 9 widgets
    over metrics AWS already publishes (no new emitters for this part):
    Step Functions execution outcomes (24h singleValue) + `ExecutionTime`
    avg/p90/max, per-integration timing (`LambdaFunctionRunTime` /
    `ServiceIntegrationRunTime` / `ActivityRunTime` — a text widget points
    at X-Ray / execution history for true per-named-state latency, which
    CloudWatch doesn't expose), the ingestion Lambda, the Athena serving
    query by workgroup, probe health, and a freshness widget (metric math
    `mN/3600` → hours). One dashboard stays within CloudWatch's always-free
    3-dashboard tier.
  - `observability/freshness_probe/handler.py` (new top-level
    `observability/` dir, mirroring `orchestration/`) — an hourly
    EventBridge Scheduler Lambda, boto3-only so **no dependency layer**
    (plain `archive_file` over one committed file, no `null_resource`/pip
    step, unlike `lambda_ingestion`). Publishes `Cerberus/Pipeline` →
    `FreshnessSeconds` with a `Signal` dimension: `PipelineRun`
    (`states:list_executions` filtered `SUCCEEDED`, `maxResults=1` — age of
    `stopDate`), `BronzeData` and `GoldData` (newest-object `LastModified`
    via paginated `list_objects_v2`). Missing signals logged + skipped, not
    emitted as zero.
  - Self-contained probe execution role (`cerberus-freshness-probe`:
    `states:ListExecutions` on the state machine ARN, `s3:ListBucket` on
    bronze/gold, `cloudwatch:PutMetricData` scoped by a
    `cloudwatch:namespace` condition) and scheduler role — the same
    self-contained pattern `step_functions` uses for its own scheduler
    role, kept out of the central `iam` module because the policy is 1:1
    with this one Lambda and coupled to the state machine ARN this module
    already receives.
  - `retry_policy.maximum_retry_attempts = 2` on the probe schedule
    (unlike ingestion's 0 — the probe is a pure idempotent read +
    PutMetricData, so a retry just refreshes the same datapoints).
- **PR #23 merged, then its `terraform-apply.yml` run failed** — two
  distinct problems, cleanly separable:
  - **A (mine): `cerberus-ci-apply` had no permissions for the new
    resources.** Fixed in `terraform/modules/github_oidc` (PR #24): four
    grants, same name-prefix scoping as the rest of the policy —
    `ManageStandingIamRoles` + `role/cerberus-freshness-probe*` (covers
    `iam:PassRole`), `ManageIngestionLambda` renamed `ManageStandingLambdas`
    + `function:cerberus-freshness-probe*`, `ManageLogGroups` +
    `log-group:/aws/lambda/cerberus-freshness-probe*` (the ingestion
    Lambda has no explicit log group, so `/aws/lambda/*` was never needed
    here before), and a new `ManageObservabilityDashboard`
    (`cloudwatch:PutDashboard`/`GetDashboard`/`DeleteDashboards`). Like the
    Phase 5 IAM fixes, this had to be applied locally as `cerberus-admin` —
    `cerberus-ci-apply` can't modify its own policy (the self-escalation
    guard).
  - **B (pre-existing, not mine):
    `module.orchestration_runner.null_resource.build_and_push` cannot run
    in CI** — its `local-exec` shells out to `docker` and
    `aws … --profile cerberus-admin`, neither present on a GitHub runner.
    Dormant until `9ce67a0` (2026-08-24, PR #20) ran `ruff format` over
    `transform/spark/promote_payments_spark.py` — a cosmetic reformat that
    still moved `filemd5` — and no terraform-touching PR merged between
    then and #23 to apply it, so PR #23 was simply the first apply to trip
    it. **Decision (with the user): option (a) — reconcile now, track the
    proper fix separately.** Documented the local-apply-first workflow in
    `orchestration_runner/main.tf`'s header; a real fix (a CI build/push
    job, deleting the `null_resource`) is deferred as its own decision —
    see below.
- **Recovery, applied locally as `cerberus-admin`** (`terraform apply
  -auto-approve` on `dev-standing` — the non-`-auto-approve` run stalled
  at the interactive prompt because the harness backgrounds long commands
  and their stdin gets EOF, cancelling the apply): `Apply complete!
  11 added, 2 changed, 2 destroyed` — `module.observability` created, the
  `github_oidc` policy updated, `build_and_push` rebuilt+pushed (3m32s),
  plus the usual Faker-layer churn. Verified live: dashboard renders;
  `aws lambda invoke cerberus-freshness-probe` →
  `{"reported": {"PipelineRun": 649651, "BronzeData": 1009994,
  "GoldData": 649745}, "missing": []}`; all three metrics visible via
  `aws cloudwatch list-metrics --namespace Cerberus/Pipeline`.
- **PR #24 merged; its `terraform-apply.yml` run was green** — the only
  change was the known Faker-layer churn (`build_and_push` was *not*
  replaced — the local apply reconciled its trigger hash and CI computed
  the same one). `main`'s apply badge is green again.
- **Finding the probe caught on its first run:** the daily orchestrated
  pipeline has failed 7/7 since 2026-08-21 (last `SUCCEEDED` 2026-08-20).
  `RunTransform` needs the EKS cluster, which is torn down between compute
  exercises — so the EventBridge-scheduled daily run has been failing at
  that step ever since the Phase 4 demo. Recorded under Next up + below;
  to be resolved before/within 6.2 (a daily-failing pipeline breaks naïve
  alarm thresholds).
- **6.1 checked off** in Phases.md; Phase 6's heading flipped ⬜→🔨 and
  `docs/plan.md`'s roadmap row flipped ⬜ Planned → 🔨 In progress (status
  marker only), same partial-completion precedent as Phases 3/4/5.

### 2026-09-01

_Recovered the stranded 6.1 `/end-day` writeup, then resolved the
pipeline-failure finding it had left open. No new subtask; Phase 6 stays
at 6.1 done, 6.2 next._

- **Recovered the 2026-08-27 `/end-day` bookkeeping** (commit `84fd999`).
  That session shipped all of 6.1 via PRs #23/#24 but never committed the
  four sync files — `checkpoint.md`'s 2026-08-27 entry + Next-up rewrite,
  Phase 6 → 🔨 in `Phases.md` and `docs/plan.md`, README's Phase 6
  paragraph — which had been sitting uncommitted in the working tree. The
  implementation was already on `main`; only the narrative was stranded.
- **Resolved the pipeline-failure finding (Option A + ADR 0011
  amendment).** PR #25 (`b1e37ad`). Decision confirmed with the user:
  - New **`pipeline_active`** bool, committed in
    `terraform/envs/dev-standing/variables.tf` (default `false`), threaded
    to `module.step_functions`, where it sets
    `aws_scheduler_schedule.daily`'s `state` to `ENABLED` / `DISABLED` (an
    in-place update, no destroy/recreate).
  - Default-off is the honest default: since 4.3 folded the platform's
    only schedule into the state machine's parent, the *whole* pipeline —
    ingestion included — is dormant by design while `dev-compute` (EKS) is
    torn down, which is the normal state. An always-ENABLED schedule then
    just failed `RunTransform` daily (7+ failed executions, 3 Fargate task
    starts each, since 2026-08-21).
  - Committed default rather than a local `-var` override: CI applies
    `dev-standing` on every terraform-touching merge with no `-var` flags,
    so an override would be silently reverted mid-exercise. Flipping it is
    a small visible PR bracketing a compute exercise — runbook added to
    `terraform/envs/dev-compute/main.tf`'s header, keyed to the `Makefile`
    `standing-*` / `compute-*` targets.
  - **ADR 0011 gained an "Amendment (2026-09-01)" section**: the decision,
    why a committed default, and the two rejected alternatives — (b) leave
    the schedule on and make 6.2's alarms tolerant (rejected: blinds the
    alarms whenever compute is down, i.e. most of the time), and (c)
    decouple `RunTransform` from EKS (rejected: erodes Phase 3's
    Spark-on-EKS showcase to work around a scheduling problem).
  - Verified live: CI `terraform-apply.yml` run on the merge showed
    `aws_scheduler_schedule.daily: state = "ENABLED" -> "DISABLED"` in-place,
    `Apply complete! 1 added, 2 changed, 1 destroyed` (the add/destroy is
    the known Faker-layer churn), and
    `aws scheduler get-schedule --name cerberus-ingest-payments-daily`
    returns `"State": "DISABLED"`.
- **Softened README's Phase 2 status line** — it claimed ingestion "runs
  on a Lambda triggered by EventBridge Scheduler, confirmed firing
  unattended," which stopped being the steady state once the schedule went
  DISABLED-by-default. Now describes the Lambda + the `pipeline_active`
  gate.

### 2026-09-04

_6.2 and 6.3 both built, applied live, and merged — Phase 6 is now 4 of 6
subtasks done._

- **Built 6.2, CloudWatch alarms + slow-job alerting** (PR #26,
  `403c6d1`/`96f77d3`). New `terraform/modules/observability/alarms.tf`:
  a dedicated `cerberus-pipeline-alerts` SNS topic (email subscription
  managed in Terraform — deliberately a new topic, not a reuse of the
  Phase 0 `cerberus-billing-alerts` one, so a pipeline page and a cost
  page stay separate channels — confirmed by the user's own choice among
  three options offered) plus seven alarms:
  - **Two unconditional** (freshness-probe self-health — if the observer
    breaks, every gated alarm below goes stale-blind):
    `cerberus-freshness-probe-errors` (`AWS/Lambda Errors`, `notBreaching`)
    and `cerberus-freshness-probe-silent` (`AWS/Lambda Invocations`
    dead-man switch, 3-of-3 hourly periods, `breaching` on missing data).
  - **Five gated on `var.pipeline_active`** (threaded from
    `envs/dev-standing` into `module.observability`, same switch ADR
    0011's 2026-09-01 amendment already committed 6.2 to using):
    `cerberus-pipeline-run-unsuccessful` (a metric-math alarm summing
    `ExecutionsFailed`+`ExecutionsTimedOut`+`ExecutionsAborted`),
    `cerberus-pipeline-execution-slow` (`ExecutionTime` Maximum > 45min —
    Maximum, not p90/p99, since a once-daily execution has only one
    datapoint per run), `cerberus-ingestion-errors`,
    `cerberus-freshness-pipeline-run` and `cerberus-freshness-gold-data`
    (`FreshnessSeconds{Signal}` > 36h, `treat_missing_data = missing` —
    not `breaching` — so flipping `pipeline_active` on for a new exercise
    doesn't guarantee a false page before the first run completes). No
    `BronzeData` freshness alarm: the ingestion Lambda is still
    `RETIRE_ON_OR_AFTER=2026-08-17`-capped, so bronze doesn't refresh even
    during an active exercise — a manual-generation concern, not a
    pipeline-health signal, matching the dashboard's own framing.
  - Extended `cerberus-ci-apply` (`terraform/modules/github_oidc`) with
    scoped `cloudwatch:PutMetricAlarm`/`DeleteAlarms`/tag actions on
    `alarm:cerberus-*`, scoped `sns:*` on `cerberus-pipeline-alerts*`, and
    `cloudwatch:DescribeAlarms` on `"*"` (no resource-level support) —
    added proactively, but not enough on its own (see below).
  - **Hit the same self-escalation guard `ReadOwnCiIdentity` documents**:
    the first CI apply on merge failed —
    `iam:PutRolePolicy on resource: role cerberus-ci-apply` denied,
    because the new grants lived inside `cerberus-ci-apply`'s *own*
    policy, and that role cannot widen its own permissions (by design —
    the same guard 027d663 hit for 6.1). Fixed the documented way: applied
    locally as `cerberus-admin` (5 added/2 changed/1 destroyed — the
    policy fix, the SNS topic+subscription, the 2 probe-health alarms,
    plus the pre-existing cosmetic Faker-layer churn), confirmed via a
    follow-up `terraform plan` showing "No changes," then let the merge's
    CI apply proceed as intended.
  - Verified live: both probe-health alarms created and evaluating
    (`probe_errors` → `OK`, `probe_silent` → settling to
    `INSUFFICIENT_DATA` as expected right after creation), the 5 gated
    alarms correctly absent (`pipeline_active` still `false`), and the SNS
    email subscription confirmed by the user
    (`PendingConfirmation: false`) — the topic actually delivers now.
- **Planned 6.3 before building it**, at the user's request ("Have we
  planned 6.3?") — nothing existed beyond Phases.md's one-liner and
  plan.md's phase-level "dbt tests (or Great Expectations)" note. Laid out
  a concrete first pass grounded in the actual dbt models/schema
  (`transform/dbt/models/`) and a real finding:
  `orchestration/runner/entrypoint_dbt.sh` ran `dbt run`, not `dbt test`/
  `dbt build`, so no test would ever execute in the orchestrated pipeline
  even once written — plan.md's Phase 6 "done when" (bad data fails
  loudly) wasn't met by test YAML alone. Recommended dbt tests over Great
  Expectations (no second framework/runner needed — the dbt project
  already runs as an ECS Fargate step) and `dbt run` → `dbt build`; user
  confirmed both as the defaults to build.
- **Built 6.3, dbt tests for data quality** (PR #27, `64c19f6`/`c16cb13`).
  New `transform/dbt/macros/test_non_negative.sql` (a custom generic test
  for `amount >= 0` — no `dbt_utils` dependency added for one check).
  `transform/dbt/models/sources.yml` gained column tests on
  `payments_events` (`not_null`, `accepted_values` on `event_type` and
  `currency` — values confirmed against `payments_lib.py`'s actual
  generation logic, not guessed). New `transform/dbt/models/marts/
  schema.yml`: `unique`+`not_null` on both dimension tables' keys; on
  `fct_transactions`, `unique`+`not_null` on `transaction_id` (the exact
  invariant the 2026-08-11 tiebreak bug violated — this is the test that
  would have caught it), `accepted_values` on `status`, `non_negative` on
  `amount`, `relationships` to both dimensions. Used dbt 1.12's newer
  nested `arguments:` syntax for `accepted_values`/`relationships` (the
  flat form is deprecated as of this dbt-core version) after `dbt parse`
  surfaced the deprecation warning live. `entrypoint_dbt.sh`: `dbt run` →
  `dbt build`, closing the loop with 6.2 — a failing test now fails the
  ECS task → fails `RunDbt` → fails the execution →
  `cerberus-pipeline-run-unsuccessful`.
  - **Found and fixed a real latent gap**: `orchestration_runner`'s
    `null_resource.build_and_push` only ever hashed `dbt_project.yml`/
    `profiles.yml` as triggers, never the `models/`/`macros/` files the
    Dockerfile `COPY`s wholesale into the image — a model/test-only change
    would have silently never rebuilt the deployed image, the exact
    "stale deploy, no signal" bug class 6.3 exists to close. Fixed with
    two `fileset()`-based trigger hashes (`dbt_models_hash`,
    `dbt_macros_hash`), scoped to those two directories and excluding
    dbt's gitignored `target/`/`logs/` (matching `.dockerignore`) so the
    hash stays reproducible between a local apply and CI's checkout.
  - **Verified thoroughly before merging, not just parsed**: `terraform
    validate` clean; `dbt parse` (CI's exact profile/invocation) clean,
    no deprecation warnings; `sqlfluff lint models/` (CI's exact
    invocation) clean; **`dbt build` against live Athena data**
    (`cerberus-transform` profile) — **25/25 pass, 0 errors, 0 warnings**,
    including `unique_fct_transactions_transaction_id` passing on real
    data. `terraform plan` on `dev-standing` came back 1-add/0-change/
    1-destroy (only `null_resource.build_and_push` — docker build/push,
    which CI cannot run). Applied locally as `cerberus-admin`: image
    rebuilt and pushed to ECR in 8m44s, confirmed via a follow-up
    `terraform plan` showing "No changes." The merge's CI apply then ran
    as a clean no-op, confirming the local-apply-first workflow left
    nothing for CI to reconcile.
  - Not yet exercised through a real orchestrated `RunDbt` execution —
    that needs a `dev-compute` exercise (`pipeline_active = true`),
    intentionally out of scope for this subtask.

### 2026-09-07

_Phase 6 taken from 3/6 to fully ✅ complete in one long session — 6.4
(all four units + the Spark live-verification), 6.5, and 6.6. Ten PRs
(#28–#36, all merged), a real `dev-compute` EKS exercise, and the
platform's first Well-Architected risk-bucket movement since milestone 1._

- **6.4a — curated lineage doc + dbt DAG on Pages** (PR #28,
  `d003afb`/`70cfb74`). `docs/lineage.md`: the whole-pipeline view at
  table + column granularity across both transform engines, three findings
  (dbt only sees its slice; `payments_current` is orphaned in the
  orchestrated path; the silver schema has three hand-synced definitions),
  and a "why not Marquez/DataZone" rationale. New `.github/workflows/
  dbt-docs.yml` builds dbt's model DAG fully offline (`dbt parse` +
  `dbt docs generate --empty-catalog --no-compile` — no warehouse
  connection, same basis as `code-ci.yml`) and deploys it + a
  `docs/pages/index.html` landing page to **GitHub Pages** (enabled via
  `gh api ... -f build_type=workflow`, `build_type=workflow`). Fourth
  README build badge added.
- **6.4b — serverless OpenLineage collector** (PR #29, `ca36b04`/`f04b29a`;
  ADR 0013 accepted separately in `6b36727`). Decision (scoped with the
  user first): OpenLineage as the capture standard; collect via **API
  Gateway HTTP API → Lambda → S3** rather than Marquez (standing
  Postgres + web service) or Amazon DataZone (managed domain) — both
  rejected on cost/standing-infra grounds, ADR 0007/0009/0011's line.
  **Unauthenticated + rate-capped** (10/s, 20 burst) — the first
  unauthenticated ingress in the stack, accepted on blast-radius grounds
  (write-only to a private lifecycle-expiring prefix, no producer
  credential to sign with, SigV4 not natively supported by
  openlineage-spark). New `terraform/modules/lineage`: dedicated bucket
  `cerberus-platform-lineage-<acct>` (no versioning — write-once keys;
  90-day expiry), `lineage/collector/handler.py` (boto3-only, verbatim
  storage, `events/malformed/` for bad bodies, always 200), the HTTP API
  with access logging. `github_oidc` gained scoped grants. Applied locally
  as `cerberus-admin` (self-escalation guard), smoke-tested live (valid
  event → 200 + stored verbatim; malformed → `events/malformed/`).
  - **GitHub GraphQL incident during the `gh pr merge` for #29** — the
    merge commit landed on `main` correctly, but the PR shows CLOSED (not
    MERGED) and the `push` webhook that fires `terraform-apply.yml` was
    dropped. Recovered by **PR #30** (`163e8f0`/`14efbf7`): added
    `workflow_dispatch` to `terraform-apply.yml` (a genuine manual
    re-apply lever), whose merge re-triggered the apply on `main` — CI
    apply then ran green with only the Faker churn, confirming
    `cerberus-ci-apply` handles the new lineage resources. PR #29's
    CLOSED-not-MERGED metadata is cosmetic and left as-is.
- **6.4c — wire the OpenLineage producers** (PR #31, `e5f16fd`/`39c7510`).
  dbt: `openlineage-dbt==1.53.0` in `transform/dbt/requirements.txt`,
  `entrypoint_dbt.sh` runs `dbt-ol build` (emits after dbt finishes,
  returns dbt's own exit code — a collector outage never fails `RunDbt`).
  Spark: `io.openlineage:openlineage-spark_2.12:1.53.0` via Ivy
  `deps.packages` + listener `sparkConf` with a `__OPENLINEAGE_URL__`
  placeholder that `entrypoint_transform.sh` / `submit_job.sh` substitute
  (or rewrite to a `console` transport when unset). `orchestration_runner`
  task defs get `OPENLINEAGE_URL`/`OPENLINEAGE_NAMESPACE`;
  `null_resource.build_and_push` now also hashes
  `transform/dbt/requirements.txt` (the same COPYed-but-never-hashed gap
  6.3 closed for `models/`/`macros/`). **dbt path verified live twice** —
  a local `dbt-ol build` against Athena, then the real
  `cerberus-orchestration-dbt:2` runner image as a standalone Fargate task
  (run in a public subnet with a public IP, since NAT is down while
  `dev-compute` is torn down): 16 events landed with column-level lineage.
  Applied locally as `cerberus-admin` (docker rebuild + task-def
  revisions + state-machine repoint).
- **6.4d — render the captured events** (PR #32, `8558cb5`/`a06307f`).
  `lineage/render/render_graph.py` (pure stdlib): reads the events
  (synced from S3), emits `/lineage/` on the Pages site — a Mermaid
  dataset/job graph (transform jobs only; dbt tests counted, not drawn), a
  column-lineage table per output, a dataset-identifier map. `dbt-docs.yml`
  on push assumes `cerberus-ci-plan` (read-only OIDC, same role
  `terraform-plan.yml` uses) and `aws s3 sync`s the events; PRs smoke-test
  the renderer against committed `lineage/render/sample/` fixtures — no
  AWS on PRs. **PR #33** (`ff42987`/`25e278a`) added `workflow_dispatch`
  to `dbt-docs.yml` too — the page's content depends on S3 state, not just
  code, so it needs a re-render lever after a compute exercise.
- **Spark caveat resolved — a real `dev-compute` exercise** (PR #34,
  `e024d6a`/`692dfc2`). Chose the manual `submit_job.sh` path over a full
  orchestrated run (targets the caveat directly, no `pipeline_active`
  toggle). `make compute-apply` brought up VPC NAT + EKS + Spark Operator
  (~20 min; one transient `CreateAccessEntry` 404 on the last resource,
  fixed by a re-apply). `submit_job.sh` ran the Spark job to `COMPLETED`;
  **`openlineage-spark_2.12:1.53.0` resolved via Ivy and paired cleanly
  with Spark 3.5.9**, the listener emitted the `bronze → silver` write as
  dataset + column lineage (`s3://…-bronze-…/payments` →
  `s3://…-silver-…/payments`, 16 cols). silver verified (8,723 rows via
  Athena). `render_graph.py` gained **`canonical()`** — the Spark
  integration names datasets by S3 path, dbt by catalog table, so without
  it the graph showed two disconnected halves; silver's `payments` and the
  catalog's `payments_events` now collapse to one node, joining the
  engines: `bronze → payments_events → {fct_transactions, dim_*}`.
  `spark-application.yaml`'s header updated to record the verification.
  - **Teardown hit the documented NAT/pod-termination gotcha**
    (`context deadline exceeded` on the `spark-operator` namespace) —
    worked around by force-clearing the namespace finalizer via the public
    EKS API (`kubectl replace --raw .../finalize`), then re-ran
    `terraform destroy` for the remaining 12 resources. Verified fully
    torn down (0 EKS / 0 NAT / 0 EIP / 0 EC2, `cerberus-spark` gone).
    Also found and **released an orphaned Elastic IP** (`54.89.47.36`,
    tagged `Phase=3`, unassociated, not in any Terraform state — a
    leftover from a prior Phase 3/4 exercise costing ~$3.60/mo).
- **6.5 — SLO write-up** (PR #35, `6afa6ef`/`5b4c83e`). `docs/slo.md`:
  six SLOs backed entirely by the 6.1/6.2 SLIs and alarms — no new
  instrumentation. Scoped with the user first (6-objective set, lightweight
  halt-and-fix error-budget policy, doc-only). Central idea: objectives
  split **active-window** (only while `pipeline_active = true`) vs
  **always-on** (the freshness probe), since the platform is dormant by
  design. Honest "current standing" section — the pipeline has run
  `SUCCEEDED` end to end only a handful of times, so trailing-window
  accounting starts from here.
- **6.6 — Phase 6 Well-Architected pass** (ADR 0014; PR #36,
  `89482fc`/`c8f6454`). Diffed milestone 5 → **new
  milestone 6** (`phase-6-observability-and-data-quality-complete`, saved
  and confirmed live). Eight questions re-answered via `update-answer`;
  **three moved a risk bucket** — the first movement since milestone 1,
  after Phases 2–5 all held flat at 25/18/9/5:
  - OpsEx `workload-observability` MEDIUM → NONE (6.1 dashboard + custom
    metrics + 4.3 traces surfaced from it)
  - Reliability `monitor-aws-resources` HIGH → MEDIUM (the freshness probe
    *computes* metrics; 6.2's metric-math alarm; 6.5's SLI formulas;
    "regularly review monitoring scope")
  - Performance `process-culture` HIGH → MEDIUM (perf KPIs from the latency
    SLO + timing widgets; monitoring solutions from the dashboard)
  Five more gained genuine new evidence without a bucket move:
  `observability` (+identify KPIs from the SLOs), `event-response` (off
  "None of these" for the first time — process-per-alert, dashboards,
  prioritise-by-impact), `operations-health`, `dev-integ` (+code quality:
  6.3 tests + 5.3 lint), `mitigate-interaction-failure` (+fail fast: 6.3's
  data-quality gate). Overall 25/18/9/5 → **23/19/10/5**. ADR is candid
  that a phase whose purpose *is* observability moving the observability
  questions doesn't imply Phase 7 will move anything (7.3's least-privilege
  review is the next real candidate, Security only).
- **Phase 6 flipped to ✅ complete** across `Phases.md` (6.4/6.5/6.6 +
  heading), `docs/plan.md`'s roadmap row, and `README.md`'s Status
  section, with ADR 0014 — PR #36 (`89482fc`/`c8f6454`).

### 2026-09-29

_Phase 7 started: 7.1 (scaled-up workload) and 7.2 (full orchestrated run)
both built and verified live in one `dev-compute` window._

- **Scoping discussion first**, per the "worth a scoping discussion" note
  left in Next up — three genuine open decisions, resolved via
  `AskUserQuestion` before touching code: `TRANSACTION_COUNT` 200 → 2000
  (10x, not 50x); 3-5 orchestrated executions in one `dev-compute` window
  rather than waiting on the real daily schedule across several days
  (cost discipline — avoids leaving EKS/NAT up for days just to get
  multiple runs); `RETIRE_ON_OR_AFTER` bumped forward (not removed) —
  keeps the cap itself as a live, working control rather than deleting it.
- **Built 7.1** (PR #37, `84b3843`): bumped the ingestion Lambda's
  `TRANSACTION_COUNT` 200 → 2000 and `RETIRE_ON_OR_AFTER` 2026-08-17 →
  2026-10-15 (`terraform/modules/lambda_ingestion/variables.tf`) — the cap
  had already passed (today is 2026-09-29), so the Lambda was a pure
  no-op before this. Also dropped the variable's stale "kept in sync with
  `run_payments_scheduled.sh`" claim — that script was fully decommissioned
  at 2.5; this Terraform variable is the only place the cap lives now.
  Clean `terraform plan` (0 add / 1 change / 0 destroy, both env vars
  only), CI plan check passed, merged, CI applied — verified live via
  `aws lambda get-function-configuration`.
- **Started 7.2's exercise** (PR #38, `85422e3`): flipped
  `pipeline_active = true` in `dev-standing` per the dev-compute runbook
  (ADR 0011). Plan showed the expected 6 alarms/dashboard widgets created
  and the schedule flipped `ENABLED`, plus the already-known cosmetic
  Faker-layer hash churn (checkpoint's existing note) — not a new issue.
  Merged, CI applied.
- **Brought up `dev-compute`** (`make compute-apply` equivalent, run
  directly via `terraform apply`): 23 resources — VPC NAT Gateway, EKS
  cluster, Spark Operator, Spark job service account. One real gotcha hit
  live: `aws_eks_access_entry.orchestration_transform` failed with
  `ResourceNotFoundException: No cluster found` immediately after the EKS
  cluster's own `Creation complete` — an EKS control-plane propagation lag
  right after creation, not a config error. Fixed by re-running
  `terraform apply`, which picked up just that one remaining resource
  cleanly (1 add / 0 change / 0 destroy) once the API caught up.
- **Ran 7.2's exercise: 3 manually-started state-machine executions**,
  all `SUCCEEDED`, ~6 minutes each end to end (`InvokeIngestion` →
  `RunTransform` → `RunDbt` → `RunServingQuery` → `PipelineSucceeded`).
  Verified every layer directly, not just the console's green checkmark:
  fresh bronze partitions at the new 2000-transaction volume (`aws s3 ls`,
  ~230-440KB per partition vs. the old ~35KB/200-txn runs); fresh silver
  Parquet written by the Spark job on EKS across both new and
  historically-backfilled `dt=` partitions (full-rebuild semantics, 1.7's
  design, confirmed still holds through the Spark path); dbt's
  `fct_transactions`/`dim_merchants`/`dim_customers` marts rebuilt with
  today's timestamp; the Athena serving query itself completing inside
  `RunServingQuery`; OpenLineage `START`/`COMPLETE` events for all three
  dbt models plus the `payments_events` source landing at the 6.4
  collector. Chose to stop at 3 (of the planned 3-5 range) rather than
  push to 5 — three identical successful runs already demonstrated
  repeatability; each additional run only extends billed `dev-compute`
  time without adding new signal.
  - **Freshness alarms (`cerberus-freshness-gold-data`,
    `-pipeline-run`) stayed in `ALARM` through all 3 runs** — correctly
    so, not a bug: the hourly freshness probe's last evaluation (04:29:24)
    predated the first run (04:53), so it was accurately reporting 6
    weeks of real staleness. Confirmed this is a timing gap, not a wiring
    problem, by checking the probe's schedule (`rate(1 hour)`, next due
    ~05:29) rather than assuming something was broken — a live
    demonstration that the alarm design (6.2) actually detects real
    staleness, not just a schedule wired to fire.
- **Tore down `dev-compute` — hit exactly the documented destroy-order
  gotcha** from this same checkpoint's Notes/blockers (captured
  2026-08-18/2026-08-20, predicted to "very likely recur on every future
  destroy"): the NAT Gateway destroyed before the node group left nodes
  `NotReady`, which stalled two `Terminating` pods in the `spark-operator`
  namespace (`context deadline exceeded` on the namespace delete).
  Diagnosed via `kubectl get namespace/pods -o json` (confirmed
  `NamespaceDeletionContentFailure`, pods stuck with an unmet
  `deletionTimestamp`), fixed exactly per the existing note —
  `kubectl delete pod --grace-period=0 --force` on both stuck pods, then
  re-ran `terraform destroy` for the remainder (EKS cluster, node group,
  IAM). Confirmed fully clean afterward: 0 EKS clusters, 0 NAT gateways,
  0 EIPs, empty `dev-compute` Terraform state.
- **Closed the exercise** (PR #39, `ac39ab4`): flipped `pipeline_active`
  back to `false` in `dev-standing` — plan mirrored PR #38 in reverse (6
  alarms/widgets destroyed, schedule `DISABLED`), merged, CI applied.
  Follow-up `terraform plan` on `dev-standing` shows only the pre-existing
  cosmetic Faker-layer churn — fully reconciled otherwise.
- **7.1 and 7.2 checked off** in `Phases.md`; Phase 7's heading flipped
  from ⬜ to 🔨 (in progress — 7.3-7.6 still open).
- **Built 7.3, the least-privilege IAM review repaying Phase 0's
  `AdministratorAccess` shortcut on `cerberus-admin`.** Scoped to
  `cerberus-admin` only (not the already-carefully-scoped service/execution
  roles, not ADR 0013's lineage-endpoint auth gap — both explicitly deferred
  per user decision during scoping).
  - **Method: real usage, not guesswork.** No CloudTrail trail exists in
    this account, so IAM Access Analyzer's automatic "generate policy from
    CloudTrail" feature was unavailable (it requires a trail, confirmed via
    docs — the default 90-day Event History alone isn't enough). Instead,
    pulled `cerberus-admin`'s **complete** CloudTrail history directly
    (`lookup-events`, no trail needed for data within 90 days) — 25,516
    events, 241 distinct operations, spanning the whole project since
    2026-07-31. Cross-checked against every Terraform resource type in the
    repo; added the data-plane actions CloudTrail's management-events-only
    view can't show (S3 object ops, DynamoDB item ops); added `iam:PassRole`
    (never its own CloudTrail event) scoped to the exact 5 services this
    project's own trust policies actually use (confirmed by reading
    `terraform/modules/iam/main.tf` directly, not guessed).
  - **6 customer-managed policies** (storage, analytics, compute,
    orchestration, network, iam-and-governance — split because IAM's
    6,144-char-per-policy limit can't hold this in one), committed to
    `iam/cerberus-admin/policies/` as the audit trail. Deliberately **not**
    Terraform-managed — self-managing `cerberus-admin`'s own policies via
    its own `terraform apply` is a bootstrapping risk, same reasoning as
    `terraform/bootstrap/`'s exception for the state backend (see
    `iam/cerberus-admin/README.md`).
  - **Rigorous verification caught real bugs before anything went live**
    (the whole point of the agreed "test then swap" approach): a
    completeness sweep (241/241 observed operations covered, the one
    apparent gap — `sts:GetCallerIdentity` — confirmed via AWS docs to
    require no IAM permission at all) and a 29-case `iam:simulate-custom-policy`
    battery (every real resource → `allowed`, every deliberately-unrelated
    resource → `implicitDeny`, `PassRole`'s condition correctly gated,
    deliberately-excluded actions correctly denied) caught a first bug — an
    IAM role ARN missing its required empty region segment
    (`arn:aws:iam:us-east-1:...` instead of `arn:aws:iam::...`, since IAM is
    a global service) — which would have silently broken every
    `CreateRole`/`PassRole`/`AssumeRole` call.
  - **Live `terraform plan` testing (after attaching the 6 policies and
    detaching `AdministratorAccess`) caught two more real gaps** the
    simulation battery's curated sample had missed: `s3:GetBucketLifecycle`
    isn't a real IAM action (Terraform's actual call needs
    `s3:GetLifecycleConfiguration`) and `logs:DescribeLogGroups` has no
    resource-level permission support at all (needs `Resource: "*"`).
    Rather than patch just those two, cross-checked **every** action across
    all 6 policies against AWS's Service Authorization Reference JSON
    (`servicereference.us-east-1.amazonaws.com`) — a stricter check than
    "does the action exist" also verified ARN **shape** (segment count,
    region presence) against each resource type's documented `ARNFormats`.
    Found and fixed 15 more real problems this way: S3's
    lifecycle/encryption/replication/ownership-controls/public-access-block
    actions all have different real IAM names than their CloudTrail event
    names (and no separate "Delete" action exists for several — deleting is
    done via the same `Put*` action with an empty config, confirmed against
    AWS docs); AWS Budgets' real IAM actions (`ViewBudget`/`ModifyBudget`)
    are completely different from its API operation names
    (`DescribeBudget`/`DeleteBudget` etc. aren't real IAM actions at all);
    `eks:CreateCluster` has no resource-level support (needs `"*"`, same
    reason EC2's networking actions do — the resource doesn't exist yet at
    authorization time); the EKS `access-entry` ARN needs 5 path segments,
    not the 3 guessed; the CloudWatch `dashboard` ARN has no region segment
    (`arn:aws:cloudwatch::account:dashboard/...`) while `alarm` does. (A
    same-checker flag on 7 Logs actions was confirmed a false positive — the
    checker's naive segment-splitting breaks on log group names that
    contain `/` themselves, e.g. `/aws/lambda/cerberus-ingest-payments`;
    already-passing simulation results confirmed those were never actually
    broken.)
  - **Hit a genuine, by-design self-lockout getting the fix live**:
    `cerberus-admin` couldn't call `iam:CreatePolicyVersion` on its own
    policies (self-policy-management was deliberately never granted, to
    avoid exactly the self-escalation risk `iam:PassRole` warns about,
    applied symmetrically) — and confirmed via the simulation battery that
    it couldn't re-attach `AdministratorAccess` to itself either. Required
    root-console intervention (MFA sign-in, CloudShell) to re-attach
    `AdministratorAccess` temporarily; pushed the corrected policy versions
    from there, then detached `AdministratorAccess` again. This is the
    intended, permanent shape of the boundary, not a bug to fix later — see
    `iam/cerberus-admin/README.md`'s "What's deliberately NOT granted".
  - **Final verification, live, with `AdministratorAccess` fully
    detached**: `terraform plan` across all three roots —
    `terraform/bootstrap` ("No changes"), `terraform/envs/dev-standing`
    (only the pre-existing cosmetic Faker-layer churn), and
    `terraform/envs/dev-compute` (23 to add, matching its normal torn-down
    state) — all clean, zero `AccessDenied`.
  - **7.3 checked off** in `Phases.md`.
- **Built 7.4, the full 57-question Well-Architected review across the
  whole platform** (not a per-phase diff pass like 1.13/2.6/3.8/4.5/5.5/6.6)
  — ADR 0015, milestone 7 (`phase-7-end-to-end-validation-complete`).
  User explicitly chose full honest re-review of all 57 questions over a
  faster "likely movers only" pass.
  - **Delegated to a forked instance** (57 questions × real evidence
    review × ADR drafting was too much mechanical back-and-forth to do
    inline) — the fork read every question's current choices, weighed
    7.1/7.2/7.3's real evidence against each honestly, called
    `update-answer` where warranted, saved the milestone, and drafted the
    ADR on its own branch without opening a PR, leaving that for review.
  - **Result: no risk bucket moved** — 23 HIGH / 19 MEDIUM / 10 NONE / 5
    N/A, identical to milestone 6. Two questions gained new,
    notes-recorded evidence without crossing: security `permissions`
    (added "Establish emergency access process" — 7.3's twice-exercised
    root-console path) and reliability `testing-resiliency` (added "Test
    scalability and performance requirements" — 7.1+7.2's verified 10x-
    volume runs). Honest outcome for a phase whose completed work so far
    is a config change, a verification exercise, and a permission-scope
    change — not the kind of pillar-defining build Phase 6 was.
  - **Independently verified the fork's work before trusting it**: milestone
    7's risk counts and both changed answers' exact selected-choices
    checked directly against live AWS state (`get-lens-review`,
    `get-answer`) — matched the ADR exactly.
  - **Sent the drafted ADR to an independent Opus review before merge**,
    at user's request, mirroring this project's own established practice
    (ADR 0005 was reviewed this way and real problems were found, not
    style nits). This one held up well but the review caught four real
    issues, all verified before fixing, not taken on trust:
    1. A dangling forward reference — ADR 0014 had explicitly deferred
       Performance Efficiency's `process-culture` "load test" choice to
       "Phase 7's scaled synthetic workload," by name. 0015 credited that
       same 7.1+7.2 evidence to `testing-resiliency` but never revisited
       `process-culture` itself — confirmed live: its Tool note was still
       Phase 6's, untouched. Fixed by adding an explicit decline (both in
       the ADR and live in the Tool via `update-answer --notes`, no
       choice change): the evidence answers a narrower question (meets a
       defined requirement at higher volume) than what "load test" asks
       (a repeatable capacity-limit-seeking practice), and 2000 rows/run
       is still a modest absolute scale.
    2. A self-contradictory sentence ("right in kind... but not in
       degree") that fought the review's own null-result table — rewritten
       plainly.
    3. "All 57 questions were re-answered" corrected to "re-reviewed" —
       only 2 of 57 actually changed.
    4. The `permissions`/emergency-access credit and its matching
       Consequences bullet were asserting a *mature* process as settled
       fact; qualified in both places (no break-glass role beyond root
       itself, no drill before this session, no audit trail given the
       account's missing CloudTrail trail) — same discipline ADR 0014
       used for `event-response`. Also strengthened `testing-resiliency`'s
       reasoning to cite `docs/slo.md`'s Objective 3 directly instead of
       arguing past its own concession.
  - **ADR 0015 accepted** by user after the Opus-driven revision; Status
    flipped to `Accepted`. 7.4 checked off in `Phases.md`.

### 2026-10-02

_7.5 (cost + security summary) completed, Phase 7 re-scoped to add
Prometheus (7.6–7.8), and 7.6 (ADR 0016) accepted. Run on the
`/home/chirag` workstation, the second machine, which has no Terraform
install._

- **7.5 scoping decisions** (via `AskUserQuestion`):
  1. **Cost data:** push a widened `ce:`/`tag:` read grant from root.
  2. **ADR 0013's lineage endpoint:** gate it on `pipeline_active`,
     rather than accept it as-is or add real auth.
  3. **No CloudTrail trail:** accept it as a documented gap.
- **Found and fixed an unapplied repo change.** Commit `2db7945` (made
  outside a session, 2026-09-30) added `ce:GetCostAndUsage`/
  `GetCostForecast` to the governance policy JSON, but it had never been
  pushed live (`AccessDenied` confirmed). Widened it with
  `ce:ListCostAllocationTags` and a new `TagCoverageRead` Sid
  (`tag:GetResources`). Action names were verified against the Service
  Authorization Reference, and `simulate-custom-policy` showed the four
  reads allowed and the write-side neighbours still denied.
  `simulate-custom-policy` rejects inputs over 2,000 chars, so the changed
  Sids were simulated in isolation. The user pushed the new version from
  the root console, and `ce:GetCostAndUsage` succeeding verified it live.
- **The user asked whether Claude could have its own policy-edit IAM
  user instead.** Recommended against it: any identity with
  `iam:CreatePolicyVersion` on `cerberus-admin`'s policies is
  `AdministratorAccess` one call away, which undoes 7.3. Offered an
  MFA-gated, policy-edit-only role as the middle ground if changes become
  frequent. **The user chose the root paste.** Recorded as residual risk 3
  in the summary.
- **Lineage collector narrowed (ADR 0013 amended).** The route's
  `authorization_type` now follows `pipeline_active`: `NONE` during an
  exercise, `AWS_IAM` otherwise, with no `execute-api:Invoke` grantee.
  Gating the route's auth rather than the API/stage was deliberate:
  `collector_url` is baked into the ECS task definitions (recreating the
  API would change the URL), and removing the only route from an
  auto-deploy stage risks a failed redeploy leaving the old route live.
  The first CI run failed `terraform fmt`: `type`/`default` weren't
  aligned with a heredoc `description` above them. Fixed after putting
  Terraform 1.16.5 in the scratchpad and running `fmt -check` + `validate`
  (with `TF_DATA_DIR` in scratchpad and `-lockfile=readonly`, so the repo
  wasn't modified). The CI plan was exactly as expected: 1 in-place route
  change plus the Faker churn. After merge and apply, an unsigned
  `POST /api/v1/lineage` → **403**, verified live.
- **Cost findings (Cost Explorer, unblended):**
  - **Every month's usage is exactly offset by credits**, so the real
    out-of-pocket cost is $0.00. Budgets' "actual" $9.39 is gross usage.
  - **About $6.59 of account spend was never the platform:** a stopped
    `t3.micro` `sre-lab` (`i-0b65d9fb63ede2e26`, ap-south-2, launched
    2026-06-29). Its EBS volume billed ~$0.73/month while stopped.
  - **The platform (us-east-1) cost $5.74 gross:**
    - $2.26 (39%) was an orphaned EIP, idle 2026-08-19 → 2026-09-07.
      CloudTrail showed two `AllocateAddress` calls 13 minutes apart
      during the 08-19 partial-apply crash, and state kept only the second.
      This is the same orphan released by hand on 09-07; now it has a
      price.
    - $3.20 (56%) was `dev-compute` exercises.
    - $0.28 was everything standing over three months.
  - **Lesson recorded:** teardown "0 EIP" checks must be account-wide
    (`describe-addresses`), not relative to state.
- **Tagging:** 41 of the 43 resources the Tagging API sees carry
  `Project=cerberus-platform`. The two exceptions are the Phase 0
  hand-built billing alarm and a billing payment instrument. Every
  user-defined tag was `Inactive` as a cost-allocation tag.
- **Account-owner actions from root, at the user's request:**
  - **Terminated `sre-lab`.** `cerberus-admin` correctly lacks
    `ec2:TerminateInstances`. The console greyed out Hyderabad even though
    `get-region-opt-status` returned `ENABLED`, so the user ran
    `terminate-instances` from root CloudShell instead. Its root volume
    had `DeleteOnTermination = true`. Verified `terminated`.
  - **Activated `Project`** as a cost-allocation tag. Verified `Active`
    2026-10-02 15:30 UTC.
- **`docs/cost-security-summary.md`** covers cost by month and bucket,
  why the platform is cheap, tagging, the identity table, data
  protection, 7.5's changes, and five accepted residual risks:
  1. Lineage open during exercise windows.
  2. No CloudTrail trail.
  3. Root-only `cerberus-admin` policy changes.
  4. The three organisational OpsEx HIGHs.
  5. Carried operational debt.

  Two drafting claims were caught and corrected against the repo before
  merge: there are no customer-managed KMS keys anywhere (the draft said
  EKS secrets used one), and the 09-07 EIP release came from PR #34's
  exercise session, not 6.6. Linked from README; `iam/cerberus-admin/README.md`
  gained a "Changes since 7.3" log. **PR #42**, merged.
- **Scope addition.** The user wanted orchestration and Prometheus
  discussed. View given: CloudWatch already covers all the serverless and
  managed layers natively, so Prometheus's real value is the EKS/Spark
  layer, which has no metrics collection at all. **The user chose to add
  it inside Phase 7, before the demo**, rather than as a new Phase 8.
  `Phases.md` now has 7.6 ADR, 7.7 build + live verification, and 7.8
  demo (renumbered from 7.6). `docs/plan.md` gained a *Scope addition*
  bullet, the roadmap row, and the demo artifact now includes
  observability. **PR #43**, merged. The orchestration topic itself was
  raised but not specified; carried to Next up.
- **7.6 — ADR 0016, Prometheus for the EKS/Spark layer.** The
  Well-Architected method reference was rendered verbatim first.
  - Facts verified before drafting: no add-ons, Container Insights or
    Prometheus in code; the cluster is public-only with
    `authentication_mode = "API"`; nodes are 2× `m7i-flex.large`; Spark is
    1 driver + 1 executor at 1g. Current AMP, Managed Grafana and
    CloudWatch pricing came from the AWS pricing pages; the managed
    collector's requirements from its user guide; AMP retention (150-day
    default, 1,095 max, Terraform-settable) was confirmed.
  - **Key finding:** the AMP managed collector needs *private* endpoint
    access, which ADR 0007 rules out, so it's recorded as a follow-up.
  - **Decision (option B):**
    - Storage: an AMP workspace in `dev-standing`.
    - Collection: an in-cluster Prometheus agent in `dev-compute` with a
      bounded scrape scope.
    - Spark: the native `PrometheusServlet`.
    - Viewing: in-cluster Grafana via port-forward only, with AMP plus
      read-only CloudWatch data sources and JSON-provisioned dashboards.
    - Rejected: Managed Grafana (fixed $9/month minimum) and Container
      Insights, both enhanced and OTel (it covers infra, but Spark would
      be the bolted-on part).
  - **Independent Opus review** (user-requested, as for ADR 0015), with
    findings verified before applying. It caught two real must-fixes:
    1. **Two manual steps, not one.** `cerberus-ci-apply` can't modify
       its own policy (`github_oidc/main.tf` comment), so the first
       `dev-standing` apply is local, after a root paste.
    2. **The Container Insights argument was wrong.** Custom metrics are
       prorated hourly, and the OTel variant was missing.

    Should-fixes applied: the managed collector costs ~$29/month if left
    standing; the Pushgateway would not be standing; 7.2 had no metrics to
    compare; Thanos/S3 and ADOT alternatives added; Spark Operator scope;
    free-tier hedge. Nits applied: bounded scrape scope behind the ~10k
    estimate; "56%" means all `dev-compute`; IRSA `cerberus-*` naming;
    remote_state wiring (confirmed present); WAL flush before NAT
    teardown; `spark.ui.prometheus.enabled`; Grafana's AMP plugin. One
    reviewer citation was wrong (it pointed at ADR 0013's new amendment),
    but the finding stood on the code comment. Declined: dropping the
    "Sustainability: Follows Cost" row.
  - **Accepted** by the user; **PR #44**.

### 2026-10-03

_7.7's standing half built and live, its `dev-compute` half built and
checked offline. Ran on the `/home/chirag` workstation and closed after
midnight (2026-10-04)._

- **Decisions at start of day:**
  1. **Ingestion retirement moved** 2026-10-15 → **2026-10-30**
     (`lambda_ingestion` `retire_on_or_after`). PR #45 merged; CI
     applied it; the live Lambda's `RETIRE_ON_OR_AFTER` was checked.
  2. **Tooling: install on this machine.** Terraform 1.16.5, `kubectl`
     v1.37.1 and `helm` v4.3.0 are now single binaries in `~/.local/bin`,
     each checksum-verified. `docker` and `aws` were already here.
  3. **Orchestration: Step Functions stays; Airflow only if needed
     later.** That matches ADR 0009 as written, including its own "revisit
     Airflow (likely MWAA)" trigger, so nothing was amended. Resolves the
     open "orchestration" question carried from 2026-10-02.
- **7.7 part 1: AMP workspace + IAM (PR #46, merged and applied).**
  - `cerberus-admin`'s governance policy gained four AMP Sids:
    `AmpWorkspaceAccount`, `AmpTagOnCreate`, `AmpWorkspaceMgmt` and
    `AmpQuery`. Both pastes went through the root console, and
    `iam/cerberus-admin/README.md`'s change log explains both.
    `cerberus-ci-apply` gained matching management-only grants: no
    `RemoteWrite`, no `Query*`.
  - Action names were checked against AWS's machine-readable service
    reference (`servicereference.us-east-1.amazonaws.com/v1/aps/aps.json`)
    *and* against the provider source.
  - **The provider read always calls `aps:DescribeLoggingConfiguration`**
    even with no logging configured. It wasn't in the original checkpoint
    list, and without it every plan would 403.
  - **A tagged `CreateWorkspace` also checks `aps:TagResource` on a
    collection ARN**, `arn:aws:aps:<region>:<acct>:/workspaces`. That ARN
    isn't in the Service Authorization Reference.
    `simulate-custom-policy` can't evaluate it (it returns `implicitDeny`
    even for `"Resource": "*"`), and the console validator rejects it as
    an error. The first two local applies 403'd on it; the second was
    because the root paste hadn't actually been saved. **The grant ended
    as `arn:aws:aps:us-east-1:<acct>:*`, `TagResource` only.** No
    workspace was orphaned either time.
  - New `terraform/modules/prometheus_workspace`: workspace alias
    `cerberus-platform` plus `aws_prometheus_workspace_configuration`
    with **90-day retention**. That matches lineage's 90 days; ADR 0016
    only required retention to be explicit. `dev-standing` exposes
    `prometheus_workspace_arn`, `prometheus_endpoint` and
    `prometheus_remote_write_url`.
  - **First apply was local as `cerberus-admin`**, after merging #45
    first. Ordering mattered: any `main` merge before #46 would have made
    CI try to remove the workspace and roll back `ci_apply`'s policy.
    Workspace `ws-87e9cc99-40d8-4bc4-bc63-7d65d6beb7b4` was verified
    `ACTIVE`, tagged, with retention 90 `ACTIVE`. The follow-up local plan
    showed **No changes**; CI's plan and apply on #46 showed only the
    Faker churn.
- **7.7 part 2: `dev-compute` (branch `phase-7-prometheus-dev-compute`,
  `a7fe0b4`).**
  - New `terraform/modules/eks_observability`, wired into `envs/dev-compute`
    with `depends_on = [module.eks, module.vpc_nat]`. The `vpc_nat` edge
    means the agent is destroyed, and flushes its WAL, before the NAT goes.
  - **Prometheus:** `prometheus-community/prometheus` 29.35.0, app v3.15.0,
    in agent mode. The IRSA role `cerberus-prometheus` holds
    `aps:RemoteWrite` on the workspace only. There are six scrape jobs:
    `prometheus-agent`, `spark-driver` (`:4040/metrics/prometheus/`),
    `spark-executors` (`:4040/metrics/executors/prometheus/`, both selected
    by the `spark-role=driver` label rather than a pod annotation),
    `spark-operator`, `kube-state-metrics` and `node-exporter`.
    Alertmanager and the Pushgateway are disabled.
  - **Grafana:** `grafana-community/grafana` 13.2.7 (Grafana 13.2.3). The
    old `grafana/helm-charts` repo stopped at 10.5.x. It's `ClusterIP`
    only, with no PVC. The AMP plugin is pinned at 3.2.0 (needs Grafana
    ≥ 12.2.5) with `sigV4AuthType: default`, and there's a read-only
    CloudWatch data source. The IRSA role `cerberus-grafana` holds AMP
    query plus CloudWatch read and `ec2:DescribeRegions`. Dashboards come
    from a ConfigMap built from `observability/grafana/dashboards/*.json`.
  - **Dashboard `spark-on-eks.json`** (20 panels, uid
    `cerberus-spark-on-eks`): Step Functions executions from CloudWatch,
    Spark Operator counts, executor and driver metrics, pod and node
    health, and agent remote-write health, including the "Samples pending"
    teardown check.
  - **`spark-application.yaml`:** the `PrometheusServlet` sink,
    `spark.ui.prometheus.enabled`, `spark.metrics.conf.driver.source.jvm.class`
    (no JVM metrics otherwise), and `spark.metrics.namespace: cerberus` (so
    series names don't carry the per-run app ID).
  - **Checked offline before any apply:**
    - **`--agent`** is the Prometheus 3 flag, confirmed against the real
      v3.15.0 binary's `--help` with a negative control.
      `--enable-feature=agent` is the removed v2 form.
    - Both charts were rendered with the module's *real* values. The plan
      can't show them, because the IRSA ARNs make every `values` string
      unknown, so a scratch root evaluated the module's own `yamlencode`
      blocks with placeholder ARNs. That caught two real chart issues:
      1. The chart injects its default jobs (apiserver, cAdvisor, all
         pods) from a separate **`scrapeConfigs` map**, on top of
         `serverFiles`. Fixed with `scrapeConfigs = null`.
      2. With `scrape_configs` and `rule_files` gone, the ConfigMap
         template rendered a stray **`{}`** and invalid YAML. Fixed by
         putting `remote_write` inside `serverFiles."prometheus.yml"`
         instead of `server.remoteWrite`.
    - **`promtool check config --agent` passes** on the final render.
    - `terraform validate` and `fmt` are clean. The `dev-compute` plan is
      31 to add. The `dev-standing` plan is `build_and_push` (the
      `spark_files_hash` trigger) plus the Faker churn.

### 2026-10-05

_A short evening session on the `/home/chirag` workstation. 7.7's
`dev-compute` half reached `main`; the live exercise didn't start. Closed
after midnight (2026-10-06)._

- **PR #47, "7.7 (part 2)".** The branch had in fact been pushed at the
  close of 2026-10-03; only the PR was missing. CI's `dev-standing` plan
  was exactly as predicted: 2 to add, 1 to change, 2 to destroy
  (`orchestration_runner.null_resource.build_and_push` replaced, plus the
  Faker layer and Lambda churn). `python-lint` and `dbt-validate` passed.
- **Runner image rebuilt locally before the merge** (the `build_and_push`
  workaround). The local plan matched CI's. The user applied the saved plan
  with `!` (2 added, 1 changed, 2 destroyed, about 4.5 minutes for the
  `docker build`/`push`). The new `cerberus-orchestration-runner:latest`
  digest in ECR (`sha256:8f54a3cd…`) matched the push output, and a
  follow-up plan showed **No changes**.
- **#47 merged** (regular merge, `da2c249`, by the user). CI's apply on
  `main` changed only the Faker layer and Lambda (1 added, 1 changed, 1
  destroyed). `build_and_push` didn't come up, so the workaround held.
- **Auto mode blocks more than IAM.** It denied the `dev-standing` apply
  even with no IAM change in the plan ("Protected-Scope IaC Apply"), and
  `gh pr merge` ("Merge Without Review"). The Notes entry below is
  updated.
- Stopped before step 3 (`pipeline_active = true`) on purpose. Flipping it
  enables the daily schedule, which fails unless EKS comes up straight
  after.

### 2026-10-06

_A long session on the `/home/chirag` workstation. 7.7 verified live, 7.8
recorded, Phase 7 closed, Phase 8 planned with ADR 0017 accepted, and 8.2
done. PRs #48–#54._

- **Exercise bracket.** `pipeline_active = true` (#48), CI apply as
  predicted (6 added / 3 changed / 1 destroyed: schedule `ENABLED`, five
  gated alarms, lineage route `AWS_IAM` → `NONE`, Faker churn). Flipped
  back to `false` after teardown (#49); schedule confirmed `DISABLED`.
- **First `dev-compute` create since 7.3 failed partway.** The cluster,
  NAT and roles came up, then the node group failed: `Failed to validate
  if SLR: AWSServiceRoleForAmazonEKSNodegroup already exists due to
  missing permissions for 'iam:GetRole'`. `cerberus-admin`'s `GetRole`
  was scoped to `role/cerberus-*`. Added `IamServiceLinkedRead`
  (`iam:GetRole` on `role/aws-service-role/eks*`) to
  `cerberus-admin-iam-and-governance.json`; root pushed the new version
  from the console; all 76 actions in that file then simulated `allowed`
  against the live user. A second plan (18 to add) applied cleanly. The
  access-entry 404 in the same failed apply did not recur on that second
  apply. _(Corrected 2026-10-07: not a timing artefact but a missing
  dependency. `spark_job` got the cluster name as a literal, so the access
  entry raced the cluster on every fresh apply. Fixed in #59.)_ Lesson: 7.3 was verified with `simulate` and `plan`, and a
  plan never exercises create-time calls.
- **7.7 checks, all passed:** 2 nodes `Ready`; 5/5 `monitoring` pods
  `Running`; IRSA annotations correct; remote-write 17,269 samples at
  first check with 0 failed / retried / pending (1,396,957 sent by
  teardown, still 0 failed); Grafana AMP data source `OK`. The CloudWatch
  data source health shows `ERROR` only for its Logs half, by design
  (metrics-only grant). All three Spark scrape targets `up`.
- **Rehearsal run** `rehearsal-7-7-20261006T063937` SUCCEEDED in 6m40s.
  Every dashboard series name checked against AMP: all correct except the
  three driver panels. PrometheusServlet exports each gauge as `_Number`
  and `_Value`, so the `.*` regexes drew duplicate lines; now `_Value`.
  `spark_application_failure_count` only appears after a failure (fine).
  **Peak 4,349 active series** (465 Spark `metrics_*`) vs ADR 0016's
  ~10k.
- **7.8 recorded:** `demo-7-8-take1-20261006T075445`, SUCCEEDED in 6m03s,
  narrated tab by tab while the user screen-recorded (Take 1 kept).
  Athena result led by Mcclure, Ward and Lee (842 settled).
- **Teardown:** 31 destroyed; account-wide 0 EKS / 0 NAT / 0 EIP / 0
  running instances; AMP stays. Samples pending was 0 before destroy.
- **Data-quality pass (14 cross-layer Athena queries, scratchpad only):**
  39,222 events / 12,862 transactions / 32 partitions. Clean: silver↔gold
  reconciliation, duplicate `(transaction_id, event_type)`, lifecycle
  (one `created`, ≤1 terminal, no refund without settle, order), refund
  events = gold `refunded` (636), partition placement, key nulls, amount
  range and stability per transaction, roster 15/75, dim FKs, email and
  `last4` masking. **Two findings, fixed in #50:** (1) hex tokens held
  13–16 digit runs, 22 of them Luhn-valid, which a DLP scanner would flag
  → tokens are now `tok_` + 16 lowercase letters (`secrets`); old bronze
  events keep their old tokens; (2) the demo query summed USD/EUR/GBP
  together → now grouped by currency (45 rows).
- **Two CI gaps found by #50:** (1) the Terraform workflows only watched
  `terraform/**`, though `dev-standing` reads six other paths via
  `file()`/`templatefile()` → both workflows now watch them, leaving the
  `build_and_push` trigger paths out on purpose; (2) `cerberus-ci-apply`
  lacked `states:ValidateStateMachineDefinition`, which the provider
  calls before updating a state machine. That action has **no resource
  types**, so only `Resource = "*"` grants it (#51). Because the CI role
  can't edit its own policy, #51 went in by a local `dev-standing` apply
  first (ADR 0016's order), then merge; both fixes confirmed live.
- **Phase 7 ✅** across Phases.md, plan.md and README (#52), with the IAM
  policy and dashboard fixes recorded.
- **Phase 8 planned** (#53): discussion settled on a mixed platform +
  data engineering thesis, $20/month, six weeks; streaming (Kafka) +
  Airflow on one start/stop EC2 instance deferred to a later phase. ADR
  0017 drafted with the pillar method and accepted.
- **8.2** (#54): budget, quotas and account plan, as summarised above.
- **Cost:** platform (`us-east-1`) posted usage $5.82 through 2026-10-05;
  today's exercise was estimated at ~$0.70, so about $6.50 for the whole
  build (confirm once it posts). The account's `ap-south-2` charges
  ($3.68 to date) are not the platform.
- **Also produced, outside the repo:** an animated dataflow page
  (private Artifact, https://claude.ai/artifact/4FRJRVYkRicRh1dwnZYcWM)
  and a LinkedIn post draft (2,978 chars) for the Take 1 video.

### 2026-10-07

_8.3 done in one session: ADR 0018, the generator, the metric set with a
baseline from existing runs, `make exercise`, and the first live exercise.
PRs #55–#60._

- **Generator design → ADR 0018 (Accepted, #55).** Tested locally in
  `apache/spark:3.5.9` before writing it: a 539 MB JSON array read with
  `multiLine=true` ran out of memory at 512 MB heap, where 538 MB of JSON
  Lines split into 5 partitions; and `multiLine=true` on JSON Lines
  silently returns only the first object. So bulk data is JSON Lines on a
  sibling prefix (`payments_bulk/run_id=/dt=/`), invisible to today's
  silver job, cumulative ladder (1M, +9M, +90M), and a first Delete grant
  in bronze limited to that prefix.
- **Generator (#56).** PySpark from `spark.range`, the roster copied from
  `payments_lib` (checked live against 886 bronze events, and by
  `check_bulk_roster.py`), every value a hash of (`run_id`, row id, salt).
  Local 100k run: 0 rule violations, identical output across runs, a
  re-run replaced only its own files. A self-review caught the count pass
  re-running the write's shuffle (45 GB at 100M); fixed before merge.
- **Metric set + baseline (#57).** All sources checked live: Step
  Functions history, Athena per-state bytes (matched by submission time),
  AMP (series and `metrics_executor_totalInputBytes`), S3 listings, an
  Athena count as `cerberus-transform`, Cost Explorer. Baseline from the
  five existing runs, which all predate #50 (it touched only
  `InvokeIngestion` and `RunServingQuery`). Findings: the silver job reads
  bronze **3×**; node instances are **untagged** ($0.33 of $0.84 on
  2026-10-06); `RunServingQuery` is ~55 s of Step Functions polling; and
  **90% of 2026-10-06's cost was the cluster waiting** (2.10 h up, 13 min
  of runs). The user asked to check the `#50` claim; the first PR text had
  understated its scope, and both the doc and the PR were corrected.
- **`make exercise` (#58).** Testing with a fake `terraform` (`TF_BIN`)
  found a real bug: a signal to the process group also killed the log
  `tee`, and the script died of SIGPIPE **before the destroy**. `tee` now
  ignores INT/TERM, the teardown ignores INT/TERM/PIPE, and preflight fails
  closed when state can't be read (it first said "empty" on a credential
  error).
- **First exercise, failed apply (11:14–11:43 UTC).** `CreateAccessEntry`
  404, "No cluster found": `spark_job` took the cluster name as a literal,
  so the access entry raced the cluster. The trap destroyed all 30
  resources; account check 0/0/0/0; cluster up 28 min (~$0.19). Fixed in
  #59 (`module.eks.cluster_name`; `terraform graph` shows the edge). The
  same 404 on 2026-10-06 had been recorded as a timing artefact; that
  entry is corrected.
- **Second exercise, succeeded (`exercise-20261007T145442Z`, 14:54–15:37
  UTC).** Apply 966 s. Generator `e1000000-20261007T151119Z`: 1,000,029
  events, 8 files, 432.6 MB, write 42.9 s (23,307 events/s); the
  `payments_bulk/` grant worked first time. Orchestrated run SUCCEEDED,
  411 s, 45,304 events; Spark read 63.1 MB = 3 × bronze `payments/` again;
  peak 4,808 series. Destroy 924 s, 31 resources; account check
  0/0/0/0. **Cluster up 42 min** against 2.10 h on 2026-10-06.
- **Collector fix (#60).** The transform's driver reused the generator
  driver's pod IP, so a few scrapes carried stale `spark_app` labels and
  the transform's bytes showed under both apps. Now grouped by Spark's
  `application_name`, after a max per executor to collapse the duplicate
  series. Record re-collected; every other field identical.
- **Workstation:** `gh` upgraded 2.46.0 → 2.102.0 in `~/.local/bin`
  (checksum-verified), because the apt build broke `gh pr view`. The user
  asked for PR links with review commands every time; saved as a
  preference.
- **Cost today:** about $0.55 (failed attempt ~$0.19, exercise ~$0.28,
  8 Cost Explorer requests $0.08). `--cost-only` tomorrow records the
  posted number.
- **8.3 checked off** in Phases.md. Phase 8 stays 🔨.

### 2026-10-07 (second session)

_8.4 done: the data-quality suite as code, its catalog and grants applied
by CI, and the first full run passing. PRs #61, #62. No cluster time._

- **Design decision:** the suite runs as Athena queries under
  `cerberus-transform`, called by the collector, not as a state-machine
  step. No cluster is needed, the result lands in each run's record, and
  the orchestrated path stays unchanged until 8.5.
- **Bronze in Athena without partitions.** Checked first: all 191 bronze
  `payments/` files are single-line JSON arrays (largest 478 KB), so
  `bronze_payments_raw` reads each file as one text line and the checks
  unpack it with `json_parse`. `bronze_payments_bulk` reads the JSON Lines
  with the OpenX SerDe. Both tables are unpartitioned; `dt` and `run_id`
  come from `"$path"`, so nothing has to be registered per run. Bronze also
  showed 6,082 letter tokens and 39,222 legacy hex tokens, which is why
  `token_format` accepts both and `token_digit_runs` is a `warn`.
- **Grants.** The bronze tables have their own module output: putting them
  in `table_names` would have widened `cerberus-serving`'s catalog grant.
  `cerberus-transform` gained read on `bronze/payments_bulk/*` and
  `GetTable`/`GetPartitions` on the two tables. The CI apply role already
  had `glue:*` on `table/cerberus_platform/*`. Local and CI plans matched
  (3 add / 2 change / 1 destroy, including the Faker churn); CI applied it
  cleanly.
- **Tests before merge:** the 14 silver/gold checks passed on live data
  with one warning (97, the same as 2026-10-06's manual count); the bronze
  checks failed with `TABLE_NOT_FOUND` before the tables existed, proving
  the suite fails closed; a duplicated event injected into the queries'
  input was caught by `silver_duplicate_keys` and
  `lifecycle_created_authorized` and by nothing else.
- **First full run (after the apply), on `exercise-20261007T145442Z`:**
  17 checks passed, 1 accepted warning. Bronze → silver 45,304 = 45,304
  with 0 key differences; silver → gold 14,862 transactions;
  `bulk_run_counts` 1,000,029 written = 1,000,029 in the manifest; 922 MB
  scanned in 21 s (about $0.005). The two bulk checks are the part of the
  suite whose cost grows with the ladder (about $0.45 per run at 100M).
- **8.4 checked off** in Phases.md. Phase 8 stays 🔨.

### 2026-10-08

_8.5 done: incremental Apache Iceberg silver and gold at about 1M events,
proved by three exercises. Also a CI guard, a Makefile default, and a
partial-cost guard. PRs #63–#70._

- **Cost step deferred, guard added (#63).** `--cost-only` for 2026-10-07
  at 04:44 UTC returned a partly posted day (0.26 of ~1.2 cluster-hours,
  $0 EC2 compute); `Estimated` stays true all month, so it can't tell. Not
  recorded; the cost section now has `complete` and warns.
- **Silver design, tested locally first** (Docker, `apache/spark:3.5.9`,
  Hadoop catalog, real bronze copies). Iceberg 1.12.0 and 1.11.0 fail on
  Java 11 (`UnsupportedClassVersionError`); **1.10.2** chosen (user). The
  watermark must commit with the data: the session-conf snapshot property
  is ignored for SQL writes, and `CommitMetadata` via py4j deadlocked, so
  the insert-only MERGE is an anti-join + DataFrame append with
  `snapshot-property.cerberus.bronze_watermark`. Bronze listed with globs
  (a bare-key probe would 403). Full load read 73.4 MB for 73.3 MB of
  bronze; re-runs added 0. Swap in place (user): Terraform retired the Hive
  table; the job recreates `payments_events` as Iceberg.
- **CI landmine, then a bad re-run.** #64 merged before the local apply;
  CI's apply failed at `build_and_push` as expected (planned changes
  applied, image missing). The user's `make standing-apply` then built
  the image. A `gh run rerun` of the *latest failed* run picked #50's run
  from 2026-10-06 (ours was `cancelled`), which re-applied that old
  commit: it deleted the 8.4 bronze tables, re-created the Hive table and
  reverted `cerberus-transform`'s policy. A local apply from `main`
  restored everything (`4 add / 2 change / 3 destroy`, then `No changes`).
  **#65:** `terraform-apply.yml` now refuses any commit that isn't
  `main`'s head, before assuming credentials; verified on its own merge.
- **Exercise 1 (`exercise-20261008T085728Z`):** the Iceberg build
  worked — 1,051,434 events from both prefixes in one read — but `RunDbt`
  failed: the dbt task role could read only `silver/payments/*`, and Spark
  writes `timestamptz`, which Hive gold can't store. **#66** fixed both
  (dbt role reads `silver/iceberg/payments_events/*`; `fct` casts),
  removed the transform task role's MSCK-only grants and env, and fixed a
  `silver_caught_up` SQL bug. Verified without a cluster: `dbt build`
  PASS=25 and the suite PASSED against the live Iceberg silver.
- **Exercise 2 (`exercise-20261008T095905Z`):** first incremental silver
  run — SUCCEEDED in 351 s, 6,097 events appended into 1,057,531,
  RunTransform 164.9 s (baseline 205.6 s), data quality PASSED. Spark read
  30.3 MB and shuffled 41.2 MB, nearly all the anti-join scanning every
  silver key (8.6).
- **Iceberg gold (#69).** First live builds surfaced three things:
  `table_unique` nested the new table under the old Hive location and the
  Hive drop deleted the new metadata (now `schema_table_unique`);
  dbt-athena's full refresh renames the old table, which Athena can't do
  to a Hive table (the Hive `fct_transactions` was dropped once via
  Athena, Glue entry only); and dbt-athena prunes Glue table versions
  (both dbt roles gained `glue:GetTableVersions`/`DeleteTableVersion`).
  An incremental run with no new events merged 0 rows; PASS=25; suite
  PASSED.
- **Exercise 3 (`exercise-20261008T115807Z`):** both layers incremental —
  SUCCEEDED in 340 s; 6,094 events appended (silver 1,063,625); gold
  merged exactly 2,000 transactions (rows by `silver_loaded_at`:
  345,000 / 2,000 / 2,000); data quality PASSED; cluster up 33 min.
- **Also:** `Makefile` defaults `AWS_PROFILE` (#68) after two credential
  failures; the user asked which resume skills this work shows (IaC,
  CI/CD safety, incident response, IAM, containers, lakehouse migration,
  data quality, FinOps) and how to watch runs in tmux.
- **Cost today:** about $0.75 (three exercises: 41 + 37 + 33
  cluster-minutes) plus one Cost Explorer request.
- **8.5 checked off** in Phases.md. Phase 8 stays 🔨.

### 2026-10-08 (second session)

_Discussion and planning, then 8.6 measurements. PRs #71 (closed), #72,
#73 (open), #74, #75; branch `phase-8-6-prune-anti-join`._

- **Serving engine:** the user asked why Redshift isn't in the stack.
  Athena was never formally compared; an interactive explainer of how the
  Glue Data Catalog connects Spark, dbt, Athena (and, hypothetically,
  Redshift Serverless through Spectrum) was published as a private
  Artifact (https://claude.ai/artifact/4TMpEcEAY7BT9WoptoapiG). A plan
  entry for a Redshift evaluation (#71) was **closed unmerged** by
  decision: serving stays on Athena for cost. **#72** records it in ADR
  0002, with Redshift noted as pluggable via the catalog.
- **Go, planned not built (#73):** the user's idea of adding Go as data
  grows was discussed; the data path is Spark/Athena, so Go goes where its
  strengths do work: Phase 9 `cerberusctl` (replacing `exercise.sh`, the
  collector and the suite) and Phase 10 Kafka streaming with a Go producer
  and consumer. 8.6–8.11 stay Python/Spark/SQL. #73 also adds "Planned
  later work": a realistic time spread for the synthetic data, and Spark
  4 / Java 17.
- **8.6 anti-join, measured locally first** (Docker, real bronze copies,
  a local 1M-event run to match production's silver):
  - Day pruning from the new files' `dt=` paths: correct, small gain
    here (13.33 → 12.61 MB) because every batch lands in the same last
    7–8 days; kept on its branch.
  - Broadcasting the batch keys: read bronze twice — rejected.
  - Bucketing silver (`bucket(16, transaction_id)`) for a
    storage-partitioned join: **Spark 3.5.9 has no one-side SPJ**
    (`spark.sql.sources.v2.bucketing.shuffle.enabled` is Spark 4), so
    silver was still shuffled — rejected for now (→ Spark 4 plan item).
  - Hash-key anti-join (option 2): exact, halves the shuffle (46 → 22.5
    MB) but +60% run time at 1.2M rows (16.3 → 26.1 s) — rejected.
- **Exercise `exercise-20261008T160759Z` (#74's log capture, #75's
  record):** SUCCEEDED in 355 s; 6,086 new events (silver 1,069,711);
  data quality PASSED. RunTransform's 178 s: ECS start 25 s, upload 7 s,
  operator submit 8 s, driver image pull 10 s, Ivy 8 s (425 MB copied;
  Maven downloads <2 s), JVM/SparkContext 10 s, executor schedule + pull +
  start 19 s, catalog/listing 16 s, **data work 28 s**, maintenance 10 s,
  completion polling 8 s, ECS stop 24 s. The package-download suspicion
  was mostly wrong; the ECS wrapper and image pulls are the big levers.
- **Also:** the user asked which resume skills the work shows and how to
  watch runs in tmux; a `!`-started `make exercise` stopped harmlessly at
  the `[y/N]` question (no stdin) before any apply.
- **Cost:** one exercise, about $0.22 (33 cluster-minutes).

## Notes / blockers

- **Resolved 2026-10-05 (was: open, noted 2026-10-03):** branch
  `phase-7-prometheus-dev-compute` *had* been pushed. PR #47 merged it to
  `main`. The checkout was found on `main` at the start of 2026-10-06.
  `git status` is authoritative.
- **Auto mode blocks IAM changes, every `terraform apply`, and PR merges
  (noted 2026-10-03, widened 2026-10-05).** In Claude Code's auto mode,
  edits that widen an IAM policy (the `iam/cerberus-admin/policies/*.json`
  files) are denied as permission grants, even after the user says "go
  ahead" in chat. So is **any** `terraform apply`, including a
  `dev-standing` apply with no IAM in its plan ("Protected-Scope IaC
  Apply"), and `gh pr merge` ("Merge Without Review"). On 2026-10-06 it
  also blocked a plain *edit* of `terraform/envs/dev-standing/variables.tf`
  (the `pipeline_active` flip), as "Protected-Scope IaC Apply", because CI
  applies that root on merge. Ways through:
  switch out of auto mode (Shift+Tab) for that step, have the user run it
  with `!` (or merge on GitHub), or add allow rules in settings. Saving a
  plan with `-out` to the scratchpad and having the user apply that file
  works well. `simulate-custom-policy`, plans, reads and opening PRs are
  not blocked.
- **Saved `dev-compute` plans expire after about 15 minutes (noted
  2026-10-06).** The `kubernetes` and `helm` providers take their token
  from `data.aws_eks_cluster_auth`, and a saved plan carries that token.
  Applying a 45-minute-old plan failed with `Failed to update Config Map:
  Unauthorized`. Make each `dev-compute` plan right before its apply.
  `dev-standing` has no such provider, so its saved plans don't expire.
- **`kubectl port-forward` to Grafana drops after a while (noted
  2026-10-06):** `error: lost connection to pod`. During a recording, run
  it in a restart loop (`while true; do kubectl port-forward -n
  monitoring svc/grafana 3000:80; sleep 2; done`). Admin password:
  `kubectl get secret -n monitoring grafana -o
  jsonpath='{.data.admin-password}' | base64 -d`. To query AMP through
  Grafana's API use `/api/datasources/uid/amp/resources/api/v1/...`; the
  `/api/datasources/proxy/...` path returns `Missing Authentication
  Token`.
- **`cerberus-admin` read gaps that are fine as they are (noted
  2026-10-06):** `scheduler:ListSchedules` and `cloudwatch:DescribeAlarms`
  (look resources up by name instead), `athena:GetQueryResults` (read
  results as `cerberus-serving` or `cerberus-transform`),
  `eks:ListAccessEntries`, `iam:ListPolicies`,
  `elasticloadbalancing:DescribeLoadBalancers` (the project creates no
  load balancers), and `freetier:GetAccountPlanState` (run it as root in
  CloudShell). None blocked any work.
- **IAM simulator quirks (noted 2026-10-06):** passing a literal `*` in
  `--resource-arns` returns `implicitDeny` even when the policy allows
  it, so test with the default resource or a concrete ARN. An action with
  **no resource types** (e.g. `states:ValidateStateMachineDefinition`)
  can only be granted on `Resource = "*"`, whatever ARN the AccessDenied
  message names. Check
  `servicereference.us-east-1.amazonaws.com/v1/<service>/<service>.json`.
- **`cerberus-admin` can't list ECR repositories with a wildcard (noted
  2026-10-05).** That's 7.3's scoping. Look the repo up by name
  (`cerberus-orchestration-runner`, or from `terraform state show
  module.orchestration_runner.aws_ecr_repository.runner`) and run
  `aws ecr describe-images` against it.
- **Tooling on the `/home/chirag` workstation (noted 2026-10-03):**
  Terraform, `kubectl` and `helm` now live in `~/.local/bin`. There's no
  `.venv` or `pip` here, but `uv` is. The Faker layer that
  `envs/dev-standing`'s plan needs is built with `uv pip install -r
  ingestion/lambda/requirements.txt --target
  terraform/modules/lambda_ingestion/build/layer/python --python-version
  3.12 --python-platform x86_64-manylinux_2_28` (gitignored). Helm repos
  added locally: `prometheus-community`, `grafana-community`,
  `spark-operator`.
  _Updated 2026-10-07:_ a `.venv` exists but is nearly empty (no `boto3`,
  `botocore` or Faker), so run Python with `uv run --no-project --with
  boto3 ...` or `--with-requirements ingestion/requirements.txt` instead.
  `gh` is 2.102.0 at `~/.local/bin/gh`: the apt 2.46.0 in `/usr/bin` broke
  `gh pr view` on GitHub's removed Projects (classic) field. Docker is
  available, and `apache/spark:3.5.9` is pulled, which is how Spark code is
  tested locally at no cost. `gh pr diff` takes no path filter; use `git
  diff origin/main...origin/<branch> -- <path>`.
- **Run `make exercise` from the user's own terminal (noted 2026-10-07).**
  Auto mode blocks its `terraform apply`. Claude watches the log under
  `observability/scale/exercises/` (gitignored) with a Monitor filtered to
  milestones and errors. Exclude `Still (creating|destroying)` and Grafana's
  `Persistence is disabled` note from the filter, or every 10 s becomes an
  event.
- **Metric-source permissions and costs (noted 2026-10-07):**
  `cerberus-admin` has `athena:GetQueryExecution` but not
  `BatchGetQueryExecution` (fetch queries one by one) and can't
  `StartQueryExecution`, so counts run as `cerberus-transform`. Each Cost
  Explorer API request costs $0.01. An AMP query signed with SigV4 must
  encode spaces as `%20` (`quote_via=urllib.parse.quote`), or AMP answers
  403. zsh doesn't word-split `$VAR`, so `aws $P ...` with options in one
  variable fails.
- **Open, minor (noted 2026-10-07): Spark labels can go stale on pod IP
  reuse.** The transform's driver reused the generator driver's IP, and a
  few scrapes carried the old pod's `spark_app`/`pod` labels. The collector
  now groups by Spark's `application_name` (#60). The Grafana driver panels
  (`metrics_cerberus_driver_*`) don't separate two apps on one cluster
  either; fix it when two apps first share a dashboard view (8.5+).
- **Open, for 8.7/8.8 (noted 2026-10-07): EKS node instances are
  untagged.** A managed node group doesn't pass the provider's
  `default_tags` to its instances, so about 40% of an exercise day misses
  the `Project` tag. The collector scopes cost by region instead. The fix
  is a launch template with `tag_specifications`.
- **Athena reads unpartitioned tables recursively (confirmed 2026-10-07).**
  `bronze_payments_bulk` points at `payments_bulk/` and returned all
  1,000,029 events from the nested `run_id=/dt=/` objects, skipping
  `_SUCCESS`. The bulk checks scan the whole JSON every run; a Parquet copy
  or an Iceberg table is the fix if the cost starts to matter.
- **Never re-run an old `terraform apply` run (noted 2026-10-08).** A
  re-run applies that run's own commit; `--status failure` can return a
  days-old run when the latest one was `cancelled`. #65's guard now fails
  such runs before credentials. To re-apply `main`, use
  `gh workflow run terraform-apply.yml --ref main`.
- **Iceberg on this platform (noted 2026-10-08).** Iceberg 1.10.2 is the
  newest that runs on `apache/spark:3.5.9` (Java 11). Silver timestamps are
  `timestamptz`; Athena's Iceberg tables store `timestamp(6)` without a
  zone, so gold casts. Every role that reads silver needs
  `silver/iceberg/payments_events/*` (the dbt role was missed once).
  dbt-athena needs `glue:GetTableVersions`/`DeleteTableVersion` and a
  `schema_table_unique` location. Gold and silver are no longer queryable
  as Hive tables; the Hive data under `silver/payments/` and
  `gold/<table>/` is orphaned.
- **Local test gotchas (noted 2026-10-08).** Files written by the
  `apache/spark` container belong to its user, so clean them with a fresh
  directory, not `rm` (Claude Code's safety check also blocks `rm` inside
  `sh -c`). Running the container as the host UID breaks Hadoop's login.
  zsh doesn't split `set -- $var`. A local script named `inspect.py`
  shadows Python's `inspect` and breaks py4j. `2>1` (no `&`) writes a file
  named `1` into the repo.
- **Spark 3.5.9 limits found in 8.6 (noted 2026-10-08).** No one-side
  storage-partitioned join (Spark 4's
  `spark.sql.sources.v2.bucketing.shuffle.enabled`); also absent:
  `allowJoinKeysSubsetOfPartitionKeys`, `allowCompatibleTransforms`. A
  bucketed silver avoids its shuffle only when both join sides are
  bucketed tables.
- **Local Spark tests (noted 2026-10-08).** `mv` keeps old file times, so
  a moved bronze file can look older than the watermark (in S3,
  LastModified is the upload time); `touch` it. Use separate warehouse
  directories per variant (Iceberg metadata holds absolute paths, so a
  copied table writes into the original). Spark event logs give bytes
  read/shuffled and run time per variant.
- **AWS CLI service name (noted 2026-10-03):** the IAM prefix is `aps:`,
  but the CLI command is `aws amp ...` (`aws aps` doesn't exist).
- **Open, deferred, not blocking (noted 2026-08-27):**
  `module.orchestration_runner.null_resource.build_and_push` runs a
  `local-exec` (`docker build`/`docker push`,
  `aws ecr get-login-password --profile cerberus-admin`) that **cannot
  execute on a GitHub Actions runner** — so any `terraform-apply.yml` run
  fails whenever one of its `triggers` changes without a local
  `AWS_PROFILE=cerberus-admin terraform apply` first to rebuild+push the
  image and reconcile the trigger in state. Trigger set as of 2026-09-07:
  `transform/spark/*`, the whole of `transform/dbt/models/` and
  `transform/dbt/macros/` (added 6.3), `transform/dbt/{dbt_project,
  profiles,requirements}.yml`/`.txt` (`requirements.txt` added 6.4c), the
  Dockerfile, `.dockerignore`, the runner entrypoints/`lib.sh`.
  `orchestration_runner`'s own module header documents the workflow.
  Hit repeatedly in Phase 6 (6.2, 6.3, 6.4b, 6.4c, and #34) — always
  resolved the documented way. **Proper fix (deferred, its own decision):
  a CI job — or a small `dev-compute`-style local runbook — that
  builds+pushes the runner image on those paths, deleting this
  `null_resource`.** It expands CI's blast radius to ECR pushes, so it
  wasn't bolted onto Phase 6. **2026-10-06:** the Terraform workflows now
  also watch `dev-standing`'s `file()` sources (Lambda code, lineage
  collector, freshness probe, state-machine template, serving query), but
  deliberately *not* this resource's trigger paths, so the workaround is
  unchanged.
- **Resolved 2026-09-01 (was: open operational, noted 2026-08-27):** the
  daily EventBridge-scheduled orchestration run
  (`aws_scheduler_schedule.daily`, `step_functions` module) failed every
  day from 2026-08-21 because `RunTransform` needs the `dev-compute` EKS
  cluster, torn down between exercises. Fixed by the `pipeline_active`
  switch (ADR 0011 amendment, PR #25) — the schedule is now `DISABLED`
  unless a compute exercise is active. Schedule confirmed `DISABLED` live
  after the CI apply. Follow-through for 6.2: its pipeline-health /
  freshness alarms must be gated on the same `pipeline_active` var so a
  normal down period doesn't page (see Next up).
- **Open, cosmetic, not blocking (noted 2026-08-24):** the Faker Lambda
  layer (`module.lambda_ingestion.aws_lambda_layer_version.faker`) is
  rebuilt via `pip install` at every single `terraform apply` — local or
  CI — and is not bit-reproducible, so `source_code_hash` differs run to
  run even with zero real change. Every `dev-standing` apply (including
  every future CI merge) will therefore always show a 1-add/1-change/
  1-destroy diff for this one resource. Confirmed pre-existing, unrelated
  to the 2026-08-22/23 IAM fixes. Worth a real fix eventually (pin the
  layer's build to something reproducible, or accept-and-document it more
  formally) but not urgent — it's noise in the plan output, not a
  functional problem.
- **Resolved 2026-08-18:** `spark-application.yaml`'s `apache/spark` image
  tag and `hadoop-aws` pairing were verified live against Docker Hub before
  the live pass — see the 2026-08-18 session entry. `3.5.9` (latest patch
  on the already-targeted 3.5.x line) confirmed via paging Docker Hub's
  tags API to its last page (the `ordering` param is silently ignored on
  that endpoint, which is what made earlier lookups look stale);
  `hadoop-aws:3.3.4` confirmed correct by reading Spark v3.5.9's own
  `pom.xml`.
- **AWS Well-Architected Tool tracked state — update this entry at every
  future phase's Well-Architected pass, per the requirement now in
  `docs/plan.md`'s Architecture guiding principle and Phases.md's
  cross-cutting Architecture bullet.** Workload `cerberus-platform`
  (`58c236e2c7844375965d22349b460084`, Framework lens, `us-east-1`) —
  verified live via `aws wellarchitected list-workloads`/`list-milestones`
  most recently on 2026-09-07 (`cerberus-admin` profile). Milestones saved
  so far: **1** `phase-1-mvp-complete` (2026-08-10), **2**
  `phase-2-event-driven-ingestion-complete` (2026-08-12), **3**
  `phase-3-scalable-compute-complete` (2026-08-18, ADR 0008), **4**
  `phase-4-orchestration-complete` (2026-08-20, ADR 0010), **5**
  `phase-5-cicd-complete` (2026-08-24, ADR 0012), **6**
  `phase-6-observability-and-data-quality-complete` (2026-09-07, ADR 0014),
  **7** `phase-7-end-to-end-validation-complete` (2026-09-29, ADR 0015 —
  the full 57-question review; no bucket moved). Current risk counts
  (get-lens-review): **23 HIGH / 19 MEDIUM / 10 NONE / 5 N/A**, unchanged
  since milestone 6 (was 25/18/9/5 through milestones 2–5). **No further
  milestone is scheduled:** Phase 7's review subtask (7.4) is closed. ADR
  0016 leaves it open whether 7.7's Prometheus work merits re-answering
  `workload-observability` / `monitor-aws-resources` and saving a milestone
  8. **Updated 2026-10-06:** milestone 8 is now part of 8.11 (Phase 8's
  Well-Architected pass), which will also take in 7.7's Prometheus
  evidence. (`cerberus-admin`'s governance policy still carries the
  Well-Architected Sids as of the 2026-10-06 root paste.)
- **AWS Agent Toolkit (`aws-core@claude-plugins-official`, installed
  2026-08-11) is in scope for the rest of the build — see `docs/plan.md`'s
  cross-cutting tracks.** Mapped to remaining phases: `aws-compute` (4.1,
  Step Functions), `aws-observability` (Phase 6), `aws-iam` (7.3),
  `aws-sdk-python-usage` (boto3 pattern-checking). Its MCP doc-search/read
  tools are the fallback wherever no packaged skill fits, notably Terraform
  (no `aws-terraform` skill exists). `aws-containers` (ECS/Fargate/ECR-named,
  not EKS-specific) was never checked across any of Phase 3's five
  Terraform-module subtasks (3.2, 3.4, 3.5, and the live pass in 3.6/3.7) —
  treating this as settled rather than still-open: it evidently doesn't
  matter for this stack, so it's not worth spending time on for Phase 3.
  Revisit only if a future phase's own skill mapping calls for it.
- **Live-pass gotchas worth knowing before any future EKS spin-up/destroy
  cycle (Phase 3 re-runs, or later phases that provision compute) — see
  the 2026-08-18 session entry for full detail:**
  - This AWS account can hit AWS's new-account Free-Tier-only EC2 launch
    restriction (`InvalidParameterCombination` on node launch). The `eks`
    module's `node_instance_types` default is now `m7i-flex.large`
    (Free-Tier-eligible, same 2 vCPU/8 GiB spec as the original
    `m5.large`) specifically to route around this — check whether the
    restriction has lifted before assuming a different instance type is
    safe to use.
  - **This cluster's public-only EKS API endpoint (ADR 0007) means worker
    nodes reach the control plane over the internet via NAT.** If
    `terraform destroy` tears down the NAT Gateway before Kubernetes-
    managed resources (namespaces, pods) finish deleting, nodes go
    `NotReady` and pods can get stuck `Terminating` forever, stalling the
    destroy (`context deadline exceeded`). Fix: `kubectl delete pod
    --grace-period=0 --force` on whatever's stuck, then re-run
    `terraform destroy` for the remainder — the AWS-side resources (node
    group, cluster, VPC) don't depend on pod-termination confirmation the
    same way. This will very likely recur on every future destroy of this
    stack; it's an inherent consequence of the public-endpoint design, not
    a one-off fluke.
  - **Never run a bare `terraform destroy` (or `plan -destroy`) against
    `envs/dev` without `-target`.** It targets the *entire* root module,
    including bronze/silver/gold, the Glue catalog, and the Lambda
    ingestion function — none of which are part of the spin-up/destroy
    design.
  - **Updated 2026-08-20, supersedes the target list below from 3.7:**
    since Phase 4 added `orchestration_runner`/`step_functions` (ECS,
    ECR, the state machine — all genuinely free sitting idle, meant to
    stay standing across EKS spin-up/destroy cycles), the destroy target
    list has to be narrower than "the whole `module.vpc`." Destroying
    `module.vpc.aws_vpc.this` itself cascades to
    `orchestration_runner.aws_security_group.runner` (real dependency,
    `vpc_id`) and from there to the *entire* state machine (its ASL
    definition embeds the security group ID). **Correct scope, leaving
    the orchestration layer standing:** `-target=module.spark_job
    -target=module.spark_operator -target=module.eks
    -target=module.iam.aws_iam_role.spark -target=module.vpc.aws_nat_gateway.this
    -target=module.vpc.aws_eip.nat` — the VPC/subnets/IGW/public route
    table stay up (all free); only EKS, the Spark stack, and the NAT
    Gateway (the two genuinely billed pieces) come down. This pulls in
    the private route table and the free S3 gateway endpoint as
    necessary dependents of the NAT Gateway going away — expected, not a
    problem (both cost nothing, both get recreated on the next spin-up).
  - **A `role_arns[...]` map-index reference from *any* new module can
    silently re-widen this scope** — see the 2026-08-20 entry's false-
    dependency bug: reading any single key off `module.iam`'s `role_arns`
    output creates a graph edge to all 9 underlying roles. Before adding a
    new consumer of a role ARN, check whether a standalone output already
    exists for it (`terraform/modules/iam/outputs.tf`); add one if not,
    the same way `ingestion_lambda_role_arn` and the four
    `orchestration_*_role_arn` outputs already do.
- **`dynamodb_table` vs. `use_lockfile`: decided 2026-08-08, keep
  DynamoDB for now — Phase 1 (MVP) is done as of today, so this is now
  revisitable with real usage data if there's appetite, but hasn't been
  actioned.** Terraform's S3 backend still accepts `dynamodb_table` but
  warns it's deprecated in favor of `use_lockfile` (native S3 locking,
  no second AWS resource needed). Explicit decision: keep the existing
  `cerberus-platform-tfstate-lock` table rather than migrate — it's
  already built (Phase 0), already imported as code (1.5), and
  effectively free on-demand. Not written up as an ADR — a config-level
  tooling call, not an architecturally significant decision on ADR
  0002/0003's scale.
- **Resolved 2026-08-12:** `cerberus-payments.timer` is retired outright
  (disabled, unlinked, unit files deleted — see this date's session entry),
  not merely self-retiring on 2026-08-17 as originally planned. The
  EventBridge Scheduler → Lambda path (`cerberus-ingest-payments-daily`,
  still capped by `RETIRE_ON_OR_AFTER=2026-08-17` in its own Lambda
  environment variable) is now bronze's only ingestion mechanism — no more
  parallel-write duplication to reason about. To get more data after
  2026-08-17, run `generate_payments.py` by hand or update the Lambda's
  environment variable; don't re-enable the deleted systemd units.
- **Resolved 2026-08-12:** the workflow-policy decision (PR-per-push,
  `docs/plan.md`'s principle 8 rewritten) — see this date's session entry.

- **Resolved 2026-08-07:** `cerberus-ingest.timer` turned out to be running
  fine all along — confirmed via journal — but from the stale
  `/home/chira/cerberus` checkout rather than this session's. Both timers
  now point at `/home/chira/projects/cerberus`; see the 2026-08-07 session
  entry above. `/home/chira/cerberus` is orphaned but not deleted.
- **Systemd linger is still off for this user.** No longer consequential
  for payments ingestion — `cerberus-payments.timer` is retired outright
  as of 2026-08-12, and the EventBridge Scheduler path has no login-session
  dependency to skip against. Still relevant if any future `--user` timer
  is ever added to this project: it would stop firing once the login
  session ends, until `sudo loginctl enable-linger $(whoami)` is run
  (needs an interactive password, can't be run from here).
- **Weather ingestion retired 2026-08-07** (user request, scoped
  explicitly to three things: the timer, the systemd unit files, and the
  S3 data — nothing else). `cerberus-ingest.timer`/`.service` disabled,
  unlinked from `~/.config/systemd/user/`, and deleted from
  `ingestion/systemd/`; all 40 weather objects under `weather/dt=*/` in
  bronze permanently purged (versioning was on, so this deleted every
  object version via `s3api delete-objects`, not just current versions —
  confirmed empty afterward). `ingestion/scripts/ingest_weather.sh` itself
  was left in place, unscheduled — deleting it wasn't part of the request.
  Payments is now bronze's only active data source.

---

## Reference — Well-Architected method for ADRs

_Stable reference material, **not** session state. `/end-day` must preserve
this section verbatim when rewriting the checkpoint; `/start-day` renders it
in full whenever ADR work appears in "Next up". Captured 2026-08-03._

### 1. Using the Framework to design an ADR

The method is simple: **treat the six pillars as a question generator, not a
checklist.** Hold each pillar up against the decision and ask "what does this
pillar have to say here?" Most produce nothing. The two or three that produce
something sharp are the ADR's real content.

For 1.1 the actual decisions on the table are roughly: one bucket or three?
what partition scheme? what file format per layer? is bronze immutable? what
lifecycle/retention?

What each pillar asks of those:

| Pillar | What it asks of the medallion layout |
|---|---|
| **Cost Optimization** | The biggest lever in the whole platform. Athena bills per **TB scanned** — so Parquet + compression in silver/gold, and partition pruning, are the difference between cents and dollars per query. Also: lifecycle rules moving aged bronze to IA/Glacier. |
| **Performance Efficiency** | Partition granularity and the **small-file problem**. The Phase 0 timer wrote one tiny JSON per hour — thousands of small objects wreck Athena and Spark performance. Do you compact? Partition daily or hourly? |
| **Security** | Do the layers need *different* access? Bronze may hold raw PII-shaped payment records; gold is aggregated and safer to expose. Separate buckets give clean IAM boundaries and a smaller blast radius; prefixes in one bucket give fiddlier policies. |
| **Reliability** | Is bronze **immutable and append-only**? If yes, silver and gold can always be rebuilt by reprocessing — that single property is what makes the whole pipeline recoverable. Versioning (already on) supports it. |
| **Operational Excellence** | Predictable naming, so a human debugging a bad partition can find it. Schema evolution: what happens when the payments generator adds a field? |
| **Sustainability** | Largely falls out of Cost here — less scanned, less compute, less energy. Rarely decisive on its own. |

**The valuable part is the tensions** — that is what makes the ADR worth
writing rather than obvious:

- **Bronze format:** Reliability says keep raw exactly as received (fidelity,
  always reprocessable). Cost says convert to Parquet immediately. The
  conventional resolution — raw in bronze, Parquet from silver on — is a
  **deliberate trade**, and saying *why* is the ADR.
- **Partition granularity:** finer partitions help Cost (less scanned) but
  hurt Performance (more small files). There is no universally right answer;
  there is a right answer *for your data volume*.
- **One bucket vs three:** Security prefers three; Operational Excellence
  mildly prefers one. Bronze already exists as its own bucket, so three is the
  path of least resistance and the ADR mostly formalises it.

**Where it goes in the Nygard template:** don't bolt on a "Pillars" section —
that is checkbox theatre and reads as filler. Let the pillar analysis
*generate* the **Context** (the forces at play) and populate **Consequences**
(what was given up). Optionally name the driving pillar inline: "chose Parquet
in silver primarily on cost-optimization grounds, accepting the loss of
human-readability."

The one place a pillar-by-pillar structure genuinely fits is the per-phase
**Well-Architected pass** ADRs (1.13, 2.6, …) — those are reviews, so a pillar
walkthrough is the natural shape.

### 2. The AWS Well-Architected Tool

- **Where:** AWS Console → search "Well-Architected Tool", or Services →
  Management & Governance. Direct: `console.aws.amazon.com/wellarchitected`.
  Regional service — use `us-east-1` to match everything else.
- **Cost:** free. `cerberus-admin` has `AdministratorAccess`, so permissions
  are already fine.
- **How it works:** define a *workload* (name, description, environment,
  regions), then apply one or more *lenses*. The default is the AWS
  Well-Architected Framework lens. Each pillar becomes a set of questions with
  best-practice checkboxes; answer honestly, mark what is genuinely not
  applicable, and it generates an improvement plan flagging **high- and
  medium-risk items**. Save **milestones** — point-in-time snapshots.
- **The lens that matters here:** the **Data Analytics Lens**, built for
  analytics/lakehouse workloads — far more relevant to Cerberus than the
  generic framework lens, and worth reading even before using the tool.

**Timing.** The Tool is built to review a workload that *exists*. At 1.1 there
is almost nothing built, so a full review today returns mostly "no" and "not
applicable" — noise, not signal. Better sequencing:

1. **Now:** read the pillars in the framework docs (free, no login) and the
   Data Analytics Lens. Use them as the design lens described above.
2. **Also now, 5 minutes:** create the workload in the Tool and save a
   **baseline milestone**. Costs nothing, gives a starting point.
3. **After each phase:** save a new milestone during the Well-Architected
   pass. The diff between milestones becomes a genuinely strong portfolio
   artifact — visible evidence the platform got better, not just bigger.
4. **Phase 7.4:** the full formal review, where the tool earns its keep.

Free reading, no account needed:
[Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html)
and the
[Data Analytics Lens](https://docs.aws.amazon.com/wellarchitected/latest/analytics-lens/analytics-lens.html)
— both pair well with the free ~1.5h Skill Builder course in
[docs/courses-map-to-phases.md](docs/courses-map-to-phases.md).
