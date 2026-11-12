# Plan: 9.4 build step 8b, publish the landing page to the standing edge

Date: 2026-11-09. Planner: Opus. Base: `origin/main` at `fe9fa26`.

**No new ADR, and no amendment to ADR 0024.** ADR 0024 already says that CI publishes the landing page into the site bucket. The plan for step 8 (`docs/plans/2026-11-06-landing-page.md` §4.2 P1, §6.6) chose the workflow shape. This plan only changes implementation details inside that scope. `live.json` stays owned by `envs/dev-console`, as ADR 0024 L107-112 says.

## 1. Question

How should CI publish `console/site-dist/` to the applied edge? Each merge that changes the page's inputs must update it. It must never delete `healthz.txt` or `live.json`, and it must cost $0 idle. Why now: #131 (builder) and #130 (edge, applied) are both on main, so 8b is the next unblocked step.

## 2. Facts

Repo (`origin/main` at `fe9fa26`):

- F1. The builder reads `content.toml`, `Phases.md`, the run records, `docs/img/scale/*.svg` and its own `*.py`. It also reads four console files: `CONSOLE_FILES = ("records.py", "sanitize.py", "grammar.py", "config.py")` (`console/cerberus_landing/build.py:21`, L192-195). The old plan's trigger list (§6.6) names only `records.py` and `sanitize.py`, so it is stale.
- F2. The output is `index.html`, `site.<10hex>.css`, `favicon.<10hex>.svg` and `img/<stem>.<10hex>.svg` (`build.py:136-137`, L161, L207-214). The 10-character hash is `sha256[:10]`. The page carries `<meta name="cerberus-build" content="$build_id">`, a 64-hex value (`page.py:45`, `build.py:196`). The CLI prints only the first 12 characters (`__main__.py`).
- F3. The three charts are on main under `docs/img/scale/`.
- F4. Makefile: `console-site` builds with `rm -rf site-dist` first (`Makefile:89-94`). `AWS_PROFILE ?= cerberus-admin` is exported (L11), and `TF_BIN ?= terraform` (L4).
- F5. The edge (`terraform/modules/console_edge/main.tf`):
  - Terraform manages only `healthz.txt` (L108-113, `content_type = "text/plain"`, no cache-control).
  - `default_root_object = "index.html"` (L197).
  - The default behaviour has `compress = true` and uses `Managed-CachingOptimized` (L225-227).
  - The response-headers policy sets the CSP (L149-162) and `content_type_options` (nosniff) (L170-172). With nosniff, a CSS file with the wrong Content-Type does not load.
  - There are no custom error responses.
  - The callback is `/terminal/index.html` (L32).
- F6. The outputs `console_url`, `console_distribution_id` and `console_site_bucket_name` exist (`terraform/envs/dev-standing/outputs.tf:126-139`).
- F7. The state backend is S3 plus a DynamoDB lock table (`terraform/envs/dev-standing/versions.tf:29-35`). The account ID already appears in plaintext in that public file. Masking the bucket name in logs only keeps the existing convention (`terraform-apply.yml:13-16`); it does not hide a secret.
- F8. `terraform-apply.yml`:
  - Triggers on `console/cerberus_console/**` and `observability/scale/runs/**`, among other paths (L17-48).
  - Has a guard that refuses any commit that is not main's head (L76-84).
  - Uses `concurrency: terraform-apply-dev-standing` with `cancel-in-progress: false` (L57-59).
  - Uses `secrets.AWS_CI_APPLY_ROLE_ARN` (L88).
  - Calls `setup-terraform@v3` with the default wrapper (L91).
- F9. `code-ci.yml` already covers `console/**` and `Phases.md` (L11-21) and runs `pytest console` (L66-79). New tests under `console/tests/` run on the PR.
- F10. IAM (`terraform/modules/github_oidc/main.tf`):
  - The `cerberus-ci-apply` trust policy accepts only this repo with `ref = refs/heads/main` (L83-105).
  - `TerraformState` grants `s3:GetObject`, `PutObject` and `ListBucket` on the state bucket (L179-183). `terraform init` and `output` need nothing more and take no lock.
  - `cerberus-ci-apply-console` grants `s3:*` on the site bucket and `/*` (L583-590), and `cloudfront:CreateInvalidation`, `GetInvalidation` and `ListInvalidations` on `distribution/*` (L662-670).
  - That policy is attached to `cerberus-ci-apply` (L732-735).

AWS (read-only, `cerberus-admin`, 2026-11-09):

- F11. The site bucket holds only `healthz.txt` (2 B). There is no `index.html` and no `live.json`.
- F12. The distribution ID is `E2LG44KXV5YFSB`. `DefaultRootObject = index.html`, cache policy `Managed-CachingOptimized` (MinTTL 1, DefaultTTL 86400, MaxTTL 31536000). `CustomErrorResponses.Quantity = 0`.
- F13. `curl -I`: `/` gives 403 (`x-cache: Error from cloudfront`), with the CSP and HSTS headers. `/healthz.txt` gives 200, `text/plain`. `/live.json` gives 403 (absent).
- F14. `simulate-principal-policy` on `cerberus-ci-apply`: `s3:PutObject`, `DeleteObject` and `GetObject` on `<site bucket>/index.html`, `s3:ListBucket` on the bucket, and `cloudfront:CreateInvalidation` and `GetInvalidation` on `distribution/E2LG44KXV5YFSB` are all allowed. No IAM change is needed.
- F15. `cerberus-admin` has the same object and invalidation actions (old plan F16, simulated 2026-11-06). This allows the local fallback.

