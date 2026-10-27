# 24. Demo console: a serverless read-only terminal and landing page, live Grafana per session

Date: 2026-10-27

## Status

Accepted (2026-10-27). Amends [ADR 0007](0007-vpc-network-design.md),
[ADR 0011](0011-ci-cd-github-actions-oidc.md),
[ADR 0016](0016-prometheus-for-eks-spark.md),
[ADR 0021](0021-pipeline-status-and-alerting.md) and
[ADR 0022](0022-live-observability-for-a-recorded-run.md)
(see the Amends list in the Decision). The build steps and the facts behind
this ADR are in [the plan](../plans/2026-10-27-demo-console.md).

## Context

Phase 9's goal is to show Cerberus in a browser to someone who will not read
the repo. The Done-when in `docs/plan.md` is that a signed-in visitor, from a
clean browser, sees the architecture, the latest run and the dashboards, and
runs each allowlisted command. Escape and injection tests must pass in CI,
and the stack must cost $0 when stopped. Today the demo is the AWS console, a
Grafana on `127.0.0.1` and JSON files in git.

The forces:

- $0 idle and no idle billed resources (user, 2026-10-27). The budget is
  $20 a month; the forecast is about $17.2 including the 8.10 take.
- "No public inbound port" (Phases.md 9.2).
- A terminal that is safe to expose to the public internet behind a sign-in.
- Data that outlives `dev-compute`, which is destroyed after each exercise.
- Open Grafana items: ADR 0021 left "where the shared Grafana runs" to 9.1
  ("one Grafana, not two"). ADR 0022 left a read-only Grafana role and the
  removal of the in-cluster Grafana to 9.1. ADR 0023 lists both as
  follow-ups.

Findings from reading the repo, AWS (read-only, 2026-10-27) and the AWS docs:

- CloudFront VPC origins point at an ALB, NLB or EC2 instance in a private
  subnet, by ARN. Creating or updating one "can take up to 15 minutes". An
  origin must be disassociated before it is updated. Whether a public-subnet
  instance works is not documented.
- The private subnets have no egress unless `dev-compute` is up: the NAT
  gateway lives in `dev-compute` (`terraform/modules/vpc_nat/main.tf`).
- There is no domain, so a public EC2 origin has no certificate. CloudFront
  would reach it over plain HTTP across the internet, carrying session
  cookies.
- App Runner has been closed to new customers since 2026-04-30.
- `cerberus-admin` is denied `cloudfront:ListDistributions`,
  `cognito-idp:ListUserPools`, `ec2:DescribeManagedPrefixLists`,
  `ec2:DescribeImages`, `ssm:GetParameter` and `route53:ListHostedZones`.
  So 9.2 needs a root-console policy change, and whether a custom domain
  exists is unknown.
- `cerberus-ci-apply` has `apigateway:*` on `/apis` (the lineage pattern,
  ADR 0013) but no CloudFront, Cognito or EC2-instance statements.
- All three dashboards default to the last 30-60 minutes, so with
  `dev-compute` down they are empty unless opened on a past run's window.
- AMP retention is 90 days (`terraform/modules/prometheus_workspace`). The
  2026-10-13 100M run stays in AMP "until about 2027-01-11" (ADR 0022). The
  8.10 take would leave around the end of January 2027, while the
  portfolio is still in active use.
- The run records (`observability/scale/runs/*.json`, 14 files) are
  permanent and in git.

The two tensions:

- *Security against cost at the edge.* A private VPC origin is the secure
  shape but needs NAT and a slow build. A public origin is cheap but cannot
  use HTTPS without a domain.
- *"Not a shell" by hardening against "not a shell" by construction.* A web
  terminal that runs a program on a PTY is hardened. A structured API has no
  shell to harden.

The audience is hiring managers and non-engineers, invited by the owner.

## Decision

**Option C: a standing serverless terminal and landing page, with a live
Grafana built per session.** The decisions below include the user's three
answers of 2026-10-27.

**Standing resources in `dev-standing` (CI-applied).** Each is pay per
request or free, with no hourly fee:

