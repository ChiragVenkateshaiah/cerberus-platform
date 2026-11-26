# Origin request count for Run D: a second meter at S3

Decision plan for ADR 0030 Decision 15 (amendment). Planned by the decision agent (Opus) on 2026-11-26.

## Owner answers (2026-11-26)

1. Root pastes the two extra IAM actions tonight with the rest of the launch policy. The ADR + IAM PR merges first.
2. Verdict threshold: 1.25 fetch-equivalents per cold chunk per POP.
3. Amend ADR 0030 in place as Decision 15 (still Proposed).

## 1. Question

Run D needs a second count of origin (S3) requests that does not come from CloudFront's own logs. Which source, in place before the IAM paste tonight (Thu 26 Nov) and Run A (Fri 27 Nov)?

## 2. Facts

- F1 (V) AWS documents how request collapsing is logged: "the first request is identified as a `Miss` in the `x-edge-result-type` field, and the collapsed requests are identified as a `Hit`". Collapsing applies only to requests that share a cache key ([request collapsing](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RequestAndResponseBehaviorCustomOrigin.html#request-custom-traffic-spikes)). `x-edge-detailed-result-type` has no collapse value; it differs from `x-edge-result-type` only for `OriginShieldHit`, `MissGeneratedResponse` and the error subtypes ([log reference](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logs-reference.html)).
- F2 (V) The logs are CloudFront reporting on itself. Delivery can be up to 24 h late (same page), and ADR 0030 already gives up "complete CDN logs" (Consequences). A Miss is a fetch from the edge to the next tier, not a proven S3 GET.
- F3 (U) Whether a regional edge cache sits between the POP and an S3 origin with OAC. If one does, S3 GETs can be lower than POP Misses.
- F4 (V) For range requests, "CloudFront might request a larger range than the client requested" ([range GETs](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RangeGETs.html)). (U) Whether CloudFront splits a 64 MiB full GET into several origin GETs. So the verdict counts bytes, not GETs.
- F5 (V) S3 request metrics (`GetRequests`, `BytesDownloaded`, 1-minute) support a prefix filter. They are "delivered on a best-effort basis… not meant to be a complete accounting", and a data point "might be delayed… or not delivered at all" ([S3 metrics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/metrics-dimensions.html)).
- F6 (V) S3 server access log records hold the bucket owner's canonical ID, the remote IP, and the requester, which can be an ARN with an account ID ([log format](https://docs.aws.amazon.com/AmazonS3/latest/userguide/LogFormat.html)).
- F7 (repo) Run D is `launch/scenarios/d.json`: d-cold is 50 clients on `patch2` (8 chunks, `launch/scenarios/sets.json`), then d-warm is 1 client. `chunk_bytes` = 67,108,864. Both `patch` (Run C) and `patch2` sit under the `patch/` prefix of the build bucket (OAC policy on `patch/*`).
- F8 (repo) `iam/cerberus-admin/policies/cerberus-admin-launch.json` (Sid `LaunchBuckets`) has no `s3:PutMetricsConfiguration`/`s3:GetMetricsConfiguration`. `cloudwatch:GetMetricStatistics` on `*` already exists in `cerberus-admin-orchestration.json`; `launch/plan_bytes.py` uses it.
- F9 (repo) Bucket names hold the account ID (`cerberus-platform-launch-<account>`). The metric dimension `BucketName` stays out of every file.

## 3. Constraints

Ceiling $40, stop $25 attributable (Decision 12). Nothing idle; stage 2 leaves nothing (Decision 2). Agents never apply; the owner applies `dev-launch`. A merge under `terraform/modules/**` triggers a CI dev-standing apply that fails until the owner's local apply (known, harmless). No account IDs or ARNs in files (Decision 10). New IAM actions pass a Service Authorization check, `simulate-custom-policy` and an `escalate: opus-security` review (Decision 14). Decision 3 stays: no Origin Shield.

## 4. Options

- **A. Logs only, plus the AWS doc.** $0. Gives up independence; "Miss = S3 GET" stays an assumption (F2, F3).
- **B. S3 request metrics on `patch/` (chosen).** One `aws_s3_bucket_metric` filter, prefix `patch/`. `results_pull` reads `GetRequests` and `BytesDownloaded` (Sum, 60 s) per sub-run window. Under $0.50 (unverified). Counts only, no new privacy surface. Gives up per-key detail and complete counts (F5).
- **C. B plus S3 server access logs.** Strongest per-chunk proof, but a new parser, a new privacy filter (F6), a bucket-policy statement and two more IAM actions; best-effort delivery of hours. Too much risk for Saturday.
- **D. CloudTrail S3 data events.** New trail, new IAM, ARNs and account IDs in every record, a new resource type for `launch-check`. Rejected.

## 5. Decision

Choose B. Logs (A) stay as the second meter. C moves to "Revisit if".

The verdict rule (bytes, because of F4):

- `F` = S3 `BytesDownloaded` for `patch/` over [d-cold start floored to the minute, d-warm end + 3 min] ÷ `chunk_bytes`. Including d-warm is conservative.
- `P` = distinct `x-edge-location` in d-cold, from the logs; 1 if no lines arrived.
- Quiet guard: S3 `BytesDownloaded` for `patch/` must be 0 in the 3 minutes before d-cold; otherwise `AMBIGUOUS` (Run C shares the prefix).
- `INCONCLUSIVE` if `F < 0.95 × 8` (meter lost data).
- `PASS` if `F / (8 × P) ≤ 1.25`.
- `FAIL` otherwise.
- Agreement (shown, not gating): S3 `GetRequests` ≤ log Misses × 1.05 + 1. S3 may be lower (F3); S3 higher than the logs is a finding about the logs.
- Headline: collapse factor = viewer cold requests (k6, 400) ÷ `F`.

Why 1.25: with 8 chunks one retried fetch gives 1.125, so 1.05 fails on a single retry; 1.25 is still 40× below the no-collapse value of 50.

## 6. ADR outline (edit 0030 in place)

- Status: "Amended 2026-11-26 (Decision 15), still Proposed."
- Context: F1, F2, F4, F5 with links; F3 under Unverified.
- Changes from the launch plan: "Run D has two meters: CloudFront logs and S3 request metrics."
- Decision 15, Origin meter: one S3 metrics configuration `cerberus-launch-patch` (prefix `patch/`) on the build bucket, created and destroyed with it; the verdict rule from section 5 word for word; the bucket name never written to a file; PASS/FAIL/INCONCLUSIVE/AMBIGUOUS labels.
- Decision 14 amendment: `LaunchBuckets` gains `s3:PutMetricsConfiguration` and `s3:GetMetricsConfiguration`, checked against the Service Authorization reference. (U) `DeleteBucketMetricsConfiguration` maps to `s3:PutMetricsConfiguration`.
- Decision 2: `launch-check` needs no new type; the config has no life outside the bucket.
- Consequences: Good — the collapse claim rests on two meters on opposite sides of the CDN. Given up — per-key origin proof. Costs — under $0.50 (unverified). Revisit if — an edge becomes standing: add S3 server access logs with an allowlist filter.
- Unverified: F3; F4 split behaviour; metric start delay after creation; the metric cost.

## 7. Build steps (one PR each, in order)

1. **ADR + IAM (today, before the paste).** ADR 0030 edit; `cerberus-admin-launch.json` (2 actions); simulate list in `iam/cerberus-admin/README.md`. Verify `jq`, minified size < 6,144 characters, `simulate-custom-policy` on `arn:aws:s3:::cerberus-platform-launch-*`, `escalate: opus-security`.
2. **Terraform.** `aws_s3_bucket_metric "patch"` in `terraform/modules/launch_edge/main.tf`, filter `prefix = "patch/"`; output the filter name only. `fmt`/`validate`; owner's `make launch-plan` shows 1 to add.
3. **results_pull.** `pull_origin(cw, windows, bucket, filter_id)` writes `origin_subrun.csv` (run_id, sub_run, s3_get_requests, s3_bytes, fetch_equivalents, quiet_before, pops, verdict). Bucket name from Terraform output at run time, never written. `launch/queries/cdn_pops.sql` for `P`. Tests: PASS (F=8), FAIL (F=400), INCONCLUSIVE (F=6), AMBIGUOUS, multi-POP (P=2, F=16 passes), no 12-digit value or bucket name in output.
4. **results_render.** "Two meters" table and the story line "400 downloads, the origin paid for 8."
5. **Runbook + article.** Run A: confirm `GetRequests` > 0 for `patch/` within 15 min of a fetch. Saturday: no `patch/` fetch in the 3 min before d-cold. Sunday: pull metrics before stage 2. Article placeholder for the verdict line.

Steps 1 and 2 must be applied before the Saturday PREWARM; step 1 merges before tonight's paste. Steps 3–5 can merge after Run A.

## 8. Risks

- Paste missed tonight: a second paste before Fri noon IST, or Saturday falls back to A.
- Metrics late or missing: INCONCLUSIVE; the article uses A plus the F1 citation.
- Metric start delay (U): the 4 h PREWARM covers it; Run A checks it.
- Several POPs: `P` handles it.
- A regional tier (F3): write "CloudFront (edge and any regional tier) collapsed".
- Run C traffic in the window: the quiet guard.
