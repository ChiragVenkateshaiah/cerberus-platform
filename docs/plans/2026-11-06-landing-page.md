# Plan: 9.4 the landing page (ADR 0024, demo-console plan section 7, build step 8)

Date: 2026-11-06. Planner: Opus. Base: `main` at `bcbf804`.

User decisions (2026-11-06):
- Sequencing: 8a is stacked on #128 (`9.3-command-set`) and reuses its `records` and `sanitize`, so the page and `cerberus run latest` always agree. It merges after the 8.10 take.
- Accepted: `noindex` on the console page (GitHub Pages stays the indexed front door); the Phase 9 heading moves to 🔨 In progress; the #130 callback becomes `/terminal/index.html` before its first apply (T1).
- The user's aim: the video and the page must look professional. Section 6.7 adds a design bar for that.
- A custom domain (for example `console.<name>.ca`) would look more professional than the CloudFront URL. It needs a domain, a certificate and Route 53, so it is a separate, later decision (a new ADR if chosen). Not in this step.
- Plan confirmed.

**No new ADR is needed.** ADR 0024 already decides a public static landing page in the S3 site bucket, published by CI with a sync and an invalidation (Decision table, "Sign-in and sessions", build step 8). The standing-edge plan (on #129) left two details to 9.4: the `/terminal/` sub-path (risk 11) and the `healthz.txt` exclude (risk 12). This plan settles both inside that scope.

**8.10 gate.** No part of this step touches AWS, `dev-compute`, the local Grafana, or any file the 8.10 take reads. Everything here is stacked on #128 or waits for #130's apply, so nothing in step 8 merges before the take (section 7).

## 1. Question

How do we build and publish the public landing page? It must show the architecture, phase status, the latest run and the scale charts. It must pass the edge CSP (no inline script or style), work on a phone, and cost $0 idle. It must also be useful to a non-engineer.

Why now: step 7 (#130) is written and waits only for the 8.10 gate. Step 8 is next. The build and its tests need no AWS, so they can be written and reviewed now and published after #130's apply.

## 2. Facts

Repo:

- F1. ADR 0024 makes the landing page "public on purpose" (L193). It is served from the S3 site bucket through CloudFront with OAC (L86-87). Its "latest run" comes from the run records (L138-139). Build step 8 is "The landing page" (L276). The plan's step 8 adds "a CI publish step (sync plus invalidation). Cross-links with the GitHub Pages site. Verify: a clean browser loads it with no sign-in. The CSP header is present." (`docs/plans/2026-10-27-demo-console.md` L285-286).
- F2. Phases.md 9.4 reads "The UI outline: a landing page (architecture, phase status, the latest run), Grafana and Prometheus panels, a terminal panel" (L171-172). Step 10 of the demo-console plan maps to "9.2 and 9.4" (L289). So 9.4 closes with step 10, not step 8.
- F3. Phases.md phase headings have the form `## Phase N — Title <status>`, where the status is ✅, 🔨 or ⬜, and Phase 1 also carries 🎯 (L32-224). Subtasks are `- [x] N.M ...` or `- [ ] N.M ...`, with 6-space continuation lines. The continuation lines mix the title with progress notes (for example 9.2, L161-167), so a subtask's full title cannot be parsed reliably. Phase 8 has 9 of 11 checked; Phase 9 has 0 of 7 and is still marked ⬜, although 9.2 has progress notes.
- F4. The standing edge (#130, branch `9.2-standing-edge`, `terraform/modules/console_edge/main.tf`; not applied):
  - The CSP is `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' <cognito>; form-action 'self' <cognito>; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; upgrade-insecure-requests` (L149-162). The response-headers policy is on the default behaviour (L218-227).
  - The default behaviour uses `Managed-CachingOptimized` with `compress = true` (L222-226), and `default_root_object = "index.html"` (L197).
  - `callback_url` is `https://<cf domain>/terminal/` (L32).
  - Terraform manages only `healthz.txt` in the bucket (L43, L108-110).
  - The outputs for 9.4 are `console_site_bucket_name`, `console_distribution_id` and `console_url` (standing-edge plan, Files 3).
- F5. Standing-edge plan risk 11: `/terminal/` returns 403 because `default_root_object` covers only `/`. Risk 12: the publish must exclude `healthz.txt`. Risk 13: xterm.js needs a `style-src` change in 9.5. (`git show origin/9.2-standing-edge-adr:docs/plans/2026-11-02-standing-edge.md`, section 11.)
- F6. ADR 0024 per-session root: `envs/dev-console` writes `live.json`, the live Grafana link the landing page shows (L107-108; plan L188). A publish with `--delete` would delete it during a session.
- F7. The run records: there are 14 files in `observability/scale/runs/`. The fields used here are `execution`, `status`, `start`, `run_seconds`, `events_processed`, `states[].state` and `.seconds`, `cost.run_usd`, `cost.usd_per_million_events`, `cost.estimated`, `cost.complete` and `data_quality.passed` (read with `jq`). The newest by `start` is `exercise-20261015T145812Z`: SUCCEEDED, 1,005,920 events, 581.2 s, $0.2928 per million events, estimated. The largest SUCCEEDED run is `exercise-20261013T055859Z`: 100,008,511 events, 742.0 s, $0.0037 per million events. There is no 8.10 record yet.
- F8. #128 (`9.3-command-set`, draft, gated) adds `console/cerberus_console/records.py`:
  - `load()` returns records sorted newest first by `(start, execution)`. A file that does not parse is skipped and counted. Helpers `dig`, `number` and `text` do typed reads.
  - `sanitize.py` strips control characters.
  - A hostile fixture, `console/tests/fixtures/runs/hostile-20990101T000000Z.json`, has an OSC 52 escape in a state name.
  - `console/ruff.toml` adds the `S` rules and bans `subprocess`. CI's `console-tests` job runs `pytest console`. `code-ci.yml` gains the `console/**` path.
- F9. The charts are not on main. They are on #107 (`phase-8-10-results`), with the generator `observability/scale/charts.py`:
  - `docs/img/scale/cost-per-million-events.svg` (3,486 B), `run-time-per-state.svg` (6,809 B) and `transform-throughput.svg` (5,278 B).
  - Each has `role="img"`, an `aria-label` and a `<title>`. Each also has an internal `<style>` element with a `prefers-color-scheme: dark` block, and no script or external link (grep).
- F10. There is no architecture image in git (`git ls-files` finds no svg, png, jpg or gif). The README diagram is Mermaid (L162-213) and describes "the target end-state, not current state". It still shows "CI/CD - Phase 5 / AWS CodePipeline", which ADR 0011 replaced with GitHub Actions.
- F11. GitHub Pages: `docs/pages/index.html` (95 lines, inline `<style>`) is deployed by `.github/workflows/dbt-docs.yml`, together with `/dbt/` and `/lineage/`. That workflow assembles the site in a directory named `site/` and uploads the whole of `site/` (L60-66, L103-107). A committed `site/` directory would therefore leak into the Pages artifact. The public URL is `https://chiragvenkateshaiah.github.io/cerberus-platform/` (README L54, L349-352).
- F12. CI patterns:
  - `terraform-apply.yml` runs only on push to main, uses `secrets.AWS_CI_APPLY_ROLE_ARN`, refuses a commit that is not main's head, and uses `concurrency` with `cancel-in-progress: false`.
  - The role ARN is a Secret so that the account ID stays out of plaintext logs (L12-15).
  - `code-ci.yml` is PR-only. Its paths include `observability/**` but not `Phases.md`.
- F13. `terraform/modules/github_oidc/main.tf`, policy `cerberus-ci-apply-console`:
  - Sid `ManageConsoleSiteBucket`: `s3:*` on the site bucket and `/*` (L583-589).
  - Sid `CloudFrontReadTagInvalidate`: `cloudfront:CreateInvalidation`, `GetInvalidation` and `ListInvalidations` on `distribution/*` (L662-669).
  - There are no CloudFront Function actions; `CloudFrontEdgePolicies` covers only OAC, response-headers, origin-request and cache policies (L683-691).
- F14. `pyproject.toml`: ruff line length 100, target py312. `requirements-dev.txt` has ruff 0.16.4 and pytest 9.1.1. Python 3.12 has `tomllib`, `string.Template`, `html` and `html.parser`, so the build needs no new dependency.

AWS (read-only, `cerberus-admin`, us-east-1, 2026-11-06):

- F15. `cerberus-ci-apply` has `cerberus-ci-apply-console` attached (v1, 2026-10-27). `simulate-principal-policy` gives:
  - Allowed: `s3:PutObject` and `s3:DeleteObject` on `<site bucket>/*`, `s3:ListBucket` on the bucket, and `cloudfront:CreateInvalidation` on `distribution/*`.
  - `s3:PutObject` on the gold bucket also returned allowed, from the existing broad apply grants, not from the console policy. The console grant does not need it.
  - `cerberus-ci-plan`: `s3:PutObject` on the site bucket and `CreateInvalidation` are both `implicitDeny`.
- F16. `cerberus-admin` is allowed `s3:PutObject`, `DeleteObject`, `GetObject` and `ListBucket` on the site bucket, and `cloudfront:CreateInvalidation`, `GetInvalidation` and `ListInvalidations` (simulated). A local publish is therefore possible as a fallback.

External (read 2026-11-06):

- F17. CloudFront pay-as-you-go: the first 1,000 invalidation paths a month are free, then $0.005 per path. CloudFront Functions cost $0.10 per million invocations. The always-free tier is 1 TB out, 10,000,000 HTTP/HTTPS requests and 2,000,000 function invocations a month ([pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/)). That page does not say how a wildcard path is counted. The developer guide says it counts as one path, but this was not read today, so it is **unverified**.
- F18. An SVG with an internal `<style>`, loaded through `<img>` on a page with `style-src 'self'`: Firefox bug 1410730 (the page's CSP turned the logo black) was closed as a duplicate of a fixed bug ([1410730](https://bugzilla.mozilla.org/show_bug.cgi?id=1410730)). There is no authoritative statement about a CSP header on the SVG response itself. Behaviour in current Chrome and Firefox is **unverified** (risk 1).
- S3 Standard list prices used in section 9: $0.005 per 1,000 PUT or LIST, $0.0004 per 1,000 GET, $0.023 per GB-month. These are **not rechecked today**.

## 3. Constraints

- $0 idle. The page is static objects in the existing bucket. Nothing new runs.
- `dev-compute` is untouched. Nothing here changes the take's inputs or the local Grafana. Nothing merges before the 8.10 take (section 7).
- CI applies `dev-standing` only. The publish is not an apply. It writes objects into a `dev-standing` resource, using grants the accepted IAM plan made for that purpose (F13). ADR 0011 is not contradicted.
- The edge CSP (F4) is fixed by #130:
  - no inline `<script>`, no `<style>` element, no `style=` attribute, no `on*=` handler;
  - all assets same-origin (no CDN, no web fonts);
  - `upgrade-insecure-requests`.
- Public repo: no account ID in new files or CI logs, no emails, no secrets. The bucket name contains the account ID, so it comes from Terraform state at run time and is masked.
- Repo tooling: `uvx ruff@0.16.4`, `TMPDIR=$HOME/.cache/tfspiketmp` for terraform, and the `console/ruff.toml` `S` rules.
- Audience: non-engineers and hiring managers. A plain-language layer sits over every technical number. Each number is real and sourced, and estimates are labelled. Databricks is shown as a partner engine (Phase 11, planned), not a rival.

## 4. Options

### 4.1 The build

| | A. Stdlib Python builder (recommended, chosen) | B. Static-site tool (MkDocs Material, Hugo) | C. Hand-written HTML | D. JS page that fetches JSON |
|---|---|---|---|---|
| What | `python -m cerberus_landing build`: `string.Template`, `html.escape`, `tomllib`, and #128's `records` and `sanitize` | A theme renders Markdown | Static files edited by hand | Builder emits `records.json`; JS renders it |
| New dependencies | None | pip or binary, plus theme | None | None, but JS |
| CSP fit | Full control; zero JS | Themes ship inline scripts, styles and Google Fonts by default (from memory, **unverified**); needs overrides | Full | Needs `script-src 'self'` only, but more surface |
| Drift | Phases, runs and charts are read at build time | Same if templated | Latest run and phases go stale | None |
| Gives up | About 400 lines of our own code | Fighting the theme against the CSP | Truth | Zero-JS, a no-JS reader, and simple tests |

The pillars that decide this:

- **Security:** a page with no JavaScript at all has the smallest CSP surface. It also leaves `script-src 'self'` for 9.5's terminal page only.
- **Operational Excellence:** one source of truth for "latest run", shared with the terminal's `run latest` (ADR 0024: "One Python package").
- **Cost:** no build service and no new dependency.

### 4.2 The publish

| | P1. Separate workflow, `cerberus-ci-apply`, Terraform outputs (recommended, chosen) | P2. Job in `terraform-apply.yml` | P3. New dedicated publish role | P4. Manual `make` only |
|---|---|---|---|---|
| Trigger | Push to main on site inputs, plus dispatch | Every apply path | As P1 | Owner |
| Effect | Site changes publish without a Terraform apply | Each `Phases.md` edit would run an apply and the Faker churn | Least privilege | No CI; fails ADR 0024 step 8 |
| IAM change | None (F15) | None | New role, local apply and root paste | None |
| Gives up | Uses a broad write role for a narrow task | Couples content to infrastructure | Effort and a new identity | Automation |

P3 is the cleaner long-term shape (Security pillar). It goes to the 9.7 Well-Architected pass as a follow-up, not into this step.

### 4.3 The `/terminal/` sub-path (risk 11)

| | T1. Callback `/terminal/index.html` (recommended, chosen) | T2. CloudFront Function rewriting `*/` to `*/index.html` | T3. Flat `/terminal.html` |
|---|---|---|---|
| Change | One line in #130 before its first apply (`local.callback_url`); all links use `terminal/index.html` | New function; `cloudfront:CreateFunction`, `PublishFunction` and similar in **both** `cerberus-admin-console-edge` (root paste) and `cerberus-ci-apply-console` (local apply) | Same as T1 |
| Cost | $0 | $0 idle; $0.10 per million after 2M free (F17) | $0 |
| Gives up | A typed `/terminal/` returns S3's 403 XML | Two IAM edits and one more runtime piece on the hot path | Each page's assets cannot sit next to it in a folder |

## 5. Recommendation

**A + P1 + T1.**

- **A.** A zero-JavaScript page built by a stdlib builder. It reuses #128's `records.load()` order and `sanitize`, so the landing page's "latest run" and `cerberus run latest` always agree. No record text reaches the HTML: state names come from a fixed list, status from an allowlist, and numbers are formatted by the builder. The page passes `script-src 'self'` with nothing to allow.
- **P1.** A separate `console-site.yml`, so content updates never run Terraform. It reads the bucket and distribution from `terraform output` (state is the single source; no names in the repo; the bucket name is masked). It uses `cerberus-ci-apply`, which already has exactly the needed grants (F15).
- **T1.** Change one line in #130 while it is still unapplied, so no in-place client update is needed later. T2 costs two IAM edits for a prettier URL.

Cache headers:

- HTML: `Cache-Control: no-cache`. With `CachingOptimized` (min TTL 1 s), CloudFront then holds HTML for at most the minimum TTL. This follows CloudFront's rule for `no-cache` with min TTL above 0, as recalled, so it is **unverified**. The verify step reads `x-cache` and `age`.
- CSS, SVG and favicon: content-hashed names (`site.<sha256[:10]>.css`) with `public, max-age=31536000, immutable`.
- Invalidate `/*` once per publish.

## 6. Design (what the executor builds)

### 6.1 Layout (under `console/`, so the `S` rules and `pytest console` apply; not `site/`, F11)

- `console/cerberus_landing/__init__.py`, `__main__.py` (`build --out DIR [--runs-dir] [--phases] [--charts-dir]`), `build.py`, `phases.py`, `runs.py`, `page.py`.
- `console/cerberus_landing/content.toml`: the plain-language text. It holds the hero, section intros, one sentence per phase (0-13), and chart captions without numbers.
- `console/cerberus_landing/static/site.css`, `favicon.svg`.
- `console/cerberus_landing/architecture.svg`: hand-drawn and inlined by the builder.
- `console/cerberus_landing/serve.py`: a local preview server bound to `127.0.0.1`. It sends the edge CSP on every response, without `upgrade-insecure-requests`, which would break plain HTTP locally. It uses `http.server` and no network.
- `console/tests/test_landing_build.py`, `test_landing_csp.py`, `test_landing_phases.py`, `test_landing_runs.py`, `test_landing_a11y.py`.
- Output `console/site-dist/` (gitignored).

### 6.2 Content and story (one page, `index.html`; section order)

1. **Hero:** "Cerberus: a payments data platform on AWS, built and run by one engineer." Two plain sentences on what it does (synthetic payments, raw to clean to business tables, answers in SQL). Then "It costs $0 when nobody is using it", citing ADR 0024 and the phase docs.
2. **How the data moves:** the inline architecture SVG, plus a five-step plain list: collect, keep the raw copy, clean at scale, model for the business, answer questions. Each step names its tool in a second line (Lambda and EventBridge Scheduler; S3 bronze; Spark on EKS per exercise; dbt on ECS Fargate with Iceberg in Glue; Athena). Add "watched by" (Prometheus to AMP, Grafana, CloudWatch) and "Open tables that other engines, such as Databricks, can read through the catalog (Phase 11, planned)".
   - Sources the executor cites in the SVG `<desc>`: ADR 0005, 0009, 0011, 0016, 0017, 0019, 0022 and 0024.
   - The diagram shows current state only. It does not copy the stale Mermaid (F10).
3. **The latest run:** from `records.load().records[0]`, as a card:
   - date in UTC, written out with a fixed English month list;
   - "processed N payment events in M min S s";
   - "cost $X per million events (estimated)", using `cost.estimated`; if `cost.complete` is false, "cost not final yet";
   - "data checks passed", "failed" or "not run";
   - a table of the four states (`InvokeIngestion`, `RunTransform`, `RunDbt`, `RunServingQuery`) with seconds and a plain label ("load", "clean with Spark", "build business tables", "answer a test query").
   - A second card, **the largest run**: the SUCCEEDED record with the most `events_processed`.
   - Both cards link to the record file on GitHub.
4. **How it scales:** the three charts as `<img src="img/<name>.<hash>.svg" width height alt=...>`. `alt` comes from each SVG's `<title>`. Each has a plain caption and a link to `docs/scale-metrics.md` on GitHub for the numbers. If `docs/img/scale/` is missing (before #107 merges), the section reads "Charts arrive with the Phase 8 results write-up" and the build still passes.
5. **Build progress:** one row per phase from `Phases.md`: number, title, status word (Complete, In progress, Planned) and "k of n steps done". The `content.toml` sentence explains the phase. For phases in progress, "Still open: 8.10, 8.11" (numbers only, F3) and a link to `Phases.md`. 8.10 shows as open: this is honest status.
6. **Live dashboards:** static in 9.4. The text says Grafana dashboards open during scheduled demos, with a link to ADR 0022's story-dashboard description on GitHub. Step 10 adds `live.js` (an external file) that reads `/live.json`.
7. **Try the terminal:** the text says invited visitors can run read-only commands such as `status`, `runs` and `cost`, and the link arrives with 9.5. **There is no sign-in link in 9.4**: the hosted UI with PKCE needs JavaScript to make the code verifier, so a static link cannot start it. In 9.5 this becomes `<a href="terminal/index.html">Sign in to the terminal</a>`, controlled by one constant in `page.py`.
8. **Footer:**
   - links to the repo, GitHub Pages (`/`, `/dbt/`, `/lineage/`), ADRs and `Phases.md`;
   - "This page uses no cookies, no trackers and no JavaScript";
   - `<meta name="cerberus-build" content="<sha256 of inputs>">` for the publish check.
   - `<meta name="robots" content="noindex">` (user decision). The public, indexed front door stays GitHub Pages.

### 6.3 Determinism

- Walk files in sorted order. Use UTF-8 and `\n`.
- No timestamps, no "N days ago", no environment-dependent locale.
- The build id is a SHA-256 over the input bytes and the builder files.
- Hashed asset names come from the content.

### 6.4 CSP and safety rules (enforced by tests, section 8)

- No `<script>`, `<style>`, `style=`, `on*=` or `javascript:` anywhere in the HTML or the inlined SVG.
- Every `src` and `<link href>` is relative (no scheme, no `//`).
- External `<a href>` only to `https://github.com/ChiragVenkateshaiah/cerberus-platform...` and `https://chiragvenkateshaiah.github.io/cerberus-platform/...`.
- Copied chart SVGs: no `<script>`, no `on*`, no `href`/`xlink:href` to anything. An internal `<style>` is allowed there (risk 1).
- Record data: `execution` must match #128's grammar token pattern, or the card links nowhere. `status` must be in an allowlist, or it shows "unknown". Strings pass through `sanitize` and then `html.escape`.

### 6.5 Accessibility and phone width

- `<html lang="en">`, viewport meta, a skip link, landmarks (`header`, `nav`, `main`, `footer`), one `h1` and no skipped heading levels.
- Tables have a `<caption>` and `scope` on headers, and sit in a `div` with `tabindex="0"` and `overflow-x: auto`.
- Images: `max-width: 100%; height: auto` and real `width`/`height` attributes (no layout shift). The inline SVG has `role="img"`, `<title>` and `<desc>`. The text list next to it repeats the diagram.
- System font stack. `color-scheme: light dark` and a `prefers-color-scheme` block reuse the chart palette from `charts.py`. Body text meets WCAG AA contrast. Status is never shown by colour alone; it always has a word.
- One column below 40rem; tap targets of at least 44 px.

### 6.6 Publish (`.github/workflows/console-site.yml` and `console/publish_site.sh`)

- Triggers: `push` to main on these paths, plus `workflow_dispatch`:
  - `console/cerberus_landing/**`
  - `console/cerberus_console/records.py`
  - `console/cerberus_console/sanitize.py`
  - `Phases.md`
  - `observability/scale/runs/**`
  - `docs/img/scale/**`
  - `console/publish_site.sh`
  - the workflow file itself
- `concurrency: console-site`, `cancel-in-progress: false`. Use the head-of-main guard from `terraform-apply.yml`.
- Steps:
  1. Check out the repo and set up Python 3.12.
  2. Run `cd console && python -m cerberus_landing build --out site-dist`.
  3. `aws-actions/configure-aws-credentials@v4` with `secrets.AWS_CI_APPLY_ROLE_ARN`.
  4. `hashicorp/setup-terraform@v3` with **`terraform_wrapper: false`**, so that `output -raw` capture is clean.
  5. `terraform -chdir=terraform/envs/dev-standing init -input=false`.
  6. Read `console_site_bucket_name`, `console_distribution_id` and `console_url`. If `console_site_bucket_name` is missing, print `::notice::console edge not applied yet; skipping publish` and exit 0. Otherwise `echo "::add-mask::$BUCKET"`.
  7. Run `console/publish_site.sh site-dist "$BUCKET" "$DIST" "$URL"`.
- `publish_site.sh` (`set -euo pipefail`, `--no-progress --only-show-errors` on each call) runs in this order:
  1. `aws s3 sync DIR s3://B --exclude '*.html' --cache-control 'public, max-age=31536000, immutable'`. Assets go first, with no delete.
  2. `aws s3 sync DIR s3://B --exclude '*' --include '*.html' --cache-control 'no-cache'`.
  3. `aws cloudfront create-invalidation --distribution-id D --paths '/*'`, then `aws cloudfront wait invalidation-completed`.
  4. `aws s3 sync DIR s3://B --delete --exclude healthz.txt --exclude live.json`. This removes stale hashed assets last, so an old cached page never points at a deleted file.
  5. Check: `curl -sI URL/` shows 200 and a `content-security-policy` header. `curl -s URL/` contains the build id. `curl -sI URL/healthz.txt` shows 200.
- The script is also the owner's fallback (`make console-site-publish`), run only with approval.

### 6.7 Professional design bar (user decision)

The page appears in the LinkedIn video and is shared with hiring managers, so it must look finished, not like a developer default page.

- A small, consistent design system in `site.css` only: CSS custom properties for a restrained palette (one accent colour, neutral greys, the chart palette from `charts.py` for data), a type scale (system font stack, about 1.0625 rem body, clear h1/h2/h3 steps, comfortable line height about 1.6), and a spacing scale (multiples of 0.25 rem).
- Layout: a centred content column (max about 72 rem for wide sections, about 42 rem for reading text), generous whitespace, cards with a subtle border and radius for the run cards, and key numbers set large (for example "100,008,511 events", "$0.0037 per million events") with a plain label underneath.
- Tone: confident and plain. No jargon in headings; the technical names sit in the second line or a table.
- Both light and dark mode are designed and checked, not only inherited.
- The verify step adds a design check: screenshots at 1440 px, 1080 px wide (the video's portrait width) and 360 px (phone), in light and dark mode, reviewed by the user before the PR leaves draft. No horizontal scroll, no orphaned single words in headings where avoidable, and every number lined up.
- After the 8.10 take: optional run-story screenshots for section 6 (step 4 in section 7).

## 7. Build steps (one PR each)

0. **Amend #130 before its first apply (risk 11, T1).** On `9.2-standing-edge`, set `callback_url = ".../terminal/index.html"` (`console_edge/main.tf` L32). In the standing-edge plan (#129), mark risk 11 "resolved by the 9.4 plan: T1". This applies nothing.
   - Verify: `terraform fmt -check`; the module's `callback_url` local ends in `/terminal/index.html`.
   - Phases.md: none.
1. **8a. The builder, content and tests** (branch `9.4-landing-page`, **stacked on `9.3-command-set`** (#128), because it imports `records` and `sanitize`).
   - Files: section 6.1. Add `.gitignore` `console/site-dist/`. Add `Makefile` targets `console-site` and `console-site-preview`. Add `Phases.md` to `code-ci.yml` paths, so a Phases.md-only PR runs the parser tests before main publishes.
   - Flip the Phase 9 heading to 🔨 and `docs/plan.md`'s roadmap row 9 to "🔨 In progress" (user decision).
   - Verify:
     - `uvx ruff@0.16.4 check console && uvx ruff@0.16.4 format --check console`
     - `cd console && uv run --no-project --python 3.12 --with pytest==9.1.1 pytest -q` passes.
     - `make console-site` twice into two directories, then `diff -r`, gives no difference.
     - `make console-site-preview`, then open `http://127.0.0.1:8088/` in Firefox and Chrome. DevTools Console shows **no CSP violation**, and the charts render in colour in light and dark mode (risk 1). Responsive mode at 360 px shows no horizontal page scroll.
     - The design check in 6.7 (screenshots for the user).
     - Chrome Lighthouse Accessibility is at least 95 (no new dependency).
     - Output total is under 150 KB.
   - Merges after #128.
2. **8b. The publish workflow** (`console-site.yml`, `publish_site.sh`, `make console-site-publish`), stacked on 8a.
   - Verify on the PR: `actionlint` is not in the repo, so review by reading; `bash -n console/publish_site.sh`; a test greps the script for both `--exclude healthz.txt` and `--exclude live.json` on the `--delete` line.
   - Merge after #130's CI apply. If it merges earlier, the skip path keeps main green.
   - Live verify: A1-A2 in section 11.
3. **8c. Cross-links and records.**
   - Add a "Demo console" card to `docs/pages/index.html` with the CloudFront URL, and a README Documentation line.
   - Demo-console plan step 8: a progress note. `Phases.md` 9.4: "Landing page live YYYY-MM-DD (#PR); Grafana and terminal panels follow in 9.5 and step 10".
   - Verify: the Pages deploy (`dbt-docs.yml`) is green, and both sites link each other from a clean browser.
4. **Optional, after the 8.10 take:** one or two PNG screenshots of the run-story dashboard on the take's window, for section 6 of the page (under 200 KB each), so a visitor sees Grafana without a session. This is content only.

PR dependencies: #128 → 8a → 8b; #130 (with step 0) → apply → 8b's first publish → 8c. **Nothing merges before the 8.10 take**: 8a is stacked on gated #128, and 8b and 8c need #130's apply. Nothing in step 8 is needed by the take. The take's new run record will republish the page automatically once 8b is live.

## 8. Tests in CI (no AWS; run by `console-tests`, `pytest console`)

- **Determinism:** two builds give byte-identical trees; asset names match the content hash.
- **CSP scan** (`html.parser`) over every `.html` file and the inlined SVG, with the rules in 6.4. A negative test feeds a fixture page with each banned pattern and expects a failure for each.
- **Links:** every relative `href` or `src` resolves to a file in the output. Every `#id` resolves. External links are in the allowlist.
- **Phases:** the real `Phases.md` parses to phases 0-13. A ✅ phase has all subtasks checked. Status is in the known set. `content.toml` has exactly one sentence per parsed phase. Synthetic bad headings and items raise errors (fail loudly, not silently).
- **Runs:**
  - The latest run equals `records.load().records[0]["execution"]` for the real directory.
  - With #128's fixtures, the hostile record's text never appears raw: no `\x1b`, no `<` from data.
  - An empty runs directory gives "no runs recorded yet".
  - A record with `cost.complete: false` shows "not final".
- **Charts:** present gives three `<img>` with non-empty `alt`; absent gives the placeholder text.
- **Accessibility basics:** `lang`, viewport, one `h1`, heading order, `alt` on every image, `<title>` on every inline SVG, `<caption>` on every table.

## 9. Cost

- **Idle: $0** (estimate, not a bill reading). About 50 KB in S3 Standard, which is about $0.000001 a month. No new resource.
- **Per publish:** about 12 PUT and 3 LIST requests, about $0.00008 (S3 list price, not rechecked today), plus one invalidation path. That path is free within 1,000 paths a month (F17); if a wildcard were billed per file it would be about 12 paths, still free. GitHub Actions minutes are free for a public repo.
- **Per visitor:** inside CloudFront's always-free 10M requests and 1 TB (F17). S3 GETs only on cache misses, at $0.0004 per 1,000.
- No CloudFront Function (T1), so there is no function cost.

## 10. Open questions for the user

Answered 2026-11-06; see User decisions at the top.

## 11. AWS commands for the user to approve (all after #130's local and CI apply and 8b's merge)

A1. The first publish. A CI write, so it needs approval:
```
gh workflow run console-site.yml --ref main
gh run watch "$(gh run list --workflow console-site.yml --limit 1 --json databaseId -q '.[0].databaseId')"
```
A2. Read-only checks (local, `AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1`):
```
O() { TMPDIR=$HOME/.cache/tfspiketmp terraform -chdir=terraform/envs/dev-standing output -raw "$1"; }
SITE=$(O console_url); DIST=$(O console_distribution_id)
curl -sI "$SITE/" | grep -iE '^(HTTP|content-security-policy|cache-control|x-cache|age)'   # 200, CSP, no-cache
curl -s "$SITE/" | grep -c '<script'                                                       # 0
curl -sI "$SITE/healthz.txt" | head -1                                                      # 200 (not deleted)
curl -s "$SITE/" | grep -o 'site\.[0-9a-f]*\.css' | head -1 | xargs -I{} curl -sI "$SITE/{}" | grep -i cache-control   # immutable
curl -s -o /dev/null -w '%{http_code}\n' "$SITE/terminal/index.html"                        # 403 until 9.5 (expected)
aws cloudfront list-invalidations --distribution-id "$DIST" --max-items 3 --query 'InvalidationList.Items[].[Id,Status,CreateTime]' --output text
```
Then open `$SITE` in a private window in Firefox and Chrome, and on a phone. Expect no sign-in, no Console CSP errors, and charts in colour.

A3. **Only if A1 fails on permissions:** `make console-site-publish` as `cerberus-admin` (F16). This is a write, so it needs approval.

## 12. Risks

1. **Chart `<style>` under the CSP** (F18, unverified). The local preview sends the same CSP on the SVG responses, so 8a's verify reproduces this before AWS. Fallback: the builder inlines the charts without `<style>`. `charts.py` (#107) then emits prefixed classes (`cx-ink`), and `site.css` carries the rules. A visitor who opens a chart URL directly gets the SVG as a document under the CSP and may see it without colour. This is minor; the images are not wrapped in links.
2. **`--delete` removes Terraform's or a session's object.** Both `healthz.txt` and `live.json` are excluded, and a test checks this.
3. **`setup-terraform`'s wrapper corrupts `output -raw`.** Set `terraform_wrapper: false`.
4. **The account ID in CI logs.** The bucket is masked, the sync runs with `--only-show-errors`, and no ARN is echoed.
5. **The architecture SVG drifts from reality.** It is hand-drawn, its sources are cited in `<desc>`, and the reviewer checks it against the ADRs. Each phase PR that changes the shape should touch it.
6. **`Phases.md` format changes break the parser.** 8a adds `Phases.md` to `code-ci` paths, so the failure shows on the PR, not on main's publish.
7. **The take's record arrives incomplete** (cost is collected later). The card says "not final" until the follow-up record update republishes.
8. **A typed `/terminal/` or a wrong path returns S3's 403 XML.** Accepted. A `custom_error_response` would also rewrite the API's 401 and 403 through `/api/*`, so do not add one.
9. **`cerberus-ci-apply` is broader than the publish needs.** The 9.7 follow-up is a dedicated publish role (P3).
10. **The CloudFront URL looks raw in the video and in shared links.** Mitigation now: the video and posts link the GitHub Pages site, which links the console. Later option: a custom domain (a separate decision).

Sources: [CloudFront pay-as-you-go pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/), [CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/), [Mozilla bug 1410730](https://bugzilla.mozilla.org/show_bug.cgi?id=1410730), [Mozilla bug 1637954](https://bugzilla.mozilla.org/show_bug.cgi?id=1637954), [Mozilla bug 1494356](https://bugzilla.mozilla.org/show_bug.cgi?id=1494356), [Mozilla bug 1459872](https://bugzilla.mozilla.org/show_bug.cgi?id=1459872).
