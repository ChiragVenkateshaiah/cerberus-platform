# Plan: the demo console (Phases.md 9.1, ADR 0024)

Date: 2026-10-27. Planner: Opus. Status of the ADR it produces: Proposed; accepted 2026-10-27.

**User decisions (2026-10-27):** (1) live Grafana is built per demo (`envs/dev-console`, $0 idle), not a stopped instance; (2) one invited Cognito account per visitor, created by the owner with `admin-create-user`, no emails in the repo; (3) AMP retention goes from 90 to 400 days.

## 1. Question

How should Cerberus show itself in a browser to someone who will not read the repo? That means the host, the terminal tool, the edge and sign-in, the data shown while `dev-compute` is down, and which Grafana is the shared one. It must cost $0 when idle and must not hand a visitor a shell.

Why now: Phase 8 ends with the 8.10 video (31 Oct / 1 Nov). 9.1 is the next subtask. ADR 0021 and ADR 0022 both left "where the shared Grafana runs" to 9.1. ADR 0023 (accepted today) lists "remove the in-cluster Grafana (9.1)" and "a read-only Grafana role (9.2)" as follow-ups.

## 2. Facts

Repo:

- F1. Phases.md L154-173: the 9.1-9.7 text. 9.2 asks for "the console instance (start/stop, tagged, read-only IAM role, no public inbound port), the CloudFront + Cognito (or SSO tunnel) edge, and `make console-up` / `make console-down`". 9.5 asks for "a session time limit and an idle auto-stop".
- F2. docs/plan.md L321-364 (Phase 9):
  - Stack: "one small EC2 instance that starts and stops on demand ... so it costs cents"; ttyd or xterm.js; CloudFront + Cognito or an SSO tunnel; Grafana fed by AMP and the run records; Python commands now, `cerberusctl` in Phase 12.
  - Out of scope: a real shell, any write or run-control command, accounts beyond the demo sign-in.
  - Done when: a signed-in visitor, from a clean browser, sees the architecture, the latest run and the dashboards, and runs each allowlisted command; escape and injection tests pass in CI; the stack costs $0 when stopped.
- F3. ADR 0021, Decision: Grafana provisioning must be portable repo files. Local Compose "stays as the development loop". "Where the shared Grafana runs is Phase 9's decision (9.1) ... one Grafana, not two." `make status` (10.5) "must be the same code as Phase 9's `cerberus status` (9.3)". Revisit if 9.1 picks a host that cannot read the provisioned files.
- F4. ADR 0022: local Compose Grafana 13.2.3 with AMP plugin 3.2.0 on `127.0.0.1:3000`, reading AMP and CloudWatch with the mounted `~/.aws` (`observability/grafana/compose.yaml` L35). The amendment adds:
  - the story dashboard;
  - run annotations posted by `exercise.sh` with an Editor service-account token (`cerberus-exercise`).

  Annotations "live in the Grafana volume, not in git". Its follow-ups are a read-only Grafana role and removing the in-cluster Grafana in 9.1.
- F5. ADR 0023, Consequences 3: "A read-only Grafana role (9.2). Remove the in-cluster Grafana (9.1)." `identities` stays HIGH, partly because static admin keys are mounted into the local Grafana. Consequence 14: no CloudTrail trail.
- F6. ADR 0016, Decision: "Viewing: Grafana in-cluster", amended by ADR 0022. The in-cluster Grafana is still built:
  - `terraform/modules/eks_observability/main.tf` L93-140: IRSA role `cerberus-grafana` with AMP query and CloudWatch read;
  - same file, L474-560: `helm_release.grafana`.
- F7. AMP retention is 90 days: `terraform/modules/prometheus_workspace/variables.tf` L1-2 and `main.tf` L32. ADR 0022 says the 2026-10-13 100M run stays in AMP "until about 2027-01-11".
- F8. All three dashboards default to the last 30-60 minutes (`observability/grafana/dashboards/*.json`, `.time`):
  - `cerberus-run-story.json` has 7 AMP panels, 2 Grafana annotation panels and 1 Mixed panel (CloudWatch metric math, per the ADR 0022 amendment);
  - `cerberus-run-live.json` and `spark-on-eks.json` each have one CloudWatch panel.

  With `dev-compute` down they are empty unless they are opened on a past run's window.
