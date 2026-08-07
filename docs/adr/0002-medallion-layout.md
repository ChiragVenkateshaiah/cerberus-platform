# 2. Medallion layout: bucket topology, partitioning, and file formats

Date: 2026-08-05

## Status

Accepted

## Context

Phase 1 needs a concrete bronze/silver/gold design before 1.4 (Terraform S3
medallion module) or 1.7 (bronze → silver → gold transform) can be built.
One constraint is already fixed, not hypothetical:
`cerberus-platform-bronze-131715059025` was hand-created in Phase 0
(versioned, SSE-S3, public access blocked) and holds live weather objects
under `weather/dt=YYYY-MM-DD/` — it is adopted into Terraform in 1.4/1.5,
not recreated. Silver and gold don't exist yet.

Working the open questions through the Well-Architected pillars (per the
method in checkpoint.md's reference section — pillars as a question
generator, not a checklist):

| Pillar | What it asks of this decision |
|---|---|
| **Cost Optimization** | Athena bills per TB scanned. Parquet + compression in silver/gold, plus partition pruning, is the difference between cents and dollars per query. Bronze staying raw JSON is a deliberate cost trade against Reliability, not an oversight. |
| **Performance Efficiency** | Partition granularity and the small-file problem. Phase 0's hourly timer proved this: one tiny JSON object per hour compounds into thousands of small files that hurt Athena/Spark scan performance. |
| **Security** | Bronze can hold raw, payments-shaped records before any masking. Separate buckets per layer give a clean IAM boundary — a policy scoped to `gold/*` cannot accidentally expose raw data — and a smaller blast radius than prefix-based rules in one bucket. |
| **Reliability** | If bronze is immutable and append-only, silver and gold are always rebuildable by reprocessing. That single property is what makes the pipeline recoverable rather than a one-way pipe. |
| **Operational Excellence** | Predictable naming lets a human find a bad partition without guessing. Bronze staying schema-loose (raw JSON) means new fields from the payments generator don't break ingestion; schema evolution is instead handled explicitly at the silver/gold Parquet boundary. |
| **Sustainability** | Follows from Cost here — less scanned, less compute — not independently decisive. |

The tensions worth naming explicitly:

- **Bronze format:** Reliability wants raw-as-received fidelity; Cost wants
  Parquet immediately. Resolved by keeping bronze raw and only converting to
  Parquet from silver onward — the standard medallion trade, and the reason
  it's worth stating rather than assuming.
- **Bucket topology:** Security mildly prefers three buckets; Operational
  Excellence mildly prefers one. Bronze already exists as its own bucket, so
  three is both the Security-preferred outcome and the path of least
  resistance — this ADR mostly formalizes an already-settled fact.
- **Partition granularity:** finer partitions reduce bytes scanned (Cost) but
  multiply small files (Performance). At this project's data volume — a
  synthetic generator, not production traffic — daily partitioning is the
  right side of that trade; hourly repeats Phase 0's proven mistake.

## Decision

**Bucket topology.** Three buckets, one per layer, following the existing
naming pattern:

- `cerberus-platform-bronze-131715059025` (existing, adopted via `terraform
  import` in 1.4/1.5 — not recreated)
- `cerberus-platform-silver-<account-id>` (new)
- `cerberus-platform-gold-<account-id>` (new)

All in `us-east-1`, matching existing infrastructure. Each gets the same
baseline hardening as bronze: versioning on, SSE-S3, public access blocked,
tagged `Project`/`Phase`/`Layer`.

**Partitioning.** Hive-style `dt=YYYY-MM-DD`, daily granularity, at every
layer — reusing the convention Phase 0 already established
(`weather/dt=.../`). Payments data lands under its own top-level prefix,
`payments/dt=YYYY-MM-DD/`, so it never collides with the legacy weather
prefix inside the same bronze bucket. Daily (not hourly) partitioning is a
direct response to the small-file problem the Phase 0 timer already
demonstrated.

**File formats.**
- Bronze: raw as received — JSON for the payments generator's output. No
  transformation, no compaction. This is the source of reprocessability.
- Silver and gold: Parquet with Snappy compression, written by the 1.7
  transform. This is where the small-file problem gets addressed — the
  transform compacts daily bronze partitions into columnar files, not
  ingestion.

**Immutability.** Bronze is append-only. Objects are never overwritten in
normal operation; the daily-partitioned key structure makes that the default
behavior rather than something enforced separately. Versioning (already
enabled) is the backstop against accidental overwrite, not the primary
mechanism.

**Lifecycle.** Bronze objects transition to S3 Standard-IA after 30 days.
No Glacier transition for now — this is a portfolio-scale demo, not a
retention-compliance workload, and IA is enough to demonstrate the practice
without adding restore-latency complexity. The threshold is a Terraform
variable in 1.4, not a hardcoded value, so it can be tuned later without a
new ADR.

**IAM boundary (forward pointer, not decided here).** The three-bucket split
is what makes 1.6's IAM module able to scope policies per layer — e.g., an
ingestion role with `PutObject` on bronze only, a transform role with read on
bronze and write on silver/gold, a serving role with read-only on gold. The
actual policy documents are 1.6's decision, not this one.

## Consequences

- 1.4 must `terraform import` the existing bronze bucket rather than create
  it, and must parameterize the silver/gold names off the same account-ID
  suffix convention.
- 1.7's transform is responsible for both the JSON→Parquet conversion and
  small-file compaction — bronze ingestion (Phase 2's Lambda, eventually)
  stays simple and dumb by design.
- Three buckets means three sets of lifecycle/versioning/tagging config to
  maintain in Terraform, versus one — accepted in exchange for the IAM
  blast-radius reduction.
- Bronze carries raw payments-shaped data (pre-masking) indefinitely, aged
  into IA after 30 days rather than deleted — any future PII-handling
  decision (masking, deletion, retention compliance) is out of scope here
  and would need its own ADR if the project ever needs to justify it beyond
  "this is a portfolio demo."
- The `dt=YYYY-MM-DD` / `payments/` vs `weather/` prefix convention set here
  is binding on every future ingestion source unless superseded by a new
  ADR — this is the naming contract 1.8's Glue Data Catalog registration
  will assume.
