# 3. Synthetic payments data model: entity shape, event semantics, and PII handling

Date: 2026-08-06

## Status

Proposed

## Context

1.3 (the synthetic payments generator) and 1.7 (the bronze → silver → gold
transform) both need a concrete data model before either can be built. ADR
0002 already fixed the container — raw JSON in bronze under
`payments/dt=YYYY-MM-DD/`, Parquet+Snappy from silver on, bronze immutable
and append-only — but not what's *inside* that container. [plan.md](../plan.md#the-data-domain--synthetic-payments)
names the domain as transactions, merchants, customers, and settlement
status, chosen specifically because status transitions and joins force real
design thinking even though every record is generated.

Working the open questions through the Well-Architected pillars (per the
method in checkpoint.md's reference section):

| Pillar | What it asks of this decision |
|---|---|
| **Reliability** | ADR 0002 already decided bronze is immutable and append-only. A payment's status changes over its lifecycle (created → authorized → settled/failed) — if that's modeled as *updating* a transaction record, it breaks the immutability decision outright. It has to be modeled as new, additive events. |
| **Security** | Merchants and customers are exactly the PII-shaped fields ADR 0002 flagged and deferred ("any future PII-handling decision... would need its own ADR"). This is that decision, scoped to generation: what fields exist, and whether anything sensitive-looking is ever generated in the first place. |
| **Cost Optimization** | Denormalized records (merchant/customer detail embedded in every event) repeat bytes across every event for the same merchant or customer. At this project's synthetic scale that's negligible; at real scale it's exactly what silver/gold normalization exists to fix. |
| **Performance Efficiency** | Whatever shape the generator emits is what 1.7's transform has to parse at volume. A single flat entity is simpler to compact and convert than multiple correlated entity types landing separately. |
| **Operational Excellence** | Stable identifiers matter more here than in 0002: downstream (1.7, 1.9) needs to resolve "what is this transaction's current status" from a stream of events, which requires an unambiguous ordering key, not just a transaction ID. |
| **Sustainability** | Follows from Cost, as in 0002 — not independently decisive. |

**The tensions worth naming:**

- **Normalize now or later?** A "real" data model would separate
  transactions (fact) from merchants and customers (dimensions) from the
  start — three entity types, three prefixes. But that's not what a real
  ingestion source actually sends: a payment gateway webhook is one
  self-contained JSON event per transaction, with merchant/customer detail
  embedded inline. Bronze's job (per ADR 0002) is to hold data *as
  received*, not as it will eventually be modeled — normalization is
  silver/gold's job, not bronze's. Landing a single denormalized "payment
  event" is both more realistic and simpler for the generator; the
  fact/dimension split becomes 1.7's and 1.9's problem to solve, which is
  where a medallion pipeline is supposed to earn its keep.
- **Mutable status vs. append-only events.** The natural first instinct —
  "a transaction has a status field, update it when the status changes" —
  is exactly what ADR 0002's immutability decision rules out. Resolving
  this the Reliability way means every status change is a *new* event
  referencing the same `transaction_id`, and "current status" becomes a
  read-time (or transform-time) concept: whoever's asking has to resolve
  latest-event-wins, not read a single mutable field. This is more work
  downstream in exchange for bronze staying truthfully append-only and the
  full history staying reconstructable.
- **Realism vs. sensitivity.** The domain was chosen partly to force real
  PII-shaped thinking (plan.md's words). But there's no reason to actually
  generate a sensitive-looking field just to mask it later — masking is
  free if it happens at generation instead of as remediation. Resolved
  toward Security: nothing that looks like a real card number is ever
  generated at all.

## Decision

**Entity: a single "payment event."** Bronze holds one JSON object per
event, denormalized — merchant and customer detail embedded inline rather
than referenced. There is no separate `merchants/` or `customers/` prefix at
bronze; normalization into fact/dimension tables is deferred entirely to the
1.7 transform and 1.9's dbt models. This keeps 1.3's generator responsible
for exactly one shape of record, and keeps bronze a truthful record of "what
was received," per ADR 0002.

Each event carries, at minimum:
- `transaction_id` — stable across every event in a transaction's lifecycle.
- `event_type` — `created` / `authorized` / `settled` / `failed` /
  `refunded`.
- `event_timestamp` — the ordering key. Combined with `transaction_id`, this
  is the natural key for the event stream; there is no separate
  auto-incrementing event ID.
- `amount`, `currency`.
- `merchant` — embedded object (`merchant_id`, `name`, `category`).
- `customer` — embedded object (`customer_id`, `name`, `email`).
- `payment_method` — embedded object, pre-masked (see below).

The exact JSON Schema (optional fields, enum values, nesting details) is
1.3's implementation concern, not fixed here — same deferral pattern ADR
0002 used for 1.6's IAM policy documents.

**Event semantics: append-only, not update-in-place.** A transaction's
lifecycle is a sequence of events sharing one `transaction_id`, each
immutable once written, landing under `payments/dt=YYYY-MM-DD/` keyed by the
day the *event* occurred (not the day the transaction was created — a
`settled` event three days after `created` lands in its own day's
partition). "Current status" is not a field anyone reads directly off
bronze; it's derived downstream by resolving the latest event per
`transaction_id` — 1.7's transform and 1.9's gold models are what compute
it, not the generator.

**Referential integrity is structural, not enforced.** Because
merchant/customer detail is embedded inline rather than referenced by
foreign key, there's no dangling-reference failure mode to guard against in
bronze — a consequence of the denormalization choice above, not a separate
mechanism.

**PII handling: nothing sensitive-looking is ever generated.**
`payment_method` never contains a full card number. It's generated
pre-masked: a synthetic token plus `last4`, with no field that could be
mistaken for a real PAN even in a demo. Names and emails are generated via a
synthetic-data library producing realistic-but-obviously-fake values (e.g. a
controlled fake email domain) — realistic enough to demonstrate PII-shaped
handling, never anything resembling a real person's data.

**Reference roster, not fully random.** 1.3's generator reuses a small,
fixed roster of merchants and customers across many transaction events,
rather than generating a new merchant/customer per event. This is what
makes joins and aggregations in 1.9's gold models meaningful instead of
degenerate — the exact roster size is a generator parameter, not part of
this decision.

## Consequences

- 1.3's generator emits append-only JSON events, one per transaction
  lifecycle step, denormalized per event — it never rewrites or deletes a
  bronze object.
- 1.7's transform is now explicitly responsible for two things ADR 0002
  only implied: compacting daily partitions into Parquet, *and* resolving
  latest-event-wins per `transaction_id` to produce a current-state view.
  Full event history and current-state derivation both need to survive into
  silver/gold.
- 1.9's dbt models are where the fact/dimension split actually
  happens — `fct_transactions`, `dim_merchants`, `dim_customers` (or
  equivalent) are extracted from the flat bronze event shape, not designed
  at generation time.
- 1.8's Glue Data Catalog registration crawls a schema-loose, evolving JSON
  shape (new `event_type` values or optional fields over time) — consistent
  with ADR 0002's bronze being schema-loose by design.
- No unmasked payment-method field exists anywhere in the pipeline, at any
  layer — there is nothing to remediate later, because nothing sensitive was
  ever generated.
- Reconstructing a transaction's full history is always possible by
  replaying its events in `event_timestamp` order — a direct payoff of
  keeping bronze append-only rather than mutable.
