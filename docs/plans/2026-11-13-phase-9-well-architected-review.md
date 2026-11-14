# Plan: Phases.md 9.7, the Phase 9 Well-Architected pass (ADR 0026)

Date: 2026-11-13. Planner: Opus. Mode: plan. Branch: `decision-well-architected-phase9` (main 9fd55a0).
Save as `docs/plans/2026-11-13-phase-9-well-architected-review.md`.

## 1. Question

How should we record Phase 9 (the demo console) against the six pillars? For each finding, do we fix it now, defer it with a trigger, or accept the risk? And when do the Tool answers change and milestone 9 get saved, given that the live Grafana session (step 10 PR F) and the 9.6 live check have not run?

Why now:
- 9.7 is the last Phase 9 subtask.
- ADR 0023 L359-368 left the Phase 9 IAM changes to 9.7.
- The review tells the owner what the live run must prove.

## 2. Facts

**Well-Architected Tool (read-only, `cerberus-admin`, 2026-11-13)**

- T1. Workload `cerberus-platform` is at 18 HIGH / 18 MEDIUM / 16 NONE / 5 N/A, `UpdatedAt` 2026-11-12 (`list-workloads`). These are the milestone 8 counts (ADR 0023 L332-336).
- T2. HIGH and MEDIUM questions by pillar (`list-answers`):
  - Security: HIGH `securely-operate`, `identities`, `protect-data-transit`, `incident-response`, `application-security`. MEDIUM `permissions`, `detect-investigate-events`, `data-classification`.
  - Reliability: HIGH `manage-service-limits`, `mitigate-interaction-failure`, `withstand-component-failures`, `testing-resiliency`, `planning-for-recovery`. MEDIUM `monitor-aws-resources`, `tracking-change-management`, `backing-up-data`.
  - Operational Excellence: HIGH `priorities`, `ops-model`, `org-culture`, `observability`, `ready-to-support`, `event-response`. MEDIUM `dev-integ`, `mit-deploy-risks`. NONE `evolve-ops`.
  - Cost: HIGH `cloud-financial-management`, `govern-usage`. MEDIUM `type-size-number-resources`, `pricing-model`. NONE `evaluate-cost-effort`.
  - Performance: MEDIUM `compute-hardware`, `data-management`.
  - Sustainability: all six questions MEDIUM.
  - Read with `--max-results 50`. Per-pillar HIGH: OE 6, Sec 5, Rel 5, Perf 0, Cost 2, Sus 0, matching ADR 0023 L265-272.
- T3. The five N/A answers are `network-protection`, `protect-compute`, `planning-network-topology`, `data-transfer` and `networking`.
  - Their notes say "No VPC/network layer exists in Phase 1", "No compute to harden ... Relevant again once Phase 3's EKS/Spark or Phase 2's Lambda land", and "Single-region, single-account serverless stack".
  - They have been stale since Phase 3 (ADR 0007). Since Phase 9 they are plainly wrong: there is a public internet edge, a VPC origin and an EC2 host.
- T4. The live `identities` note has no sentence about Grafana or mounted keys (`get-answer`). ADR 0023 L362-365 says it does. So there is nothing to remove, and ADR 0023's record is inaccurate.
- T5. Current selected choices:
  - `identities`: enforce_mechanisms, unique, secrets.
  - `permissions`: define, least_privileges, emergency_process, continuous_reduction, share_securely_third_party, analyze_cross_account.
  - `mitigate-interaction-failure`: throttle_requests, limit_retries, fail_fast, client_timeouts, stateless. Not graceful_degradation or emergency_levers.
  - `protect-data-transit`: encrypt, authentication. Not key_cert_mgmt.
  - `detect-investigate-events`: app_service_logging only. The note is the Phase 1 systemd text.
  - `monitor-aws-resources`: 6 of 7, not automate_response.
  - `sus_hardware`: a2, a4.
- T6. `cerberus-admin` has `UpdateAnswer` and `CreateMilestone` on the workload (`iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json` L94-107).

**Other AWS reads (2026-11-13)**

- A1. The Lambda account concurrency limit is still 10 (`lambda get-account-settings`).
- A2. `cloudtrail describe-trails`: 0 trails.
- A3. `cloudwatch:DescribeAlarms` is denied for `cerberus-admin`, so the live alarm count is unknown.
- A4. `cerberus-admin-console-edge` allows `AdminDisableUser`, `AdminEnableUser`, `AdminUserGlobalSignOut` and `ListUsers` on the pool (policy file, Sid `CognitoUserPool`). It is 4,730 of 6,144 non-whitespace characters. `console-host` is 2,363.
- ADR 0025 L7-10 says the 9.7 ADR takes the next free number. That is **0026**.

**Standing edge, in code and live**

- E1. `terraform/modules/console_edge/main.tf` L128-132: "The default certificate and no standard logging are known limits ... both go to 9.7's Well-Architected pass."
- E2. Headers and transport (`main.tf`):
  - Strict CSP (no `unsafe`, `frame-ancestors 'none'`), HSTS 1 year, `nosniff`, `DENY`, `no-referrer`, Permissions-Policy (L157-207).
  - `redirect-to-https` (L237); `/api/*` is `https-only` (L248); origin TLSv1.2 to API Gateway (L230-231).
  - `PriceClass_100`, IPv6, `http2and3` (L213-215).
- E3. OAC read plus `DenyCloudFrontArtifacts` (L94-119). PR A #154 verified a 403 on `artifacts/*`.
- E4. Cognito (L276-345): ESSENTIALS, `deletion_protection = ACTIVE`, **`mfa_configuration = "OFF"`** (L280), admin-create only, `admin_only` recovery, 12-character password policy. The SPA client is public, code flow, `openid`, 60-minute tokens, refresh-only auth flows.
- E5. API (L360-423): JWT route with the `openid` scope, throttle 1/3, access log with `sub` kept 30 days. Reserved concurrency defaults to -1 (`variables.tf`).
- E6. Lambda (L465-511): arm64, python3.12, 25 s, 256 MB. The logs-only inline policy is scoped to its own log group.
- E7. Roles (`terraform/modules/console_roles/main.tf` L113-182): `cerberus-console-cli` can read Step Functions, use one workgroup and read gold metadata only. Its write set is exactly four actions, pinned by `console/tests/test_edge_config.py`: `athena:StartQueryExecution` and `athena:StopQueryExecution` on the console workgroup, and `s3:PutObject` and `s3:AbortMultipartUpload` on the results prefix only. `cerberus-grafana-read` has AMP query plus CloudWatch read, with 12 h sessions.
- E8. No alarm covers the console Lambda or API. All alarms are in `terraform/modules/observability/alarms.tf`: 7 resources, 5 of them gated on `pipeline_active`. CI may create alarms named `cerberus-*` (`terraform/modules/github_oidc/main.tf` L369-377). The topic is output as `alerts_topic_arn` (`terraform/modules/observability/outputs.tf` L21-23).
- E9. Command output carries no ARN. The execution ARN is used only internally (`console/cerberus_console/commands.py` L119-120, L319), and error codes are capped at 64 characters (`config.py` L48). The two strict xfails are at `console/tests/test_sanitize.py` L81-89.
- E10. Fail-closed handling (`api.py` L64-80). A failed source becomes an "unavailable" section while the rest of the answer stands (`commands.py` L87-92 and L129-344). This is graceful degradation.

**Session root (in code, never run live)**

