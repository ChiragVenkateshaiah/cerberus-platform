# Plan: Databricks Free Edition as the presentation workspace (ADR 0028), and platform-development traceability (ADR 0029)

Date: 2026-11-20. Planner: Opus. Mode: plan only; the owner answered the open questions on 2026-11-20 (section 10). It reads `origin/main` at `831d12f` and draft PR #169 (`origin/decision-public-showcase`, ADR 0027 Proposed). Save as `docs/plans/2026-11-20-databricks-free-edition-showcase.md`. Proposed branch: `decision-databricks-free-edition`.

Owner request, verbatim: "Let's use Databricks Free Edition as much as possible if we can route the dashboard to Databricks Free edition to present better and production level aesthetics and performance. I would like you to do that plan and come up with new ADR please, if we have one. Let's build another one for traceability of the platform development." And: "Review with Opus and myself."

## 1. Question

Two decisions:
1. What should Databricks Free Edition do in Cerberus? Specifically, can the public dashboard be "routed" to it for production-level look and performance without breaking $0 idle, the credential rules or ADR 0027?
2. What does "traceability of the platform development" mean, and how is it built?

Why now: ADR 0027 is still Proposed (#169). Its Databricks column and its builder step (15.2) depend on this answer, and Phase 11.1, the Databricks ADR, is still unwritten.

## 2. Facts (V = verified, U = unverified)

**Repo**

- R1 (V). The next free ADR number is 0028. `git log --all` finds no `docs/adr/002[7-9]*` or `003*` file other than `0027-public-showcase.md` (#169, the only open PR, draft).
- R2 (V). Phase 11 on #169:
  - 11.1 is "ADR: Databricks as a second engine through the catalog (Free Edition vs. trial, Glue federation, Terraform scope, cost guardrails)".
  - 11.2 is "Free Edition: port one pipeline step as a Lakeflow job or pipeline with expectations; workspace objects in Terraform".
  - 11.3–11.6 cover the trial, Glue federation and the measured comparison. 11.5 carries the `comparison.json` note.
- R3 (V). The `docs/plan.md` Phase 11 text says these things:
  - "Free Edition (no cost, no end date): serverless only, one workspace and one metastore, no account console or account-level APIs, outbound internet access limited to trusted domains, at most 5 concurrent job tasks, one 2X-Small SQL warehouse, compute shut down for the day when the quota is exceeded, non-commercial use only."
  - Open: "whether Free Edition can reach Cerberus's S3 at all".
- R4 (V). ADR 0027 (Proposed):
  - Decision 1: a static snapshot on CloudFront.
  - Decision 2: the snapshot is anonymous; the terminal and Grafana are invite-only.
  - Decision 3: git-only sources and the `observability/showcase/*.json` contract.
  - Decision 4: fail-closed redaction.
  - Decision 7: the Databricks column is the 11.5 measured step only.
  - Phase 15 gate: 9.4, 10.3, 10.6 and 11.5. 15.2 is the builder.
- R5 (V). The status values come from the run records in git (ADR 0027 Context; plan F6). The GitHub repo is public, so the run records are already public.
- R6 (V). ADR 0024 sets "No public inbound port" and invite-only sign-in. ADR 0021 keeps AMP as the store, with Grafana local or per session.
- R7 (V). Positioning: Databricks is "a second engine reading through the catalog"; "Not a migration" (`docs/plan.md` Phase 11).

**Databricks Free Edition** (docs read 2026-11-20)

- D1 (V). [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations):
  - Compute and quotas:
    - Serverless only.
    - "outbound internet access is restricted to a limited set of trusted domains".
    - One SQL warehouse, capped at 2X-Small.
    - At most 5 concurrent job tasks.
    - "One active pipeline per pipeline type".
    - Over quota, "your workspace's compute resources will be shut down" for the rest of the day; data and settings are kept.
  - Apps: up to 3, and each stops 24 h after it is started or deployed.
  - Admin: one workspace and one metastore; "No account console or account-level API access"; no private networking or security customization.
  - Sign-in: email OTP, Google or Microsoft. No SSO or SCIM.
  - Unsupported: "Custom workspace storage locations".
  - Terms: "Databricks may delete Free Edition accounts that are inactive for a prolonged period"; no SLA; "Non-commercial use only".
  - LinkedIn verification can raise some usage limits.
  - What is new against R3: Apps, Lakebase, AI Search, LinkedIn verification, inactive-account deletion, no SLA, and no custom storage locations. Nothing in R3 is contradicted.
- D2 (V). [Free Edition overview](https://docs.databricks.com/aws/en/getting-started/free-edition): "Use Genie to interact with and visualize your data" (interactive dashboards), and Lakeflow for pipelines. It is for "learning or experimenting" and "personal use". No expiry and no region are stated, so the region is U.
- D3 (V). [Share a dashboard](https://docs.databricks.com/aws/en/dashboards/share/share):
  - Viewers must be workspace users or "registered members of your Databricks account".
  - "Anyone in my account can view" is the widest scope.
  - Registration limits access to designated members, "rather than allowing anyone with the link to view it".
  - No public or anonymous link is described. Published dashboards can be exported to PDF.
- D4 (V). [Dashboard embedding](https://docs.databricks.com/aws/en/dashboards/share/embedding/) and [external embedding](https://docs.databricks.com/aws/en/dashboards/share/embedding/external-embed):
  - Basic embedding requires viewers to sign in with Databricks credentials.
  - External embedding needs a service principal with an OAuth secret, and "your application server" generates a user-scoped token for each user (OAuth tokens last 1 h; the secret lasts 1–730 days).
  - A workspace admin sets the allowed domains.
  - Free Edition support is not stated (U).
- D5 (V). [Databricks Apps permissions](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/permissions): "You can't make Databricks apps public. Anonymous access and bypassing single sign-on (SSO) are not supported."
- D6 (U, conflicting). Storage credentials and external locations to your own S3 on Free Edition: a Databricks Community thread reports that AssumeRole validation fails, but a July 2025 blog reports success. Glue federation on Free Edition is not documented (U).
- D7 (U). Personal access tokens (PATs), the CLI, Asset Bundles and the Terraform provider on Free Edition: community reports are mixed. One says bundles fail to download Terraform because outbound access is restricted; another says bundles deployed a job and a pipeline. No official list exists.
- D8 (U). Whether a Free Edition workspace admin can add other users (invited viewers) without the account console. Whether dashboards export as `.lvdash.json` and deploy by bundle on Free Edition. Whether the PDF export carries the workspace URL or the user's email.

## 3. Constraints

- $0 idle and the $20/month budget. Free Edition costs $0, but it is quota-limited (D1).
- No account ID, workspace URL or ID, domain, email or token in repo files.
- No AWS credential and no Databricks token or OAuth secret on any public host.
- Claude never writes to Databricks or AWS. Workspace actions and uploads are owner-run.
- Do not weaken ADR 0024 (no public inbound port; invite-only terminal and Grafana) or ADR 0021 (AMP as the store). Keep ADR 0026's redaction rules (gap 7) for anything that leaves git.
- Positioning: Databricks is a partner engine; complement, not compete. The portfolio is production-level for the Canadian market. "Observability for everyone" means plain-language stories. Every number is real and sourced.
- Free Edition terms: non-commercial, no SLA. Never claim uptime for it.

## 4. Options

**D-a. What runs on Free Edition**

1. **Dashboard only**, on uploaded CSV. Low effort, but no data contract and no "as code".
2. **Showcase JSON as Delta tables plus AI/BI dashboards plus a Genie space (recommended).**
   - What: the same sanitised `observability/showcase/*.json` that feeds CloudFront is loaded into a Unity Catalog volume and then into Delta tables by one notebook or job. The dashboards are kept as files in git.
   - Strengths: one data contract for both surfaces; parity by construction; production-style look; Genie gives plain-language questions ("observability for everyone").
   - Costs: an owner upload step; dashboard-as-code is U on Free Edition (D7, D8).
3. **The above plus the original 11.2 Lakeflow port** (one pipeline step with expectations). This is already in scope; the recommendation keeps it as the second part of 11.2.
4. **Databricks reads Cerberus gold directly** (external location or Glue federation on Free Edition). U and conflicting (D6). It needs an IAM role trusted by a Databricks-owned account, and the cost cannot be measured on Free Edition. Keep it as a time-boxed $0 spike only. It does not replace the trial in 11.3–11.5, because cost per million events needs billing data (R3).

**D-b. How the public sees it**

1. **Link to the Databricks-hosted dashboard.** Not possible anonymously (D3). Viewers would need a Databricks sign-in and a registration.
2. **External embedding in the CloudFront page.** Rejected:
   - It needs a token-minting server holding an OAuth secret (D4). That breaks the "no credentials on a public host" rule, or it adds a Lambda holding the secret, which is a new secret in AWS.
   - It is U on Free Edition.
   - It is non-commercial use behind a public portfolio (D1).
3. **A Databricks App.** Rejected: apps "can't be made public" (D5) and stop after 24 h.
4. **Exported images, video and a live invite (recommended).**
   - Dashboard PDF exported to PNG, plus a short video, committed under `observability/showcase/databricks/` and shown on the CloudFront page as "Built in Databricks AI/BI (Free Edition)".
   - Live access for a named visitor by invitation, matching the ADR 0024 model, if D8 allows invites.

**D-c. Data flow and credentials**

1. **Git → owner laptop → Free Edition (recommended).**
   - Only the sanitised showcase JSON leaves git, and it is already public (R5).
   - The owner uploads it with the UI or `databricks` CLI on OAuth U2M (`databricks auth login`), so no PAT is stored.
   - No AWS credential exists in Databricks. No Databricks credential exists in CI or on a public host.
2. **Free Edition pulls from GitHub** (raw URL or Git folder). It depends on the trusted-domain list (U). It is a fallback, and it is still credential-free for a public repo.
3. **CI pushes with a PAT secret.** Rejected: a long-lived Databricks token in CI, for $0 gain.

**D-d. Durability ("everyday")**

- Free Edition has no SLA, stops for the day when the quota runs out, and may delete inactive accounts (D1).
- So the public everyday page stays on CloudFront (ADR 0027).
- Everything in Databricks must be rebuildable from git: the JSON, the load notebook and the dashboard files.
- A monthly owner sign-in keeps the account active. The prolonged-inactivity period is U.

**D-e. Where the work goes in the roadmap**

1. **ADR 0028 is the 11.1 ADR (recommended).**
   - It decides the Free Edition scope now and restructures 11.2.
   - It keeps the existing trial and federation design (R3) as written, to be re-verified by an ADR 0028 amendment before 11.3.
   - The git-only showcase builder moves from 15.2 to 11.2a, because both surfaces need it.
2. **A new phase just for Free Edition.** Rejected: it duplicates Phase 11's goal.
3. **Fold everything into Phase 15.** Rejected: Phase 15 is gated on 11.5, and the Free Edition work does not need the trial.

**Traceability: the likely meanings of "another one"**

- **T1. A traceability record (recommended).**
  - A CI-generated dataset links each subtask → ADR → plan → PR → merge commit → run record → dashboard panel and Well-Architected milestone.
  - It is built from git, Phases.md, the ADR files and the `gh` PR list (`GITHUB_TOKEN`, read-only).
  - It is published as `observability/showcase/history.json`, shown on the site and as a second Databricks dashboard ("how the platform was built").
  - It needs its own ADR (0029).
- **T2. A second dashboard only** (the development timeline on Databricks). It is part of T1.
- **T3. A second ADR as a decision log.** The ADRs already are the decision log. Low value alone.
- **T4. Requirements traceability** (each "Done when" criterion → evidence). This can be one field inside T1.

## 5. Recommendation and design

- D-a 2 (plus the existing Lakeflow port, and the federation spike as optional).
- D-b 4, D-c 1, D-d as stated, D-e 1.
- T1 (with T2 and T4 inside it), as ADR 0029.

Why: Free Edition gives the production-level look and the Genie "ask it in plain English" layer. It cannot give anonymous public access (D3, D5), and the only route that comes close puts a secret on a server (D4). So Databricks becomes the polished room that invited visitors enter, and its pictures go in the public window. Security and Cost decide this, as in ADR 0027. Positioning gains: Cerberus produces the gold, and Databricks presents and explores it — complement, not compete.

**Design**

- **One contract.** `observability/showcase/*.json` (ADR 0027 §5.1), plus `history.json` (ADR 0029). Both surfaces read the same files.
- **Load.** One notebook or job reads the volume files into Delta tables `cerberus_showcase.runs`, `status`, `slo`, `comparison` and `history` (names U until build), with a fixed schema and no inference. The source is in git under `databricks/showcase/`.
- **Dashboards in git as files.**
  - The run story (for everyone), the scale story, Cerberus | Databricks (after 11.5), and how it was built (T1).
  - Warehouse and catalog are referenced by name, not ID, wherever the file format allows. If an exported file embeds an ID, the commit script replaces it with a placeholder before commit.
- **Genie.** One space on the showcase tables, with curated instructions and sample questions. The instruction text lives in git.
- **Public output.**
  - PNGs of the published dashboards, with metadata stripped, committed under `observability/showcase/databricks/`.
  - A CI check allows only PNG, caps the size and requires a sidecar `.json` with the source dashboard file, the export date and the owner checklist ticked: no workspace URL, email or IDs visible.
  - CI cannot read images, so this check is the owner's checklist plus a size and type gate. The plan says so.
- **`comparison.json` is optional until 11.5.** The 11.2a builder runs before the 11.5 comparison record exists. The builder omits `comparison.json` when the record is absent, and the page and the Databricks dashboards show no Databricks comparison column until it exists. This closes a gap Part A flagged; it is a decision made by the planner's follow-up, not by the owner.
- **Labels on screen.** "Databricks Free Edition: learning tier, not a production SLA; numbers come from Cerberus run records." Free Edition run times are never presented as Databricks performance benchmarks. Only the 11.5 trial step is a measured comparison (ADR 0027 Decision 7).

## 6. ADR outlines

### ADR 0028. Databricks Free Edition as the partner workspace and presentation layer

Status: Proposed (2026-11-20). It is the Phase 11.1 ADR. It extends ADR 0027 through the edits made in #169 while ADR 0027 is Proposed (done in commit `a72ddaa`): Decisions 3 and 7 are extended, and 15.2 moves to 11.2a. ADR 0024, 0021 and 0026 are not amended.

**Context**
- The owner's request, quoted.
- Facts D1–D8 and R2–R7.
- The tensions:
  - A polished Databricks dashboard against public reach: anonymous access is impossible (D3, D5).
  - Live embedding against credential rules (D4).
  - Free Edition convenience against durability (no SLA, deletion).
  - The positioning risk of presenting learning-tier numbers as benchmarks.

**Decision**
1. Free Edition hosts the showcase tables, AI/BI dashboards and a Genie space, loaded from the sanitised showcase JSON in git.
2. The public sees exported images and a video on CloudFront. Live access is by invitation only.
3. No Databricks credential in CI or on any public host. No AWS credential in Databricks, except during the optional federation spike, under a read-only, gold-scoped role.
4. Uploads and deploys are owner-run, with OAuth U2M and no stored PAT.
5. Everything is rebuildable from git, and the CloudFront page stays the public everyday face.
6. 11.2 is split into 11.2a–11.2e (section 7). The trial and federation design (11.3–11.5) stands, to be re-verified by an amendment before 11.3.
7. Rejected options, each with its reason from section 4:
   - A direct public link.
   - External embedding (it needs a secret on an app server).
   - A Databricks App (it cannot be public).
   - CI pushes with a PAT.
   - Replacing the trial with Free Edition (no billing data).
   - A separate phase.

**Consequences**
- **Good:** a production-style look and Genie for non-engineers at $0; one data contract; Databricks in the story months before the trial.
- **Given up:** no live public Databricks view; manual owner exports; image redaction depends on a human checklist; Free Edition outages or deletion hit only the invited path.
- **Risks:** D6–D8 are unverified; the terms are "non-commercial" (the owner reads them); quota stops.
- **Revisit if:** Databricks adds anonymous published dashboards, the trial or a paid workspace exists, or embedding becomes possible without a server-held secret.

### ADR 0029. Platform-development traceability

Status: Proposed (2026-11-20). It extends the ADR 0027/0028 data contract with `history.json`. It amends nothing.

**Context**
- Evidence is spread across Phases.md, ADRs, plans, PRs, run records and Well-Architected milestones, and links between them are kept by hand.
- Portfolio readers ask "how was this built, and why?".

**Decision**
1. A generator (`tools/traceability/`, Python, no AWS) builds `history.json` and the `docs/traceability.md` table from git, Phases.md, the ADR Status lines, plan files, run records and `gh pr list --state merged` (CI `GITHUB_TOKEN`, `pull-requests: read`).
2. A CI check fails on dangling links: a checked subtask with no PR, an ADR Accepted without a plan, a run record not referenced.
3. It is shown on the site (15.3) and as the Databricks "how it was built" dashboard.
4. Only public metadata: PR number, title, dates. No author emails.

**Consequences**
- **Good:** audit-style traceability; a living timeline; it catches bookkeeping drift.
- **Given up:** a new CI job; history before structured PR titles is partial.
- **Revisit if:** PR title conventions change.

## 7. Phases.md placement and build steps

**Phase 11 (replace 11.1 and 11.2; 11.3–11.7 unchanged):**

```
- [ ] 11.1 ADR: Databricks Free Edition as the partner workspace and
      presentation layer; trial and Glue federation re-verified by an
      amendment before 11.3. ADR 0028
- [ ] 11.2 Free Edition
      - 11.2a Showcase builder (git only): `observability/showcase/*.json`,
        fail-closed redaction, parity with the named query set (moved from
        15.2)
      - 11.2b Workspace as code: schema, volume, load notebook or job,
        dashboards and the Genie instructions in `databricks/showcase/`;
        owner-run deploy (bundle if it works on Free Edition, else UI import)
      - 11.2c AI/BI dashboards (run story for everyone, scale story, how it
        was built) and a Genie space; exported PNGs with the checklist
      - 11.2d Port one pipeline step as a Lakeflow job or pipeline with
        expectations
      - 11.2e Optional $0 spike: Free Edition reads Cerberus gold (external
        location or Glue federation) with a read-only role; record yes or no
```

**Phase 15 (#169, edited in `a72ddaa`):** 15.2 becomes "Showcase publish: use the 11.2a builder; add the Databricks images (11.2c)". The 15.3 view adds the "Built in Databricks" section.

**Traceability:** a new Phase 16, "Development traceability", numbered 16. It is git-only, $0 and has no dependency, so it can run any time after ADR 0029 is accepted. Slot: after Phase 10 (10.7), before 14.2 (owner answer 2, section 10).

```
- [ ] 16.1 ADR: platform-development traceability. ADR 0029
- [ ] 16.2 Generator: `history.json` and `docs/traceability.md` from git,
      Phases.md, ADRs, plans, run records and merged PRs; CI dangling-link
      check
- [ ] 16.3 Shown on the site and as the Databricks "how it was built"
      dashboard (with 11.2c and 15.3)
- [ ] 16.4 Well-Architected pass + ADR
```

The 16.4 subtask also needs adding to the Well-Architected list at Phases.md ~L23. `docs/plan.md` needs a roadmap row, a `### Phase 16` block in the Phase 14 shape, and an updated Phase 11 block. `README.md` needs a row 16 and an updated row 11 ("Planned: ADR 0028 proposed").

**Build steps and verification**

1. **PR 1, docs.**
   - ADR 0028 and ADR 0029 Proposed, this plan, the Phases.md, `docs/plan.md` and README edits, and the #169 edits to ADR 0027 (done in `a72ddaa`).
   - Verify: no URL, ID or email (`grep -nE 'cloud\.databricks\.com|[0-9]{12}|@'` on the diff, allowing the redaction-rule text); every claim traces to section 2.
2. **Owner spike, $0, about 1 h; it settles D7 and D8.**
   - Sign up for Free Edition (or reuse an account).
   - `databricks auth login` (OAuth U2M).
   - Try `databricks bundle validate` and `deploy` on an empty bundle.
   - Try adding a second user.
   - Export one dashboard as a file and as a PDF, and check for the workspace URL or email.
   - Record the results in the plan; these are not secrets.
3. **PR 2 (11.2a).**
   - The builder from ADR 0027 §5.1–5.2.
   - Verify: tests, the planted-ARN failure, and parity with `make status-e2e`.
4. **PR 3 (16.2).**
   - The generator and the CI job.
   - Verify: the generator is deterministic; a planted dangling link fails the CI check; the output has no emails.
5. **PR 4 (11.2b).**
   - `databricks/showcase/` (load notebook, fixed schemas, dashboard files with placeholders, Genie instructions) and `make databricks-showcase-upload`, an owner-run CLI step.
   - Verify: a local schema test against the JSON; the owner runs the deploy, and the table row counts equal the record counts.
6. **Owner (11.2c).**
   - Publish the dashboards, export the PNGs, strip the metadata, fill in the sidecar checklist. Commit happens through a PR.
   - Verify: the CI gate on type, size and sidecar.
7. **PR 5 (11.2d).**
   - The Lakeflow port (original 11.2). Verify: the expectations pass on Free Edition.
8. **Optional (11.2e).**
   - The spike, with a read-only role in a dev-standing PR, removed if the spike fails.
   - Verify: one `SELECT count(*)` on gold, then remove the role.
9. **Phase 15 and 16.3** follow their gates.

## 8. Unverified items

- D4 external embedding on Free Edition.
- D6 S3 and Glue access from Free Edition.
- D7 CLI, bundles and the Terraform provider.
- D8 user invites, dashboard file export and PDF content.
- The region and the inactivity period.
- Whether a job-hunting portfolio counts as "non-commercial" (the owner reads the [Terms of Use](https://www.databricks.com/terms-of-use)).
- Genie quotas on Free Edition.

## 9. Owner steps

- Accept or change ADR 0028 and ADR 0029.
- Sign up for Free Edition and verify LinkedIn (it raises limits, D1).
- Run the step 2 spike.
- Do all uploads, deploys, publishes and exports, plus a monthly sign-in.
- Do the 11.2e spike (accepted, section 10).

## 10. Owner answers (2026-11-20)

All five were answered as recommended.

1. **Traceability** means the generated record (ADR 0029): a phase, ADR, plan, PR and run record link, shown on the site and as a second Databricks dashboard.
2. **Phase 16** runs right after Phase 10 (10.7), before 14.2.
3. **Free Edition steps 11.2a-c** also move ahead of 14.2-14.4, right after Phase 10. They need no AWS and no trial, and they feed Phase 15 and Phase 16.
4. **ADR 0027** is edited in #169 while it is Proposed. Done in commit `a72ddaa`.
5. **The optional 11.2e gold spike** is accepted. It is time-boxed and $0. The read-only, gold-scoped role is removed on failure. It does not replace the trial.

Sources:
- [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
- [Free Edition overview](https://docs.databricks.com/aws/en/getting-started/free-edition)
- [Share a dashboard](https://docs.databricks.com/aws/en/dashboards/share/share)
- [Embed a dashboard](https://docs.databricks.com/aws/en/dashboards/share/embedding/)
- [Embedding for external users](https://docs.databricks.com/aws/en/dashboards/share/embedding/external-embed)
- [Databricks Apps permissions](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/permissions)
- [Community: Free Edition S3 storage credential](https://community.databricks.com/t5/data-engineering/databricks-free-edition-aws-s3-storage-credential-validation/td-p/175318)
- [Blog: Free Edition external table on user S3](https://dev.classmethod.jp/articles/databricks-free-edition-dataload-from-s3/)
- [Community: Free Edition and Asset Bundles](https://community.databricks.com/t5/get-started-discussions/free-edition-and-databricks-asset-bundles/m-p/122137)
- [Databricks Terms of Use](https://www.databricks.com/terms-of-use)

