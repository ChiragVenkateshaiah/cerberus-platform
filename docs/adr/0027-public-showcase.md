# 27. Public showcase: a published metrics snapshot on the standing edge, with Databricks as a partner column

Date: 2026-11-20

## Status

Proposed (2026-11-20). It amends [ADR 0024](0024-demo-console.md): a public,
anonymous, static metrics view is added (see Amends in the Decision). It
records the [ADR 0026](0026-phase-9-well-architected-review.md) Security gap 1
trigger and ADR 0024's "invites go beyond a handful" trigger as fired by this
phase. The build steps and the facts behind this ADR are in
[the plan](../plans/2026-11-20-public-showcase.md).

Related: ADR 0028 (Databricks Free Edition as the partner workspace and
presentation layer) extends this ADR; ADR 0029 (traceability) extends the
data contract with `history.json`.

## Context

The owner asked for a Cerberus that anyone from GitHub and LinkedIn can see,
every day, served from the laptop. The request was gated on showing Cerberus
metrics and performance, with Databricks as a column. The full request is in
the plan.

What exists today:

- The landing page is public on purpose. The terminal and the per-session
  Grafana are invite-only, behind Cognito (ADR 0024).
- `console-site.yml` publishes the site from git on every push to main that
  touches the run records. The build step has no AWS credentials.
- The Phase 10 status values are a function of the run records, which are
  already in git (the 10.2 publisher reads the run record; plan F6). The named query set has 13 queries.

What a laptop-hosted public stack would mean:

- The local Grafana binds to loopback on purpose, because the short-lived
  read-only credentials in that container must not be reachable from the
  network. Serving it to the public would put those credentials on the host
  that serves the public.
- ADR 0024 sets "No public inbound port" and rejected Cloudflare Tunnel as a
  third-party vendor in an AWS portfolio.
- Cloudflare Tunnel needs a domain on Cloudflare. Tailscale Funnel needs no
  domain, but its bandwidth limits are not published and TLS ends on the
  laptop.
- Uptime would depend on the laptop being awake.

The Databricks data is one measured step from Phase 11.5, taken during the
trial. The trial is cancelled in 11.6, so no live source remains. Databricks is
a partner engine that reads Cerberus gold through the catalog. It is not a
migration, and it is not a rival.

The tensions:

- Reach against exposure: anonymous public access against invite-only.
- Liveness against safety: a live Grafana UI against a published snapshot.
- Cost against protection: with no flat-rate plan there is no hard cap on
  public traffic at $0.

## Decision

**A sanitised static snapshot on the existing standing edge.** The decisions
below include the owner's four answers of 2026-11-20 and a fifth on the 11.5
record.

1. **Serving.** A sanitised static snapshot on the existing standing edge
   (S3 and CloudFront). No laptop-hosted public stack, no port-forward, no
   tunnel.
2. **Access.** The snapshot page is anonymous. The terminal and the live
   Grafana stay invite-only, as ADR 0024 decides.
3. **Data and credentials.** The sources are git only: the run records and
   the 11.5 comparison record. The data contract is
   `observability/showcase/*.json`. The build has no AWS credentials, and
   no serving host has any. A parity test against the 13 named queries,
   run offline, proves the numbers match. The same sanitised
   `observability/showcase/*.json` also feeds Databricks Free Edition. An
   owner-run step loads it as Delta tables (see ADR 0028). The builder is
   built in step 11.2a, not 15.2, because both surfaces need it. No
   Databricks credential exists in CI or on any public host.
4. **Redaction.** Fail-closed at build time and again before upload. The
   build allowlists every output field and fails on `arn:`, `s3://`,
   `amazonaws.com`, `cloudfront.net` or `@` in any value. Before upload, CI
   reads the real account ID and searches the built site for that exact
   value; a plain "12 digits" search is not used because run records hold
   byte counts of 12 digits. The two strict xfails of ADR 0026 Security gap
   7 (`console/tests/test_sanitize.py`) become passing tests.
5. **Refresh.** On each merged run record, through `console-site.yml`. No
   scheduled job.
6. **Abuse.** Run the $0 CloudFront Free flat-rate plan spike (ADR 0026
   Security gap 1) before any public announcement, and adopt the plan or not on
   its result. In both cases, add a CloudFront `Requests` alarm on the
   existing topic after checking the live alarm count, and keep Budgets.
