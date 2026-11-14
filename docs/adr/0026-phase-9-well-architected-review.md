# 26. Phase 9 Well-Architected review

Date: 2026-11-13

## Status

Proposed. The build, the facts and the full note texts are in
[the plan](../plans/2026-11-13-phase-9-well-architected-review.md). The owner
answered the three open questions on 2026-11-14; they are in the Decision.
Milestone 9: see the section below (added at close-out).

## Context

Phase 9 (the demo console) is done except for 9.2 (the live Grafana session),
9.4 (the landing page rebuild), 9.6 (its live check) and this subtask, 9.7.
This review records Phase 9 against the Well-Architected Framework, and it
lists what the live run still has to prove.

**What Phase 9 built.** One line each:

- 9.1: [ADR 0024](0024-demo-console.md) and its two amendments (2026-11-02,
  2026-11-12).
- 9.2: the standing edge (#130), the roles and the console subnet (#125), a
  local Grafana on short-lived credentials (#126), the in-cluster Grafana
  removed (#148), and the session pull requests A to E (#154 to #158).
- 9.3: the command set (#127, #128).
- 9.4: the landing page was rejected on 2026-11-12 (text, not interactive).
  It is being rebuilt as an interactive showcase in a separate session.
- 9.5: the terminal (#149 to #152).
- 9.6: the safety suite (#160).

**Baseline.** The baseline is milestone 8 (`phase-8-scale-validation-complete`,
2026-11-12), at 18 HIGH, 18 MEDIUM, 16 NONE, 5 N/A. The Tool shows the
workload `UpdatedAt` as 2026-11-12 (`list-workloads`, read 2026-11-13). No
answer has changed since milestone 8.

**Why this pass is not like Phase 8's.** Phase 9 made the workload
internet-facing. There is now a public CloudFront edge, a sign-in, an API, and
a per-session EC2 host behind a VPC origin. Five answers are marked N/A:
`network-protection`, `protect-compute`, `planning-network-topology`,
`data-transfer` and `networking`. Their notes say "No VPC/network layer exists
in Phase 1", "No compute to harden ..." and "Single-region, single-account
serverless stack". That has been false since Phase 3 ([ADR
0007](0007-vpc-network-design.md)), and it is plainly wrong now. This pass
answers all five: four now, `protect-compute` after PR F. The count of HIGH answers may therefore rise. If it does,
that means a wider workload, not a worse one: a question that was out of
scope is now in scope and is not yet fully answered.

**Phase 9 IAM changes, recorded here as [ADR
0023](0023-phase-8-well-architected-review.md) asked.**

- Three `cerberus-admin-console-edge` statements: ApiGatewayTags,
  ApiGatewayStageTags and HttpApiLogDelivery (`iam/cerberus-admin/README.md`,
  from L176).
- `cerberus-admin-console-host`.
- The roles `cerberus-console-cli` and `cerberus-grafana-read`
  (`terraform/modules/console_roles/main.tf`, L113-182), and
  `cerberus-console-grafana`, which exists only during a session.
- The CI grant `ManageConsoleIamRoles`
  (`terraform/modules/github_oidc/main.tf`, from L596).
- Policy sizes: `cerberus-admin-console-edge` is 4,730 of 6,144
  non-whitespace characters, and `console-host` is 2,363. `console-edge` is
  the one closer to the limit.

**A correction to ADR 0023.** ADR 0023 said the `identities` note mentions
Grafana and mounted static keys, and that a later subtask would remove that
sentence. The live note was read on 2026-11-13, and it has no such sentence.
So there is no note text to remove, and ADR 0023's record is inaccurate. The
reasoning behind it stands: static keys left the local Grafana with #126
(short-lived read-only credentials, merged 2026-11-09). ADR 0023 gets a
one-line Status note.

**ADR 0024 "To confirm in build", status.**

- Closed: arm64 builds exist (Grafana 13.2.3 at 430,350,990 bytes and plugin
  3.2.0 at 18,143,563 bytes are staged with sha256 metadata, #155); Cognito
  Lite has no managed login, and access tokens validate by `client_id` (2026-11-02
  amendment); the VPC-origin spike times were measured
  (`docs/plans/2026-10-27-vpc-origin-spike.md`); `/logout` clears the hosted
  UI cookie (9.5 live check, 2026-11-12).
- Open, waiting for the live Grafana session (the last build step of
  [the console session plan](../plans/2026-11-12-console-session.md); this ADR
  calls it **PR F**): `generic_oauth` with Cognito and the email placeholder;
  Viewer access to Inspect, and Explore off; the AMP plugin on instance
  credentials; the full-stack wake and destroy times; and `console-check`
  reading 0 after a real session.
- Open, no date: list prices (`pricing:GetProducts` is denied, so the
  2026-10-27 prices were not rechecked) and the bytes scanned by the `status`
  query.

**What depends on the live run.** Several claims in this ADR cannot be
checked until three things happen. Each is marked "live" where it appears.

- PR F: everything marked PR F above and in the pillars below. The session
  host, the Grafana settings and the full-stack timings are in code, and they
  have never run.
- The 9.6 live check, steps 2 to 7: headers by curl, the 401 responses, the
  GET status, the refusals with their `sub`, the IAM deny check, and
  `live.json` absent after the destroy.
- The new 9.7 live checks (build step 5 in the plan): the TLS floor on both
  distributions, the Grafana Viewer settings paths, the disabled-user token
  test, the Grafana CSP, and any CloudFront 504 on the long query windows.

**The decision drivers.** Security (the internet edge) and Cost ($0 idle,
$20 a month). They pull against each other: real edge protection costs
money, or it lives outside Terraform.

## Decision

**Decision 1: answers that are proven now, and answers that wait.** An answer
changes now only if its evidence is in merged code **and** has a live or CI
result. That covers the 9.5 live check, the merged pull requests #154 to #160,
the tests, and the read-only AWS reads of 2026-11-13. An answer whose evidence
is a session that has never run waits for PR F. This follows ADR 0023,
Decision 2: milestones cannot be edited, so the record must match what was
shipped.

The Tool writes happen in three passes:

1. The "now" set, after this ADR is accepted.
2. The "live" set, after PR F, the 9.6 live check and the build step 5 results.
3. Milestone 9, last.

**Decision 2: answer the five N/A questions.** Four have standing evidence
and are answered now: `network-protection`, `planning-network-topology`,
`data-transfer` and `networking`. `protect-compute` waits for PR F, because
its only host has never booted. The Tool decides the buckets. This ADR
predicts no counts.

**Owner answers (2026-11-14).**

1. Milestone 9 waits for 9.2, 9.4 and 9.6, including the 9.4 interactive
   rebuild. It is saved only in the close-out PR, because the name says
   "complete".
2. Two always-on CloudWatch alarms are accepted (PR 2, below), together with
   one root-console paste of `cloudwatch:DescribeAlarms` to
   `cerberus-admin-console-edge`. The cost of $0 is an estimate: the free tier
   is 10 standard alarm metrics (from memory of the pricing page, not
   rechecked), and the live alarm count is unknown because
   `cloudwatch:DescribeAlarms` is denied today. Unverified.
3. Edge protection: the CloudFront Free flat-rate plan is deferred, with the
   trigger in Security gap 1. There is no spike now.

**Options considered for timing.**

- Everything now (answers and milestone 9). Rejected: it writes unverified
  session claims into the Tool, and a milestone cannot be edited.
- Wait for the live run, then do everything. Rejected: it delays this ADR,
  which is the list of what the live run must prove.
- Verified answers now, live-dependent answers after the live run, milestone
  last. Chosen.

### Pillar by pillar

Each pillar lists what is good, the gaps, and a decision per gap.

#### Security (the driving pillar)

**What is good.**

- The console is "not a shell" by construction. Rules 1 to 9 are pinned by 833
  console tests plus 2 strict xfails, and 5 mutation checks were each caught
  (#160).
- CloudFront reads S3 through origin access control, with an explicit deny on
  `artifacts/*`. PR #154 verified a 403. The API route needs a JWT with the
  `openid` scope. The CSP is strict (no `unsafe`, `frame-ancestors 'none'`),
  HSTS is one year, and `nosniff`, `DENY`, `no-referrer` and a
  Permissions-Policy are set (`terraform/modules/console_edge/main.tf`,
  L94-119 and L157-207).
- Sign-in is invite-only: Cognito admin-create only, `admin_only` recovery, a
  12-character password policy, and deletion protection on the pool.
- `cerberus-console-cli` reads gold metadata only, and its write set is
  exactly four actions, pinned by `console/tests/test_edge_config.py`:
  `athena:StartQueryExecution` and `athena:StopQueryExecution` on the console
  workgroup, and `s3:PutObject` and `s3:AbortMultipartUpload` on the results
  prefix only (`console_roles/main.tf`). Errors fail closed (`api.py`
  L64-80).
- Depends on PR F: the session host has no key pair and no public IP, uses IMDSv2 with a
  hop limit of 1, accepts port 3000 only from the CloudFront service security
  group, allows egress on 443 only, and checks artifacts by sha256 at boot. This
  is in code (`terraform/envs/dev-console/main.tf`, `user_data.sh.tftpl`) and
  has not run.
- The client secret never touches S3, tags or user data (console session plan,
  option 4.2 A). No static keys are mounted in the local Grafana (#126), and no
  new file carries the account ID.

**Gaps and decisions.**

1. *No WAF and no rate limit on static paths.* The API throttle (1 request per
   second, burst 3) is stage-wide (2026-11-02 amendment). **Accept.**
   **Defer** the CloudFront Free flat-rate plan. It reportedly costs $0 a
   month and includes WAF with IP-based rate limiting, but it is outside
   Terraform, the web ACL cannot be removed while the plan is attached, and a
   subscribed distribution cannot be deleted until the plan is cancelled
   (AWS documentation). Eligibility for this account is unverified. Pay-as-you-go
   WAF is about $5 a month per web ACL plus $1 per rule (list price from
   memory, unverified), which breaks $0 idle and uses about 30% of the budget.
   *Trigger:* invites go beyond a handful (ADR 0024's trigger), or a month's
   CloudFront requests are not explained by invites, or a Terraform (or
   `awscc`) resource for the subscription exists. Run a $0 spike before
   adopting the plan.
2. *Default certificate: no TLS policy.* CloudFront reportedly ignores
   `minimum_protocol_version` on the default `*.cloudfront.net` certificate and
   allows TLSv1. The source is a CDK issue, not AWS documentation. **Accept.**
   *Trigger:* a domain (ADR 0024). **Live:** measure the floor with
   `openssl s_client` in build step 5.
3. *Logging.* There are no CloudFront standard logs, the Grafana logs go to
   the console and die with the instance (`[log] mode = console`), and there
   is no CloudTrail trail (`describe-trails` returned none on 2026-11-13).
   **Defer** CloudFront logs with gap 1's trigger. The trail stays as
   ADR 0023 follow-up 14. **Accept** the Grafana logs: Viewer only, session
   only.
4. *MFA is off for visitors, and a disabled user's access token may still pass
   the JWT authorizer until `exp`* (at most 60 minutes; unverified). **Accept**:
   the console is read-only, throttled and invite-only. **Live:** measure the
   token behaviour in build step 5.
5. *No written emergency levers or invite lifecycle.* **Fix now** (PR 3).
6. *The session distribution sends no CSP.* It uses
   `Managed-SecurityHeadersPolicy` (`terraform/envs/dev-console/edge.tf`,
   L29-31 and L139). **Defer to PR F:** try Grafana's
   `[security] content_security_policy` in the second, full session. Keep it
   if the dashboards load. Otherwise accept the risk and say why.
7. *Two redaction gaps* (the strict xfails at `console/tests/test_sanitize.py`,
   L81-89). **Accept**: no command output carries an ARN today, because the
   execution ARN is used only internally and error codes are capped at 64
   characters. *Trigger:* any new output field that carries ARNs or S3 URIs
   (the Phase 10 series, the agent text in ADR 0025).
8. *The five stale N/A answers.* **Fix now** (Decision 2).

**Tool changes, now.**

- `network-protection`: now applicable; add create layers and control traffic
  within layers.
- `identities`: note only. It stays open: keys are not rotated.
- `permissions`: note only now; the lifecycle choice follows PR 3.
- `detect-investigate-events`: note only. Replace the Phase 1 text with the
  API access log keyed by `sub` and "still no trail".
- `protect-data-transit`: note only. The TLS floor result is added after build
  step 5.
- `application-security`: add automated testing through the lifecycle (the
  #160 safety suite). Penetration testing and pipeline assessment are not
  claimed.
- `incident-response`: a note after PR 3.

**Tool changes, after PR F.** `protect-compute`: validate software integrity
and reduce manual management. Vulnerability management stays unselected,
because there is no scanning, only the newest AMI per session.

#### Reliability

**What is good.**

- The standing path is managed, multi-AZ services with no host to patch.
- Graceful degradation per section: a failed source becomes an "unavailable"
  section while the rest of the answer stands (`commands.py` L87-92 and
  L129-344). The terminal and the landing page stay up while `dev-compute`
  and the session are down.
- Fixed timeouts and caches (2026-11-02 amendment).
- Teardown has layers: the EXIT trap, `setsid`, a retry with `-refresh=false`,
  the host terminating itself, `console_check.sh`, and Budgets
  (`orchestration/console_session.sh`, L154-170). The traps are set before the
  apply. The `setsid` test passed (#158), and the same fix went into
  `exercise.sh` (#159).
- Pool deletion protection is on, and the site rebuilds from git.

**Gaps and decisions.**

1. *No alarm covers the console Lambda or API.* All alarms are in
   `terraform/modules/observability/alarms.tf`: 7 resources, 5 of them gated
   on `pipeline_active`. **Fix now** (PR 2, accepted by the owner).
2. *The Lambda concurrency pool is shared.* The account limit is 10 (read
   2026-11-13), and there is no reservation. **Accept** (2026-11-02
   amendment). *Trigger:* the limit reaches at least 102.
3. *The session is one AZ and one instance.* **Accept** for a scheduled demo.
4. *A dead trap is found only by Budgets*, with a lag of up to about a day. A
   dead trap costs about $1.20 a day (console session plan). **Fix now**
   (PR 3): `make console-check` runs in `/start-day`, which is read-only and
   catches a dead trap within a day. **Defer** a standing reaper (a Scheduler
   plus a Lambda with `ec2:DeleteNatGateway`), because it is a new standing
   write role and a drift against the `dev-console` state. *Trigger:* the
   first dead trap, or more than 4 sessions a month.
5. *CloudFront's 30 s origin timeout on heavy AMP queries.* **Live (PR F).**
6. *A stale `live.json`.* The reader must hide the link once `ends` has
   passed (`console/README.md`, L195-213). This is a **gate on the 9.4
   rebuild**: its review must check the `ends` handling.

**Tool changes, now.**

- `mitigate-interaction-failure`: add graceful degradation. Emergency levers
  follow PR 3 and the build step 5 test.
- `manage-service-limits`: note only (limit 10, throttle under the limit).
- `planning-network-topology`: now applicable; add highly available public
  endpoints (CloudFront and the regional API; the single-AZ session is
  stated), IP subnet allocation and non-overlapping IP ranges.
- `monitor-aws-resources`: a note after PR 2.

#### Operational Excellence

**What is good.**

- One command per session, with a preflight and the cost shown before the
  y/N prompt (`console_session.sh`, L210-213).
- A read-only check, `console_check.sh`: a value it cannot read fails the
  check. A live `console_check` printed all counts 0 and `distributions_total`
  1 (#158).
- The publish verifies the response headers. One plan per step, and CI suites
  on two Python versions (#159 and #160).

**Gaps and decisions.**

1. *`dev-console` is never planned in CI* (ADR 0011 amendment), so its first
   real plan is owner-run. 20 resources are expected and the offline validate
   passed (#157), but `console-plan` has not run. **Accept.**
2. *The first session is also the first test of the Grafana ini keys.* Several
   key names in `grafana.ini.tmpl` are marked "unverified". **Accept:** PR F
   starts with `MINUTES=30`.
3. *`cerberus-admin` cannot read alarms.* **Fix with PR 2:** one root-console
   paste of `cloudwatch:DescribeAlarms` (read) into `console-edge`. The policy
   is 4,730 of 6,144 non-whitespace characters today. Its size after the paste
   is unverified; the PR 2 check must confirm it stays under the limit.

**Tool changes.** `dev-integ` and `mit-deploy-risks` get a note about the
safety suite and its mutation checks. The choice titles were confirmed with
`get-answer` before any new choice was proposed.

#### Performance Efficiency

**What is good.** `PriceClass_100` (North America and Europe, which matches a
Canadian audience), HTTP/3, compression, immutable cached assets, result
reuse, an arm64 Lambda, and an S3 gateway endpoint for the 430 MB artifact.

**Gaps and decisions.**

1. *`status` takes 5.6 s cold and 3.0 s warm* (9.5 live check). **Accept.**
   Provisioned concurrency and SnapStart both bill while idle. *Trigger:* the
   Phase 10 status series in AMP (`Phases.md`, 9.3).
2. *The full-stack wake time is unmeasured.* **Live (PR F).** ADR 0024's
   20-minute trigger stands.

**Tool changes.** `networking`: now applicable; add understanding how
networking affects performance, evaluating networking features, choosing
network protocols, and choosing the workload location.

#### Cost Optimization

**What is good.**

- $0 idle by design, one line per resource (ADR 0024 table).
- A session costs about $0.068 an hour and about $0.14 for 90 minutes. The
  cost is shown before the y/N prompt. The list prices are from 2026-10-27
  and were not rechecked.
- The S3 gateway endpoint keeps the artifact download off the NAT per-GB
  charge.
- The worst month at the throttle is about $3.4 to $7.7 (2026-11-02
  amendment). The November forecast is about $12.7 of $20.

**Gaps and decisions.**

1. *The idle cost has not been read from a bill* (ADR 0024). **Fix
   (scheduled):** one Cost Explorer read in early December for 9 to 30
   November, and one in early January for December. That is 2 requests at
   $0.01 each (list price).
2. *A flood of static pages is bounded only by Budgets.* Same as Security
   gap 1.
3. *The NAT and its IPv4 address are $0.050 of the $0.068 hourly cost*, about
   74%. **Accept:** the token endpoint needs internet (ADR 0024).
4. *The list prices are from 2026-10-27.* **Accept:** the owner reads the
   public pricing pages once before the milestone.

**Tool changes.** `data-transfer`: now applicable; add modeling, optimized
components and implemented services. `govern-usage`: a note (cost at the point
of action).

#### Sustainability

**What is good.** Graviton for every new compute (the command Lambda and the
session host); no idle host; a 10 KB DOM terminal against 496 KB for xterm.js
(2026-11-12 amendment); cached static assets.

**Gap.** Each session downloads 430 MB. **Accept:** a baked AMI would bill
snapshot storage while idle.

**Tool changes.** `sus_hardware`: add "Use instance types with the least
impact" (the title is confirmed with `get-answer`). This partly closes ADR
0023's "Graviton never evaluated" gap, for the console only. The Spark
executors are still x86.

**Amends: none.** This ADR amends no earlier ADR, and it does not contradict
ADR 0024 or its two amendments. ADR 0023 gets a one-line Status note:
"Milestone 8's identities point corrected by ADR 0026."

## Overall

The table is filled after the "now" answers are written and the Tool is read
back (`get-lens-review`). No count is predicted here.

| Pillar | Milestone 8 HIGH | After the 9.7 answers HIGH |
|---|---|---|
| Operational Excellence | 6 | |
| Security | 5 | |
| Reliability | 5 | |
| Performance Efficiency | 0 | |
| Cost Optimization | 2 | |
| Sustainability | 0 | |
| **Total (HIGH / MEDIUM / NONE / N/A)** | 18 / 18 / 16 / 5 | |

The Milestone 8 column is from ADR 0023 (per-pillar HIGH, confirmed by
`list-answers` on 2026-11-14). The other column stays empty until the Tool is
read back.

## Consequences

Each item names the owner phase where one exists.

1. *The live-dependent list.* PR F, the 9.6 live check and build step 5
   (above). Phase 9.
2. *Milestone 9 timing.* It waits for 9.2, 9.4 and 9.6, including the 9.4
   rebuild (owner answer 1).
3. *The CloudFront Free flat-rate plan or WAF.* Deferred until the Security
   gap 1 trigger fires; spike first.
4. *CloudFront logs.* Deferred with the same trigger.
5. *The TLS floor and a domain.* Measure the floor in build step 5; a domain
   is the trigger for a custom policy.
6. *The standing reaper.* Deferred until the first dead trap, or more than 4
   sessions a month.
7. *Reserved concurrency.* Revisit when the account limit reaches at least
   102.
8. *The redaction xfails.* Revisit when any output field carries ARNs or S3
   URIs (the Phase 10 series, ADR 0025).
9. *Grafana CSP and the ini keys.* Settled in PR F.
10. *Grafana audit trail.* Accepted: the logs die with the instance.
    *Trigger:* invites beyond a handful.
11. *MFA off.* Accepted. *Trigger:* invites beyond a handful.
12. *The Cost Explorer reads.* Early December and early January.
13. *Carried from ADR 0023:* the CloudTrail trail (item 14), the stale
    workload description (item 9), the Data Analytics Lens (item 10, deferred
    again: it is about analytics, not the console) and key rotation.
14. *The 9.4 rebuild must honour `ends`* in `live.json`.

**Given up.** No edge WAF, no custom TLS policy, no Grafana audit trail after
the destroy, one AZ for the session, and HIGH may rise.

The build steps (PR 2 with two alarms, PR 3 with the runbook and
`console_check.sh`, and the owner's live checks) are in the plan, section 7.

## Milestone 9 (added at close-out)

The counts, the Cost Explorer readings, and the outcomes of PR F and the 9.6
live check go here when milestone `phase-9-demo-console-complete` is saved.