External:

- F16. A wildcard invalidation path such as `/*` counts as one path. The first 1,000 paths a month are free, across all distributions in the account ([PayingForInvalidation](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/PayingForInvalidation.html)).
- F17. When the minimum TTL is above 0 and the origin sends `Cache-Control: no-cache`, CloudFront caches the object for the minimum TTL (1 s here) and browsers obey the header ([Expiration](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Expiration.html)).

### Deviations from the old plan §6.6

1. Trigger paths: add `grammar.py` and `config.py` (F1).
2. Remove the "edge not applied, skip" path. The edge is applied (F11-F13), so a missing output means something is broken and the job must fail.
3. Replace `aws s3 sync --delete --exclude healthz.txt --exclude live.json` with a delete that only touches keys the builder owns (an allowlist of key patterns, section 3). A denylist would delete 9.5's `terminal/…` and step 10's files unless someone remembered to extend it, and a `sync` pass can re-upload a file without the per-class headers.
4. Set Content-Type explicitly for each file class, because of nosniff (F5).
5. Invalidation `/*` and HTML `no-cache` are now verified (F16, F17).
6. The old "grep the `--delete` line" test is replaced by pytest on the stale-key function.

## 3. Decision

**Publish shape: S1, a separate `console-site.yml`** using `cerberus-ci-apply` and the Terraform outputs. Rejected: S2 (a job after the apply in `terraform-apply.yml`; a `Phases.md` edit would run a full apply) and S3 (`workflow_run` after the apply; publishes even when no site input changed and cannot see the changed paths). The page does not depend on the apply in steady state, and the two workflows write disjoint things (the Lambda zip versus bucket objects), so running in parallel is safe.

**Credentials:** `cerberus-ci-apply`, through the existing secret (F14). A dedicated least-privilege publish role is a 9.7 follow-up. IAM change: none. Root paste: none.

**Cache and invalidation:**

| Object | Content-Type | Cache-Control |
|---|---|---|
| `index.html` | `text/html; charset=utf-8` | `no-cache` (edge holds it 1 s, F17; browser revalidates with ETag) |
| `site.*.css` | `text/css; charset=utf-8` | `public, max-age=31536000, immutable` |
| `favicon.*.svg`, `img/*.svg` | `image/svg+xml` | `public, max-age=31536000, immutable` |
| `healthz.txt`, `live.json` | not touched | not touched |

Invalidate `/*` once per publish, after the uploads (1 path; F16). `/*` also clears the 403 cached today at `/` (F13).

**Stale delete:** delete only keys that match `^(site\.[0-9a-f]{10}\.css|favicon\.[0-9a-f]{10}\.svg|img/[a-z0-9-]+\.[0-9a-f]{10}\.svg)$` and are absent from the new build, after the invalidation completes. `index.html`, `healthz.txt`, `live.json` and anything under `terminal/` can never match.

## 4. Files (one PR, branch `9.4-landing-publish`)

