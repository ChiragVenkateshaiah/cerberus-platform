# 28. Databricks Free Edition as the partner workspace and presentation layer

Date: 2026-11-20

## Status

Accepted (2026-11-20). This is the Phase 11.1 ADR. It extends
[ADR 0027](0027-public-showcase.md) through the edits made to that ADR in
PR #169 while it was Proposed: Decisions 3 and 7 are extended, and
the builder step moves from 15.2 to 11.2a. It amends nothing that is
Accepted: ADR 0024, ADR 0021 and ADR 0026 are not changed. The build steps
and the facts behind this ADR are in
[the plan](../plans/2026-11-20-databricks-free-edition-showcase.md).

Related: [ADR 0029](0029-platform-traceability.md) (traceability) adds
`history.json` to the data contract that this ADR loads into Databricks.

## Context

The owner asked to use Databricks Free Edition as much as possible, and to
route the dashboard there for a better presentation and production-level
aesthetics and performance. The full request is in the plan.

What exists today:

- Phase 11 plans a Free Edition build step and a 14-day trial. Free Edition
  has no cost and no end date. It is serverless only, with one workspace and
  one metastore, no account console or account-level API, outbound internet
  limited to trusted domains, one 2X-Small SQL warehouse, and at most 5
  concurrent job tasks. Compute shuts down for the day when the quota is
  exceeded (`docs/plan.md` Phase 11; [Free Edition
  limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)).
- Databricks is a second engine reading through the catalog. It is not a
  migration (`docs/plan.md` Phase 11).
- ADR 0027 publishes a sanitised static snapshot on CloudFront, built from
  git only. Its Databricks column is the 11.5 measured step.
- The run records are in a public GitHub repo, so the sanitised showcase
  JSON is already public.
- ADR 0024 sets "No public inbound port" and invite-only sign-in for the
  terminal and Grafana. ADR 0021 keeps AMP as the store.

What Free Edition adds (docs read 2026-11-20):

- Up to 3 Databricks Apps, and each stops 24 hours after it starts or
  deploys.
- AI/BI dashboards and Genie, a plain-language question layer.
- No SLA. Databricks "may delete Free Edition accounts that are inactive for
  a prolonged period". Use is non-commercial only.