7. **Databricks column.** The 11.5 measured step only: same input, run time
   and cost per million events. Scope, source, date and "trial data, not live"
   are on screen. It is shown side by side as a partner engine, never ranked.
   Phase 11.5 writes its result in the `comparison.json` fields, so no field
   has to be measured after the trial ends. The record has these fields:
   `step`, `input` (`run_id`, `events`), `measured_on` and `trial`; per
   engine, `run_seconds`, `usd`, `usd_per_million_events`, `cost_source`
   (`run_record` or `databricks_billing`) and `estimated`; and `caveats`
   (fixed IDs). The public page may also show exported images and a short
   video of the Databricks AI/BI dashboards built on Free Edition (ADR 0028).
   They are labelled "Built in Databricks AI/BI (Free Edition)" and
   "learning tier, not a production SLA", and are never presented as a
   performance benchmark. Live Databricks access is invite-only: Free
   Edition cannot give an anonymous public dashboard or app. Viewers must
   be registered Databricks users ([Share a
   dashboard](https://docs.databricks.com/aws/en/dashboards/share/share)),
   and "You can't make Databricks apps public"
   ([Apps permissions](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/permissions)).
8. **Rejected.**
   - A router port-forward: an inbound port on a home network, the home IP
     exposed, no TLS without a domain, and it breaks "No public inbound
     port".
   - Cloudflare Tunnel: it needs a domain on Cloudflare and a third vendor,
     which ADR 0024 already rejected.
   - Tailscale Funnel as the primary route: its bandwidth limits are not
     published, TLS ends on the laptop and uptime depends on the laptop. Its
     fallback shape is kept in the plan.
   - Anonymous Grafana: a Viewer can send any query through `/api/ds/query`,
     which removes ADR 0024's "bounded by invitation only" cost bound.
   - An AMP read path for the snapshot: the same numbers as the run records,
     plus a step that needs credentials.
   - A daily laptop job: it republishes unchanged numbers and needs the
     `cerberus-admin` static keys unattended.
   - Pay-as-you-go WAF: about $5 a month per web ACL plus $1 per rule (list
     price from memory, unverified), which breaks $0 idle.
   - A ranked view: it breaks the partner-engine positioning.
   - A live Databricks link: the trial is cancelled in 11.6.
   - External embedding of a Databricks dashboard in the page: it needs a
     server that holds an OAuth secret and mints a token for each viewer
     ([Embedding for external users](https://docs.databricks.com/aws/en/dashboards/share/embedding/external-embed)).
     That puts a Databricks credential on a public host, or a new secret in
     AWS. Free Edition support is unverified, and Free Edition is
     non-commercial use.
   - A Databricks App as the public page: apps cannot be made public, and
     each app stops 24 hours after it starts or deploys
     ([Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)).
9. **Amends.** ADR 0024 gets a one-line Status note, "Amendment proposed by
   ADR 0027 (2026-11-20): a public, anonymous, static metrics and comparison
   view on the standing edge; the terminal and the live Grafana stay
   invite-only." It reads "Amended by ADR 0027" once this ADR is Accepted.
   ADR 0024's Decision is not rewritten. ADR 0026 is not amended: the trigger
   it set has fired, and this ADR acts on it.

## Consequences

**Good**

- $0 idle, and no new resource except one alarm.
- The page is up all day, with no home exposure and no credentials on a
  serving host.
- The numbers equal the alert and dashboard numbers by construction.
- The redaction gaps of ADR 0026 close.
- The Databricks column is honest about its scope.
- The page can show polished Databricks AI/BI images at $0, with no
  Databricks credential on a public host.

**Given up**

- No live Grafana UI for anonymous visitors.
- The numbers change only per exercise.
- The Databricks column is one step, and it is fixed.
- No live public Databricks view. The Free Edition images are manual owner
  exports.
- If the flat-rate plan is adopted, part of the edge is outside Terraform and
  blocks `standing-destroy` until the plan is cancelled.
- Public traffic is bounded only by Budgets until step 15.4 closes.

**Risks**

- The entry gate is far away: it needs the 9.4 rebuild, 10.3 and 10.6, and
  11.5.
- The 11.5 record does not exist yet, and no schema was set for it. The note
  on Phases.md 11.5 closes this, but 11.5 must follow it.
- The CloudFront free allowance, the flat-rate plan terms and Terraform
  support are unverified. They are checked in 15.4.
- Free Edition has no SLA and may delete inactive accounts. Only the
  invited path and the images depend on it; the public page does not.

**Revisit if**

- A live public UI is wanted. Use the Funnel fallback shape, with a new ADR.
- A domain is acquired.
- Phase 11 is redone with a longer-lived Databricks workspace.
- Monthly CloudFront requests pass the free allowance.