- F9. Datasource provisioning is shared by uid (`amp`, `cloudwatch`) between the local and in-cluster Grafanas (`observability/grafana/provisioning/datasources/local.yaml`).
- F10. The run records (`observability/scale/runs/*.json`, 14 files) hold `execution`, `states`, `cost`, `data_quality`, `events_processed`, `run_seconds`, `status`, `storage_snapshot` and other fields. They are permanent and in git.
- F11. Network (`terraform/modules/vpc/main.tf`):
  - the VPC (10.0.0.0/16, IGW, two public and two private subnets, S3 gateway endpoint) is in `dev-standing`;
  - the NAT gateway is in `dev-compute` (`terraform/modules/vpc_nat/main.tf`);
  - the private route table has no NAT route unless `dev-compute` is up.

  ADR 0007 gives NAT at about $0.045/h plus per GB.
- F12. ADR 0011 and `terraform/envs/dev-standing/main.tf` header: two roots. `dev-standing` is CI-applied, with zero idle cost. `dev-compute` is human-run and destroyed after each exercise.
- F13. The API Gateway HTTP API pattern already exists: `terraform/modules/lineage/main.tf` L172-200 (ADR 0013). `cerberus-ci-apply` already has `apigateway:*` on `/apis` (`terraform/modules/github_oidc/main.tf`, Sid `ManageLineageApi`). It has no CloudFront, Cognito or EC2-instance statements (Sid list, same file).
- F14. GitHub Pages already hosts the project's public front page (`docs/pages/index.html`, deployed by `.github/workflows/dbt-docs.yml`; linked in README L54, L349-350).
- F15. `orchestration/exercise.sh` L188-200: the account-wide check after destroy counts EKS clusters, NAT gateways, EIPs and running instances. If any is non-zero, it warns.
- F16. `cerberus-admin` policy files (`iam/cerberus-admin/policies/`): there are six. `cerberus-admin-iam-and-governance.json` is 5,954 bytes, close to the 6,144-character managed-policy limit.
- F17. Month forecast is about $17.2 against $20, including the 8.10 take (ADR 0022 Consequences).

AWS (read-only, `cerberus-admin`, us-east-1, 2026-10-27):

- F18. `ec2 describe-instances` returned no instances. VPCs: the default `172.31.0.0/16` and `cerberus-platform-vpc` `10.0.0.0/16`. The only VPC endpoint is the S3 gateway.
- F19. AccessDenied for `cerberus-admin` on:
  - `cloudfront:ListDistributions`
  - `cognito-idp:ListUserPools`
  - `ec2:DescribeManagedPrefixLists`
  - `ec2:DescribeImages`
  - `ssm:GetParameter` (AMI alias)
  - `route53:ListHostedZones`

  So a custom domain is unknown, and 9.2 needs a root-console policy change.

External (docs read 2026-10-27):

