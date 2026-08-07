# Checkpoint

_State file for `/start-day` and `/end-day`. `/start-day` reads this to
resume work; `/end-day` writes it at the close of a session.
[Phases.md](Phases.md) is the authoritative phase/subtask checklist — this
file is the session-to-session narrative plus a concrete "what's next"
pointer._

## Current phase

Phase 1 — MVP: end-to-end lakehouse (🔨 in progress — ADRs 0002 and 0003
accepted, 1.1/1.2/1.3/1.4 checked off) — see
[Phases.md](Phases.md#phase-1--mvp-end-to-end-lakehouse--). Phase 0 —
Foundation is ✅ complete.

**Note:** the roadmap was re-scoped on 2026-08-03 from 9 phases (0–8) to
8 (0–7). The old "Phase 1 — IaC foundation" no longer exists as a phase;
Terraform is now cross-cutting and its work is absorbed into Phase 1's
subtasks. Session history entries before that date use the old numbering.

## Next up

- 1.5 Terraform: adopt the hand-built state backend as code — bring
  `cerberus-platform-tfstate-131715059025` (S3) and
  `cerberus-platform-tfstate-lock` (DynamoDB) themselves under Terraform via
  `terraform import`, in `terraform/bootstrap/` (currently empty).
- 1.6 Terraform: IAM module (least-privilege roles for bronze/silver/gold)
- 1.7 Minimal transform promoting bronze → silver → gold

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

## Notes / blockers

- **`dynamodb_table` is deprecated in Terraform's S3 backend** (warns on
  every `init`/`plan`/`apply`; Terraform 1.11+ prefers `use_lockfile` for
  native S3 locking, no DynamoDB needed). Deliberately not switched — the
  Phase 0 DynamoDB lock table (`cerberus-platform-tfstate-lock`) already
  exists and 1.5 is explicitly about adopting it as code, so dropping it
  now would orphan already-provisioned, already-documented infrastructure.
  Revisit only if 1.5 decides to retire the DynamoDB table outright.
- **The payments timer self-retires 2026-08-17.** After that date
  `cerberus-payments.timer` will be auto-disabled (not deleted) by
  `run_payments_scheduled.sh` the next time it fires. To get more data
  after that, run `generate_payments.py` by hand (see above) — don't
  re-enable the timer without deciding whether the 10-day cap still
  applies.

- **Resolved 2026-08-07:** `cerberus-ingest.timer` turned out to be running
  fine all along — confirmed via journal — but from the stale
  `/home/chira/cerberus` checkout rather than this session's. Both timers
  now point at `/home/chira/projects/cerberus`; see the 2026-08-07 session
  entry above. `/home/chira/cerberus` is orphaned but not deleted.
- Systemd linger is still off for this user — `cerberus-payments.timer`
  will stop firing once the current login session ends, until you run
  `sudo loginctl enable-linger $(whoami)` yourself (needs an interactive
  password, can't be run from here).
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