- S1. Host (`terraform/envs/dev-console/main.tf` L166-200): t4g.small, no key pair, no public IP, IMDSv2 with hop limit 1, shutdown behaviour terminate. It shuts down at boot + MINUTES + 45 (L45-51; `user_data.sh.tftpl` L18).
- S2. Security group (`main.tf` L130-161): port 3000 only from the CloudFront service SG, egress 443 only.
- S3. The session distribution uses `Managed-SecurityHeadersPolicy`, so it sends **no CSP** (`edge.tf` L29-31, L139). The origin is `http-only` inside the VPC origin (L37-41).
- S4. Artifacts are checked by sha256 at boot (`user_data.sh.tftpl` L30-44, L63-65). The AMI is the latest AL2023 arm64 from SSM (`main.tf` L166-168).
- S5. `observability/grafana/console/grafana.ini.tmpl`:
  - Viewer only (strict), login form off, 2 h login maximum, 30 min idle, Explore, snapshots and public dashboards off.
  - Several key names are marked "unverified" (L10-12, L74-89).
  - `[log] mode = console` (L94-95), so no Grafana log outlives the instance.
- S6. `orchestration/console_session.sh`:
  - `HOURLY=0.068` (L36-37); the cost is shown before the y/N (L210-213).
  - The traps are set before the apply (L217-219).
  - The destroy runs under setsid and retries once with `-refresh=false` (L154-163), then runs `console_check.sh` (L170).
- S7. `orchestration/console_check.sh`: read-only, and a value it cannot read fails the check (L1-25). `distributions_total` is expected to be 1 (L99).
- S8. The `live.json` contract is in `console/README.md` L195-213: the reader must hide the link once `ends` has passed.

**Measured (caller-supplied, with sources)**

- M1. 9.5 live check, 2026-11-12 (`docs/plans/2026-11-12-terminal-panel.md` §7a L140-162): `status` 5.6 s cold and 3.0 s warm; refusals were 400 at 87 bytes; `/logout` clears the hosted UI cookie; every log entry had a `sub`.
- M2. PR B #155: Grafana 13.2.3 arm64 (430,350,990 bytes) and plugin 3.2.0 (18,143,563 bytes) are staged with sha256 metadata.
- M3. PR C #156: the local AMP-only verify showed data and annotations, with no "datasource not found".
- M4. PR D #157: 20 resources expected; the offline validate passed. `console-plan` has not run.
- M5. PR E #158: a live `console_check` printed all counts 0 and `distributions_total 1`. The setsid test passed, and the same fix went into `exercise.sh` (#159).
- M6. #160: 833 console tests plus 2 xfail, and 80 Grafana module tests on Python 3.9. Edge headers, the JWT route, throttle 1/3, the Cognito client and the 4-action write set are pinned by tests. 5 mutation checks were caught.
- M7. VPC-origin spike: wake 11:52 and about 15:35; destroy about 11 min; ENIs gone in about 1 min; WebSocket 101 (`docs/plans/2026-11-12-console-session.md` F6).
- M8. Cost:
  - A session is about $0.068/h and about $0.14 per 90-minute session. A dead trap costs about $1.20/day (console-session plan §8).
  - The list prices are from 2026-10-27 and were not rechecked, because `pricing:GetProducts` is denied (F27).
  - The NAT plus its IPv4 is $0.050 of the $0.068 hourly, about 74%.
  - The November forecast is about $12.7 of $20 (F26).
  - The standing idle cost has not been read from a bill (ADR 0024 L106-108).

**External (unverified for this account)**

- X1. The CloudFront **Free flat-rate plan** costs $0 a month. It allows 1M requests and 100 GB, and includes WAF with IP-based rate limiting, with no overage charges.
  - A web ACL must stay attached while the distribution is subscribed.
  - A subscribed distribution cannot be deleted until the plan is cancelled; Free plans cancel at once.
  - VPC origins need the Business tier. Access logs to CloudWatch need Pro or higher.
  - Free Tier accounts are not eligible. The limit is 3 Free plans per account.
  - No Terraform resource was found; CloudFormation has `AWS::PricingPlanManager::Subscription`.
- X2. With the default `*.cloudfront.net` certificate, CloudFront reportedly ignores `minimum_protocol_version` and allows TLSv1. The source is a CDK issue and PR, not AWS docs. It can be measured with `openssl s_client` at $0.
- X3. CloudWatch's always-free tier includes 10 standard alarm metrics. This is from memory of the pricing page and was not rechecked.

## 3. Constraints

- $0 idle, $20/month budget; nothing hourly outlives a session.
- `dev-console` keeps the destroy-leaves-nothing contract. CI applies `dev-standing` only.
- No account ID, domain, pool ID or secret in **new** repo files. This rule postdates the older roots: `envs/dev-standing/versions.tf` L30 and the `cerberus-admin` policy files still carry the account ID, as acknowledged in `.github/workflows/console-site.yml` L8-9 and `envs/dev-console/versions.tf` L23-25.
- No contradiction of ADR 0024 or its 2026-11-02 and 2026-11-12 amendments. This ADR amends none of them.
- Tool writes (`update-answer`, `create-milestone`), alarm applies and Cost Explorer reads are owner-approved. Code and Terraform changes from this ADR wait until it is accepted.
- No claim depends on PR F or the 9.6 live check unless it is marked as depending on them.

## 4. Options

**The central choice: what the review claims, and when.**

- **A. Everything now: answers and milestone 9.** Effort: low. It writes unverified session claims into the Tool, and milestones cannot be edited. Rejected.
- **B. Verified answers now, live-dependent answers after the live run, milestone last.**
  - Now: the ADR and the answers backed by merged code plus a live or CI result.
  - After PR F and the 9.6 live check: the answers that depend on them.
  - Last: milestone 9, once 9.2, 9.4 and 9.6 are checked.
  - Cost $0. Effort: three small Tool passes. This follows ADR 0023 Decision 2.
- **C. Wait for the live run, then do everything.** It delays the ADR, which is the list of what the live run must prove, and it gains nothing.

**Sub-choices** (each feeds a pillar decision in §6):

- **Edge protection.**
  - (i) Accept: throttle, invite-only and Budgets. $0.
  - (ii) Pay-as-you-go WAF: about $5 a month per web ACL plus $1 per rule (list price from memory, unverified). That breaks $0 idle and uses about 30% of the budget.
  - (iii) Free flat-rate plan (X1): $0 and caps CloudFront cost under a flood. But it is outside Terraform, the web ACL cannot be removed, it blocks `standing-destroy` until the plan is cancelled, and eligibility is unverified.
- **Dead-trap guard.**
  - (i) Budgets only: lag of up to about a day.
  - (ii) Add `make console-check` to `/start-day`: $0, read-only, catches a dead trap within a day.
  - (iii) A standing reaper (Scheduler plus a Lambda with `ec2:DeleteNatGateway`): $0 idle, but a new standing write role and drift against the `dev-console` state.
- **Console health signal.**
  - (i) None: a visitor finds the outage first.
  - (ii) Two CloudWatch alarms on the existing topic, CI-applied. Estimated $0 inside the free 10 (X3; the code shows 2 always-on alarms, live count unread per A3).
  - (iii) Wait for Phase 10's AMP alerting, which does not see Lambda or API Gateway metrics.

## 5. Recommendation

**B**, with:
- Edge protection (i), with (iii) named as the path when a trigger fires.
- Dead-trap guard (ii).
- Health signal (ii).