- F20. CloudFront VPC origins: ALB, NLB or EC2 instances in private subnets. The VPC needs an IGW. A VPC origin points at the resource's ARN. Creating or updating one "can take up to 15 minutes". An origin must be disassociated before it can be updated. Origin-request and origin-response Lambda@Edge are not supported. Ingress comes from the CloudFront prefix list or the service-managed SG. ([docs](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)) Whether a public-subnet instance works is not documented ([re:Post thread](https://www.repost.aws/questions/QU-_-44OsPRYmHT8VVtemoEw/cloudfront-504-gateway-timeout-for-ec2-vpc-origin-ipv6-private-ipv4)).
- F21. App Runner has been closed to new customers since 2026-04-30 ([AWS](https://docs.aws.amazon.com/ja_jp/apprunner/latest/dg/apprunner-availability-change.html)).
- F22. Cognito Lite and Essentials include 10,000 free MAU for direct sign-in ([pricing](https://aws.amazon.com/cognito/pricing/)). Whether Lite includes managed login is unverified.

List prices used below (us-east-1). Recheck them in 9.2; they are not read from a bill:

| Item | Price |
|---|---|
| t4g.small | $0.0168/h |
| NAT gateway | $0.045/h + $0.045/GB |
| Public IPv4 | $0.005/h |
| gp3 | $0.08/GB-month |
| API Gateway HTTP API | $1.00 per million requests |
| CloudWatch `GetMetricData` | $0.01 per 1,000 metrics |
| Athena | $5/TB, 10 MB minimum per query |
| Cost Explorer API | $0.01 per request |

## 3. Constraints

- $0 idle and no idle billed resources (user, 2026-10-27; Phases.md 9.1). Budget $20/month, about $17.2 forecast.
- `dev-compute` keeps its destroy-leaves-nothing contract and must not change before the 8.10 take (31 Oct / 1 Nov).
- CI applies `dev-standing` only. `cerberus-ci-apply` cannot edit its own policy, so the first apply of new resource types runs locally as `cerberus-admin` (the ADR 0016 precedent). `cerberus-admin` changes go through the root console (`iam/cerberus-admin/`).
- Public repo: no visitor emails, passwords or tokens in Terraform or git.
- ADRs this one must amend by name: 0007 (a console subnet and a session NAT), 0011 (a third root), 0016 (in-cluster Grafana removed; retention), 0021 (shared Grafana settled), 0022 (follow-ups closed). It must not contradict 0013 (lineage) or 0023.
- Positioning: AWS-native and production-shaped for the Canadian market. The audience includes non-engineers, so the console is a story, not a list of graphs.

## 4. Options

### 4.1 Host and runtime (the main axis)

| | A. One start/stop EC2 hosts everything | B. Per-session stack hosts everything | C. Standing serverless terminal + landing; live Grafana per session (recommended) | D. "Serverless Grafana" (App Runner, Fargate, Lambda) |
|---|---|---|---|---|
| What | A persistent instance (stopped when idle) in a private subnet runs landing, Grafana and a PTY terminal. Standing CloudFront + VPC origin + Cognito. Egress (NAT) per session. | `envs/dev-console` applies the instance, NAT, VPC origin, distribution and Cognito app client per demo, then destroys them | S3 + CloudFront + Cognito + API GW + Lambda, always on. Live Grafana per session as in B. | Grafana on a managed runtime |
| Idle | about $0.64/month (8 GiB gp3 root; size unverified, F19). Not $0. | $0 | $0 (S3 objects and logs: cents at most) | — |
| Per use | about $0.067/h (instance + NAT + IPv4) | about $0.067/h | Terminal: about $0 per command, hard-bounded. Grafana: about $0.067/h. | — |
| Wake time | about 2-3 min (NAT create + start) | about 15-20 min (VPC origin "up to 15 minutes", F20; unmeasured) | Terminal: none. Grafana: as B. | — |
| Gives up | $0 idle; landing dark when stopped; a PTY on a host | Always-on landing; stable URL; asynchronous visitors | Two runtimes; the Grafana URL changes per session; a "terminal" without a PTY | App Runner closed (F21). Fargate cannot be a VPC origin, and a public origin needs a certificate for a domain we do not have. Lambda gives one SQLite per instance and cold-start fan-out per panel. Rejected. |

How the pillars split these options:

- **Security against cost.** "No public inbound port" for an EC2 origin means a VPC origin in a private subnet (F20). Then egress costs money (NAT), and the origin is bound to one instance ARN. The cheap alternative, a public subnet with a CloudFront-prefix-list SG, loses for a reason that settles it: with no domain we have no certificate for the EC2 hostname. CloudFront would talk to the origin over plain HTTP across the internet, carrying session cookies. Rejected.
- **Reliability and Ops against cost.** A stable URL and a fast wake need a stopped disk (A, idle cost). $0 idle needs a slow per-session build (B/C). This is Open question 1.
- **Security: "not a shell".** A PTY tool gives the visitor a process on a host. A structured API gives the visitor a function call. C removes the host from the terminal path entirely.
- **Cost exposure.** C's terminal path is bounded in code and config: throttling, reserved concurrency, fixed SQL, a workgroup cutoff and no Cost Explorer calls. Any Grafana path is bounded only by who is invited. A Viewer can send any datasource query through `/api/ds/query`, and CloudWatch `GetMetricData` is billed per metric. So the console Grafana gets AMP only (see 4.5).

E. **SSM port-forward ("SSO tunnel") only.** Owner-only, $0. A visitor would need an AWS identity in the platform account, so this fails the Done-when. It is kept as the owner's debug path only.

### 4.2 Web terminal tool

| Tool | Model | Verdict |
|---|---|---|
| ttyd (C, libwebsockets) | Runs a program on a PTY. Input is off unless `-W` (unverified, ttyd 1.7+). | Needs a host. The escape surface is the REPL plus anything it starts (pagers, readline). Wrong fit for an allowlist. |
| GoTTY (fork `sorenisanerd/gotty`) | Same as ttyd | Same verdict; the original is unmaintained |
| WeTTY | SSH/login based | Wrong model |
| **xterm.js + a structured JSON API** | Browser line editor. Each command is `POST {"argv":[...]}`. | **Chosen.** No PTY and no interpreter fed visitor text. It needs more front-end code (about 150 lines: echo, history, help). |
| CloudShell / SSM in the browser | Needs an AWS identity | Not for visitors |

### 4.3 Edge and sign-in

- **CloudFront + Cognito (chosen).**
  - Standing distribution with OAC to the S3 site and `/api/*` to the HTTP API (same origin, no CORS), plus a response-headers policy (CSP, HSTS, `frame-ancestors 'none'`).
  - Cognito user pool with self sign-up off. Users are admin-created outside Terraform.
  - The SPA uses managed login with PKCE. The API checks tokens with the API Gateway JWT authorizer (no code).
  - Grafana uses `generic_oauth` to Cognito, maps everyone to Viewer and turns off the login form. This is why the session needs NAT rather than VPC endpoints: Grafana's server must reach the managed-login token endpoint.
- **Lambda@Edge auth.** Not needed: each origin enforces its own sign-in, and the landing page is public on purpose. It also adds replica-deletion lag.
- **ALB + Cognito.** Needs a certificate and a domain. A standing ALB is about $16/month. Rejected.
- **Cloudflare Tunnel + Access.** Free and outbound-only, but it adds a third-party vendor to an AWS portfolio. Rejected.
- **SSM / IAM Identity Center tunnel.** Owner debug path only (4.1 E).

### 4.4 Where the data comes from while `dev-compute` is down

| Source | Holds | Kept | Used by |
|---|---|---|---|
| Run records (git) | states, cost, DQ, events per run | Permanent | `runs`, `run <id>`, `cost`, `dq`, `slo`; landing "latest run" |
| Step Functions API | Executions and history | 90 days after close (Standard; unverified for this account) | `status`; `run <id>` detail while available |
| AMP | Spark/EKS series for exercise windows | 90 days today (F7); proposed 400 | Grafana; optional fixed PromQL in `run <id>` |
| CloudWatch | SFN, Lambda, Athena metrics | 1-min 15 d, 5-min 63 d, 1-h 455 d | Local Grafana only (see 4.5) |
| Athena (gold) | Tables | Permanent | One fixed `status` freshness query on a new `cerberus_platform_console` workgroup with a small cutoff |
| Grafana annotations | Step and DQ marks | Local volume only (F4) | The console Grafana rebuilds them at boot from the run records |
| Cost Explorer | Daily cost | — | Never from the visitor path ($0.01 per request). `cost` reads the run record. |

Proposed amendment to ADR 0016: AMP retention goes from 90 to 400 days.

- Why: the 2026-10-13 100M run would otherwise leave Grafana around 2027-01-11, and the 8.10 take around the end of January. That is while the portfolio is still in active use.
- Cost: storage at $0.03/GB-month. About 15 exercise windows of at most about 10k series is an estimated well under 1 GB, so under $0.03/month. This is an estimate.
- The ADR 0021 queries (`[30d]`, a 90-day window) do not change.

### 4.5 Grafana: one shared, or local only

- **Chosen: one file set, two hosts, in-cluster removed.**
  - The repo's `observability/grafana/` loads in two places:
    - *local Compose*: the owner's dev loop and recording host, with admin, the Editor token and annotations from `exercise.sh`;
    - *the session Grafana*: visitors, Viewer only, the instance role, and an AMP-only datasource file.
  - This matches ADR 0021: one shared viewer, plus the dev loop that ADR 0021 kept by name.
  - The in-cluster Grafana and the `cerberus-grafana` IRSA role are removed after the 8.10 take.
  - The datasource file is split into `amp.yaml` and `cloudwatch.yaml`, so the console mounts only AMP.
  - The story dashboard's CloudWatch Mixed panel gets an annotation-based fallback. CloudWatch's 1-minute data for the 100M run expires around 2026-10-28 anyway (ADR 0022 amendment).
- **Local Grafana credentials.** `make grafana-up` assumes a new read-only role, `cerberus-grafana-read` (AMP query plus CloudWatch read). It passes short-lived credentials (up to 12 h) as environment variables. `~/.aws` is no longer mounted. This removes the Grafana part of ADR 0022's accepted risk ("static admin keys in a container"); ADR 0023's `identities` stays HIGH (keys not rotated). The keys stay on the laptop.
- **Rejected: local only.** It fails the Done-when: a visitor cannot see dashboards. ADR 0021 asks for a shared viewer.
- **Rejected: keep in-cluster.** It exists only during exercises, and nobody uses it since ADR 0022.

## 5. Recommendation

Option C, with 4.2 xterm.js + structured API, 4.3 CloudFront + Cognito, 4.4 run records first plus AMP retention at 400 days, and 4.5 one file set with in-cluster removed. Why C wins the tensions:

- **It meets $0 idle without giving up a visitor path.** Everything standing is pay-per-request with no fixed fee (S3, CloudFront, Cognito under 10k MAU, HTTP API, Lambda). Only the Grafana session bills by the hour, and it is destroyed like an exercise.
- **"Not a shell" is true by construction, not by hardening.** There is no PTY, no host and no interpreter of visitor text on the terminal path. The Lambda takes a JSON argv of at most 8 tokens of at most 64 characters each. It matches them against a table of commands and argument patterns, and refuses anything else with a fixed message. It fails closed on any exception. It strips control characters from data-derived output to stop escape injection into xterm.js. It has no `subprocess`, `os.system`, `eval` or `exec`; ruff's `S` rules enforce this in CI.
- **Defence in depth.**
  - The role is read-only.
  - Athena runs only fixed SQL in a dedicated workgroup with `enforce_workgroup_configuration`.
  - Iceberg writes are impossible at IAM: no `glue:UpdateTable`, no gold `s3:PutObject`. The one write is Athena's own result object, in a dedicated prefix with a 1-day lifecycle.
  - HTTP API throttling (for example 2 rps, burst 5), Lambda reserved concurrency of 2, and a 25 s timeout (the HTTP API maximum is 30 s).
  - Access logs include the Cognito `sub`. This stands in for the missing CloudTrail trail (ADR 0023 item 14) on this path.
- **Session limits.**
  - Terminal: a 60-minute Cognito token with no refresh in the SPA, and a 15-minute idle drop in the page.
  - Grafana: `login_maximum_lifetime_duration` 2 h and an inactive limit of 30 min. The instance self-terminates at the session limit (`instance_initiated_shutdown_behavior = terminate` plus a timer). `make console-session` destroys the root from an EXIT trap and runs the account-wide check, the `exercise.sh` pattern.
- **AWS-native and production-shaped.** OAC, response-headers policy, VPC origin, a JWT authorizer, Graviton (t4g, which also starts ADR 0023's "Graviton never evaluated" item), and IaC with a destroy contract.

What it gives up:
- A real terminal feel (no tab completion beyond our own).
- A stable Grafana URL; the landing page shows the live link while a session is up (`live.json`, written and deleted by `dev-console`).
- Up to about 20 minutes to bring Grafana up, so live Grafana is for scheduled demos.
- A third Terraform root.

If the 9.2 spike measures more than 20 minutes up, or a teardown that is not reliable, switch the Grafana host to option A's stopped instance. That needs the user's consent to about $0.64/month idle.

## 6. ADR outline

**Title:** `24. Demo console: a serverless read-only terminal and landing page, live Grafana per session`. File: `docs/adr/0024-demo-console.md`. Status: Proposed. Date: 2026-10-27.

**Context**
- Phase 9's goal and Done-when (plan.md). The gap: today the demo is the AWS console, a localhost Grafana and JSON files.
- The forces:
  - $0 idle;
  - "no public inbound port";
  - a terminal that is safe to expose;
  - data that outlives `dev-compute` (the retention table);
  - ADR 0021/0022/0023's open Grafana items.
- Findings: VPC origins need a private subnet and a fixed instance ARN, and take up to 15 minutes (F20). The private subnets have no egress without `dev-compute`'s NAT (F11). There is no domain, so a public EC2 origin cannot use HTTPS. App Runner is closed (F21). `cerberus-admin` cannot touch CloudFront or Cognito today (F19).
- The two tensions:
  - Security against cost at the edge.
  - "Not a shell" by hardening (PTY) against by construction (API).
- Who the audience is: hiring managers and non-engineers, invited.

**Decision**
- Standing in `dev-standing` (CI):
  - S3 site bucket and CloudFront (OAC, response headers, `/api/*`);
  - Cognito pool with admin-created users and managed login;
  - HTTP API with a JWT authorizer and throttling;
  - the `cerberus` command Lambda;
  - roles `cerberus-console-cli` and `cerberus-grafana-read`;
  - the `cerberus_platform_console` Athena workgroup;
  - a console private subnet and route table.
- Per session: `envs/dev-console` (human-run, destroy-leaves-nothing): t4g.small with no key pair and no public IP, NAT for its route table only, VPC origin, distribution, Cognito app client, and `live.json`. `make console-session MINUTES=90`.
- The command set (9.3): `status`, `runs`, `run <id>`, `cost`, `dq`, `slo`, `help`, with the sources from 4.4. One Python package serves the CLI and the Lambda, so 10.5's `make status` reuses it.
- The "not a shell" rules (section 5).
- Grafana per 4.5. The in-cluster Grafana is removed after the 8.10 take.
- AMP retention 400 days.
- Rejected: options A (unless the trigger fires), B, D and E; ttyd, GoTTY, WeTTY; Lambda@Edge, ALB, Cloudflare.
- Amends:
  - ADR 0007: a console subnet and a session NAT;
  - ADR 0011: a third root with the dev-compute contract;
  - ADR 0016: Viewing (in-cluster removed) and retention;
  - ADR 0021: the shared Grafana is settled and the file set is split by datasource;
  - ADR 0022: the read-only role replaces mounted keys; console annotations come from run records.

  Each amended ADR gets a one-line Status note.

**Consequences**
- *Good:*
  - $0 idle, with a list of every standing resource and why each is $0;
  - the terminal is always available;
  - the visitor path costs are hard-bounded;
  - static keys leave the Grafana container;
  - history is viewable for 400 days;
  - one Grafana file set.
- *Given up:*
  - no PTY;
  - the Grafana URL changes per session;
  - up to about 20 minutes to bring Grafana up;
  - a third root;
  - the console Grafana has no CloudWatch;
  - Grafana-path cost is bounded by invitation only (Viewer API access);
  - a running session trips `exercise.sh`'s account check (F15), which is correct but noisy;
  - IAM work: a new `cerberus-admin-console` policy by root paste, CI role statements, and a local first apply.
- *To confirm in build:* the list in section 8.
- *Revisit if:*
  - the session takes more than 20 minutes up, or its teardown leaves resources (switch to A with consent);
  - a domain is acquired;
  - invites go beyond a handful of people;
  - Phase 10 series replace the run-record annotations.

## 7. Build steps (one PR each; mapped to Phases.md)

1. **9.1. ADR 0024 (Proposed) and this plan.** Also: Phases.md wording for 9.2 and 9.5 (below), plan.md Phase 9 "Stack" line, and a checkpoint note.
   - Verify: Opus review. The user accepts, then a status flip to Accepted.
2. **9.2. IAM prerequisites.**
   - `iam/cerberus-admin/policies/cerberus-admin-console.json`, a new seventh policy (F16 headroom): CloudFront distribution, VPC origin and OAC; Cognito pool and admin users; EC2 run, terminate and describe-images; `ssm:GetParameter` on the AMI alias; `ec2:DescribeManagedPrefixLists`; PassRole for the instance profile. Plus README history.
   - `github_oidc` statements for the standing CloudFront, Cognito, site bucket, workgroup and Lambda.
   - Verify: the user pastes the policy at root. The previously denied F19 reads now succeed. A local `standing-plan` shows the CI role diff.
3. **9.2. Spike, about $0.10.** A minimal `envs/dev-console`: t4g.nano running nginx "hello" in the console subnet, plus NAT, VPC origin and distribution.
   - Measure apply time, destroy time, the WebSocket upgrade, HTTP to the origin, and leftover ENIs or SGs.
   - Verify: timings are recorded in the plan. The account check returns zero. If it takes more than 20 minutes, raise Open question 1 again.
4. **9.2. Read-only roles and the console subnet, plus local Grafana on short-lived credentials** (`dev-standing`, CI).
   - Verify: `make grafana-up` loads the story dashboard on the 2026-10-13 window. `docker inspect` shows no `/aws` mount. `iam simulate-principal-policy` denies writes for both roles.
5. **9.2. AMP retention to 400 days** (one line, CI).
   - Verify: `describe-workspace-configuration`. The 2026-10-13 series still return.
6. **9.3. The command set package**, with fixtures, pytest and ruff `S` rules. No AWS in CI.
   - Verify: tests pass, including refusals and output sanitising. A local read-only run of every command works as `cerberus-console-cli`, assumed.
7. **9.2. The standing edge.** S3, CloudFront, Cognito, HTTP API, Lambda from step 6, and the workgroup. First apply local, then CI.
   - Verify: an unauthenticated `/api` call returns 401. A signed-in token call to `runs` returns rows. The CI plan is clean.
8. **9.4. Landing page.** A static build from the repo: architecture, phase status, the latest run from the records, and `docs/img/scale` charts. A CI publish step (sync plus invalidation). Cross-links with the GitHub Pages site.
   - Verify: a clean browser loads it with no sign-in. The CSP header is present.
9. **9.5. Terminal panel.** xterm.js vendored and pinned, PKCE, a 60-minute token, a 15-minute idle drop, help, and a refusal message.
   - Verify: each command works from a clean browser. A hostile input gets the fixed refusal.
10. **9.2 and 9.4. The live Grafana session.**
    - `envs/dev-console` and `make console-session`: EXIT-trap destroy, self-terminate, an account check that includes tagged distributions.
    - User-data installs Grafana and the AMP plugin from an S3 artifacts prefix.
    - Cognito OAuth maps everyone to Viewer. AMP-only datasource. Annotations are rebuilt from the run records. Dashboard links open on each run's window. `live.json`.
    - Verify: sign in from a clean browser; the story dashboard shows the 2026-10-13 and 8.10 runs; destroy leaves the account check at zero; Cost Explorer the next day.
11. **9.2. Remove the in-cluster Grafana** (`eks_observability`, `dev-compute`). **Only after the 8.10 take.**
    - Verify: the next exercise plan shows the Grafana release and role gone, and the agent still writes to AMP.
12. **9.6. Safety and live check.** A CI escape and injection suite (`;`, `$( )`, backticks, newline, NUL, `../`, Unicode, long input, type confusion, ANSI/OSC 52 in data). An IAM deny check. A demo from a clean browser. Teardown to $0.
    - Verify: CI green, a recorded short video, and the account check at zero.
13. **9.7. Well-Architected pass, ADR 0025, and milestone `phase-9-demo-console-complete`.**

Proposed Phases.md wording:
- **9.2:** "Terraform: the standing edge (S3 + CloudFront + Cognito + API Gateway + the command Lambda, read-only roles) and the per-session Grafana root (`envs/dev-console`, `make console-session`); remove the in-cluster Grafana after 8.10."
- **9.5:** "...with a session time limit; the Grafana session self-terminates and is destroyed at its limit."

## 8. Facts to verify (each in the named step)

- VPC origin create and delete times in practice, and leftover service ENIs or SGs (step 3).
- An EC2 VPC origin over HTTP in a private subnet; WebSocket through it (step 3).
- The Grafana arm64 tarball and AMP plugin 3.2.0 have `linux_arm64` builds. If not, use t3.small at about $0.0208/h (step 10).
- Grafana 13 `generic_oauth` with Cognito managed login, `role_attribute_path` to Viewer, and `disable_login_form` (step 10).
- Whether Cognito Lite includes managed login; otherwise Essentials, still 10k MAU free (F22) (step 7).
- The HTTP API JWT authorizer with Cognito access tokens (`client_id` rather than `aud`) (step 7).
- Step Functions read APIs are not billed, and Standard history lasts 90 days (step 6).
- Bytes scanned by the `status` Athena query, and the cutoff value (step 6).
- Raising AMP retention keeps existing samples (step 5).
- The AMP plugin and the CloudWatch datasource read environment-variable session credentials in Compose (`GF_PLUGINS_FORWARD_HOST_ENV_VARS`) (step 4).
- A Grafana Viewer can open Inspect → Query without Explore (step 10).
- The AL2023 arm64 root size (needed only if Open question 1 picks A) (step 2 reads).
- The list prices in section 2 (step 3, then Cost Explorer).

## 9. Open questions for the user

Answered 2026-10-27; see User decisions at the top.

1. **Idle cost against Grafana wake time.** The recommended per-session Grafana is $0 idle, but takes about 15-20 minutes to come up and gets a new URL each session. The alternative is a stopped instance: about $0.64/month idle for an 8 GiB disk (size unverified), about 2-3 minutes to wake, a stable URL, and a visitor "wake" button possible later. Recommendation: per-session. Answer "accept the stopped disk" to switch.
2. **Sign-in model.** One invited account per visitor (recommended; the owner runs `admin-create-user`, and emails never enter the repo), or one shared demo account handed out on request?

AMP retention at 400 days is part of the recommendation, not a question. Veto it in review if you do not want it.

## 10. Review checklist (for the executor's ADR PR)

- Number 0024, status Proposed, date 2026-10-27, Nygard sections, no "Pillars" section. The style matches ADR 0021/0022: short paragraphs and a dated Status.
- Every price is marked as a list price with a date. Every unmeasured claim is marked unverified. Nothing is quoted that is not in section 2.
- The idle claim lists each standing resource and why it costs $0.
- The "not a shell" rules are concrete: argv limits, allowlist table, fail-closed, output sanitising, banned calls, IAM.
- The amendments to ADRs 0007, 0011, 0016, 0021 and 0022 are each named in 0024 and noted in the amended ADR's Status.
- No Cognito users, emails, passwords or tokens in Terraform or docs.
- No `dev-compute` change before the 8.10 take. The in-cluster removal is sequenced after it.
- Phases.md 9.2/9.5 and plan.md Phase 9 wording are updated consistently. The build steps map to 9.2-9.7.
- Open questions are recorded as the user answered them.

Sources: [CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html), [App Runner availability change](https://docs.aws.amazon.com/ja_jp/apprunner/latest/dg/apprunner-availability-change.html), [Cognito pricing](https://aws.amazon.com/cognito/pricing/), [re:Post: VPC origin 504](https://www.repost.aws/questions/QU-_-44OsPRYmHT8VVtemoEw/cloudfront-504-gateway-timeout-for-ec2-vpc-origin-ipv6-private-ipv4), [advancedweb.hu on VPC origins](https://advancedweb.hu/shorts/finally-its-possible-to-host-ec2-instances-without-paying-the-public-ipv4-price-using-cloudfront-vpc-origins/).

