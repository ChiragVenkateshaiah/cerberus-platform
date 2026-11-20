# Plan: Phase 15, the public showcase (Cerberus metrics and performance, with Databricks as a partner column)

Date: 2026-11-20. Planner: Opus. Mode: plan for a new phase (Phases.md 15.1–15.7) and ADR 0027. It reads `origin/main` at `85fcf35`, plus HEAD `6ed9b22` (branch `10.2c-status-e2e`, not merged) where marked. Save as `docs/plans/2026-11-20-public-showcase.md`. Proposed branch: `decision-public-showcase`.

Updated 2026-11-20 after the Databricks Free Edition plan (docs/plans/2026-11-20-databricks-free-edition-showcase.md): the builder step moves from 15.2 to 11.2a, because both the CloudFront page and Databricks Free Edition need it; 15.2 now publishes with that builder and adds the Databricks images (11.2c).

Owner request, verbatim: "Up next let's deploy Cerberus on local port which I will expose while docker runs it everyday locally. This makes my Cerberus Platform available for viewers from GitHub and LinkedIn. Add this as a Phase which we should get done if we are in a state of exposing Cerberus metrics and performance by appreciating Databricks as a column in the dashboard. Review it Opus once before any decision. Review with me too."

The Opus proposal and the owner's answers came first, on 2026-11-20 (section 8). The owner chose option D: a published, sanitised snapshot on the existing CloudFront standing edge. This rules out a laptop-hosted stack, a port-forward and a tunnel.

## 1. Question

How should the public see Cerberus's metrics and performance, with Databricks shown as a partner column? Viewers come from GitHub and LinkedIn and are anonymous. The answer must keep $0 idle, add no internet exposure of the owner's machine, and not weaken ADR 0024's invite-only terminal and Grafana.

Why now:
- The owner asked for a phase now.
- Its entry gate depends on three phases already in flight (9.4, 10.x, 11.5).
- So the gate and the data contract must be written before those phases fix their outputs.
- The build waits for the gate.

## 2. Facts (V = verified, U = unverified)

**Local stack**

- F1 (V). The local Grafana binds `127.0.0.1:3000` only, with anonymous access off (`observability/grafana/compose.yaml` L15-22). The compose comment says the bind is loopback because "the short-lived read-only credentials in this container must not be reachable from the network".
- F2 (V). `make grafana-up` (`observability/grafana/up.sh`) assumes `cerberus-grafana-read` from the `cerberus-admin` profile, for at most 12 h. It passes the keys as environment variables. ADR 0021 calls local Compose the owner's dev loop (admin, an Editor token).
- F3 (V). Other local ports:
  - The landing preview on `127.0.0.1:8088` (`console/cerberus_landing/serve.py`).
  - The 10.2c throwaway Prometheus on `127.0.0.1:9099` (`observability/status/e2e.sh`, HEAD only).
  - No port 3300 appears in origin/main or HEAD.

**The standing edge (ADR 0024)**

- F4 (V). S3, CloudFront (OAC), Cognito, the HTTP API and the command Lambda are in `dev-standing`, at about $0 idle (ADR 0024 table).
  - "The landing page is public on purpose" (ADR 0024, Sign-in and sessions).
  - The terminal and the per-session Grafana are invite-only (Cognito admin-create).
  - CSP is `default-src 'self'`; `connect-src 'self' <cognito>` (`terraform/modules/console_edge/main.tf` L164-171).
  - `PriceClass_100` (L213).
  - Two console alarms exist: `api_5xx` and `lambda_errors` (L531, L555).
  - There is no CloudFront request alarm.
- F5 (V). `.github/workflows/console-site.yml` rebuilds and publishes the site on every push to main that touches `observability/scale/runs/**`, `docs/img/scale/**`, `Phases.md` or the builder.
  - The build step has no AWS credentials.
  - Credentials are assumed after the build, for the upload.
  - It refuses a commit that is not main's head.
  - `console/publish_site.sh` never bulk-deletes. It never touches `healthz.txt` or `live.json`.

**Data sources**

