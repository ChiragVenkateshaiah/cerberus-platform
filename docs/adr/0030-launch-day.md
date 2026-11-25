# 30. Launch day: a second event family and a per-session delivery edge

Date: 2026-11-25

## Status

Proposed (2026-11-25). This is the Phase 17.1 ADR. It amends
[ADR 0011](0011-ci-cd-github-actions-oidc.md) (a fourth Terraform root,
`dev-launch`) and [ADR 0018](0018-bulk-bronze-json-lines.md) (a second bulk
prefix, `downloads_bulk/`), and extends
[ADR 0017](0017-iceberg-incremental-processing.md) (silver scope gains
`download_events`). It adds a dated budget exception that ends 2026-11-30.
ADR 0002, 0003 and 0024 are not changed. The facts and build steps are in
[the decision plan](../plans/2026-11-25-launch-day-decision.md). The launch
plan it corrects is
[the launch plan](../plans/2026-11-25-launch-day.md).

## Context

The owner asked to model the GTA VI launch-day download surge as the second
data domain, now, and to publish an article by 2026-11-29. The owner approved
spend above the $20/month guardrail for this phase, with a $40 ceiling and a
$25 stop rule. Phase 9 open items pause until Monday. The event and claim
rules are in the launch plan (sections 3 and 4).

What the decision plan found, against the launch plan (V = verified,
U = unverified):

- (V) AWS does not allow load tests on origins with Origin Shield enabled, or
  on behaviours with Lambda@Edge viewer triggers. It recommends several
  regions, independent DNS per client and all returned IPs. CloudFront
  Functions are not named in the ban ([load
  testing](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/load-testing.html)).
  Origin Shield is also skipped when the regional edge cache is in the Shield
  Region, so one us-east-1 client would show little ([Origin
  Shield](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/origin-shield.html)).
- (V) Standard logs usually arrive within an hour, can be 24 h late, and are
  reliably delivered about four hours after enabling ([log
  reference](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logs-reference.html)).
  A 120-minute session cannot depend on them. Reliable delivery after four
  hours does not ensure complete logs.
- (V) November Cost Explorer (read-only, 2026-11-25): Usage $10.90, Credit
  -$10.90, net about $0. A $25 rule on the unfiltered figure would never fire.
  The account budget reports $10.895 actual, so it shows the uncredited
  figure. Only `Project` is an active cost-allocation tag in the part of the
  list read, so tags cannot isolate Phase 17.