- Dashboard viewers must be workspace users or registered members of the
  Databricks account. No public or anonymous link is described ([Share a
  dashboard](https://docs.databricks.com/aws/en/dashboards/share/share)).
  "You can't make Databricks apps public" ([Apps
  permissions](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/permissions)).
- Embedding for external users needs a service principal with an OAuth
  secret, and an application server that mints a user-scoped token for each
  viewer ([Embedding for external
  users](https://docs.databricks.com/aws/en/dashboards/share/embedding/external-embed)).
  Free Edition support is unverified.
- Unverified or conflicting: storage credentials to your own S3 and Glue
  federation on Free Edition; personal access tokens, the CLI, Asset Bundles
  and the Terraform provider; whether a workspace admin can invite viewers;
  whether dashboards export as files; and what the PDF export carries.

The tensions:

- A polished Databricks dashboard against public reach: anonymous access is
  not possible.
- Live embedding against the rule that no credential sits on a public host.
- Free Edition convenience against durability: no SLA, and possible deletion.
- The positioning risk of presenting learning-tier numbers as benchmarks.

## Decision

Free Edition is the partner workspace and the presentation layer. The public
everyday page stays the CloudFront snapshot of ADR 0027.

1. **What runs there.** Free Edition hosts the showcase tables, AI/BI
   dashboards and a Genie space. They load from the sanitised
   `observability/showcase/*.json` in git (and `history.json`, ADR 0029).
   One notebook or job loads the files from a Unity Catalog volume into
   Delta tables with a fixed schema and no inference. Table names are not
   final until the build. The load code, dashboard files and Genie
   instructions live in git under `databricks/showcase/`. The dashboards are
   the run story for everyone, the scale story, the Cerberus | Databricks
   view (after 11.5), and how the platform was built (ADR 0029).
2. **What the public sees.** Exported dashboard images and a short video on
   the CloudFront page, labelled "Built in Databricks AI/BI (Free Edition)"
   and "Databricks Free Edition: learning tier, not a production SLA;
   numbers come from Cerberus run records." Live access is by invitation
   only, like the terminal, if inviting viewers works on Free Edition
   (unverified). Free Edition run times are never presented as Databricks
   performance benchmarks. Only the 11.5 trial step is a measured
   comparison (ADR 0027 Decision 7).
3. **Credentials.** No Databricks credential exists in CI or on any public
   host. No AWS credential exists in Databricks, except during the optional
   11.2e spike, under a read-only role scoped to gold.
4. **Owner-run uploads and deploys.** The owner uploads and deploys with the
   UI or the `databricks` CLI on OAuth U2M (`databricks auth login`). No
   personal access token is stored. Claude does not write to Databricks.
5. **Rebuildable from git.** Everything in Databricks (the JSON, the load
   notebook and the dashboard files) can be rebuilt from git. Where an
   exported dashboard file embeds a workspace or warehouse ID, the commit
   step replaces it with a placeholder. A monthly owner sign-in keeps the
   account active; the inactivity period is unverified.
6. **Image gate.** The exported images go in
   `observability/showcase/databricks/` as PNG with metadata stripped. CI
   allows only PNG, caps the size and requires a sidecar `.json` with the
   source dashboard file, the export date and the owner checklist ticked: no
   workspace URL, email or ID visible. CI cannot read images, so this gate
   is the owner's checklist plus a type and size check.
7. **`comparison.json` is optional until 11.5.** The 11.2a builder runs
   before the 11.5 comparison record exists. The builder omits
   `comparison.json` when the record is absent, and the page and the
   dashboards show no Databricks column until it exists. The record cannot be required, because 11.2a runs before 11.5.
8. **Phase 11 is split.** 11.2 becomes 11.2a to 11.2e:
   - 11.2a: the git-only showcase builder, moved from 15.2, with fail-closed
     redaction and parity with the named query set.
   - 11.2b: the workspace as code, deployed by the owner.
   - 11.2c: the AI/BI dashboards, a Genie space and the exported images.
     If export or invites fail on Free Edition, record it; the Phase 15
     gate then needs 11.2a-b only.
   - 11.2d: the original port of one pipeline step as a Lakeflow job or
     pipeline with expectations.
   - 11.2e: an optional, time-boxed, $0 spike: Free Edition reads Cerberus
     gold, with a read-only gold-scoped role removed on failure. It does
     not replace the trial.

   Steps 11.2a-c run right after Phase 10, ahead of 14.2-14.4. The trial and
   Glue federation design (11.3 to 11.5) stands as written. An amendment to
   this ADR re-verifies it before 11.3.
9. **Rejected.**
   - A direct public link to the Databricks dashboard: viewers need a
     registered Databricks identity, so it cannot be anonymous.
   - External embedding in the CloudFront page: it needs a server that holds
     an OAuth secret and mints tokens. That puts a Databricks credential on
     a public host, or a new secret in AWS. Free Edition support is
     unverified, and the terms are non-commercial.
   - A Databricks App as the public page: apps cannot be made public, and
     each stops 24 hours after it starts or deploys.
   - CI pushes with a personal access token: it needs a long-lived
     Databricks token in CI, for no gain at $0.
   - Replacing the trial with Free Edition: Free Edition gives no billing
     data, and cost per million events needs billing data.
   - A separate phase for Free Edition: it duplicates the goal of Phase 11.
   - Free Edition reading Cerberus gold as the primary path: access to your
     own S3 and Glue federation on Free Edition is unverified, with
     conflicting reports. It is kept only as the time-boxed 11.2e spike.

## Consequences

**Good**

- A production-style look, and Genie for non-engineers, at $0.
- One data contract feeds both surfaces, so parity holds by construction.
- Databricks is in the story months before the trial.
- No new credential on any public host.

**Given up**

- No live public Databricks view. Anonymous access is not possible.
- The exports are manual owner steps.
- Image redaction depends on a human checklist.
- A Free Edition outage, quota stop or account deletion affects only the
  invited path and the next export. The public page does not depend on it.

**Risks**

- These are unverified: S3 and Glue access from Free Edition, the CLI,
  Asset Bundles and the Terraform provider, user invites, dashboard file
  export, the PDF content, the region, the inactivity period, Genie quotas,
  and embedding on Free Edition.
- The terms are "non-commercial". The owner reads the [Terms of
  Use](https://www.databricks.com/terms-of-use) on whether a portfolio
  counts.
- Free Edition has no SLA, so no uptime is claimed for it.

**Revisit if**

- Databricks adds anonymous published dashboards.
- A trial or a paid workspace exists.
- Embedding becomes possible without a server-held secret.