- F6 (V). The status publisher's input is the run record, `observability/scale/runs/<execution>.json` (plan `docs/plans/2026-11-20-pipeline-status-exporter.md` L178). `make status-e2e` (HEAD) pushes run records to a local Prometheus and checks all 13 named queries. So every Phase 10 status value is a function of a file already in git.
- F7 (V). 17 run records exist. The keys of `demo-100m-20261108T135119Z.json` include `status`, `run_seconds`, `events_processed`, `events_per_second`, `states`, `data_quality` (`passed`, `errors`, `warnings`, …) and `cost` (`usd`, `usd_per_million_events`, `estimated`, …).
  - A grep for `arn:` and `s3://` finds nothing in that record.
  - A 12-digit grep matches byte counts (for example a byte count at L336).
  - So a "12 digits = account ID" rule gives false positives.
- F8 (V). The named query set is `observability/queries/status.json`, with 13 entries from `latest_status` to `newest_started_execution`.
- F9 (V). `console/tests/test_sanitize.py` L81-89 has two strict xfails: a 13-digit account in an ARN, and a 12-digit S3 bucket name. ADR 0026 Security gap 7's trigger is "any new output field that carries ARNs or S3 URIs (the Phase 10 series …)".

**Phases and positioning**

- F10 (V). Phases.md status:
  - 9.4: the page was rejected on 2026-11-12 and is being rebuilt as an interactive showcase in a separate session.
  - 10.3 and 10.6 are open.
  - Phase 11 has not started.
  - Order (checkpoint "Next up" 3): 10.2–10.7 → 14.2–14.4 → Phase 11.
- F11 (V). The Phase 11 scope in `docs/plan.md`:
  - 11.5 is "same input on both engines, run time and cost per million events".
  - "Done when" says "one pipeline step runs on Databricks".
  - 11.6 cancels the trial.
  - Databricks is "a second engine reading through the catalog", "Not a migration".
  - So the Databricks numbers are fixed, measured data for one step. No live source remains after 11.6.
- F12 (V). No record schema for the 11.5 comparison exists in the repo.

**ADRs**

- F13 (V). ADR 0024:
  - Phases.md 9.2 rule: "No public inbound port".
  - Rejected: "Cloudflare Tunnel (a third-party vendor in an AWS portfolio)".
  - The Grafana-path cost "is bounded by invitation only, because a Viewer has API access".
  - Revisit if "Invites go beyond a handful of people".
- F14 (V). ADR 0026:
  - Security gap 1 defers the CloudFront Free flat-rate plan. The trigger is "invites go beyond a handful (ADR 0024's trigger), or a month's CloudFront requests are not explained by invites", and the rule is "Run a $0 spike before adopting the plan".
  - Consequence 14: the 9.4 rebuild must honour `ends` in `live.json`.
- F15 (V). The roadmap tables have one row per phase: `docs/plan.md` "Roadmap overview" (14 rows, 0–14) and `README.md` "## Roadmap" (0–14). `docs/plan.md` "Phases in detail" has one `### Phase N` block per phase. The Phase 14 block (after Phase 13) is the model for an out-of-order phase number.

**Vendor facts (for the rejected options and step 15.4)**

- X1 (V, docs read). Cloudflare Tunnel is outbound-only. To publish an app, "you must add a website to Cloudflare", so it needs a domain. Quick Tunnels are "for testing and development", with "no uptime guarantee" and 200 in-flight requests. Cloudflare's page says "available on all plans"; I did not read the fine print, so the $0 claim is U.
- X2 (V, docs read). Tailscale Funnel:
  - Ports 443, 8443 and 10000 only.
  - "non-configurable bandwidth limits" (the numbers are not published, U).
  - A `*.ts.net` name.
  - TLS terminates on the device.
  - "available for all plans".
- X3 (V, docs read). Grafana:
  - Anonymous access is "an early way to share dashboards"; public dashboards are "a more secure way".
  - Shared dashboards "can only execute the queries stored on the original dashboard" and do not support template variables.
  - Support for the Amazon Prometheus plugin in shared dashboards is U.