- (V) `cerberus-admin` is scoped, with 8 of 10 managed-policy slots used. The
  `console-edge` policy file fails to save (#187). Root must paste a new
  policy, because `cerberus-admin` cannot change its own policies.
- (V) At the 5 Gbps instance limit ([EC2
  bandwidth](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html))
  a session of 120 minutes could move 4.5 TB, about $300 at $0.085/GB
  ([CloudFront
  pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/)). A
  one-minute CloudWatch metric that arrives minutes late is notification, not
  control.
- (V) The free tier per month is 1 TB out, 10M requests, 2M Function
  invocations and 2M KVS reads (same pricing page). Two licence runs reach
  the 2M figures: Run A and the 403 tests exceed them. An overrun costs
  cents.
- (V) The VPC and `public_subnet_a_id` are in `terraform/envs/dev-standing`
  (`outputs.tf`), not in `dev-compute`.
- (V) The dbt role has no bronze or silver access today; its comment in
  `terraform/modules/iam/main.tf` (near line 324) says dbt only touches gold.
  Reading bronze is therefore new.
- (V) Public keys and key groups cannot be tagged (CloudFront [service
  reference](https://servicereference.us-east-1.amazonaws.com/v1/cloudfront/cloudfront.json)).
- (U) The expected phase cost of $8 to $15 is an estimate (decision plan
  section 6).

Tensions: honesty against spectacle; cost against throughput; least
privilege against a weekend.

## Changes from the launch plan

Where the two differ, the decision plan wins. The disagreements:

- **Origin Shield is removed** (section 4, 17.7 and the article). Run D
  becomes a cold patch for 50 clients at T0, then a warm repeat by one
  client, to measure origin requests through request collapsing.
- **"TTFB by edge POP" becomes "TTFB by source"** (us-east-1 EC2, Bengaluru
  laptop), with the observed `x-edge-location` codes. Hit ratio is
  "single-metro, 50 virtual clients", not global. The test does not follow
  AWS's multi-region advice, so it is not a CloudFront performance
  assessment. Client TTFB (k6) and server `time-to-first-byte` (logs) are
  different numbers and are never mixed.
- **Probe P** drops "vs a US-edge hostname"; the two sources are compared. It
  runs inside the live session, with cookies from tmpfs, before stage 1. Its
  bytes are in the plan total.
- **`PriceClass_All` becomes `PriceClass_200`.** It includes India, with
  fewer costly regions ([price
  classes](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_cloudfront.PriceClass.html)).
- **The private key is never in AWS.** The launch plan stored it in SSM for
  the instance to read. See Decision 4.
- **`/license*` also requires the key group.** Whether signature checks run
  before the Function is unverified; Run A proves it.
- **KVS:** Terraform writes `release_at`; there is no runtime KVS write. See
  Decision 4.
- **Logging:** plain/JSON, not Parquet; client IP and similar fields
  deselected; a destination prefix set; k6 output is primary evidence.
- **Destroy is two-stage** and the launch plan's one-step destroy changes.
- **Byte control is four layers**, not a pre-check and an alarm.
- **The $25 rule is defined** (Decision 12); the launch plan left it
  undefined.
- **Silver table** is `cerberus_platform.download_events`, because Glue has
  one database. The launch plan's `silver.download_events` is not a valid
  name here.
- **VPC:** the VPC is in `dev-standing`, not `dev-compute`. The generator
  uses `public_subnet_a_id`; no new VPC and no NAT.
- **Gold marts are `fct_*`**, not `agg_*`, because the dbt role is already
  allowed `fct_*`.
- **The envelope is not adopted by Phase 13 here.** This ADR binds
  `downloads` only and is an input to the 13.1 ADR.
- **Bytes are recalculated** in decimal GB. The launch plan mixed GiB and GB.
  With the new Run D, `bcd` is 354 GB and the total is 361 GB.

**Corrections from the ADR review.** The review of the first draft changed
the design in seven places:

- **Key lifecycle:** PREWARM holds no usable key (Decision 4).
- **`release_at`:** a far-future sentinel at PREWARM, an explicit variable at
  the live apply, never `timestamp()` (Decision 4).
- **Stage 2:** with PREWARM or HOLD no automation runs it; the owner runs
  `make launch-destroy`. The instance also shuts itself down (Decision 2).
- **Ledger:** an all-in hourly rate plus a flat allowance, with no
  "over-counts" claim (Decision 12).
- **$40 and $25:** $40 is the account total of November Usage; $25 is
  attributable spend (Decision 12).
- **CDN privacy:** an explicit field allowlist, checked before copying
  (Decision 10).
- **dbt and bronze:** reading bronze is new, so it is a named exception
  (Decision 11).

## Decision

1. **Claim.** The phase models the launch; it does not replicate it. Every
   chart and the article show the scale ratio and say the telemetry is
   synthetic. Our peak is one region. 33.03 Tbps is a total exchange peak,
   not GTA traffic, and is never compared as if it were. Synthetic names
   only.
2. **Lifecycle.** A fourth root, `dev-launch`, with a partial backend. It is
   human-run, like the root in ADR 0024, and CI never applies it.
   `terraform-apply.yml` keeps its `dev-standing` path filter, and 17.3 does
   not add `dev-launch` or `launch_edge` paths to it. Destroy is in two
   stages. Stage 1 terminates the instance and deletes the cookie parameter
   and the private key. Stage 2 destroys the rest.
   - Without `PREWARM` or `HOLD`, the EXIT trap runs stage 1, then stage 2.
   - With either flag, no automation runs stage 2. The owner runs
     `make launch-destroy` by the printed deadline. It needs no shell state.
   - A failed PREWARM apply runs both stages.
   - A trap does not survive SIGKILL or power loss (the notes in
     `orchestration/console_session.sh` say the same of a trap that died). So
     the instance shuts itself down at `MINUTES` plus a margin, with shutdown
     behaviour `terminate`. The margin is set in 17.4 (unverified).
     `launch-destroy` also deletes a leftover parameter.

   `launch-check` must report 0 over the distribution, Function, KVS, public
   key, key group, cache policy, OAC, log source, destination and delivery,
   instance and volumes, security group, instance profile, role, SSM
   parameter, buckets and state. Resources carry `Project` and
   `Stack=dev-launch` tags. Public keys and key groups cannot be tagged, so
   the check matches the `cerberus-launch-` name prefix. KVS, Function and
   key group delete after the distribution. Delete duration is unverified;
   allow 30 minutes. Buckets use `force_destroy`. Bronze, silver and gold data
   are the deliberate exception to destroy-leaves-nothing.
3. **Edge.** Pay-as-you-go, `PriceClass_200`, no Origin Shield, OAC, immutable
   content-addressed chunks, no query string, cookie or header in the cache
   key.
4. **Entitlement and unlock.** The private key exists only in `$XDG_RUNTIME_DIR`
   (tmpfs) during a live session, and never in AWS.
   - **PREWARM** holds no usable key. Terraform applies a default public PEM
     whose private half was discarded. The default also lets `launch-destroy`
     work after a crash. `release_at` is a far-future sentinel.
   - **Live `launch-session`** does these steps in order: generate the RSA-2048
     pair; apply the public PEM (the public key resource uses
     `create_before_destroy`, because a key group references it); wait for
     `Deployed`; read the domain from the Terraform output; mint one
     custom-policy cookie set scoped to that domain, with expiry = mint time
     plus `MINUTES`; write the cookies to an SSM SecureString outside
     Terraform; create the instance.
   - The live apply passes an explicit `release_at` variable, calculated from
     the B-to-C schedule. It never uses `timestamp()`. The session checks that
     `/license` returns 403 before T0. A Terraform re-apply is not a runtime
     KVS write.
   - Stage 1 deletes the private key and the parameter. During HOLD no valid
     signer exists, and issued cookies expire at session end.
   - The instance role reads that one parameter, so a compromised instance can
     download only until expiry. `/license*` is a CloudFront Function reading
     `release_at` from a KeyValueStore: 403 before, 200 after.
5. **WAF.** None. A web ACL adds about $5/month prorated (unverified), and a
   rate rule would block our single source. Compensation: every behaviour is
   signed, cookies are short-lived, byte controls apply. Revisit if an edge
   becomes standing.
6. **Load generator.** One Spot instance in the `dev-standing` public subnet
   with a public IPv4, no ingress, egress 443 plus DNS, IMDSv2, a pinned k6
   (version and sha256), per-client DNS (`ttl=0`, random select) and under
   5 Gbps. Its role holds one SSM parameter, seed writes to the build bucket
   and Session Manager. The traffic stays below the EC2 testing policy's
   limits ([EC2 testing](https://aws.amazon.com/ec2/testing/)).
7. **Envelope (`downloads` v1).** The seven launch-plan fields: `event_id`,
   `event_family`, `event_type`, `occurred_at`, `ingested_at`,
   `schema_version`, `payload`. `event_id` uses the UUIDv7 bit layout: a
   48-bit `occurred_at` in ms and 74 bits from SHA-256 of (run_id, client_id,
   event_type, sequence). It is not random. The same arguments give the same
   IDs. A different `run_id` gives different ones, so dedup works within a run
   and the generator must not run twice under two IDs for one dataset.
   `ingested_at` is the run-timestamp argument. `schema_version` starts at 1.
8. **Payments untouched.** Its key stays (`transaction_id`, `event_type`).
9. **Separate silver job.** `promote_downloads_spark.py` is separate on
   purpose. This is accepted debt; Phase 13.5 owns it.
10. **Bronze.** `downloads_bulk/` holds JSON Lines with `_manifest.json`
    written last. This amends ADR 0018, which allowed no write or delete
    outside `payments_bulk/`. `downloads_cdn/` is written by `collect.sh` and
    is append-only. `cerberus-spark` gains read, write and delete on
    `downloads_bulk/*` only. CDN log privacy:
    - An explicit field allowlist names the fields that may enter bronze. It
      excludes `c-ip`, `x-forwarded-for`, `c-port`, `cs(Cookie)`,
      `cs(Referer)` and `cs(User-Agent)`. It includes `x-edge-request-id`
      (Decision 13).
    - `collect.sh` checks every file's fields against the allowlist BEFORE it
      copies, and refuses any path or content that holds an account ID.
    - CDN gold has no client address and no user agent.
11. **Silver and gold.** Silver is `cerberus_platform.download_events` under
    `silver/iceberg/download_events/`, with the same watermark method as ADR
    0017. Every mart is named `fct_*`. The dbt role's silver read gains
    `iceberg/download_events/*`, applied through `dev-standing` by CI. dbt
    reading bronze is new, so it is a named exception: read on
    `downloads_cdn/*` and its one catalog table only, with no silver step. The
    reason: the CDN run logs are small, already structured and have one
    consumer. The exception is listed under Costs.
12. **Cost and controls.** The exception covers usage dated 2026-11-25 to
    2026-11-30. The Tuesday 2026-12-01 read is read-only confirmation, with
    its range fixed to November. From 2026-12-01 stored data counts against the
    $20 guardrail, and the alert returns to $20 after that read.
    - **$40** is the account total November `Usage` (credits excluded),
      matching the alert. **$25** is attributable spend. This is the reading
      of the decision review, for the owner to confirm on acceptance.
    - Attributable is the November `Usage` total (credits excluded, all
      services) minus the total through 2026-11-24, recorded once in a
      committed baseline file before Run A. Plus a ledger estimate for the
      period Cost Explorer has not yet reported.
    - The ledger uses one all-in dev-compute hourly rate (about $0.40/h,
      launch plan section 6), load-generator instance hours and GB over the free
      tier at list price, plus a flat allowance for Athena, S3 and CloudWatch.
      An entry is appended before each apply and corrected at exit.
      It overlaps with reported spend on purpose.
    - `launch-session` and `launch-exercise` refuse when reported plus
      estimate plus next-run estimate exceeds $25, and refuse if the baseline
      file is absent. `launch-destroy` and `launch-collect` are never
      refused. Cost Explorer confirms on Monday and Tuesday; it is not the
      trigger.
    - Byte control has four layers:
      1. `plan_bytes.py` refuses a session over 400 GB, and a month-to-date
         CloudFront total plus session over 900 GB (a ledger of earlier runs
         plus CloudWatch `BytesDownloaded`). Probe P bytes are in the total.
      2. k6 uses fixed iterations, not duration.
      3. An `nftables` quota drops instance ingress above budget plus 10%
         (headers and TLS add about 3%, an estimate; licence responses and
         retransmits add more). It has no exemptions and Run A tests it. Root
         on the instance could remove it; then expiry is the limit.
      4. `session.sh` polls `BytesDownloaded` each minute and runs stage 1
         above budget. It can lag by minutes.

      Cookie expiry and `MINUTES` add to these. The per-session alarm and
      SNS are dropped. `make` refuses; the owner decides.
13. **Saturday edge and logs.** The Saturday edge is created about four hours
    before the run (`PREWARM=1`, no instance). With the owner's agreement,
    `HOLD=1` keeps the edge and log bucket up to 24 h between stages at about
    $0, with a printed deadline. With no instance running, logs are collected
    in that window. Collection can repeat: it skips existing keys, and gold
    dedups on `x-edge-request-id`. Stage 2 is done by Sunday noon IST, and
    `launch-check` stays red until then. `cdn_logs_complete` compares log
    lines with k6 counts. Below 99% the CDN marts are labelled partial. The
    DQ check "logs present for every run" is a warning.
14. **IAM.** One new file, `iam/cerberus-admin/policies/cerberus-admin-launch.json`,
    a ninth slot. The existing `console-edge` file is not edited. Every
    action is checked against the Service Authorization reference before the
    paste, and by `simulate-custom-policy` (review: `escalate: opus-security`).
    Root pastes and attaches it by Thursday 2026-11-26 evening IST. If it is
    not pasted by Friday 2026-11-27 noon IST, the phase falls back to
    telemetry only (no edge). The policy is detached after 17.9.

Owner answers of 2026-11-25 are folded into Decisions 12 to 14: the Thursday
paste with the Friday noon fallback, the 24 h Saturday hold with stage 2 by
Sunday noon IST, and the end of the Origin Shield comparison.

## Consequences

**Good**

- Bounded bytes, with a hard stop at run time and not only an alert.
- No standing key and no usable key between sessions; a leaked cookie expires
  with the session.
- A reusable second event family, and the first per-session edge with a byte
  budget.

**Given up**

- Origin Shield evidence, multi-region load, and complete CDN logs.
- WAF on the edge, for this phase only.

**Costs**

- A ninth admin policy and a wider bronze delete.
- A new dbt read on bronze (`downloads_cdn/*` and one catalog table), the
  exception in Decision 11.
- About $0.6 to $1.3/month of storage until a retention decision. This
  is 100M events at about 450 bytes (the ADR 0018 size), 45 GB; the larger
  envelope makes it bigger (unverified). It persists after Sunday. Phase 17.10
  owns the retention decision.
- Duplicate silver code until 13.5.
- Phase cost of $8 to $15 is plausible (unverified estimate). At $25
  attributable, account usage is near $36, which fits a $40 alert only if
  nothing else spends.
- Free-tier overrun on Functions and KVS reads (2M each) costs cents.

**Revisit if**

- An edge becomes standing.
- Phase 13.1 decides the shared envelope.
- A two-pass job over 10M events is needed. The 742 s figure in
  `docs/scale-metrics.md` is the 100M state machine, not this job.
- 17.10 (after the weekend) also rewords 13.5 and owns the bronze retention
  decision.

## Unverified

- That signature checks run before the `/license*` Function (Run A).
- The delete duration of the distribution and its dependents (allow 30 min).
- Whether `Stack` is an active cost-allocation tag.
- The exact free-tier account-pooling wording, and any discount for EC2
  viewers (assume EC2 downloads count).
- Whether a supported viewer option chooses an edge location.
- WAF web ACL cost (about $5/month prorated).
- Whether the provider needs `CancelSpotInstanceRequests` and
  `DescribeSpotInstanceRequests`.
- Silver storage size with the larger envelope.
- The instance self-shutdown margin beyond `MINUTES` (set in 17.4).
- The $40 and $25 reading (owner confirms on acceptance).
- The $8 to $15 phase cost estimate.