| Resource | Why it is $0 idle |
|---|---|
| S3 site bucket | Storage only: static files, cents at most |
| CloudFront distribution (OAC to S3, `/api/*` to the API, response-headers policy) | Billed per request and per GB out; no fixed fee |
| Cognito user pool, self sign-up off, managed login | 10,000 free monthly active users for direct sign-in (Cognito pricing, read 2026-10-27); whether the Lite tier includes managed login is unverified, and Essentials has the same free allowance |
| API Gateway HTTP API with a JWT authorizer and throttling | List price $1.00 per million requests (2026-10-27); no requests, no charge |
| The `cerberus` command Lambda | Billed per invocation and duration; no provisioned concurrency |
| IAM roles `cerberus-console-cli` and `cerberus-grafana-read` | IAM has no charge |
| Athena workgroup `cerberus_platform_console` | Billed per query ($5/TB list price, 10 MB minimum per query, 2026-10-27); no queries, no charge |
| A console private subnet and route table | Subnets and route tables have no charge. The route table has no NAT route at rest |
| Log groups and the Athena result prefix | Storage cents at most; the result prefix has a 1-day lifecycle |

The `/api/*` behaviour of the distribution does not cache and forwards the
`Authorization` header (an origin request policy), so the JWT authorizer
receives the token.

Estimated idle cost is cents a month at most. This is an estimate, not a
bill reading. The list prices are list prices as of 2026-10-27 and are
rechecked in 9.2. Check Cost Explorer after the first full month.

**Per session in `envs/dev-console` (human-run, a third Terraform root).**
It follows the `dev-compute` contract: destroy leaves nothing. It creates a
t4g.small with no key pair and no public IP, a NAT gateway for the console
route table only, a CloudFront VPC origin, a distribution, a Cognito app
client, and `live.json` (the live link shown on the landing page). The
instance's security group allows inbound only from the CloudFront
service-managed group `CloudFront-VPCOrigins-Service-SG`, on the Grafana
port. Outbound is 443 only. There is no SSH and no port 22. The owner's
debug path is SSM Session Manager.
The command is `make console-session MINUTES=90`. It destroys the root from an
EXIT trap and then runs the account-wide check used by `exercise.sh`. The
check also counts tagged distributions.

Session cost is about $0.067 an hour at list prices (t4g.small $0.0168/h,
NAT $0.045/h plus $0.045/GB, public IPv4 for the NAT's EIP $0.005/h; 2026-10-27, not read from
a bill). The wake time is up to 15 to 20 minutes, because a VPC origin
"can take up to 15 minutes". That time is **unverified** until the 9.2
spike measures it. Live Grafana is for scheduled demos.

**User decisions (2026-10-27).**

1. Live Grafana is built per demo (`envs/dev-console`, $0 idle), not kept as
   a stopped instance. The stopped-instance alternative would cost about
   $0.64 a month idle for an 8 GiB gp3 disk (root size unverified) and wake
   in about 2 to 3 minutes. It stays available if the trigger in "Revisit
   if" fires.
2. One invited Cognito account per visitor. The owner creates each with
   `admin-create-user`, outside Terraform. No emails, passwords or tokens
   enter the repo.
3. AMP retention goes from 90 to 400 days.

**The command set (9.3).** `status`, `runs`, `run <id>`, `cost`, `dq`,
`slo` and `help`. Sources:

- Run records in git: `runs`, `run <id>`, `cost`, `dq`, `slo`, and the
  landing page's "latest run".
- Step Functions read APIs: `status`, and `run <id>` detail while the
  execution history lasts. Standard history lasts 90 days after close; this
  is unverified for this account.
- One fixed `status` freshness query on the gold tables, in the
  `cerberus_platform_console` workgroup with a small cutoff. The cutoff
  value and the bytes scanned are unverified.
- Never Cost Explorer from a visitor request ($0.01 per request, list
  price). `cost` reads the run record.

One Python package serves the CLI and the Lambda, so 10.5's `make status`
reuses it, as ADR 0021 requires.

**The "not a shell" rules.** The terminal is xterm.js in the browser. It
sends each command as `POST {"argv": [...]}` to the API. There is no PTY, no
host and no interpreter of visitor text on this path. The rules:

1. Input limits: `argv` has at most 8 tokens, each at most 64 characters. A
   wrong type, an empty list or a longer input gets the fixed refusal.
2. Allowlist table: the first token must be a command in the table. Each
   command has its own argument patterns (for example `run <id>` accepts one
   run id matching a fixed pattern). Anything that does not match gets a
   fixed refusal message that does not echo the input.
3. Fail closed: any exception returns the same fixed message. No stack trace
   or internal error text leaves the Lambda.
4. Output sanitising: control characters (ANSI escapes, OSC 52 and others)
   are stripped from data-derived output, to stop escape injection into
   xterm.js.
5. Banned calls: the package has no `subprocess`, `os.system`, `eval` or
   `exec`. Ruff's `S` rules enforce this in CI.
