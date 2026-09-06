# 13. Lineage: OpenLineage events to a serverless collector

Date: 2026-09-06

## Status

Accepted

## Context

Phase 6.4's goal ([plan.md](../plan.md#phase-6--observability--data-quality))
is one word — "lineage" — with no further spec. The phase's "done when" and
artifact list don't mention it at all, so 6.4 is the softest-defined
subtask in the phase and a modest, in-character scope is legitimate.

**What lineage has to cover here, and why one tool can't.** The transform
path is heterogeneous:

- **bronze → silver** is a Spark job on EKS (`promote_payments_spark.py`,
  the orchestrated `RunTransform`) — or the pandas
  `promote_payments.py` on the manual path.
- **silver → gold marts** is dbt (`dbt build`, the orchestrated `RunDbt`).
- **silver → `payments_current`** is pandas only.

6.4a already publishes dbt's own model-level DAG (`dbt docs generate` →
GitHub Pages). But dbt's `ref()`/`source()` graph is structurally blind to
everything upstream of the `payments_events` source, and to
`payments_current` — see [lineage.md](../lineage.md)'s findings. A
whole-pipeline lineage view has to be assembled from **runtime capture on
both engines**, and the only standard that spans Spark and dbt with one
event schema is **[OpenLineage](https://openlineage.io/)** — it has a
first-party Spark listener (`openlineage-spark`) and a dbt wrapper
(`openlineage-dbt` / `dbt-ol`). Adopting OpenLineage as the capture
standard isn't the hard part of this decision; **where the events go is.**

OpenLineage emits events over a transport — HTTP to a collector, or Kafka,
or a local file/console. The options for the collector:

| Option | What it is | Fit |
|---|---|---|
| **Marquez** | The OpenLineage reference server — a Postgres database plus a web service, with a lineage UI (dataset graph, run history, column-level view) | A standing service with a monthly bill |
| **Amazon DataZone** | A managed data-governance domain with an OpenLineage ingestion API | A managed domain (projects, environments, blueprints) priced and shaped for an organization, not a solo pipeline |
| **Serverless collector** | API Gateway HTTP API → Lambda → S3; events stored verbatim, rendered later by a static job | Zero idle cost; same pattern as 6.1's freshness probe and the Phase 4 orchestration layer |
| **File / console transport** | Spark writes events to the driver pod's filesystem, or to stdout | The driver pod is ephemeral and launched indirectly (ECS task → `kubectl` → EKS), so retrieving a file off it is awkward; console means grepping logs. No durable, queryable store. |

Working the choice through the pillars (per the method in
[checkpoint.md](../checkpoint.md)'s reference section — pillars as a
question generator, most produce nothing):

| Pillar | What it says about the collector choice |
|---|---|
| **Cost Optimization** | The deciding pillar, as in every prior infrastructure ADR here (0005, 0007, 0009, 0011). Marquez needs a host for Postgres + the web app — either a standing container (ECS/EKS) or RDS, both idle cost. DataZone's domain carries its own pricing. The serverless collector is pay-per-request: at this pipeline's volume (a dozen-ish events per run, one run a day) it is effectively $0 — API Gateway HTTP API is \$1.00/million requests, the Lambda stays in the perpetual free tier, and S3 storage is trivial under a 90-day expiry. |
| **Operational Excellence** | The serverless collector has the "nothing to operate when idle" property every Phase 1–4 compute choice in this stack already holds — no metadata database to back up, no webserver to patch, no service health to monitor. Marquez reintroduces all three. |
| **Security** | Cuts the *other* way, and this ADR doesn't gloss it: an HTTP collector is a new ingress, and the decision below makes it **unauthenticated** (see the tension section). Marquez behind auth would avoid that. The mitigations — write-only, a private lifecycle-expiring prefix, a request-rate cap, no read path — are covered below; they are why the trade is acceptable, not why it's free. |
| **Reliability** | The collector is deliberately *not* in the pipeline's critical path. The handler always returns 200, and the producers treat lineage transport as best-effort — a dropped event leaves lineage incomplete but never fails a Spark job or a dbt run. Lineage here is observability *about* the pipeline, not a step *in* it. |
| **Sustainability** | Follows Cost — no idle compute running 24/7 to catch an event a few times a day. |
| **Performance Efficiency** | Irrelevant at this volume. |

**The tension worth naming — the first unauthenticated ingress in the
stack.** Every other entry point into this platform is authenticated: CI
assumes its roles via GitHub OIDC (ADR 0011), compute uses IRSA and ECS
task roles (ADR 0007, Phase 4), the CLI uses SigV4 with chained profiles
(Phase 1). An anonymous `POST /api/v1/lineage` breaks that streak. It is
accepted here as a **scoped, deliberate trade**, on three grounds:

1. **Blast radius.** The endpoint's entire capability is "write one JSON
   object to a private, lifecycle-expiring S3 prefix". No read, no data
   exfiltration, no compute beyond a 128 MB Lambda. A malformed or hostile
   body is stored under `events/malformed/` and inspected later, never
   executed.
2. **The producers have no credential to sign with.** `cerberus-spark`
   (IRSA) is scoped to S3 only; the dbt Fargate task role likewise.
   Neither has `execute-api:Invoke`, and the alternatives — grant it, or
   share a static API key across both — reintroduce exactly the
   secret-management surface the 2026-08-03 re-scope removed from this
   project ("no real secret exists in this stack"). SigV4 auth is also
   blocked mechanically: `openlineage-spark`'s HTTP transport has no
   native SigV4 signer, so IAM auth would need a custom transport class or
   a sidecar proxy — disproportionate for synthetic payment data.
3. **A rate cap is a sufficient abuse ceiling** for a portfolio project
   whose repo, CI, and (as of 6.4a) lineage site are all already public by
   design.

**The other tension — buy vs. build.** Marquez is the polished OpenLineage
experience: a real UI with an interactive, column-level lineage graph and
per-run history. A serverless collector plus a static renderer (6.4d) is
more work and a coarser result. But the polished version costs money to
keep running for a graph that a reviewer looks at occasionally, and the
static render can live on the same free GitHub Pages site 6.4a already set
up.

## Decision

**Adopt OpenLineage as the lineage-capture standard**, emitting from
`openlineage-spark` on the EKS transform job and `openlineage-dbt` on the
Fargate dbt task. The producer wiring (the Spark listener jar via Ivy
`deps.packages` — no image rebuild; `openlineage-dbt` in the runner image —
an image rebuild; config threading) is **6.4c**, not this ADR.

**Collect the events with a serverless collector**: API Gateway **HTTP API**
(v2, not REST — \$1.00 vs \$3.50 per million, and all this needs is one
route with a Lambda proxy integration and a stage rate cap) → a boto3-only
Lambda → S3. New `terraform/modules/lineage`, instantiated from
`envs/dev-standing` alongside the other zero-idle-cost modules.

- **Unauthenticated**, with the API stage's `default_route_settings`
  capping request rate (10/s steady, 20 burst — an abuse ceiling, not a
  capacity limit). Justified in the tension section above.
- **One object per event, stored verbatim**, under
  `events/received_date=YYYY-MM-DD/…json`. Verbatim so no field is lost to
  a parsing assumption; partitioned by receipt date so 6.4d's reader and
  the lifecycle rule share a predictable prefix.
- **The handler always returns 200.** A non-2xx would surface in the Spark
  driver log as a scary error for something that must not break the
  pipeline. Unparseable bodies are stored under `events/malformed/` so
  producer-side drift is visible in S3, not silently dropped.
- **Dedicated bucket** `cerberus-platform-lineage-<account-id>`, matching
  the one-bucket-per-purpose convention (bronze/silver/gold/tfstate/
  athena-results are all separate). **No versioning** — every key is
  unique and write-once, so versioning would only add cost and clutter.
  Lifecycle expiry at **90 days** — these are per-run operational records,
  not a data layer.

**6.4d** reads the accumulated events back out of S3 and renders a
whole-pipeline graph onto the Pages site, next to the dbt DAG.

**Marquez and Amazon DataZone are explicitly rejected for this project**,
on cost and standing-infrastructure grounds — not on capability. Nothing
about this pipeline's lineage needs a metadata database or a governance
domain; what it needs is the events captured somewhere durable and
rendered somewhere free.

## Consequences

- **This is the first unauthenticated ingress in the stack.** It should be
  re-examined at 7.3 (the least-privilege review) — is the trade still
  warranted, has a producer credential become available, is the rate cap
  the right number. Documented here so that review has a starting point,
  not a surprise.
- **Lineage capture is best-effort.** If the collector is down or an event
  is dropped, the rendered graph is incomplete but no pipeline step fails.
  This is acceptable because [lineage.md](../lineage.md) — hand-maintained
  — is the authoritative view; the captured events are the *cross-check*
  against it, per that document's own maintenance note.
- **6.4c inherits real work**, not just config: the `openlineage-spark`
  coordinate and its `sparkConf` on the SparkApplication manifest, and
  `openlineage-dbt` added to the runner image (triggering the
  `null_resource.build_and_push` rebuild — the documented
  local-apply-first dance). The Spark path can only be verified live
  during a `dev-compute` exercise; the dbt path can be verified against
  Athena without EKS.
- **No lineage UI.** 6.4d's static render is coarser than Marquez's
  interactive graph. If a future phase genuinely needs interactive
  column-level exploration, the re-examination is Marquez run *ephemerally*
  during an exercise (the same spin-up/destroy pattern as EKS) or dbt
  Explorer — not a reversal of this ADR's cost reasoning at today's scope.
- **`cerberus-ci-apply` gains scoped grants** for the new bucket, Lambda,
  execution role, HTTP API, and two log groups
  (`terraform/modules/github_oidc`). Because those grants live in
  `cerberus-ci-apply`'s own policy, the first apply must run locally as
  `cerberus-admin` before CI can apply the rest — the self-escalation
  guard, same as 6.1 and 6.2.
- **Cost impact: effectively none.** API Gateway HTTP API at \$1.00/million
  requests against a few requests a day, Lambda in the free tier, S3
  storage negligible under the 90-day expiry. Well inside the \$10/month
  billing alarm.
