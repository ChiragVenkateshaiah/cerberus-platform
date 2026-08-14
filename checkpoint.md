# Checkpoint

_State file for `/start-day` and `/end-day`. `/start-day` reads this to
resume work; `/end-day` writes it at the close of a session.
[Phases.md](Phases.md) is the authoritative phase/subtask checklist — this
file is the session-to-session narrative plus a concrete "what's next"
pointer._

## Current phase

Phase 1 — MVP: end-to-end lakehouse is **✅ complete** (1.1–1.13, see
[Phases.md](Phases.md#phase-1--mvp-end-to-end-lakehouse--)). Phase 2 —
Event-driven ingestion is **✅ complete** (2.1–2.6, all verified live — see
[Phases.md](Phases.md#phase-2--event-driven-ingestion-)). Phase 3 —
Scalable compute is **🔨 in progress**: **3.1 and 3.3 are ✅ complete**
(ADR 0007 accepted — VPC/subnet layout and the multi-AZ node-group
decision). **3.2 is written but not yet checked off**: the VPC + EKS
Terraform modules exist (`terraform/modules/vpc/`, `terraform/modules/eks/`),
`terraform plan` is verified clean (24 to add, 0 to change, 0 to destroy),
but nothing has been applied — deliberately, since EKS/NAT both bill on
apply regardless of load, and apply is deferred until 3.4/3.5 are also
ready so one apply exercises the whole stack. 3.4–3.8 haven't started.

**Note:** the roadmap was re-scoped on 2026-08-03 from 9 phases (0–8) to
8 (0–7). The old "Phase 1 — IaC foundation" no longer exists as a phase;
Terraform is now cross-cutting and its work is absorbed into Phase 1's
subtasks. Session history entries before that date use the old numbering.

## Next up

- **3.4 Spark Operator install and 3.5 Spark job manifest against S3** —
  write both in code next, *before* running `terraform apply` on 3.2's VPC
  + EKS modules. The plan is one combined live session: apply the VPC/EKS
  stack, install the Spark Operator, submit the job manifest, verify writes
  to silver/gold (3.6, including confirming Spark's S3 traffic actually
  routes through the Gateway endpoint per ADR 0007's Consequences), then
  `terraform destroy` (3.7) — one apply exercising the whole stack rather
  than standing up a paid, idle EKS cluster with nothing to run on it.
  3.2 gets checked off in Phases.md only once that live apply/verify
  actually happens, not before.
- Worth a quick check before or during 3.4: whether the AWS Agent
  Toolkit's `aws-containers` skill (ECS/Fargate/ECR-named, not
  EKS-specific) gives any useful coverage here — still unconfirmed, see
  Notes / blockers.
- **3.8's Well-Architected pass, once 3.1–3.7 land, must also save a new
  Tool milestone** (`phase-3-scalable-compute-complete` or similar), not
  just write the ADR — this is now an explicit requirement in
  `docs/plan.md`/Phases.md, not optional. See Notes / blockers for the
  workload ID and current milestone list.
- No open blockers gate starting 3.4/3.5 — see Notes / blockers below for
  what's still open generally.

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

## Notes / blockers

- **AWS Well-Architected Tool tracked state — update this entry at every
  future phase's Well-Architected pass, per the requirement now in
  `docs/plan.md`'s Architecture guiding principle and Phases.md's
  cross-cutting Architecture bullet.** Workload `cerberus-platform`
  (`58c236e2c7844375965d22349b460084`, Framework lens, `us-east-1`) —
  verified live via `aws wellarchitected list-workloads`/`list-milestones`
  on 2026-08-14 (`cerberus-admin` profile). Milestones saved so far:
  **1** `phase-1-mvp-complete` (2026-08-10), **2**
  `phase-2-event-driven-ingestion-complete` (2026-08-12). Next one is due at
  **3.8**, once 3.1–3.7 are actually built — not before: per the Reference
  section's timing guidance, reviewing a workload before it exists just
  returns "no"/"not applicable" noise, not signal. When 3.8 lands, save
  milestone 3 (`phase-3-scalable-compute-complete` or similar) and add it to
  this list; repeat at 4.5, 5.5, 6.6, and the formal review at 7.4.
- **AWS Agent Toolkit (`aws-core@claude-plugins-official`, installed
  2026-08-11) is in scope for the rest of the build — see `docs/plan.md`'s
  cross-cutting tracks.** Mapped to remaining phases: `aws-compute` (4.1,
  Step Functions), `aws-observability` (Phase 6), `aws-iam` (7.3),
  `aws-sdk-python-usage` (boto3 pattern-checking). Its MCP doc-search/read
  tools are the fallback wherever no packaged skill fits, notably Terraform
  (no `aws-terraform` skill exists). Still open/unconfirmed: whether
  `aws-containers` (ECS/Fargate/ECR-named, not EKS-specific) actually gives
  useful coverage for Phase 3 — 3.2's Terraform modules (2026-08-14) were
  written without checking this, so it's still genuinely unresolved, not
  silently answered. Worth checking before 3.4 (Spark Operator install).
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
