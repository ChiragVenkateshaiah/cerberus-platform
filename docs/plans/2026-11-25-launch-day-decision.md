# Plan: ADR 0030, launch day (decision for 17.1)

Date: 2026-11-25. Mode 1. Scope: §3, §4 and §6 of `docs/plans/2026-11-25-launch-day.md` (the "launch plan"). Read against branch `plan-launch-day`. Timeline, $40 ceiling, $25 stop and the Phase 9 pause are settled.

## 1. Question

Which delivery edge, event envelope and cost controls does Phase 17 use, and which accepted ADRs change? It is needed now: 17.2 and 17.3 start Thursday, and one root paste of IAM must precede the first apply.

**Records to write now: one, ADR 0030.** It amends three ADRs by name (0011, 0018, 0017 scope note); each gets one Status line, no new text. No other ADR is needed:

| ADR | Verdict |
|---|---|
| 0002 medallion | No change. New bronze prefixes follow its one-prefix-per-dataset rule |
| 0003 data model | No change. It stays the payments model; the envelope covers `downloads` only |
| 0011 CI | **Amended**: a fourth root, `dev-launch`, human-run (0024 recorded the third the same way) |
| 0017 Iceberg | **Extended**: `cerberus-spark` Glue and silver scope gains `download_events`; same watermark method |
| 0018 bulk bronze | **Amended**: it says nothing outside `payments_bulk/` gains write or delete. `downloads_bulk/` now does |
| 0024 console | No change. Its session lifecycle is reused, its resources are not touched |
| Budget | Dated exception inside 0030; it ends 2026-11-30 |

Splitting edge and envelope into two ADRs was considered. They share one phase, claim and expiry, so one is enough. 17.10 stays after the weekend.

## 2. Facts

V = verified, U = unverified.

**Blocking findings**