- X4 (U). CloudFront free allowance of 1 TB and 10M requests a month: the FAQ wording on usage above the allowance conflicts. The Free flat-rate plan's terms (100 GB, 1M requests, WAF included) come from an AWS blog. Eligibility for this account and its Terraform support are U (ADR 0026 gap 1).
- X5 (U). The alarm free tier is 10 standard alarms (ADR 0026 owner answer 2, from memory). 9 alarm resources exist in code (7 in `observability/alarms.tf`, 2 in `console_edge`), but `cerberus-admin` could not read the live count until the PR 2 paste. One more alarm may reach the free limit.

## 3. Constraints

- $0 idle and the $20/month budget. Nothing new bills hourly.
- No resource is added to `dev-compute` or `dev-console`. CI applies `dev-standing` only (ADR 0011).
- No account ID, ARN, S3 URI, domain, pool ID or token in new repo files or in published site files.
- No inbound exposure of the owner's machine. No AWS credentials on any host that serves the public.
- Do not contradict ADR 0021 (local Compose stays the dev loop; one Grafana file set). Do not contradict ADR 0024 (invite-only terminal and Grafana). Amend ADR 0024 only to add a public, anonymous, static metrics view, and do it by name.
- Positioning: Databricks is a partner engine. No ranking. Every number is real, sourced and labelled with its scope. Estimates are labelled as estimates.
- "Observability for everyone": a plain-language story layer over the numbers. The page must be interactive, not text (the 9.4 rejection).
- The page must keep the CSP (`script-src 'self'`, `style-src 'self'`, no inline code) and the safe publish.

## 4. Options

Each decision lists its options with the pillar trade-offs. The owner's choices are marked.

**D1. Where the public view is served (Security, Reliability)**

- **A. Router port-forward to the laptop's Docker stack.** Rejected.
  - It exposes the home IP and an inbound port on a home network.
  - It has no TLS without a domain, and CGNAT may block it.
  - The serving host holds the F2 credentials and sits beside the `cerberus-admin` static keys (ADR 0023 `identities`, still HIGH).
  - It breaks ADR 0024's "No public inbound port".
- **B. Cloudflare Tunnel from the laptop.** Rejected.
  - It has no inbound port, but it needs a domain on Cloudflare (X1) and a third vendor, which ADR 0024 already rejected.
  - Uptime depends on the laptop being awake.
- **C. Tailscale Funnel from the laptop.** Rejected as the primary; kept as the documented fallback.
  - It needs no domain and the tunnel costs nothing.
  - The bandwidth limits are not published (X2). TLS ends on the laptop. Uptime depends on the laptop.
  - Fallback shape, only if a live UI is wanted later, and with a new ADR:
    - A separate Compose project.
    - A local Prometheus filled from run records by `publish.py --url` (the 10.2c pattern), so the host has no AWS credentials.
    - Shared dashboards only, Explore off, `hide_version`.
    - A "may be offline" banner, with the CloudFront page kept as the primary link.
- **D. A sanitised static snapshot on the existing CloudFront site. Chosen (owner, 2026-11-20).**
  - Cost: $0 idle, no new resource.
  - Reliability: up 24/7.
  - Security: no home exposure, no credentials on a serving host, no visitor-written queries.
  - Gives up: a live Grafana UI for anonymous visitors.

**D2. Who can see it (Security, Cost)**

- **(a) Anonymous for the snapshot page only. Chosen.** The terminal and the live Grafana stay invite-only (ADR 0024).
- (b) Invite-only for everything. Rejected: it blocks the GitHub and LinkedIn audience, which is the point of the phase.
- **Anonymous Grafana. Rejected.** Even as Viewer, `/api/ds/query` accepts any query to AMP (and to CloudWatch locally, which bills per metric). That removes ADR 0024's "bounded by invitation only" cost bound (F13, X3).

**D3. What data is shown, and where credentials sit (Security, Operational Excellence)**