1. `console/cerberus_landing/publish.py` (new, stdlib only, no `subprocess`): `MANAGED` regex; `local_keys(dir) -> set[str]` (posix relative paths); `stale_keys(local, remote) -> list[str]` (sorted; `k` only if `MANAGED.fullmatch(k)` and `k not in local`).
2. `console/cerberus_landing/__main__.py`: subcommand `stale --dir DIR`. Reads a JSON list of remote keys on stdin (`list-objects-v2 --query 'Contents[].Key' --output json`; `null` means empty) and prints one stale key per line. Exit 1 on bad input.
3. `console/publish_site.sh` (new, executable, `set -euo pipefail`). Usage: `publish_site.sh DIR BUCKET DIST_ID URL`. `--no-progress --only-show-errors` on every `aws s3` call; never echo the bucket. Steps:
   1. Check `DIR/index.html`; read the 64-hex `build_id` from its `cerberus-build` meta, or fail.
   2. Upload `site.*.css` with `text/css; charset=utf-8` and the immutable cache header.
   3. Upload `favicon.*.svg` and `img/*.svg` with `image/svg+xml` and the immutable cache header.
   4. Upload `index.html` with `text/html; charset=utf-8` and `no-cache`.
   5. Create an invalidation for `/*` and wait for `invalidation-completed`.
   6. List the bucket keys, pipe them to `python3 -m cerberus_landing stale --dir DIR` (with `PYTHONPATH` set to the script's directory), and `aws s3 rm` each printed key.
   7. Checks (any failure exits non-zero): `URL/` has a CSP header and `cache-control: no-cache`; `URL/` contains `content="$build_id"`; `URL/healthz.txt` returns 200; the CSS file named in `index.html` shows `immutable` and `content-type: text/css`; if `live.json` was listed before, `head-object` on it still succeeds. Print `published build <first 12 of build_id>`.
4. `.github/workflows/console-site.yml` (new): on push to main for `console/cerberus_landing/**`, the four console files, `Phases.md`, `observability/scale/runs/**`, `docs/img/scale/**`, `console/publish_site.sh` and the workflow itself, plus `workflow_dispatch`. `permissions: id-token: write, contents: read`; `concurrency: console-site-publish`, no cancel. Steps: checkout; the main-head guard copied from `terraform-apply.yml` L78-84; Python 3.12; build the site (no AWS); assume `secrets.AWS_CI_APPLY_ROLE_ARN`; `setup-terraform@v3` with `terraform_wrapper: false`; `terraform init -input=false -lockfile=readonly` and read the three outputs (mask the bucket) into `GITHUB_ENV`; run `console/publish_site.sh`. The build runs before credentials are assumed.
5. `Makefile`: `console-site-publish` (depends on `console-site`) as the owner fallback, reading the three outputs with `$(TF_BIN) -chdir=terraform/envs/dev-standing output -raw …` and calling `console/publish_site.sh`. Its help text says it is an AWS write that needs approval.
6. `console/tests/test_landing_publish.py` (new): every built file except `index.html` matches `MANAGED`; `stale_keys` never returns `healthz.txt`, `live.json`, `index.html`, `terminal/index.html` or `terminal/app.<hash>.js`; it returns old hashed CSS and SVG; it does not return the current build's assets; `stale` on `null` prints nothing and bad JSON exits 1; the script contains no `--delete` and no `sync`.
7. `console/README.md` "Landing page" section: a "Publish" paragraph (workflow, cache table, builder-owned delete rule, fallback target).
8. `docs/plans/2026-11-06-landing-page.md` §6.6: one line, "Superseded in detail by `docs/plans/2026-11-09-landing-page-publish.md` (deviations 1-6)".

No Terraform, IAM, `Phases.md` or ADR change in 8b.

## 5. PR split

- **PR 8b:** files 1-8. CI runs `code-ci`. Locally: `bash -n console/publish_site.sh`, `shellcheck` if available, `make console-site`, then `python -m cerberus_landing stale --dir site-dist <<< '["healthz.txt","live.json","site.0000000000.css"]'` prints only the CSS key.
- **Merging 8b starts the first publish automatically** (it touches `console/cerberus_landing/**` and the workflow). The user's "merge #N" is also the approval of that first AWS write. The PR body must say this.
- **PR 8c** (cross-links and records, old plan §7 step 3) comes after the live check passes and adds the Phases.md 9.4 note.

## 6. Verification after merge (read-only)

```
gh run watch "$(gh run list --workflow console-site.yml --limit 1 --json databaseId -q '.[0].databaseId')"
SITE=https://d1uxw5ox9pla18.cloudfront.net
curl -sI "$SITE/" | grep -iE '^(HTTP|content-security-policy|cache-control|content-type|x-cache|age)'   # 200, CSP, no-cache, text/html
curl -s "$SITE/" | grep -c '<script'                                                                  # 0
CSS=$(curl -s "$SITE/" | grep -o 'site\.[0-9a-f]\{10\}\.css' | head -1)
curl -sI "$SITE/$CSS" | grep -iE '^(cache-control|content-type)'                                      # immutable, text/css
curl -sI "$SITE/healthz.txt" | head -1                                                                 # 200
aws s3api list-objects-v2 --bucket <site bucket> --query 'Contents[].Key' --output text               # healthz.txt + 6 built files
aws cloudfront list-invalidations --distribution-id E2LG44KXV5YFSB --max-items 3                      # newest Completed
curl -s -o /dev/null -w '%{http_code}\n' "$SITE/terminal/index.html"                                  # 403 until 9.5
```

Then a private window in Firefox and Chrome, and a phone: no sign-in, no CSP errors, charts in colour. The `live.json` keep check happens at the first `envs/dev-console` session. A second-publish check (old hashed assets gone, `healthz.txt` kept) happens at the first content change.

## 7. Risks

1. Merge equals publish (section 5); the PR body says so.
2. Two merges close together: the older run fails at the head guard; the newer one publishes.
3. Cached old HTML and the delete: the delete runs after the invalidation completes, and the HTML lives 1 s at the edge. Negligible.
4. A PR that changes both the CSP and the page (9.5's `style-src`) can leave the page briefly under the old CSP. The 9.5 plan must order those changes.
5. Future root objects (step 10's `live.js`, 9.5's `terminal/`) are never deleted, but their own stale versions are not cleaned until their plans extend `MANAGED`.
6. `cerberus-ci-apply` is broad. The workflow runs only on main after review; a dedicated publish role is a 9.7 follow-up.
7. `terraform init` in the publish job adds about 30 s and needs the committed lock file.
8. Content-Type or charset problems under nosniff are caught by the step-7 CSS check and the post-merge SVG check.

## 8. Cost

Idle $0: no new resources; 6 small objects (about 50 KB) in S3. Per publish: about 6 PUT, 1 LIST and up to 6 DELETE requests, plus 1 invalidation path (free within 1,000 a month).