6. Fixed SQL: Athena runs only fixed statements in the dedicated workgroup
   with `enforce_workgroup_configuration`. No visitor text enters a query.
7. IAM: the role `cerberus-console-cli` is read-only. It has no
   `glue:UpdateTable` and no `s3:PutObject` on gold. The one write is
   Athena's own result object, in a dedicated prefix with a 1-day lifecycle.
8. Rate and size bounds: HTTP API throttling (for example 2 requests per
   second, burst 5; the values are to be set in 9.2), Lambda reserved
   concurrency of 2, and a 25 s timeout (the HTTP API maximum is 30 s).
9. Audit: access logs include the Cognito `sub`. This stands in for the
   missing CloudTrail trail (ADR 0023, item 14) on this path.

**Sign-in and sessions.**

- The SPA uses Cognito managed login with PKCE. The API checks tokens with
  the API Gateway JWT authorizer (no code). Whether Cognito access tokens
  validate with `client_id` rather than `aud` is to be confirmed in build.
- Terminal: a 60-minute token with no refresh in the SPA, and a 15-minute
  idle drop in the page.
- Grafana: `generic_oauth` to Cognito, everyone mapped to Viewer, login form
  off, `login_maximum_lifetime_duration` 2 h and an inactive limit of
  30 min. The instance self-terminates at the session limit
  (`instance_initiated_shutdown_behavior = terminate` plus a timer). This is
  why the session needs NAT: Grafana's server must reach the managed-login
  token endpoint.
- The landing page is public on purpose. Each origin enforces its own
  sign-in, so Lambda@Edge is not needed.

**Grafana: one file set, two hosts.** The repo's `observability/grafana/`
loads in two places:

- *Local Compose*: the owner's dev loop and recording host, with admin, the
  Editor token and the annotations from `exercise.sh`. `make grafana-up`
  assumes a new read-only role, `cerberus-grafana-read` (AMP query plus
  CloudWatch read), and passes short-lived credentials (up to 12 h) as
  environment variables. `~/.aws` is no longer mounted. The keys stay on the
  laptop.
- *The session Grafana*: visitors, Viewer only, the instance role, and an
  AMP-only datasource. The datasource file is split into `amp.yaml` and
  `cloudwatch.yaml`, so the console mounts only AMP. The reason: a Viewer can
  send any datasource query through `/api/ds/query`, and CloudWatch
  `GetMetricData` is billed per metric ($0.01 per 1,000 metrics, list price
  2026-10-27). Annotations are rebuilt at boot from the run records. The
  story dashboard's CloudWatch Mixed panel gets an annotation-based
  fallback; the 1-minute CloudWatch data for the 100M run expires around
  2026-10-28 anyway (ADR 0022 amendment).

The in-cluster Grafana and the `cerberus-grafana` IRSA role are removed
after the 8.10 take, never before. Nothing in `dev-compute` changes before
then.

**AMP retention: 400 days** (one line in `prometheus_workspace`, CI-applied).
The 2026-10-13 100M run would otherwise leave Grafana around 2027-01-11.
Storage is $0.03 per GB-month (list price, 2026-10-27). About 15 exercise
windows of at most about 10k series is an estimated well under 1 GB, so
under $0.03 a month. This is an estimate. The ADR 0021 queries (`[30d]`, a
90-day window) do not change. Whether raising retention keeps existing
samples is unverified; build step 5 checks it.

**Rejected:**

- Option A, one start/stop EC2 hosting everything (about $0.64 a month idle,
  landing dark when stopped, a PTY on a host), unless the revisit trigger
  fires.
- Option B, a per-session stack for everything (the landing page would be
  dark, and the URL unstable).
- Option D, "serverless Grafana": App Runner is closed; Fargate cannot be a
  VPC origin, and a public origin needs a certificate for a domain we do not
  have; Lambda gives one SQLite per instance and a cold-start fan-out per
  panel.
- Option E, an SSM port-forward only. A visitor would need an AWS identity
  in the platform account. It stays as the owner's debug path.
- ttyd, GoTTY and WeTTY. They run a program on a PTY or a login, so the
  escape surface is the program plus anything it starts. An allowlist is
  the wrong fit.
- A public-subnet EC2 origin with a CloudFront prefix-list security group
  (no certificate, above); Lambda@Edge auth (not needed, and it adds
  replica-deletion lag); an ALB with Cognito (needs a domain and a
  certificate; a standing ALB is about $16 a month, estimate); Cloudflare
  Tunnel (a third-party vendor in an AWS portfolio).

**Amends:**