- D1 (V). "Load testing isn't allowed on origins that have Origin Shield enabled", nor on behaviours with Lambda@Edge viewer triggers. AWS recommends several regions, independent DNS per client, and use of all returned IPs. ([load-testing](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/load-testing.html)) The page has no notice form or rate. CloudFront Functions are not named in the ban. (U2 closed.)
- D2 (V). Origin Shield is skipped when the regional edge cache is in the Shield Region. us-east-1 requests show `Hit`, not `OriginShieldHit`. ([origin-shield](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/origin-shield.html)) Run D could show little from one us-east-1 client even if allowed.
- D3 (V). Logs usually arrive within an hour, can be up to 24 h late, and are "reliably" delivered only **about four hours after enabling**. ([reference](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logs-reference.html)) A 120-minute session with a 20-minute poll cannot depend on them.
- D4 (V). v2 to S3 has no delivery charge (Parquet output does) and is configured in us-east-1. Fields are selectable. Without a destination prefix, the S3 path contains the account ID. ([standard-logging](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging.html)) (U1 closed.)
- D5 (V, live, read-only). November Cost Explorer: Usage **$10.90**, Credit **-$10.90**, net ~$0. An unfiltered $25 rule would never fire. The account budget is $20 and reports $10.895 actual, so it shows the uncredited figure.
- D6 (V, live). Only `Project` is an active cost-allocation tag in the part of the list read; `Stack` activation is U. Tags cannot isolate Phase 17.
- D7 (V, repo). `cerberus-admin` is scoped (`iam/cerberus-admin/policies/`). It has 8 of 10 policy slots used. The `console-edge` file fails to save (#187).

**Supporting**

- D8 (V). Free tier per month: 1 TB out, 10M requests, 2M Function invocations, **2M KVS reads**. ([pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/)) It is always free, and tracked per account ([free tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/tracking-free-tier-usage.html)); exact account-pooling wording is U. Treat the console edge as sharing it. Its November use is about 1.5 MB and ~220 requests (D5 query), so the effect is nil. No discount for EC2 viewers was found (U): assume EC2 downloads count.
- D9 (V). Instances under 32 vCPUs get at most 5 Gbps through an internet gateway ([EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html)); small sizes have a lower baseline.
- D10 (V). EC2 testing policy names traffic shaping above 25 Gbps and bans DDoS-style tests ([policy](https://aws.amazon.com/ec2/testing/)). We stay below both.
- D11 (V). The VPC is in **dev-standing**, not `dev-compute` (`envs/dev-standing/main.tf` L38), with public subnets and an internet gateway. (U3 closed: use `public_subnet_a_id`; no new VPC, no NAT.)
- D12 (V). Glue has one database, `cerberus_platform`; `silver.download_events` is not a valid name here. The dbt role's silver access is `iceberg/payments_events/*` and its DDL is prefix-scoped (`modules/iam/main.tf` L44–45, L423–431).
- D13 (V). `PriceClass_200` includes India. ([CDK enum](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_cloudfront.PriceClass.html)) No supported viewer option to choose an edge was found (U): the POP follows DNS and routing.
- D14 (V). Phase 13.1 is itself an ADR. 13.5 says silver "covers the streaming prefix"; it does not say "generalise" (`Phases.md` L313–318).

**Byte arithmetic (decimal GB).** The plan mixes GiB and GB.

| Run | Plan | Recalculated |
|---|---|---|
| A | ~5 | 4.8 |
| B 50 × 4 GiB | ~200 | 214.7 (3,200 requests) |
| C 50 × 0.5 + 20 × 4 GiB | ~105 | 112.7 |
| D 100 × 0.5 GiB | ~50 | 53.7 if a full patch is 64 MiB chunks: 800 requests, not ~6k |
| P | ~2 | ~2 |
| Total | ~360 | **388** with D as planned |

Session `bcd` = 381 GB, under the 400 GB guard but close. The replacement D (§5) halves D to 26.8 GB: `bcd` = 354 GB, total = 361 GB. A full re-run is then about 722 GB in November: it fits 1 TB. Two licence runs reach 2M Function and KVS reads exactly; overrun costs cents. Run B averages about 0.95 Gbps; licence load is 1,667 requests/s.

**Controls.**

- CloudFront publishes one-minute metrics, minutes late. At 5 Gbps the link moves 37.5 GB/min, so 10 minutes of lag is 375 GB. A 450 GB alarm above a 400 GB guard is notification, not control.
- An email does not stop anything. A per-session SNS email subscription needs confirmation every session.
- Uncontrolled worst case: 120 min × 5 Gbps = 4.5 TB, about **$300** at $0.085/GB. The launch plan's "bounded by the guard" is true only if the guard also acts at run time.

**Cost.** $8–15 is plausible. Two additions:

- 100M events at the ADR 0018 size of ~450 bytes is 45 GB, about $1.04/month Standard and $0.56 in IA. The envelope makes it larger (U). It persists after Sunday.
- At $25 attributable, account usage is near $36. That fits a $40 account alert only if nothing else spends.

742 s (launch plan §4) is the 100M state machine, not the generator or a windowed two-pass job (`docs/scale-metrics.md` L495). Do not cite it as proof for either.

## 3. Constraints

- $0 idle outside sessions; `dev-launch` follows destroy-leaves-nothing. Bronze, silver and gold data are the deliberate exception.
- CI applies `dev-standing` only. `terraform-apply.yml` already runs in that directory only; 17.3 must not add `dev-launch` or `launch_edge` paths to it.
- `cerberus-admin` cannot change its own policies; root must paste.
- No account ID, home IP or key in git, published data or state.
- Never cut: byte guard, EXIT-trap destroy, `launch-check`, honesty rules.

## 4. Options

| | A. Launch plan as written | B. Corrected per-session edge | C. Telemetry only |
|---|---|---|---|
| Edge | Shield, `PriceClass_All` | No Shield, `PriceClass_200` | None |
| Source | One EC2 + laptop | Same | None |
| Key | Private key in SSM, read by instance | Ephemeral key on owner machine; instance gets expiring cookies | — |
| Evidence | CDN logs | k6 first, CDN logs second | Synthetic only |
| Byte stop | Pre-check + email | Four layers (§5) | — |
| Idle / phase cost | $0 / $8–15 | $0 / $8–15 | $0 / $4–8 |
| Effort | Highest | About the same; no Shield A/B | Lowest |
| Gives up | Breaks AWS rules (D1) | Shield comparison | Half of the phase |

Multi-region generators were rejected: more IAM and VPC work than the weekend allows. Flat-rate Free was rejected: 100 GB cap (launch plan F9), and its Functions/KVS limits were not checked. WAF was rejected, see §6.

## 5. Recommendation

**Option B.** It keeps the story, obeys D1, and makes cost and key exposure bounded rather than watched. C is the fallback if root IAM is not pasted by Friday noon IST.

**Disagreements with the launch plan, for the ADR to record**

- **§4 Origin Shield: remove it. §5 17.7, §9: remove every Shield claim.** Run D becomes "cold patch, 50 clients at T0, then a warm repeat by 1 client": measure origin requests through request collapsing. Only the cold half is bulk (26.8 GB plus 0.5).
- **§4 "TTFB by edge POP": rename.** One source reaches the POPs near Ashburn, one laptop the Indian POP it is given. Report "TTFB by source (us-east-1 EC2, Bengaluru laptop)" with the observed `x-edge-location` codes. Hit ratio is "single-metro, 50 virtual clients", not global, and is flattered by one warm location. State that the test does not follow AWS's multi-region advice, so it is not a CloudFront performance assessment. Client TTFB (k6) and server `time-to-first-byte` (logs) are different numbers; never mix them.
- **§4 Probe P: remove "vs a US-edge hostname" (D13).** Compare the two sources instead.
- **§4 `PriceClass_All` → `PriceClass_200`.** Same Indian edge, fewer costly regions.
- **§4 private key → never in AWS.** `launch-session` generates an RSA-2048 pair in `$XDG_RUNTIME_DIR` (tmpfs). Terraform gets the public PEM only, as a string variable with a default so `launch-destroy` works after a crash. The script mints one custom-policy cookie set (expires at session end, this distribution only) and puts it in an SSM SecureString outside Terraform. The EXIT trap deletes key and parameter. The instance role reads that one parameter, so a compromised instance can only download until expiry. The owner's Thursday key step disappears.
- **§4 `/license*`: require the key group too.** This limits public invocation. That signature checks run before the Function is U; prove it in Run A (no cookie: 403 and no invocation).
- **§4 KVS:** `release_at` is written by Terraform at apply (now + offset); the scenario reads its schedule from it. No runtime KVS write.
- **§4 logging:** plain/JSON, not Parquet. Deselect `c-ip`, `x-forwarded-for`, `c-port`, `cs(Cookie)`, `cs(Referer)`, `cs(User-Agent)`; the laptop probe would otherwise put a home IP into append-only bronze. Set a destination prefix. The default is: k6 outputs are the primary evidence, logs enrich.
- **§4 destroy: two stages.** Stage 1 (EXIT trap, always): terminate instance, delete cookie parameter and key. Stage 2: destroy the rest. `HOLD=1` (owner choice, Saturday only) keeps the edge and log bucket up to 24 h between stages at about $0, with a printed deadline; `launch-check` stays red until stage 2. Create the Saturday edge about four hours before the run (`PREWARM=1`, no instance). `cdn_logs_complete` compares log lines with k6 counts; below 99% the CDN marts are labelled partial. The DQ check "logs present for every run" becomes a warning.
- **§4, §6 byte control: four layers.**
  1. `plan_bytes.py` refuses a session over 400 GB **and** a month-to-date CloudFront total plus session over 900 GB. The total is a ledger of earlier runs plus CloudWatch `BytesDownloaded`.
  2. k6 uses fixed iterations, not duration, so bytes are exact by design.
  3. An `nftables` quota drops instance ingress above budget + 5%. This is the hard stop for the instance.
  4. `session.sh` polls `BytesDownloaded` each minute and destroys above budget.

  Plus cookie expiry and `MINUTES`. Drop the per-session alarm and SNS, or keep the alarm without an action.
- **§6 $25 rule: define it.** Attributable = November `Usage` record type (credits excluded, all services) minus the total through 2026-11-24, taken before Run A. Add a ledger estimate for the last 48 h: instance hours, node hours, GB over the free tier, at list price. `launch-session` and `launch-exercise` refuse when reported + estimate + next-run estimate exceeds $25. Cost Explorer is the confirmation (Mon/Tue), not the trigger. This over-counts, which is the safe side.
- **§4 U3 and silver name:** D11, D12. Table is `cerberus_platform.download_events` under `silver/iceberg/download_events/`.
- **§4 envelope "Phase 13 adopts it for every family": soften (D14).** 0030 binds `downloads` only. It is the input to the 13.1 ADR. "13.5 retires the debt" needs 13.5 reworded.

## 6. ADR outline

**ADR 0030, "Launch day: a second event family and a per-session delivery edge".** Status `Proposed`. Amends 0011 and 0018, extends 0017; budget exception.

**Context.** The event and claim rules (launch plan §3). D1–D3, D5, D7. Tensions: honesty against spectacle; cost against throughput; least privilege against a weekend.

**Decision**

1. *Claim.* Model, not replica. Scale ratio on every chart. Our peak is one-region; 33.03 Tbps is a total exchange peak, not GTA traffic. Synthetic names only.
2. *Lifecycle.* `dev-launch`: partial backend, human-run, two-stage destroy, `launch-check` = 0 over distribution, Function, KVS, public key, key group, cache policy, OAC, log source/destination/delivery, instance and volumes, SG, instance profile, role, SSM parameter, buckets, state. `Project` + `Stack=dev-launch` tags; key groups and public keys cannot be tagged, so the check matches the `cerberus-launch-` name prefix. KVS, Function and key group delete after the distribution; delete duration is U, so allow 30 min. Buckets use `force_destroy`.
3. *Edge.* Pay-as-you-go, `PriceClass_200`, no Shield, OAC, immutable content-addressed chunks, no query/cookie/header in the cache key.
4. *Entitlement and unlock.* Ephemeral key, expiring cookies, Function + KVS.
5. *WAF.* None. A web ACL adds about $5/month prorated (U) and a rate rule would block our single source. Compensation: every behaviour signed, short life, byte controls. Revisit if an edge becomes standing.
6. *Load generator.* One Spot instance; dev-standing public subnet; public IPv4, no ingress; egress 443 plus DNS; IMDSv2; pinned k6; per-client DNS (`ttl=0`, random select); below 5 Gbps. Role: one SSM parameter, seed writes to the build bucket, Session Manager.
7. *Envelope (downloads v1).* The seven launch-plan fields. `event_id`: UUIDv7 **bit layout**, 48-bit `occurred_at` ms and 74 bits from SHA-256 of (run_id, client_id, event_type, sequence). Say "v7 layout": it carries event time and is not random. Same arguments give the same IDs; a different `run_id` gives different ones, so dedup works within a run and the generator must not run twice under two IDs for one dataset. `ingested_at` is the run-timestamp argument. `schema_version` starts at 1.
8. *Payments untouched.* Key stays (`transaction_id`, `event_type`).
9. *Separate silver job.* Accepted debt; owner is 13.5.
10. *Bronze.* `downloads_bulk/` JSON Lines with `_manifest.json` written last (0018 amendment); `downloads_cdn/` written by `collect.sh`, append-only. `cerberus-spark` gains read/write/delete on `downloads_bulk/*` only.
11. *Gold.* Name every mart `fct_*`, for example `fct_isp_minute` and not `agg_*`: the dbt role is already allowed `fct_*`. Silver read for dbt gains `iceberg/download_events/*` and the bronze CDN table, via dev-standing (CI).
12. *Cost.* Exception to 2026-11-30; ceiling, stop rule and byte controls as §5. `make` refuses, the owner decides.

**Consequences.** Good: bounded bytes; no standing key; reusable second family; the first real per-session edge with a byte budget. Given up: Shield evidence, multi-region load, complete CDN logs. Costs: a ninth admin policy; a wider bronze delete; about $0.6–1.3/month storage until a retention decision; duplicate silver code. Revisit: standing edge, 13.1, two-pass job over 10M.

## 7. Build steps

1. **17.1** (today): executor writes 0030 and the three Status lines; Opus review; owner accepts. Verify: `make verify`.
2. **17.3a IAM, Thursday first, the critical path.** Executor adds `iam/cerberus-admin/policies/cerberus-admin-launch.json` (**a new file, ninth slot**; do not edit `console-edge`, which cannot be saved). Validate every action against the Service Authorization JSON **before** the paste, plus `simulate-custom-policy`; `escalate: opus-security`. Root pastes and attaches; detach after 17.9. The missing actions:
   - **CloudFront, new:** `Create/Get/GetConfig/Update/Delete/List` for `PublicKey` and `KeyGroup` (not taggable and no resource type, so `*`); `CreateFunction`, `DescribeFunction`, `GetFunction`, `UpdateFunction`, `PublishFunction`, `TestFunction`, `DeleteFunction`, `ListFunctions` (`function/cerberus-launch-*`; Create and List on `*`); `Create/Describe/Update/Delete/ListKeyValueStores` forms (`key-value-store/*`); `TagResource`, `UntagResource` and `ListTagsForResource` on both types; `AllowVendedLogDeliveryForResource` on `distribution/*`. Action names are singular as in the Service Reference, for example `GetPublicKeyConfig`.
   - **KVS data plane:** `cloudfront-keyvaluestore:DescribeKeyValueStore`, `GetKey`, `ListKeys`, `PutKey`, `DeleteKey`, `UpdateKeys`.
   - **Logs v2:** `logs:PutDeliverySource`, `GetDeliverySource`, `DeleteDeliverySource`, `PutDeliveryDestination`, `GetDeliveryDestination`, `DeleteDeliveryDestination`, `GetDeliveryDestinationPolicy`, `PutDeliveryDestinationPolicy`, `DeleteDeliveryDestinationPolicy`, `CreateDelivery`, `GetDelivery`, `DeleteDelivery`, `UpdateDeliveryConfiguration`, `DescribeDeliveries`, `DescribeDeliverySources`, `DescribeDeliveryDestinations`, `DescribeConfigurationTemplates`; add `logs:TagResource` and `ListTagsForResource` on the delivery ARNs. The existing `CreateLogDelivery` grant is the older API.
   - **S3:** bucket and object actions including `PutBucketPolicy`, `GetBucketPolicy`, `DeleteBucketPolicy` on `cerberus-platform-launch-*`. The storage policy covers six named buckets and has no bucket-policy writes.
   - **SSM:** `PutParameter`, `GetParameter`, `DeleteParameter`, `AddTagsToResource` on `parameter/cerberus/launch/*`; `DescribeParameters` and `DescribeInstanceInformation` on `*`. `StartSession` is already tag-scoped.
   - **IAM:** instance-profile actions on `cerberus-launch-*`; `PassRole` on `role/cerberus-launch-*` to `ec2.amazonaws.com`. Both existing grants cover `cerberus-console-grafana*` only.
   - **EC2:** `CancelSpotInstanceRequests` and `DescribeSpotInstanceRequests` (provider need is U). `RunInstances`, tag-scoped terminate, SG create/egress and `Describe*` exist. The Spot service-linked role may need creating (`CreateServiceLinkedRole` exists).
   - **Free tier:** `freetier:GetFreeTierUsage`, optional.
   - Verify: `aws iam simulate-principal-policy` for each row.
3. **17.2** generator and tests, parallel; needs no IAM. **17.5** adds `iam_spark` grants (owner applies `dev-compute`) and dbt/Glue changes in dev-standing (CI). `cerberus-ci-apply` has `glue:*` on the database and inline role-policy rights, so no CI grant is expected; confirm with the plan job. Do not touch the CI role's own policy.
4. **17.3b** Terraform: `launch-plan`, fmt, tfsec; CI path filters unchanged.
5. **17.4** session tooling, byte layers, spend ledger, two-stage destroy. Test: shellcheck; dry run prints 354 GB for `bcd`; unit tests refuse 401 GB and a 901 GB month; nft quota tested with a small quota in Run A.
6. **17.6 smoke (Friday):** cookie accepted/refused, pre-/post-release licence, Function-before-signature check, log arrival time, delete duration, `launch-check` = 0. Go/no-go for Saturday.
7. **Saturday:** prewarm, B, C, D, P; stage 1; telemetry exercise; hold if needed; stage 2 by Sunday noon.
8. **17.9:** cost read with the §5 definition, on Monday and again Tuesday; detach the policy; restore the alert to $20. **17.10** unchanged; also reword 13.5 and decide bronze retention.

## 8. Open questions for the owner

1. **Can you do the root paste of `cerberus-admin-launch` Thursday?** Recommended: yes, by Thursday evening IST. After Friday noon, fall back to option C. It does not depend on #187, though #187's `ApiGatewayStageTags` finding is correct: the Service Reference has no `apigateway:TagResource` or `UntagResource`.
2. **May the Saturday edge live up to 24 h (no instance) to collect logs?** Recommended: yes, with the printed deadline and stage 2 by Sunday noon. If no, the CDN marts may be partial and the article uses k6 numbers.
3. **Drop the Origin Shield comparison?** Recommended: yes; AWS does not allow the test (D1).

## Source list

[load testing](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/load-testing.html), [Origin Shield](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/origin-shield.html), [logging v2](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging.html), [log reference](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logs-reference.html), [v2 permissions](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/AWS-logs-infrastructure-V2-S3.html), [pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/), [signers](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-trusted-signers.html), [EC2 bandwidth](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html), [EC2 testing](https://aws.amazon.com/ec2/testing/), [free tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/tracking-free-tier-usage.html), CloudFront service reference (`servicereference.us-east-1.amazonaws.com/v1/cloudfront/cloudfront.json`).

## Owner answers (2026-11-25)

1. **Root paste of `cerberus-admin-launch`:** yes, Thursday 2026-11-26 evening IST. If it is not pasted by Friday 2026-11-27 noon IST, fall back to option C (telemetry only).
2. **Saturday edge held up to 24 h with no instance to collect logs:** yes. Stage 2 (destroy of the rest) is done by Sunday noon IST.
3. **Origin Shield and its comparison:** dropped. Run D is the cold-patch run with a warm repeat.