- **(a) Git only. Chosen (planner, within the owner's answer 1).** The snapshot is built from the run records and the 11.5 comparison record. The Phase 10 values are computed from the same run records (F6). The build needs no AWS identity, and the numbers match AMP by construction. A CI check proves they match.
- (b) Read AMP with `cerberus-grafana-read` on the owner's machine and commit the result. It gives the same numbers with an extra credentialed step. Rejected: it adds work and a credential path for no new data.
- In both cases, a fail-closed redaction gate runs at build time and again before the upload (section 5.2).

**D4. Refresh cadence (Operational Excellence, Cost)**

- **(a) On each merged run record, through the existing `console-site.yml`. Chosen.** Data changes only per exercise, a few times a month (ADR 0021 Context).
- (b) A daily job on the laptop. Rejected:
  - It would republish the same numbers.
  - It would need unattended use of the `cerberus-admin` static keys.
  - It fails when the laptop sleeps.
- This is how the "everyday" in the request is met: the page is always up, not restarted daily.

**D5. Abuse and DoS on the public page (Security, Cost)**

- (i) Accept with a CloudFront `Requests` alarm and Budgets. $0, but no hard cap.
- (ii) Pay-as-you-go WAF, at about $5 a month per web ACL plus $1 per rule (ADR 0026, from memory, U). Rejected: it breaks $0 idle.
- **(iii) The CloudFront Free flat-rate plan (ADR 0026 gap 1). Chosen: spike first (owner answer 3).**
  - It is $0, with WAF and a cost cap (X4, U).
  - It is outside Terraform, its web ACL cannot be removed while the plan is attached, and the distribution cannot be deleted until the plan is cancelled (ADR 0026).
  - Step 15.4 runs the spike and records adopt or not. The page is not announced until 15.4 is closed.
  - (i) is the fallback if the spike says no.

**D6. The Databricks column (positioning)**

- **(a) Side-by-side columns: "Cerberus" and "Databricks (partner engine)". Chosen (owner answer 4).**
  - Metrics: the 11.5 measured step only (same input; run time; cost per million events).
  - Scope and source are shown on screen: which step, which input, the date, "measured during the trial, not live", and the cost basis (run records against billing data).
  - The story text explains how the two fit together: Databricks reads Cerberus gold through the catalog with no copy.
- (b) A ranked or "winner" view. Rejected: it breaks the positioning.
- (c) A live Databricks connection. Rejected: the trial is cancelled in 11.6 (F11).

## 5. Recommendation and design

Option D, with D2(a), D3(a), D4(a), D5(iii) then (i), and D6(a).

The drivers are Security and Cost, as in ADR 0026. D needs no new resource, puts nothing on the home network and gives visitors no query surface. Reliability is a bonus: the page is up while the laptop is off.

### 5.1 Data contract: `observability/showcase/*.json`

The files are written by the 11.2a builder and committed. One file per concern, each with `schema_version: 1`, `generated_from` (repo-relative source paths and their git blob SHAs) and `generated_at` (UTC). There is no free text from records; values are numbers, fixed enums or allowlisted tokens.

- `runs.json`: one entry per run record. Fields:
  - `execution` (must match `cerberus_console.grammar._TOKEN`, else dropped).
  - `kind` (exercise | demo | rehearsal, from the file name).
  - `status` (allowlist).
  - `start`, `end` (UTC ISO).
  - `run_seconds`, `events_processed`, `events_per_second`.
  - `dq_passed`, `dq_errors`, `dq_warnings`.
  - `cost_usd`, `cost_usd_per_million_events`, `cost_estimated` (bool).
  - `steps`: a list of `{state, seconds}` for the four fixed state names in `console/cerberus_landing/runs.py` `STATES`.
- `status.json`: the values of the 13 named queries for the latest run (F8), computed from the run records with the same code path as `publish.py`. `newest_*_execution` is filtered through the grammar token.
- `slo.json`: the SLO results over the trailing 20 runs (`docs/slo.md`), computed from `runs.json`.
- `comparison.json` (only after 11.5):
  - `step` (fixed name), `input` (`run_id`, `events`), `measured_on` (date), `trial` (bool, true).
  - Per engine: `run_seconds`, `usd`, `usd_per_million_events`, `cost_source` (enum `run_record` | `databricks_billing`), `estimated` (bool).
  - `caveats`: a list of fixed caveat IDs that map to page text in `content.toml`.
  - Its source is the 11.5 record (section 8, answer 5).

### 5.2 Redaction gate (fail-closed)

- **At build time (no AWS):**
  - Every output string must match a field allowlist (enum or token pattern).
  - Any `arn:`, `s3://`, `amazonaws.com`, `cloudfront.net` or `@` in any value fails the build.
  - The ADR 0026 xfails at `test_sanitize.py` L81-89 become passing tests. The trigger fired (F9).
- **Before upload (CI, after the credentials are assumed):**
  - `console/publish_site.sh` gets one new check: read the account ID with `aws sts get-caller-identity` into a variable that is never echoed.
  - Then `grep -rF` it across the built site directory. Any hit stops the publish before any upload.
  - Exact match only, because of the F7 false positives. The value is never written to a file or a log.
- **On error:** a missing field, an unknown enum value or a parse error stops the build. Nothing is published, and the last good site stays live.

### 5.3 What 11.2a and 15.3 build (15.2 publishes with the 11.2a builder)

- **11.2a (moved from 15.2):** `cerberus_landing/showcase.py` (or a sibling package if the 9.4 rebuild restructures the builder), with these parts:
  - The builder above.
  - `make showcase-snapshot` to write and check the JSON.
  - A parity test: for the latest run, `status.json` values equal the 13 named-query results from `make status-e2e` (offline, Docker, no AWS). This extends the 10.2c job in `code-ci.yml`.
  - Redaction tests.
  - Add `observability/showcase/**` to `console-site.yml` paths.
- **15.3:** the interactive view on the 9.4 page. It has three parts:
  - A run explorer: pick a run, follow its stages with their real seconds, and see events, DQ and cost.
  - The 1M → 100M scale story.
  - The Cerberus | Databricks (partner engine) columns, with scope and source on screen.
  - Rules: data comes from same-origin `fetch` of the published JSON (allowed by `connect-src 'self'`). JS and CSS are same-origin files. Rendering uses `textContent` only. It has a plain-language layer, works on phones, and passes the a11y and CSP tests (`console/tests/test_landing_*`).
  - The "live Grafana" link shows only while `live.json` `ends` is in the future (ADR 0026 consequence 14).

## 6. ADR outline

**File:** `docs/adr/0027-public-showcase.md`, "# 27. Public showcase: a published metrics snapshot on the standing edge, with Databricks as a partner column". Date 2026-11-20. Shape: Nygard, as ADR 0024/0025, with no Pillars section.

### Status

Proposed (2026-11-20). It amends [ADR 0024](0024-demo-console.md) (a public, anonymous, static metrics view; see Amends). It records the [ADR 0026](0026-phase-9-well-architected-review.md) Security gap 1 trigger and ADR 0024's "invites go beyond a handful" trigger as fired by this phase. Plan: `docs/plans/2026-11-20-public-showcase.md`.

### Context

- The owner asked for a daily, public, laptop-hosted Cerberus for GitHub and LinkedIn viewers, gated on showing metrics and performance with Databricks as a column. The request is quoted in full.
- What exists: the public landing page and the invite-only terminal and Grafana (F4), the CI publish from git (F5), and the status values derived from run records (F6, F7, F8).
- What the laptop path would mean:
  - The credential facts F1 and F2.
  - "No public inbound port" and the Cloudflare Tunnel rejection (F13).
  - The vendor facts X1–X3.
  - Uptime tied to laptop sleep.
- The Databricks data is one measured step, fixed after 11.6 (F11). The positioning is "a partner engine".
- The tensions:
  - Reach against exposure: anonymous public access against invite-only.
  - Liveness against safety: a live Grafana UI against a published snapshot.
  - Cost against protection: no hard cap at $0 unless the flat-rate plan is adopted.

### Decision

1. **Serving.** A sanitised static snapshot on the existing standing edge (option D). No laptop-hosted public stack, no port-forward, no tunnel.
2. **Access.** The snapshot page is anonymous. The terminal and the live Grafana stay invite-only, as ADR 0024 decides.
3. **Data and credentials.** Git-only sources (run records, the 11.5 comparison record). The data contract is `observability/showcase/*.json` (section 5.1). There are no AWS credentials in the build, and none on any serving host. A parity test against the named query set (offline) proves the numbers match.
4. **Redaction.** Fail-closed at build and before upload (section 5.2). The ADR 0026 gap-7 xfails are closed.
5. **Refresh.** On each merged run record, through `console-site.yml`. No scheduled job.
6. **Abuse.** Run the $0 CloudFront Free flat-rate plan spike (ADR 0026 Security gap 1) before any public announcement, and adopt the plan or not on its result. In both cases, add a CloudFront `Requests` alarm on the existing topic after checking the live alarm count, and keep Budgets.
7. **Databricks column.** The 11.5 measured step only: same input, run time and cost per million events. Scope, source, date and "trial data, not live" are on screen. Shown side by side as a partner engine, never ranked. The record has these fields: `step`, `input` (`run_id`, `events`), `measured_on` and `trial`; per engine, `run_seconds`, `usd`, `usd_per_million_events`, `cost_source` (`run_record` or `databricks_billing`) and `estimated`; and `caveats` (fixed IDs).
8. **Rejected.**
   - A router port-forward: an inbound port on a home network, the home IP exposed, no TLS without a domain, and it breaks "No public inbound port".
   - Cloudflare Tunnel: it needs a domain on Cloudflare and a third vendor, which ADR 0024 already rejected.
   - Tailscale Funnel as the primary route: its bandwidth limits are not published, TLS ends on the laptop and uptime depends on the laptop. Its fallback shape is kept in the plan.
   - Anonymous Grafana: a Viewer can send any query through `/api/ds/query`, which removes ADR 0024's "bounded by invitation only" cost bound.
   - An AMP read path for the snapshot: the same numbers as the run records, plus a step that needs credentials.
   - A daily laptop job: it republishes unchanged numbers and needs the `cerberus-admin` static keys unattended.
   - Pay-as-you-go WAF: about $5 a month per web ACL plus $1 per rule (list price from memory, unverified), which breaks $0 idle.
   - A ranked view: it breaks the partner-engine positioning.
   - A live Databricks link: the trial is cancelled in 11.6.
9. **Amends.**
   - ADR 0024 gets a one-line Status note: "Amended by ADR 0027 (2026-11-20): a public, anonymous, static metrics and comparison view on the standing edge; the terminal and the live Grafana stay invite-only."
   - ADR 0024's Decision is not rewritten.
   - ADR 0026 is not amended: the trigger it set has fired, and this ADR acts on it.

### Consequences

- **Good:**
  - $0 idle, no new resource except one alarm.
  - Up 24/7, with no home exposure and no credentials on a serving host.
  - The numbers equal the alert and dashboard numbers by construction.
  - The redaction gaps close.
  - The Databricks column is honest about its scope.
- **Given up:**
  - No live Grafana UI for anonymous visitors.
  - The numbers change only per exercise.
  - The Databricks column is one step and fixed.
  - If the flat-rate plan is adopted, part of the edge is outside Terraform and blocks `standing-destroy` until it is cancelled.
  - Public traffic is bounded only by Budgets until 15.4 closes.
- **Risks:**
  - The gate is far: it needs the 9.4 rebuild, 10.6 and Phase 11.
  - The 11.5 record schema does not exist yet (F12).
- **Revisit if:**
  - A live public UI is wanted (then use the Funnel fallback shape with a new ADR).
  - A domain is acquired.
  - Phase 11 is redone with a longer-lived Databricks workspace.
  - Monthly CloudFront requests pass the free allowance.

## 7. Build steps (a new Phase 15)

### 7.1 Phases.md block (insert after the Phase 14 block)

```
## Phase 15 — Public showcase ⬜

_Added 2026-11-20. Numbered 15 so Phases 11–14 keep their numbers. It
runs after Phase 11 and before Phases 12 and 13. Starts when 9.4's
interactive page has shipped, 10.3 and 10.6 are checked (status series and
dashboard proven live), 11.2a-c are checked (the showcase builder and the
Databricks Free Edition images), and 11.5 has a recorded measured
comparison (same input, run time and cost per million events on both
engines), so the page can show Cerberus metrics and performance with
Databricks as a partner column. ADR 0027._

- [ ] 15.1 ADR: the public showcase (a sanitised static snapshot on the
      standing edge vs. a laptop-hosted stack; anonymous scope; data
      contract and redaction; refresh on each merged run record; edge abuse
      controls; the Databricks partner column)
- [ ] 15.2 Showcase publish: use the 11.2a builder; add the Databricks
      images (11.2c); published by `console-site.yml`
- [ ] 15.3 The showcase view on the 9.4 page: run explorer, scale story and
      the Cerberus | Databricks (partner engine) columns with scope and
      source on screen, plus a "Built in Databricks" section (exported
      AI/BI images and a short video, labelled "Built in Databricks AI/BI
      (Free Edition)" and "learning tier, not a production SLA"); same-origin
      JS, CSP unchanged, mobile and a11y tests
- [ ] 15.4 Public-edge protection, before any public link: the $0 CloudFront
      Free flat-rate plan spike (ADR 0026 gap 1), adopt or not; a CloudFront
      requests alarm; the account-ID check before upload
- [ ] 15.5 Links: README and the LinkedIn post point at the page; the live
      Grafana link shows only while `live.json` `ends` is in the future
- [ ] 15.6 Live check: from a clean browser and a phone through the GitHub
      and LinkedIn links; headers by curl; no account ID, ARN or S3 URI in
      the published files; Cost Explorer read after one month
- [ ] 15.7 Well-Architected pass + ADR
```

### 7.2 Steps and verification

1. **PR 1, docs (now, this branch; 15.1).**
   - Changes:
     - ADR 0027 Proposed and this plan.
     - The Phases.md block (7.1).
     - A one-line Status note on ADR 0024 (it reads "Proposed amendment …" until accepted, then the note in section 6).
     - `docs/plan.md`: a roadmap row `| 15 | Public showcase | A sanitised metrics snapshot on the standing edge (S3 + CloudFront), an interactive run explorer, a Databricks partner column from Phase 11 | _(CloudFront docs)_ | ⬜ Planned |`, and a `### Phase 15 — Public showcase` block after Phase 14 in the Phase 14 shape (Goal, Gap it closes, Why this skill set, Stack, The central decision, Out of scope, Done when, Artifact).
     - `README.md` Roadmap: `| 15 | Public showcase | Planned: ADR 0027 proposed | [0027](docs/adr/0027-public-showcase.md) |`.
     - A note on Phases.md 11.5 (section 8, answer 5).
   - Verify:
     - `git diff main -- . | grep -nE 'arn:|s3://|amazonaws\.com'` finds nothing new.
     - Every number traces to section 2.
     - The phase order text matches checkpoint "Next up" 3.
2. **Owner review and acceptance of ADR 0027.** No build before the entry gate.
3. **PR 2 (11.2a, moved from 15.2; no gate, git only).**
   - The builder, the four JSON files, the tests, the parity test in the `status-e2e` CI job, and the `console-site.yml` paths.
   - Verify:
     - `pytest console/tests` green, and the former xfails pass.
     - `make showcase-snapshot` is deterministic (twice gives the same bytes).
     - A planted `arn:aws:…` fixture fails the build.
     - CI `status-e2e` green.
4. **PR 3 (15.3).**
   - The view on the 9.4 page.
   - Verify:
     - `test_landing_csp.py` and `test_landing_a11y.py` green.
     - `make console-site-preview` on 127.0.0.1:8088 shows every number, and each traces to a JSON field.
     - The Databricks column shows scope, source, date and the trial note.
     - A phone-width check.
5. **PR 4 plus an owner step (15.4).**
   - PR (CI-applied, `dev-standing`):
     - A `cerberus-console-cloudfront-requests` alarm (AWS/CloudFront `Requests`, us-east-1, `DistributionId`, `Region=Global`; daily Sum above a threshold set in the PR, about 10× the 15.6 baseline).
     - The `publish_site.sh` account-ID check.
     - Read the live alarm count first (`describe-alarms`, now allowed after ADR 0026 PR 2).
   - Owner spike ($0):
     - Read the flat-rate plan's eligibility and terms in the console.
     - Record adopt or not in ADR 0027's build notes.
     - If adopted, add the cancel step to `console/README.md` "Emergency levers" and to the `standing-destroy` notes.
   - Verify:
     - The alarm is OK or INSUFFICIENT_DATA after apply.
     - A dry run of the publish with a planted account ID in a temporary file is refused before upload.
6. **PR 5 (15.5).**
   - README link, and the `ends` handling in the page.
   - Verify: a test with a past `ends` hides the link.
7. **Owner live check (15.6).**
   - Clean browser and phone through both links.
   - `curl -sI` shows CSP, HSTS, `nosniff` and `DENY`.
   - `aws s3 cp --recursive` the site to a temporary directory, then `grep -rF` the account ID (exact) and `arn:` and `s3://`: no hits.
   - One Cost Explorer read about a month after the post ($0.01).
8. **15.7.** The Well-Architected pass + ADR, next free number, milestone 15.

## 8. Owner answers

**Owner answers (2026-11-20)**, all as recommended:

1. The goal is the always-on public page on the existing CloudFront standing edge, as a published, sanitised snapshot (option D). No laptop-hosted stack, no port-forward, no tunnel. Live Grafana stays invite-only per ADR 0024.
2. Access: the anonymous snapshot page only. The terminal and live Grafana stay invite-only.
3. Run the $0 CloudFront Free flat-rate plan spike (ADR 0026 gap 1) before the LinkedIn post, recorded in 15.4.
4. The Databricks column is the 11.5 measured step only (same input; run time and cost per million events), with scope and source on screen. It is a partner engine and fixed trial data, not live.
5. Yes: Phases.md 11.5 gets a note now to write the comparison record in the ADR 0027 `comparison.json` fields.

## 9. Unverified items (to confirm in build)

- X1: Cloudflare Tunnel cost fine print (only matters for the rejected option).
- X2: Funnel bandwidth numbers (only matters for the fallback).
- X3: AMP plugin support in Grafana shared dashboards (only matters for the fallback).
- X4: the CloudFront free allowance and how usage above it is billed; flat-rate plan terms, eligibility and Terraform support. Checked in 15.4.
- X5: the live alarm count against the 10-alarm free tier. Checked in 15.4 before the new alarm.
- The exact CloudFront `Requests` dimensions for the alarm (`DistributionId`, `Region=Global`). Checked with `list-metrics` in 15.4.
- Whether the 9.4 rebuild keeps `cerberus_landing` as the builder. 11.2a adapts to it.

## 10. Owner steps

- Review and accept ADR 0027 (PR 1).
- After the gate, the 15.4 spike in the CloudFront console, and the decision to adopt or not.
- The 15.6 live check and the Cost Explorer read.
- Publish the LinkedIn post only after 15.4 is closed.

Sources:
- [Cloudflare Tunnel overview](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
- [Cloudflare: create a remote tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [Cloudflare Tunnel docs](https://developers.cloudflare.com/tunnel/)
- [Tailscale Funnel](https://tailscale.com/kb/1223/funnel)
- [Grafana anonymous authentication](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/anonymous-auth/)
- [Grafana externally shared dashboards](https://grafana.com/docs/grafana/latest/dashboards/share-dashboards-panels/shared-dashboards/)
- [CloudFront FAQs](https://aws.amazon.com/cloudfront/faqs/)
- [CloudFront flat-rate pricing plans](https://aws.amazon.com/blogs/networking-and-content-delivery/introducing-flat-rate-pricing-plans-with-no-overages/)