- ADR 0007: a console subnet and a session NAT.
- ADR 0011: a third root, `dev-console`, with the `dev-compute` contract.
- ADR 0016: "Viewing" (the in-cluster Grafana is removed) and retention
  (90 to 400 days).
- ADR 0021: the shared Grafana is settled, and the file set is split by
  datasource.
- ADR 0022: the read-only role replaces the mounted keys, and console
  annotations come from the run records.

Each amended ADR gets a one-line note in its Status. Their Decisions are not
rewritten. If this ADR is not accepted, the notes are removed.

**Build steps** (details and checks are in
[the plan](../plans/2026-10-27-demo-console.md), section 7):

1. This ADR, the plan file and the Phases.md and `docs/plan.md` wording.
2. IAM prerequisites: a seventh `cerberus-admin` policy by root paste, and
   CI role statements.
3. A spike of about $0.10: measure VPC origin create and destroy times, the
   WebSocket upgrade and leftover ENIs.
4. Read-only roles, the console subnet and local Grafana on short-lived
   credentials.
5. AMP retention to 400 days.
6. The command set package, with fixtures and ruff `S` rules.
7. The standing edge, applied locally first, then by CI.
8. The landing page.
9. The terminal panel.
10. The live Grafana session.
11. Remove the in-cluster Grafana, only after the 8.10 take.
12. Safety suite and live check (9.6).
13. Well-Architected pass, ADR 0025, and milestone (9.7).

## Consequences

**Good**

- *Cost:* $0 idle, with every standing resource listed above and why each is
  $0. Per-session cost is about $0.067 an hour (list prices).
- *Reliability:* the terminal and landing page are always available, even
  when `dev-compute` and the Grafana session are down.
- *Security:* "not a shell" is true by construction. The visitor-path costs
  are hard-bounded by throttling, reserved concurrency, fixed SQL, a
  workgroup cutoff and no Cost Explorer calls. Static admin keys leave the
  Grafana container, which removes the Grafana part of ADR 0022's accepted
  risk. ADR 0023's `identities` question stays HIGH, because the access
  keys are still not rotated.
- *Operational Excellence:* history is viewable for 400 days. One Grafana
  file set serves both hosts. Graviton (t4g) also starts ADR 0023's
  "Graviton never evaluated" item.

**Given up**

- No PTY: no tab completion beyond our own and no real terminal feel.
- The Grafana URL changes per session. The landing page shows the live link
  while a session is up.
- Up to about 20 minutes to bring Grafana up (unverified, above).
- A third Terraform root.
- The console Grafana has no CloudWatch datasource.
- The Grafana-path cost is bounded by invitation only, because a Viewer has
  API access.
- A running session trips `exercise.sh`'s account-wide check, which is
  correct but noisy.
- If `make console-session` dies before its EXIT trap (laptop sleep, crash
  or lost network), the instance still terminates itself, but the NAT
  gateway and its EIP keep billing at about $1.20 a day (list price:
  $0.045/h plus $0.005/h, 2026-10-27) until `terraform destroy` runs in
  `envs/dev-console`. The AWS Budgets alerts are the backstop. Re-run the
  account-wide check after any interrupted session.
- IAM work: a new `cerberus-admin-console` policy pasted at the root
  console (the `iam-and-governance` policy file is 5,954 bytes against the
  6,144-character limit, so the new one is a seventh file), CI role
  statements, and a local first apply.

**To confirm in build** (each in the plan's section 8):

- VPC origin create and delete times, leftover ENIs or security groups, and
  an HTTP and WebSocket path to a private-subnet instance.
- Grafana and AMP plugin 3.2.0 `linux_arm64` builds (otherwise t3.small at
  about $0.0208/h, list price).
- Grafana 13 `generic_oauth` with Cognito managed login, the Viewer role
  mapping, and a Viewer's access to Inspect.
- Whether Cognito Lite includes managed login, and JWT authorizer behaviour
  with access tokens.
- Step Functions read APIs are not billed, and the `status` Athena query's
  bytes scanned and cutoff.
- Whether the AMP plugin and CloudWatch datasource read session credentials
  from environment variables in Compose.
- All list prices, rechecked in 9.2 and against Cost Explorer.

**Revisit if**

- The session takes more than 20 minutes up, or its teardown leaves
  resources. Then switch the Grafana host to a stopped instance (option A).
  That needs the user's consent to about $0.64 a month idle.
- A domain is acquired (a public origin with HTTPS becomes possible).
- Invites go beyond a handful of people.
- Phase 10 series replace the run-record annotations.