B wins the Reliability and Operational Excellence tension in the same way as ADR 0023: the record matches what was shipped, and the work keeps moving. The sub-choices keep $0 idle, add no standing write role, and close the two gaps that a hiring manager would hit first: a broken console nobody noticed, and an unbounded dead-trap bill.

The Security pillar drives this ADR. Phase 9 made the workload internet-facing, so the five stale N/A answers become real answers even if HIGH rises. The ADR must say that a rise in HIGH means a wider workload, not a worse one.

## 6. ADR outline

**File:** `docs/adr/0026-phase-9-well-architected-review.md`, "# 26. Phase 9 Well-Architected review", Date 2026-11-13, Status **Proposed**. Shape: as ADR 0023, plus an explicit `## Decision` heading per the Nygard contract (0023 kept its decisions inside Context).

### Status

Proposed. Plan link. "Milestone 9: see the section below (added at close-out)."

### Context

- **What Phase 9 built.** One line each:
  - 9.1: ADR 0024 and its two amendments.
  - 9.2: the standing edge (#130), roles and subnet (#125), local Grafana on short-lived credentials (#126), in-cluster Grafana removed (#148), session PRs A-E (#154-#158).
  - 9.3: the command set (#127, #128).
  - 9.4: page rejected and being rebuilt.
  - 9.5: the terminal (#149-#152).
  - 9.6: the safety suite (#160).
- **Baseline.** Milestone 8 (T1). No answer has changed since.
- **Why this pass differs.** The workload is now internet-facing: a public CloudFront edge, a sign-in, an API, a per-session EC2 host behind a VPC origin. Five answers are N/A for reasons that stopped being true in Phase 3 (T3). This pass answers them, and HIGH may rise. Say why.
- **Phase 9 IAM changes, recorded as ADR 0023 L359-368 asked.**
  - The `cerberus-admin-console-edge` statements ApiGatewayTags, ApiGatewayStageTags and HttpApiLogDelivery (`iam/cerberus-admin/README.md` L176-).
  - `cerberus-admin-console-host`.
  - The roles `cerberus-console-cli` and `cerberus-grafana-read` (E7), and `cerberus-console-grafana` (session only).
  - The CI grant `ManageConsoleIamRoles` (`github_oidc/main.tf` L596-).
  - Policy sizes (A4).
- **Correction to ADR 0023 (T4).** The identities note never held the Grafana-keys sentence. Static keys left the local Grafana with #126, so the reasoning stands, but there is no note text to remove.
- **ADR 0024 "To confirm in build", status:**
  - Closed: arm64 builds (F28, F29); Cognito Lite has no managed login and access tokens validate by `client_id` (2026-11-02 amendment); VPC origin times (M7); `/logout` clears the cookie (M1).
  - Open, waiting for PR F: `generic_oauth` with Cognito and the email placeholder; Viewer Inspect access and Explore off; the AMP plugin on instance credentials; the full-stack wake and destroy times; `console-check` 0 after a real session.
  - Open, no date: list prices (F27); the `status` query's bytes scanned.
- **What depends on the live run.** A named list: every item in the previous point marked PR F; plus 9.6 live steps 2-7 (headers by curl, 401s, the GET status, refusals with `sub`, the IAM deny check, `live.json` absent after destroy); plus the new 9.7 live checks in build step 5.
- **The decision drivers.** Security (internet edge) and Cost ($0 idle). Their tension: real edge protection costs money or leaves Terraform.

### Decision

**Decision 1: option B.**
- An answer changes now only if its evidence is in merged code **and** has a live or CI result: M1-M6, E1-E10, A1-A4.
- Answers whose evidence is a session that has never run wait for PR F.
- Milestone 9, `phase-9-demo-console-complete`, waits until 9.2, 9.4 and 9.6 are checked.

**Decision 2: answer the five N/A questions.**
- Now, with standing evidence: `network-protection`, `planning-network-topology`, `data-transfer`, `networking`.
- After PR F: `protect-compute`, because the only host has never booted.
- The Tool decides the buckets. No count is predicted.

**Pillar by pillar.** Each pillar lists what is good, the gaps, and a decision per gap.

**Security (the driving pillar)**

- Good:
  - "Not a shell" by construction, with rules 1-9 pinned by 833 tests and 5 caught mutations (M6).
  - OAC plus the artifacts deny (E3); JWT with `openid` (E5); strict CSP and HSTS (E2).
  - Invite-only sign-in with admin-only recovery (E4).
  - The console-cli write set is exactly four actions, pinned by tests: Athena query start and stop on the console workgroup, and S3 put and multipart abort on the results prefix only (E7). Errors fail closed (E10).
  - The session host has no SSH, uses IMDSv2, accepts traffic only from the CloudFront SG, and checks artifacts by sha256 (S1, S2, S4).
  - The client secret never touches S3, tags or user data (console-session plan option 4.2 A).
  - No static keys in the local Grafana (#126). No new file carries the account ID.
- Gaps and decisions:
  1. No WAF and no rate limit on static paths; the API throttle is stage-wide (2026-11-02 amendment). **Accept.** **Defer** the Free flat-rate plan (X1). Trigger: invites go beyond a handful (ADR 0024's trigger), a month's CloudFront requests are not explained by invites, or a Terraform or `awscc` resource for the subscription exists. Do a $0 spike before adopting it.
  2. Default certificate: no TLS policy, and the floor is reportedly TLSv1 (X2). **Accept.** Trigger: a domain (ADR 0024). Measure it in build step 5.
  3. No CloudFront standard logs, Grafana logs die with the instance (S5), and there is no trail (A2). **Defer** CloudFront logs with gap 1's trigger. The trail stays ADR 0023 item 14. **Accept** the Grafana logs: Viewer only, session only.
  4. MFA is off (E4), and a disabled user's access token may still pass the JWT authorizer until `exp`, at most 60 min (unverified). **Accept**: read-only, throttled, invite-only. Measure the token behaviour in build step 5.
  5. No written emergency levers or invite lifecycle. **Fix now** (PR 3).
  6. The session distribution sends no CSP (S3). **Defer to PR F.** Try Grafana's `[security] content_security_policy` in the second, full session. Keep it if the dashboards load; otherwise accept the risk and say why.
  7. Redaction gaps (the two strict xfails). **Accept**: no command output carries an ARN today (E9). Trigger: any new output field that carries ARNs or S3 URIs (Phase 10 series, ADR 0025 agent text).
  8. Stale N/A answers (T3). **Fix now** (Decision 2).
- Tool changes, now:
  - `network-protection`: +create_layers, +layered.
  - `identities`: note only. It stays HIGH; keys are not rotated.
  - `permissions`: note only now; +lifecycle after PR 3.
  - `detect-investigate-events`: note only. Replace the stale Phase 1 text with the API access log keyed by `sub` and "still no trail".
  - `protect-data-transit`: note only. It stays HIGH; add the TLS floor result after step 5.
  - `incident-response`: note after PR 3.
  - `application-security`: +automate_testing_throughout_lifecycle (the #160 safety suite). Penetration testing and pipeline assessment are not claimed.
- Tool changes, after PR F: `protect-compute` (+validate_software_integrity, +reduce_manual_management). Leave vulnerability management unselected: there is no scanning, only the newest AMI per session.

**Reliability**

- Good:
  - The standing path is managed, multi-AZ services with no host.
  - Graceful degradation per section (E10). The terminal and landing page stay up while `dev-compute` and the session are down.
  - Fixed timeouts and caches (2026-11-02 amendment).
  - Teardown is layered: EXIT trap, setsid, a retry with `-refresh=false`, self-terminate, `console_check`, Budgets (S1, S6, S7).
  - Pool deletion protection is on, and the site rebuilds from git.
- Gaps and decisions:
  1. No console alarm (E8). **Fix now** (PR 2).
  2. The 10 Lambda concurrency slots are shared, with no reservation (A1). **Accept** (amendment). Trigger: the limit reaches at least 102.
  3. The session is one AZ and one instance. **Accept** for a scheduled demo.
  4. A dead trap is found only by Budgets. **Fix now** (PR 3, `/start-day`). **Defer** the reaper. Trigger: the first dead trap, or more than 4 sessions a month.
  5. CloudFront's 30 s origin timeout on heavy AMP queries. **Live (PR F)**.
  6. A stale `live.json` (S8). This is a **gate on the 9.4 rebuild**: its review must check the `ends` handling.
- Tool changes, now:
  - `mitigate-interaction-failure`: +graceful_degradation now; +emergency_levers after PR 3 and the build step 5 test.
  - `manage-service-limits`: note only (A1, throttle under the limit).
  - `planning-network-topology`: +ha_conn_users (CloudFront and the regional API; session single-AZ stated), +ip_subnet_allocation, +non_overlap_ip.
  - `monitor-aws-resources`: note after PR 2.

**Operational Excellence**

- Good:
  - One command per session, with a preflight and a cost prompt (S6).
  - A read-only check (S7). The publish verifies the headers.
  - One plan per step, and CI suites on two Python versions (M6, #159).
- Gaps and decisions:
  1. `dev-console` is never planned in CI (ADR 0011 amendment), so the first real plan is owner-run. **Accept.**
  2. The first session is also the first test of the unverified Grafana keys (S5). **Accept**: PR F starts with `MINUTES=30`.
  3. `cerberus-admin` cannot read alarms (A3). **Fix with PR 2**: a root paste of `cloudwatch:DescribeAlarms` (read) into `console-edge`, 4,730 of 6,144 characters.
- Tool changes: `dev-integ` and `mit-deploy-risks` get a note (M6); the executor checks the choice titles with `get-answer` before proposing new choices.

**Performance Efficiency**

- Good: `PriceClass_100` (North America and Europe, which matches a Canadian audience), HTTP/3, compression, immutable assets, result reuse, arm64 Lambda, and the S3 gateway endpoint for the 430 MB artifact.
- Gaps and decisions:
  1. `status` takes 5.6 s cold and 3.0 s warm (M1). **Accept.** Provisioned concurrency and SnapStart both bill while idle. Trigger: Phase 10 status series in AMP (Phases.md 9.3).
  2. Full-stack wake time is unmeasured. **Live (PR F)**. ADR 0024's 20-minute trigger stands.
- Tool changes: `networking`: +understand_how_networking_impacts_performance (M7), +evaluate_networking_features, +choose_network_protocols, +choose_workload_location.

**Cost Optimization**

- Good:
  - $0 idle by design, one line per resource (ADR 0024 table).
  - A session is about $0.068/h and about $0.14 per 90 minutes (M8), and the cost is shown before the y/N.
  - The gateway endpoint keeps artifact downloads off the NAT's per-GB charge.
  - The worst month at the throttle is about $3.4 to $7.7 (2026-11-02 amendment).
- Gaps and decisions:
  1. Idle cost is not read from a bill. **Fix (scheduled):** one Cost Explorer read in early December for 9 to 30 November, and one in early January for December. That is 2 requests at $0.01 each (list price).
  2. A flood of static pages is bounded only by Budgets. **Same as Security gap 1.**
  3. NAT is about 74% of the session hourly cost. **Accept** (ADR 0024 L196-198: the token endpoint needs internet).
  4. List prices are from 2026-10-27. **Accept**: the owner reads the public pricing pages once before the milestone.
- Tool changes: `data-transfer`: +modeling, +optimized_components, +implement_services. `govern-usage`: note (cost at the point of action).

**Sustainability**

- Good: Graviton for every new compute (E6, S1); no idle host; the 10 KB DOM terminal against 496 KB for xterm.js (2026-11-12 amendment); cached static assets.
- Gap: each session downloads 430 MB. **Accept**: a baked AMI would bill snapshot storage while idle.
- Tool changes: `sus_hardware` +a3 (confirm the title "least impact instance types" with `get-answer`). This partly closes ADR 0023's "Graviton never evaluated": the console only, since the Spark executors are still x86.

**Amends: none.** ADR 0023 gets a one-line Status note: "Milestone 8's identities point corrected by ADR 0026."

### Overall

A table: milestone 8 against the workload after the 9.7 answers, by pillar. **Empty until the Tool is read back.** No predicted counts.

### Consequences

A numbered follow-up list, each item with an owner phase:
1. The live-dependent list (PR F, 9.6 live, build step 5).
2. Milestone 9 timing.
3. The Free flat-rate plan or WAF (trigger).
4. CloudFront logs (trigger).
5. The TLS floor and a domain.
6. The reaper (trigger).
7. Reserved concurrency at 102.
8. The redaction xfails (trigger).
9. Grafana CSP and the ini keys (PR F).
10. Grafana audit (accept; trigger invites).
11. MFA off (accept; trigger invites).
12. The Cost Explorer reads (December, January).
13. Carried from ADR 0023: trail (item 14), workload description (9), Data Analytics Lens (10, deferred again: it is about analytics, not the console), key rotation.
14. The 9.4 rebuild must honour `ends`.

Given up: no edge WAF, no custom TLS policy, no Grafana audit trail after destroy, one AZ for the session, and HIGH may rise.

### Milestone 9 (added at close-out)

Counts, Cost Explorer readings, the PR F and 9.6 outcomes.

## 7. Build steps (Phases.md 9.7, the existing subtask)

1. **PR 1, docs (this branch).**
   - ADR 0026 Proposed, this plan, and the ADR 0023 Status line.
   - The executor adds §9 "Tool commands" (full selected sets; `update-answer` replaces the whole set) and §12 note texts, each ≤ 2,084 characters, in ADR 0023's plan format.
   - A Phases.md 9.7 progress note.
   - Verify: `git diff main -- docs | grep -E '[0-9]{12}'` finds nothing; every number traces to §2; no bucket move is claimed.
2. **After acceptance: owner-run Tool writes (now set).** The `update-answer` commands for the "now" items. Then a read-only `get-lens-review` read-back; the counts go into "Overall"; the ADR merges as Accepted.
3. **PR 2, `dev-standing` (CI-applied).**
   - `console_edge` gets `alarm_topic_arn` (from `module.observability.alerts_topic_arn`) and two alarms:
     - `cerberus-console-api-5xx`: AWS/ApiGateway `5xx` by ApiId, Sum over 300 s, at least 3.
     - `cerberus-console-lambda-errors`: AWS/Lambda `Errors`, Sum over 300 s, at least 1.
     - Both with `treat_missing_data = notBreaching`.
   - `test_edge_config.py` pins the names and thresholds.
   - A root paste of `cloudwatch:DescribeAlarms` to `console-edge` (owner).
   - Verify: the PR plan shows 2 to add plus the known Faker churn; after the CI apply, `describe-alarms` shows both in OK or INSUFFICIENT_DATA.
4. **PR 3, runbook and checks.**
   - `console/README.md` gets "Emergency levers":
     - Disable one user: `admin-disable-user` plus `admin-user-global-sign-out`; note that the access token may last until `exp`.
     - Stop everyone: a PR setting throttle 0/0, CI-applied.
     - Last resort: disable the distribution, with the Terraform drift noted.
   - It also gets "Invite lifecycle": create, demo, disable within 7 days.
   - `console_check.sh` gets an informational `enabled_users N` line (`ListUsers` is allowed, A4; the filter syntax is unverified, so fall back to counting `Enabled` with jq).
   - `.claude/commands/start-day.md`: run `make console-check` and report any non-zero value.
   - Verify: `bash -n`, shellcheck, and `make console-check` still prints `console_check ok`.
5. **Owner, during PR F and the 9.6 live session (no extra resources).**
   - (a) `openssl s_client -connect <cf>:443 -tls1` and `-tls1_1` on both distributions; record accepted or refused.
   - (b) As a Viewer: `GET /api/frontend/settings` and `/api/datasources`; record the status, and check no account ID shows.
   - (c) Disable the test user mid-session; record whether its token still passes `/api/command` until `exp`; then re-enable.
   - (d) In the second session, Grafana CSP on; record whether the dashboards load.
   - (e) Watch for CloudFront 504s on the 100M windows.
   - Record these in 9.6c.
6. **Owner-run Tool writes (live set).** `protect-compute`, plus the notes on `network-protection`, `protect-data-transit`, `decomissioning-resources`, `mitigate-interaction-failure` (+emergency_levers) and `permissions` (+lifecycle).
7. **Close-out PR, after 9.2, 9.4 and 9.6 are checked.**
   - `create-milestone phase-9-demo-console-complete`.
   - The "Milestone 9" section with the Cost Explorer readings.
   - Tick 9.7, and update Phases, the `docs/plan.md` row and the README.

## 8. Owner answers (2026-11-14)

The three open questions from the Opus plan are answered. Each answer matches the recommendation in §5.

1. **Milestone 9 timing.** Milestone 9 waits for 9.2, 9.4 and 9.6, including the 9.4 interactive rebuild. It is saved only in the close-out PR (step 7).
2. **PR 2.** Accepted: two always-on CloudWatch alarms (`cerberus-console-api-5xx` and `cerberus-console-lambda-errors`), plus one `cerberus-admin` root-console paste of `cloudwatch:DescribeAlarms`. The $0 estimate stays unverified until the live alarm count is read after the paste (A3, X3).
3. **Edge protection.** Defer the CloudFront Free flat-rate plan, with the trigger in §6 (Security gap 1). No spike now.

Sources (AWS documents only; the forum, vendor and mirror links were dropped on 2026-11-14 because they are not AWS sources and the CDK PR link used a non-GitHub domain):
- [CloudFront flat-rate pricing plans (AWS docs)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html)
- [Amazon CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/)

Key paths:
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/docs/adr/0023-phase-8-well-architected-review.md
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/docs/adr/0024-demo-console.md
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/terraform/modules/console_edge/main.tf
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/terraform/modules/console_roles/main.tf
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/terraform/envs/dev-console/main.tf, edge.tf, session.tf
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/observability/grafana/console/grafana.ini.tmpl
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/orchestration/console_session.sh, console_check.sh
- /home/chirag/projects/cerberus/.claude/worktrees/phase-9-kickoff/docs/plans/2026-10-27-phase-8-well-architected-review.md (format for §9 and §12)

## 9. WA Tool commands

**Read-only, run on 2026-11-13 and 2026-11-14 (`AWS_PROFILE=cerberus-admin`, us-east-1)**
- `aws wellarchitected list-workloads`: `cerberus-platform`, 18 HIGH / 18 MEDIUM / 16 NONE / 5 N/A, `UpdatedAt` 2026-11-12 (T1).
- `aws wellarchitected list-answers` and `get-answer` on the 15 questions below. Every choice ID in this section was read from `get-answer` on 2026-11-14 and exists. The selected sets below are the live sets on that date.
- `aws cloudtrail describe-trails`: 0 trails (A2).

**Writes, for the owner after ADR 0026 is accepted** (step 2). `update-answer` **replaces** the whole selected set and the note. Each note is at most 2,084 characters. Four answers are now marked not applicable (`IsApplicable` false, reason `ARCHITECTURE_CONSTRAINTS`); their commands pass `--is-applicable` and an empty current set, so the new choices are the whole set. The note texts are in section 12. The workload ID is a placeholder; read it with `aws wellarchitected list-workloads`. Template:

```
W=<WORKLOAD_ID>
q=<question-id>; NOTE='<note text from section 12>'
[ ${#NOTE} -le 2084 ] || echo "note too long: ${#NOTE}"
aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
  --question-id $q [--is-applicable] --selected-choices <full list below> --notes "$NOTE"
```

Full selected sets. New choices are marked with `+`. A row with no `+` is note only (same choices).
- `network-protection` (now applicable): +sec_network_protection_create_layers, +sec_network_protection_layered
- `identities` (note only): sec_identities_enforce_mechanisms, sec_identities_unique, sec_identities_secrets
- `permissions` (note only): sec_permissions_define, sec_permissions_least_privileges, sec_permissions_emergency_process, sec_permissions_continuous_reduction, sec_permissions_share_securely_third_party, sec_permissions_analyze_cross_account
- `application-security`: sec_appsec_deploy_software_programmatically, sec_appsec_train_for_application_security, sec_appsec_manual_code_reviews, sec_appsec_centralize_services_for_packages_and_dependencies, +sec_appsec_automate_testing_throughout_lifecycle
- `detect-investigate-events` (note only): sec_detect_investigate_events_app_service_logging
- `protect-data-transit` (note only): sec_protect_data_transit_encrypt, sec_protect_data_transit_authentication
- `mitigate-interaction-failure`: rel_mitigate_interaction_failure_throttle_requests, rel_mitigate_interaction_failure_limit_retries, rel_mitigate_interaction_failure_fail_fast, rel_mitigate_interaction_failure_client_timeouts, rel_mitigate_interaction_failure_stateless, +rel_mitigate_interaction_failure_graceful_degradation
- `manage-service-limits` (note only): rel_manage_service_limits_aware_quotas_and_constraints, rel_manage_service_limits_aware_fixed_limits
- `planning-network-topology` (now applicable): +rel_planning_network_topology_ha_conn_users, +rel_planning_network_topology_ip_subnet_allocation, +rel_planning_network_topology_non_overlap_ip
- `dev-integ` (note only): ops_dev_integ_version_control, ops_dev_integ_test_val_chg, ops_dev_integ_conf_mgmt_sys, ops_dev_integ_build_mgmt_sys, ops_dev_integ_share_design_stds, ops_dev_integ_code_quality, ops_dev_integ_freq_sm_rev_chg
- `mit-deploy-risks` (note only): ops_mit_deploy_risks_plan_for_unsucessful_changes, ops_mit_deploy_risks_test_val_chg, ops_mit_deploy_risks_deploy_mgmt_sys
- `networking` (now applicable): +perf_networking_understand_how_networking_impacts_performance, +perf_networking_evaluate_networking_features, +perf_networking_choose_network_protocols_improve_performance, +perf_networking_choose_workload_location_network_requirements
- `data-transfer` (now applicable): +cost_data_transfer_modeling, +cost_data_transfer_optimized_components, +cost_data_transfer_implement_services
- `govern-usage` (note only): cost_govern_usage_policies, cost_govern_usage_controls, cost_govern_usage_groups_roles, cost_govern_usage_track_lifecycle, cost_govern_usage_goal_target
- `sus_hardware`: sus_sus_hardware_a2, sus_sus_hardware_a4, +sus_sus_hardware_a3

Not in this set (section 11): `protect-compute`, `incident-response`, `monitor-aws-resources`, `decomissioning-resources`, and the second pass on `permissions`, `network-protection`, `protect-data-transit` and `mitigate-interaction-failure`.

Then the owner runs a read-only `get-lens-review`; the counts go into the ADR "Overall" table. At close-out (after 9.2, 9.4 and 9.6 are checked):

```
aws wellarchitected create-milestone --workload-id <WORKLOAD_ID> \
  --milestone-name "phase-9-demo-console-complete"
```

## 10. Choice IDs checked

The planner named choices in short form. Every one maps to a real ID (read with `get-answer` on 2026-11-14). None was missing.

| Plan name | Real choice ID |
|---|---|
| `create_layers`, `layered` | `sec_network_protection_create_layers`, `sec_network_protection_layered` |
| `graceful_degradation` | `rel_mitigate_interaction_failure_graceful_degradation` |
| `emergency_levers` (later) | `rel_mitigate_interaction_failure_emergency_levers` |
| `ha_conn_users`, `ip_subnet_allocation`, `non_overlap_ip` | `rel_planning_network_topology_ha_conn_users`, `..._ip_subnet_allocation`, `..._non_overlap_ip` |
| `understand_how_networking_impacts_performance` | `perf_networking_understand_how_networking_impacts_performance` |
| `evaluate_networking_features` | `perf_networking_evaluate_networking_features` |
| `choose_network_protocols` | `perf_networking_choose_network_protocols_improve_performance` |
| `choose_workload_location` | `perf_networking_choose_workload_location_network_requirements` |
| `modeling`, `optimized_components`, `implement_services` | `cost_data_transfer_modeling`, `..._optimized_components`, `..._implement_services` |
| `a3` (title "Use instance types with the least impact") | `sus_sus_hardware_a3` |
| `lifecycle` (later) | `sec_permissions_lifecycle` |

Two notes. The choice titles confirm the plan: `sus_sus_hardware_a3` is "Use instance types with the least impact". `network-protection`, `planning-network-topology`, `networking` and `data-transfer` have an empty selected set today, so the `+` choices are the entire new set.

## 11. Writes after the live run (step 6, not now)

These wait for PR F, the 9.6 live check and build step 5. Their note texts are written then, from the measured results. Nothing here is run now.

- `protect-compute` (now not applicable): +`sec_protect_compute_validate_software_integrity`, +`sec_protect_compute_reduce_manual_management` (both IDs confirmed with `get-answer` on 2026-11-14; the command passes `--is-applicable`). Vulnerability management stays unselected.
- `network-protection`, `protect-data-transit`: note update with the build step 5 results (TLS floor, Viewer settings paths).
- `mitigate-interaction-failure`: +`rel_mitigate_interaction_failure_emergency_levers`, after PR 3 and the build step 5 test.
- `permissions`: +`sec_permissions_lifecycle`, after PR 3.
- `incident-response`: note after PR 3. `monitor-aws-resources`: note after PR 2. `decomissioning-resources`: note after the live teardown. Current sets for these were not read in this pass.

## 12. Proposed WA Tool note texts (added by the executor)

Each block is a complete, ready-to-run command for the owner, to run after ADR 0026 is accepted. The note is read from a quoted heredoc, because several notes contain apostrophes. The length check stays in each block and skips the command when the note is too long. Every note is at most 2,084 characters; the length is shown in the heading. Where a note existed, its earlier text is kept and the Phase 9 text is added or replaces the stale line. The selected choices are the full sets from section 9, verified with `get-answer` on 2026-11-14 (read-only).

Run `export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1` first. Replace `<WORKLOAD_ID>` with the ID from `list-workloads`. `update-answer` writes to the live workload. These are the only Tool writes in this set.

### `network-protection` (901 characters)

```
W=<WORKLOAD_ID>
q=network-protection
NOTE=$(cat <<'EOF'
Phase 1: no VPC existed, so this question was marked not applicable. That reason stopped being true in Phase 3 (ADR 0007), and Phase 9 added a public internet edge. Layers: CloudFront in front of a private S3 bucket (origin access control, plus an explicit deny on artifacts/*; PR #154 verified a 403); an HTTP API where /api/* is https-only, needs a Cognito JWT with the openid scope, and is throttled at 1 request per second with a burst of 3; sign-in is invite-only. Traffic between layers is limited by design: the per-session host has no public IP and no key pair, accepts port 3000 only from the CloudFront service security group, and sends egress on 443 only. That host is in code and has not run live yet (ADR 0026, PR F). Not claimed: no AWS WAF, no inspection-based protection, no automated network protection. The CloudFront Free flat-rate plan is deferred until a trigger fires (ADR 0026).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --is-applicable --selected-choices sec_network_protection_create_layers sec_network_protection_layered \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `identities` (1069 characters)

```
W=<WORKLOAD_ID>
q=identities
NOTE=$(cat <<'EOF'
MFA on both root and cerberus-admin; every workload role (ingestion/transform/serving) is assumed via STS for temporary credentials, never long-lived keys; ADR 0003 deliberately ensures no secret-shaped data (unmasked PANs, etc.) exists anywhere in the pipeline, so there's nothing to store. Phase 5 extended 'temporary credentials' to a new machine-identity class: GitHub Actions authenticates via OIDC federation, minting short-lived STS credentials per workflow run, scoped by the token's repository/ref claims -- no AWS access key is ever stored in GitHub. Phase 9: the local Grafana for the demo uses short-lived read-only credentials from the role cerberus-grafana-read (12 h sessions), not static keys (#126). Console visitors sign in through Cognito: invite-only, admin-create only, admin-only recovery, 12-character password policy; MFA is off for them (accepted in ADR 0026: read-only and throttled). No centralized identity provider for the admin user and no credential rotation cadence: the IAM user's access keys are not rotated, so this stays an open gap.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sec_identities_enforce_mechanisms sec_identities_unique sec_identities_secrets \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `permissions` (1462 characters)

```
W=<WORKLOAD_ID>
q=permissions
NOTE=$(cat <<'EOF'
7.3 (2026-09-29): cerberus-admin's AdministratorAccess replaced with 6 scoped policies built from real CloudTrail history (continuous_reduction, reinforced). The root-console break-glass path used to push corrected policy versions (documented in iam/cerberus-admin/README.md) is now this project's defined emergency access process for the one identity that cannot self-service its own permissions. Phase 8 (note only, no new choice): new grants are scoped. cerberus-spark may delete only under bronze payments_bulk/ (terraform/modules/iam_spark); Cluster Autoscaler IRSA and the FIS role are limited by resource tag; a read-only CloudWatch metrics grant went to cerberus-admin through the same root-console path (2026-10-25). Phase 9 (note only, no new choice): the console roles are scoped. cerberus-console-cli can read Step Functions, use one Athena workgroup and read gold table metadata only, and its only writes are Athena query start and stop in that workgroup and S3 puts under the results prefix (4 actions, pinned by tests). cerberus-grafana-read has AMP query plus CloudWatch read. The command Lambda's inline policy covers its own log group only. CI manages the console roles through the ManageConsoleIamRoles grant. cerberus-admin got the console-edge and console-host policies; console-edge is 4,730 of 6,144 non-whitespace characters. The lifecycle choice (manage access based on lifecycle) waits for the invite lifecycle runbook (ADR 0026, PR 3).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sec_permissions_define sec_permissions_least_privileges sec_permissions_emergency_process sec_permissions_continuous_reduction sec_permissions_share_securely_third_party sec_permissions_analyze_cross_account \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `application-security` (768 characters)

```
W=<WORKLOAD_ID>
q=application-security
NOTE=$(cat <<'EOF'
terraform apply is the only deployment path; courses-map-to-phases.md is deliberate security/cloud training; every ADR was reviewed before being marked Accepted, and article.md drafts get reviewed before publishing; requirements.txt pins dependency versions. No automated security testing or pipeline (Phase 5) -- real gap. Phase 9 (#160): the console safety suite is automated testing in CI: 833 console tests plus 2 strict xfails, a hostile-input corpus, seeded fuzzing, the edge and IAM configuration pinned by tests, and 5 deliberate mutation checks that were each caught. ruff security (S) rules run in CI. Not claimed: penetration testing (the 9.6 live check is a walkthrough, not a penetration test) and regular assessment of the pipelines' security properties.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sec_appsec_deploy_software_programmatically sec_appsec_train_for_application_security sec_appsec_manual_code_reviews sec_appsec_centralize_services_for_packages_and_dependencies sec_appsec_automate_testing_throughout_lifecycle \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `detect-investigate-events` (698 characters)

```
W=<WORKLOAD_ID>
q=detect-investigate-events
NOTE=$(cat <<'EOF'
Phase 1: systemd journal logging existed for the ingestion and transform scripts. Pipeline alarms notify through one SNS topic (terraform/modules/observability/alarms.tf). Phase 9: the console API writes an access log keyed by the Cognito sub, kept 30 days, and the command Lambda logs to its own log group. In the 9.5 live check (2026-11-12) every log entry had a sub. Gaps, stated plainly: no CloudFront standard logs; Grafana logs go to the console and die with the session instance; and there is still no CloudTrail trail (aws cloudtrail describe-trails returned none on 2026-11-13). Not claimed: central log aggregation, correlation and enrichment of security events, or automated remediation.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sec_detect_investigate_events_app_service_logging \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `protect-data-transit` (752 characters)

```
W=<WORKLOAD_ID>
q=protect-data-transit
NOTE=$(cat <<'EOF'
All AWS API calls use TLS and SigV4 request signing by default. Phase 9: CloudFront redirects HTTP to HTTPS, /api/* is https-only, the origin connection to API Gateway uses TLSv1.2, and Strict-Transport-Security is set for one year. The edge uses the default *.cloudfront.net certificate, so there is no custom TLS policy. CloudFront reportedly allows TLSv1 with that certificate (a secondary source, not AWS documentation, not measured for this account). The floor is measured with openssl s_client in ADR 0026 build step 5 and recorded after that. The CloudFront-to-session-host hop is HTTP on port 3000 over a VPC origin (in code, not run live yet). Key and certificate management is not selected: a custom certificate waits for a domain (ADR 0024).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sec_protect_data_transit_encrypt sec_protect_data_transit_authentication \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `mitigate-interaction-failure` (1321 characters)

```
W=<WORKLOAD_ID>
q=mitigate-interaction-failure
NOTE=$(cat <<'EOF'
Athena bytes-scanned cutoff (throttle); per-state retries that are idempotency-aware not blanket (4.3 -- InvokeIngestion none per ADR 0005, RunTransform/RunDbt twice); every job stateless and full-rebuild-re-runnable (1.7/1.9/1.11); explicit per-state client timeouts tuned to each downstream (4.3 -- 120/2100/900/300s). Phase 6 adds FAIL FAST AND LIMIT QUEUES: 6.3's data-quality tests run inside 'dbt build' (entrypoint_dbt.sh, 'dbt build' not 'dbt run'), so a failed invariant (a duplicate transaction_id, a bad status, a negative amount, an orphan FK) fails the RunDbt task immediately -- the execution stops and pages instead of writing bad data into gold and letting the serving query return it. plan.md's Phase 6 'done when' -- bad data fails the pipeline loudly instead of landing silently -- is this choice. Phase 9 adds GRACEFUL DEGRADATION: each console command reads several sources, and a failed source becomes an 'unavailable' section while the rest of the answer stands (console/cerberus_console/commands.py); API errors fail closed (api.py). The landing page and the terminal stay up while dev-compute and the session are down. The API stage throttle is 1 request per second with a burst of 3. Not claimed yet: emergency levers. ADR 0026 PR 3 writes the runbook, and the choice is added only after a test.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices rel_mitigate_interaction_failure_throttle_requests rel_mitigate_interaction_failure_limit_retries rel_mitigate_interaction_failure_fail_fast rel_mitigate_interaction_failure_client_timeouts rel_mitigate_interaction_failure_stateless rel_mitigate_interaction_failure_graceful_degradation \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `manage-service-limits` (895 characters)

```
W=<WORKLOAD_ID>
q=manage-service-limits
NOTE=$(cat <<'EOF'
Phase 1: service quotas exist but are not tracked or monitored. Phase 8 (8.2, ADR 0020): the limits are known and designed around. Spot and On-Demand vCPU quotas are 32 each; the executor group maximum (4 nodes of 4 vCPU, 16 vCPU) stays inside the Spot quota. Athena limits are handled by architecture: a separate data-quality workgroup and per-query bytes-scanned cutoffs sized for each step (25 GiB shared, 20 GiB data quality; terraform/modules/athena/variables.tf). Still a gap: no quota monitoring or alarm, and no automation to raise limits. Phase 9 (note only): the account Lambda concurrent-executions limit was 10 on 2026-11-13, so the console command Lambda has no reserved concurrency and shares that pool. The stage throttle (1 request per second, burst 3) keeps use under it. Reserved concurrency needs an account limit of at least 102 (terraform/modules/console_edge/variables.tf).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices rel_manage_service_limits_aware_quotas_and_constraints rel_manage_service_limits_aware_fixed_limits \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `planning-network-topology` (831 characters)

```
W=<WORKLOAD_ID>
q=planning-network-topology
NOTE=$(cat <<'EOF'
Phase 1: no VPC existed, so this question was marked not applicable; Phase 3 (ADR 0007) added the VPC. PUBLIC ENDPOINTS: the console's public endpoints are CloudFront and the regional HTTP API, both managed, multi-AZ services. The per-session host is one instance in one AZ and one subnet; that is accepted for a scheduled demo, and it is in code, not run live yet (ADR 0026, PR F). IP ALLOCATION: ADR 0007's dedicated VPC is 10.0.0.0/16 with two AZs and /20 private subnets sized for pod IPs, and Phase 9 added a standalone console subnet outside the public and private ranges (terraform/modules/vpc/variables.tf). NON-OVERLAP: the VPC range is distinct from the account's default VPC (172.31.0.0/16, ADR 0007); no private networks are connected. Not claimed: redundant private connectivity or hub-and-spoke (not needed: one VPC).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --is-applicable --selected-choices rel_planning_network_topology_ha_conn_users rel_planning_network_topology_ip_subnet_allocation rel_planning_network_topology_non_overlap_ip \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `dev-integ` (1319 characters)

```
W=<WORKLOAD_ID>
q=dev-integ
NOTE=$(cat <<'EOF'
Git/GitHub throughout; every subtask verified by running it; Terraform is the config management system; checkpoint.md's Well-Architected reference is a shared design standard; small scoped commits. Phase 5 added GitHub Actions as a real build/deployment management system (terraform-plan/apply, code-ci). Phase 6 adds IMPLEMENT PRACTICES TO IMPROVE CODE QUALITY: 6.3's dbt schema/data-quality tests (not_null, unique, accepted_values, relationships, a custom non_negative) run inside 'dbt build' on every orchestrated run, and 5.3's ruff + sqlfluff lint Python and the dbt models on every PR -- static analysis plus enforced test suites, not just manual review. Not selecting 'fully automate integration and deployment' (envs/dev-compute stays human-run per ADR 0007/0009) or 'use multiple environments' (solo project) -- genuine remaining gaps. Phase 9: the console has a safety suite in CI (#160): 833 console tests plus 2 strict xfails, and 80 Grafana module tests. Edge headers, the JWT route, the throttle, the Cognito client and the write set are pinned by tests, and 5 deliberate mutations were each caught. CI suites run on two Python versions (#159), and the console site publish verifies the response headers. dev-console (the session stack) is never planned in CI (ADR 0011 amendment), so it stays owner-run.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices ops_dev_integ_version_control ops_dev_integ_test_val_chg ops_dev_integ_conf_mgmt_sys ops_dev_integ_build_mgmt_sys ops_dev_integ_share_design_stds ops_dev_integ_code_quality ops_dev_integ_freq_sm_rev_chg \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `mit-deploy-risks` (860 characters)

```
W=<WORKLOAD_ID>
q=mit-deploy-risks
NOTE=$(cat <<'EOF'
terraform plan before every apply; 1.11 tested destroy+apply for real, not just in principle. Phase 5 made 'test deployments' an enforced, automatic step rather than a manual habit -- terraform-plan.yml runs on every PR (posts the plan diff as a PR comment) and code-ci.yml lints/validates the Python and dbt code, both before a merge can happen. Not selecting 'automate testing and rollback' -- rollback is still entirely manual; Phase 5 didn't add any rollback automation. Phase 9: tests pin the security-relevant console settings (edge headers, JWT route, throttle, Cognito client), so a change that weakens one fails CI; 5 deliberate mutations were each caught (#160). The site publish verifies the headers after deploy. The session stack dev-console is not planned in CI, so its first real plan is owner-run (ADR 0011 amendment). Rollback is still manual.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices ops_mit_deploy_risks_plan_for_unsucessful_changes ops_mit_deploy_risks_test_val_chg ops_mit_deploy_risks_deploy_mgmt_sys \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `networking` (828 characters)

```
W=<WORKLOAD_ID>
q=networking
NOTE=$(cat <<'EOF'
Phase 1: no VPC or network layer existed, so this question was marked not applicable; Phase 3 (ADR 0007) added the VPC. Phase 9 made network performance part of the design. UNDERSTAND: the console is latency-visible, so a VPC-origin spike measured wake and destroy times (docs/plans/2026-10-27-vpc-origin-spike.md), and the 9.5 live check measured status at 5.6 s cold and 3.0 s warm. FEATURES: CloudFront with HTTP/3 and IPv6, compression, immutable cached assets, a VPC origin instead of a public IP, and an S3 gateway endpoint for the 430 MB Grafana artifact. PROTOCOLS: http2and3 at the edge and TLSv1.2 to the API origin. LOCATION: PriceClass_100 (North America and Europe) matches a Canadian audience; the stack is single-region. Not claimed: dedicated connectivity or VPN, load balancing, and tuning from network metrics.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --is-applicable --selected-choices perf_networking_understand_how_networking_impacts_performance perf_networking_evaluate_networking_features perf_networking_choose_network_protocols_improve_performance perf_networking_choose_workload_location_network_requirements \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `data-transfer` (819 characters)

```
W=<WORKLOAD_ID>
q=data-transfer
NOTE=$(cat <<'EOF'
Phase 1: single-region, single-account serverless stack, so this question was marked not applicable. Phase 9 added a public edge and a per-session host, so there is now a transfer surface. MODELING: the session cost model counts the data path. The NAT gateway plus its IPv4 address is $0.050 of the $0.068 hourly session cost, about 74% (console session plan; list prices from 2026-10-27, not rechecked). COMPONENTS: CloudFront serves compressed, cached static assets from PriceClass_100, and the command Lambda runs on arm64. SERVICES: an S3 gateway endpoint keeps the 430 MB Grafana artifact download off the NAT per-GB charge. There is still no cross-region or cross-account transfer. Not claimed: a measured transfer bill. The idle cost is not read from a bill yet; two Cost Explorer reads are scheduled (ADR 0026).
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --is-applicable --selected-choices cost_data_transfer_modeling cost_data_transfer_optimized_components cost_data_transfer_implement_services \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `govern-usage` (856 characters)

```
W=<WORKLOAD_ID>
q=govern-usage
NOTE=$(cat <<'EOF'
Phase 1: the Project/Phase/Layer tagging convention is the policy; the billing alarm is the control; the three least-privilege IAM roles are the groups and roles mechanism; Phases.md tracks lifecycle. Phase 7 (7.3): cerberus-admin was cut to scoped policies. Phase 8 (8.2): goals and targets. AWS Budgets alerts at $15 and $20 a month (docs/plan.md budget: $20 a month) and a $0 idle target, checked at each teardown by an account-wide check that no EKS cluster, NAT gateway or EIP remains (ADR 0020). Still a single account by design. Phase 9: cost control at the point of action. orchestration/console_session.sh shows the hourly cost ($0.068, about $0.14 for a 90-minute session) before the y/N prompt, the session host terminates itself, and console_check.sh reads for leftovers after the destroy. dev-console keeps the destroy-leaves-nothing contract.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices cost_govern_usage_policies cost_govern_usage_controls cost_govern_usage_groups_roles cost_govern_usage_track_lifecycle cost_govern_usage_goal_target \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

### `sus_hardware` (580 characters)

```
W=<WORKLOAD_ID>
q=sus_hardware
NOTE=$(cat <<'EOF'
Phase 1: serverless-by-default means the minimum hardware for current demand; S3, Glue, Athena, DynamoDB and IAM are fully managed. Phase 8: the Spark executor nodes are x86 4 vCPU / 16 GiB, and Graviton was never evaluated for them. Phase 9 chose least-impact instance types for all new console compute: the command Lambda is arm64, the per-session host is a t4g.small (arm64), and the Grafana build is arm64. There is no idle host: the session instance terminates itself after its time limit. This closes the Graviton gap for the console only; the Spark executors are still x86.
EOF
)
if [ ${#NOTE} -le 2084 ]; then
  aws wellarchitected update-answer --workload-id $W --lens-alias wellarchitected \
    --question-id $q --selected-choices sus_sus_hardware_a2 sus_sus_hardware_a4 sus_sus_hardware_a3 \
    --notes "$NOTE"
else
  echo "note too long: ${#NOTE}"
fi
```

Longest note: 1462 characters (limit 2,084).
