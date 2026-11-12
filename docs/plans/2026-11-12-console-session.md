# Plan: the live Grafana session (ADR 0024 build step 10)

Date: 2026-11-12. Planner: Opus. Mode: task (no new ADR, no amendment).
Phases.md: 9.2 (remainder). Branch for PR A: `9.2-console-session`.

**User decisions (2026-11-12):** the artifacts live under `artifacts/` in
the site bucket with a CloudFront deny (option 4.1 A); the home dashboard
links all 17 run records, newest first, failed runs marked.

## 1. Question

How do we build `envs/dev-console` and `make console-session`, so that an
invited visitor can sign in to a per-session, Viewer-only, AMP-only Grafana
that shows the recorded runs, and so that destroy leaves nothing billable?
9.3 and 9.5 are checked off and step 11 (the in-cluster Grafana removal) is
done, so step 10 is the last open item of 9.2; 9.6 and 9.7 depend on it.

## 2. Facts

Repo (verified unless marked):

- F1. ADR 0024 L110-121: a third root, `envs/dev-console`, with the
  `dev-compute` contract. A t4g.small (no key pair, no public IP), a NAT
  gateway for the console route table only, a CloudFront VPC origin, its own
  distribution, a Cognito app client and `live.json`. The SG allows inbound
  only from `CloudFront-VPCOrigins-Service-SG` on the Grafana port; outbound
  is 443 only. No SSH; debug through SSM Session Manager.
  `make console-session MINUTES=90`, destroy from an EXIT trap, then the
  `exercise.sh` account check plus tagged distributions.
- F2. ADR 0024 L193-198: `generic_oauth` to Cognito, everyone mapped to
  Viewer, login form off, `login_maximum_lifetime_duration` 2 h, inactive
  limit 30 min. Self-terminate is `instance_initiated_shutdown_behavior =
  terminate` plus a timer. NAT, not VPC endpoints, because Grafana's server
  must reach the hosted-UI token endpoint (also plan 2026-10-27 L131).
- F3. ADR 0024 L202-219: one file set on two hosts. The console mounts only
  `amp.yaml` (a Viewer can send any query through `/api/ds/query`).
  Annotations are rebuilt at boot from the run records. The story
  dashboard's CloudWatch Mixed panel gets an annotation-based fallback.
- F4. ADR 0024 L319-324: if the trap dies, the instance self-terminates, but
  the NAT and EIP bill about $1.20/day until `terraform destroy`. Accepted;
  Budgets is the backstop.
- F5. Plan step 10: `docs/plans/2026-10-27-demo-console.md` L292-296; its §8
  items for step 10 (L311, L312, L319): arm64 builds, `generic_oauth` with
  Cognito, a Viewer's Inspect access.
- F6. VPC-origin spike outcome (`docs/plans/2026-10-27-vpc-origin-spike.md`
  L217-255): wake 11:52 and about 15:35; destroy about 11 minutes; ENIs
  cleared in about 1 minute; HTTP and WebSocket 101 passed. Finding 1: the
  service-SG lookup races the VPC origin (a new SG per new origin). The spike
  directory `terraform/spikes/vpc-origin/` is deleted in step 10 (L104).
- F7. The standing outputs `dev-console` needs exist
  (`terraform/envs/dev-standing/outputs.tf`): `vpc_id`, `public_subnet_a_id`,
  `prometheus_workspace_arn`, `prometheus_endpoint`, `console_subnet_id`,
  `console_route_table_id`, `console_site_bucket_name`,
  `console_user_pool_id`, `console_auth_domain`.
- F8. The console subnet is 10.0.2.0/24 in us-east-1a with its own route
  table and no routes (`terraform/modules/vpc/main.tf`). The S3 gateway
  endpoint was attached only to the private route table; the association was
  deferred to step 10 (`docs/plans/2026-10-28-readonly-roles.md` L83).
- F9. `terraform/modules/vpc_nat` takes `public_subnet_id` and
  `private_route_table_id` only, so it is reused unchanged with the console
  route table.
- F10. There is no `cerberus-console-grafana` role yet; the name pattern
  belongs to `dev-console`.
- F11. The site bucket policy lets the distribution read `/*`; the 9.4
  publish deletes only keys that match `MANAGED`, so `live.json` and other
  root objects are never deleted (`console/cerberus_landing/publish.py`,
  `console/publish_site.sh`).
- F12. The landing plan says step 10 adds `live.js`, which reads `/live.json`
  (`docs/plans/2026-11-06-landing-page.md` L164). The landing page is being
  rebuilt in a separate session, so this plan writes `live.json` only and does
  not touch `console/cerberus_landing`.
- F13. `observability/grafana/compose.yaml`: `grafana/grafana:13.2.3` (OSS)
  and `grafana-amazonprometheus-datasource@3.2.0`. Datasources are split into
  `amp.yaml` (`sigV4AuthType: default`, `url: ${AMP_URL}`) and
  `cloudwatch.yaml`.
- F14. CloudWatch in the dashboards: `cerberus-run-story` panel 4 "Pipeline
  journey" (Mixed: 3 AMP, 13 CloudWatch targets) and panel 9 "Cost so far"
  (Mixed, `COST = $S + $P/2e11`, P = CloudWatch Athena bytes);
  `cerberus-run-live` panel 7 and `cerberus-spark-on-eks` panel 2 are
  CloudWatch only. Story panels 2, 5 and 6 read annotations tagged
  `cerberus-now`, `cerberus-dq`, `cerberus-teardown`; run-live panel 8 reads
  tag `cerberus`. All dashboards default to `now-30m` or `now-1h`.
- F15. `orchestration/annotate.sh --replay` needs
  `observability/scale/exercises/<run>.log` (not in the repo), Step Functions
  history (90 days) and a loopback URL. It cannot run on the console host.
- F16. There are 17 run records with `start`, `end`, `run_seconds`,
  `states[].seconds`, `data_quality`, `status`; most also have
  `generator.run_id` and `write_seconds`. For the 2026-10-13 run the state
  seconds sum to `run_seconds` (742.0). The 8.10 take is
  `demo-100m-20261108T135119Z`.
- F17. The account check is `orchestration/exercise.sh` L188-200 (EKS
  clusters, NAT gateways pending/available, EIPs, running instances); the
  EXIT-trap pattern is L153-200 and L259-260.
- F18. CI never plans or applies `dev-console`; `cerberus-ci-apply` is
  denied `CreateVpcOrigin` and `RunInstances`.
- F19. CI already has `ec2:*` on `vpc-endpoint/*` and `route-table/*`, and
  `s3:*` on the site bucket, so PR A needs no IAM change.
- F20. Ruff targets py312 with `UP`. AL2023's `python3` is 3.9 (unverified
  on the current AMI).

AWS (read-only, `cerberus-admin`, 2026-11-12):

- F21. One distribution ("cerberus demo console"); 0 VPC origins, 0 NAT
  gateways, 0 EIPs, 0 instances, 0 EKS clusters. The console route table has
  only the local route.
- F22. The Cognito pool has one client, `cerberus-console-spa`. `email` is in
  the schema but not required: invited users have no email (no PII).
- F23. The site bucket has no `live.json` and no `artifacts/`.
- F24. `simulate-principal-policy` on `cerberus-admin`: allowed for every
  action the session needs (IAM role `cerberus-console-grafana`, the Cognito
  client, NAT, EIP, routes, `RunInstances`, `tag:GetResources`, site-bucket
  writes). Implicit deny: `ec2:ModifyInstanceCreditSpecification` and
  `ec2:GetConsoleOutput` (avoid both).
- F25. Policy sizes: `console-edge` 4,730 and `console-host` 2,363 of 6,144.
- F26. Cost Explorer: November gross month-to-date (1-11 Nov) $6.75;
  forecast for 12-30 Nov $5.98; about $12.7 of $20 (whether the forecast nets
  credits is unverified).
- F27. `pricing:GetProducts` is denied, so list prices were not rechecked;
  they are ADR 0024's 2026-10-27 values.

External (read 2026-11-12):

- F28. AMP plugin 3.2.0 has a `linux-arm64` package, SHA-256
  `3426edac38d361f5d48f46f77dd67834c89b7868cc86782b39efb7131f596c2f`;
  `grafanaDependency` includes `>=12.2.5-0`
  ([grafana.com plugin API](https://grafana.com/api/plugins/grafana-amazonprometheus-datasource/versions/3.2.0)).
- F29. Grafana OSS 13.2.3 linux arm64 tarball
  `grafana_13.2.3_36482603486_linux_arm64.tar.gz`, SHA-256
  `a2a41b960ba4c25e83140484e48813730d3c81891a128439a2a9d2df6eb3840e`
  ([download page](https://grafana.com/grafana/download/13.2.3?platform=arm&edition=oss));
  read through a summariser, so PR B re-confirms it against the `.sha256`
  file. With F28 this closes "arm64 builds, otherwise t3.small": t4g.small
  stands.
- F30. Grafana generic OAuth needs an email even when login maps to another
  claim (`[auth.oauth.email.missing]`)
  ([docs](https://grafana.com/docs/grafana/next/setup-grafana/configure-access/configure-authentication/generic-oauth/),
  [community thread](https://community.grafana.com/t/login-failed-oauth/145712)).
  This matters because of F22.

## 3. Constraints

- $0 idle; nothing hourly outlives a session. Budget $20/month, forecast
  about $12.7 (F26).
- `dev-console` follows the `dev-compute` contract: human-run from the
  owner's terminal, never applied by CI; destroy leaves nothing billable.
- CI applies `dev-standing` only (PR A).
- ADR 0024 and its amendments stay as written; ADRs 0007 and 0011 already
  carry the `dev-console` notes.
- Public repo: no account ID, client secret, email or session URL in git
  (partial S3 backend config; the remote-state bucket name is built from
  `data.aws_caller_identity`).
- Do not touch `console/cerberus_landing`.

## 4. Options (only where ADR 0024 left a choice)

**4.1 Where the artifacts prefix lives.**
- **A (chosen):** `artifacts/` in the site bucket, with an explicit
  `Deny s3:GetObject` for the CloudFront service principal on
  `artifacts/*`. No IAM change (F19, F25); storage about $0.005/month
  (size unverified). Gives up a single-purpose bucket.
- B: a new artifacts bucket in `dev-standing`: one root paste, a CI policy
  statement and a local first apply.
- C: the Athena results bucket. Rejected: its lifecycle expires objects.

**4.2 How the instance gets the post-create values** (client ID, client
secret, root URL), given the cycle instance → VPC origin → distribution →
callback URL → app client.
- **A (chosen):** the instance role gets `cognito-idp:ListUserPoolClients`
  and `DescribeUserPoolClient` on the pool. At boot the instance polls for
  client `cerberus-console-grafana` and reads `ClientId`, `ClientSecret` and
  `CallbackURLs[0]`, and derives `root_url` from the callback URL. The secret
  never touches S3, tags or user-data. Gives up: the role can read every
  client in the pool (the SPA client is public, no secret).
- B: Terraform writes `session.env` to `artifacts/session/`. Puts the secret
  in an S3 object.
- C: instance tags for the URL and client ID. Adds a moving part for no gain.

**4.3 CloudWatch panels on the console host.**
- **A (chosen):** a boot-time transform of the same repo files into a
  console copy. Story panel 4: drop the CloudWatch targets, keep the AMP
  rows, add an annotation layer `tags=[cerberus, step]` (the ADR's
  annotation-based fallback). Story panel 9: `COST = $S` (compute estimate),
  relabelled. Run-live panel 7 and spark-on-eks panel 2: a text panel that
  says why. Each dashboard's default time is the newest run's window.
- B: edit the shared JSON so each panel carries both paths. Rejected: it
  changes the local recording host.

## 5. Decision and answers

4.1 A, 4.2 A, 4.3 A. Grafana runs from the tarball, not the RPM (the RPM's
dependencies on AL2023 are unverified; the tarball has none).

Everything at architecture level is decided by ADR 0024:

| Choice | Where ADR 0024 decides it |
|---|---|
| How the browser reaches Grafana | Its own per-session distribution, a VPC origin, the instance in the console subnet; no ALB, no public IP (L111-117, rejected options L249-253). Not a path on the standing distribution. |
| TLS | HTTPS on the default `*.cloudfront.net` certificate; origin HTTP stays inside the VPC origin (L50-52, L72-74). |
| Cognito app client | One per session in `dev-console` (L113): confidential, code flow + PKCE, callback `https://<session-cf>/login/generic_oauth`, logout `https://<session-cf>/login`. |
| NAT vs VPC endpoints | NAT (L196-198); the S3 gateway endpoint on the console route table is a free extra (PR A). |
| Instance type | t4g.small (L112); arm64 builds confirmed (F28, F29). |
| Session length | `MINUTES=90` (L119), Grafana 2 h maximum and 30 min idle (L194-195). Default 90, cap 120, instance timer at boot + MINUTES + 45 (PR E: the Cognito poll in user-data can take 40 minutes). |
| `live.json` | The live link for the landing page, written and deleted by `dev-console` (L114). |
| Account check | The `exercise.sh` check plus tagged distributions (L120-121). |

**Where changes go:**
- `dev-standing` (CI-applied, PR A): the S3 gateway endpoint on the console
  route table; the `DenyCloudFrontArtifacts` statement in the site bucket
  policy. No new outputs.
- `envs/dev-console` (owner-applied, PR D): everything else.
- `cerberus-admin` root paste: none expected (F24). Do not set
  `credit_specification` (T4g defaults to unlimited; the surplus for a short
  session is estimated at about $0.01, unverified); use SSM, not
  `GetConsoleOutput`. A hidden 403 follows the spike plan §9 procedure; the
  fix goes to `cerberus-admin-console-host` (about 3,780 characters of room).

**Artifacts:** `artifacts/grafana/grafana_13.2.3_36482603486_linux_arm64.tar.gz`
and `artifacts/grafana/grafana-amazonprometheus-datasource-3.2.0.linux_arm64.zip`,
pinned in `observability/grafana/console/artifacts.json` (name, version, URL,
sha256). A CI test checks that the versions match `compose.yaml`. The owner
stages them once per version with `make console-artifacts` (download into an
empty temp dir, check sha256, upload with `--metadata sha256=<hex>`, skip an
object whose metadata already matches). User-data checks sha256 again. The
per-session bundle (dashboards, `amp.yaml`, the dashboard provider, the boot
module and the run records) is an `archive_file` uploaded by Terraform as
`artifacts/session/bundle-<sha>.zip` and destroyed with the session.

**Self-terminate, trap and check:**
- The first user-data line is `shutdown -h +<MINUTES+45>` with
  `instance_initiated_shutdown_behavior = "terminate"`; Grafana's 2 h login
  maximum is the second bound.
- `orchestration/console_session.sh` copies the `exercise.sh` pattern: `trap
  teardown EXIT`, `trap 'exit 130' INT TERM`; teardown sets `trap '' INT TERM
  PIPE` and `set +e`, destroys with `-lock-timeout=120s` and retries once,
  waits up to 30 minutes for VPC ENIs to reach 0, then runs the check.
- `orchestration/console_check.sh` (read-only, `key value` lines, exit 1 on
  any non-zero session count): the four `exercise.sh` counts; instances not
  terminated with tag `Stack=dev-console`; distributions tagged
  `Stack=dev-console` (total distributions expected 1); VPC origins 0;
  Cognito clients named `cerberus-console-grafana` 0; role, instance profile
  and SG `cerberus-console-grafana` absent; no `0.0.0.0/0` route on the
  console route table; `live.json` and `artifacts/session/*` absent;
  `dev-console` state empty. Informational: VPC ENIs, the service SG.
  `exercise.sh` is not changed.

**Annotations and `live.json`:**
- New stdlib module `observability/grafana/console/` (Python 3.9-compatible),
  run on the instance with `python3 -I`:
  - `annotations.py`: run records to annotations. Per record: "Pipeline run
    started" at `start`; step regions from `states[]` with cumulative
    offsets; "Pipeline run <status>" at `end`; the DQ verdict (`cerberus-dq`,
    same text as `annotate_dq_verdict`); a `cerberus-now` "Finished"; a
    generator region from `generator.run_id` for `write_seconds` (marked
    "approx."); the teardown tile "Clean-up: not recorded in the run
    record". Tags match `annotate.sh` plus `console`.
  - `dashboards.py`: the 4.3 A transform, plus a generated home dashboard
    "0 · Recorded runs": one link per run record (all 17, newest first,
    failed runs marked) to `/d/cerberus-run-story?from=<start-10m>&to=<end+10m>`,
    widened to include the generator. Record fields are escaped.
  - `load.py`: posts the annotations to `http://127.0.0.1:3000` only.
- `annotate.sh --replay` is not reused (F15).
- `live.json` is an `aws_s3_object` at the site bucket root, created after a
  readiness probe passes, `Cache-Control: no-cache, max-age=0`:
  `{"schema":1,"url":"https://<session-cf>/","home":"/d/cerberus-runs","started":"<UTC>","ends":"<UTC>"}`.
  Destroy deletes it first. A stale file after a dead trap has `ends` in the
  past, so the reader must hide it; the contract is recorded in
  `console/README.md` for the 9.4 rebuild's `live.js`.

## 6. Build steps (one PR each)

**PR A, `dev-standing`, CI-applied.** The two changes above, plus this plan.
- Verify: the PR plan shows 2 in-place updates (`aws_vpc_endpoint.s3`,
  `aws_s3_bucket_policy.site`) plus the known Faker churn. After the apply,
  `describe-route-tables` shows the S3 prefix-list route on the console route
  table. The owner puts `artifacts/probe.txt`; CloudFront returns 403 for it
  and 200 for `/healthz.txt`; then the probe is deleted.

**PR B, artifact pinning and staging.** `observability/grafana/console/artifacts.json`,
`stage_artifacts.sh`, a Makefile `console-artifacts` target (AWS WRITE), the
version-match test. After merge the owner runs `make console-artifacts`.
- Verify: `bash -n`, shellcheck, pytest; `head-object` on both keys shows
  the size and `sha256` metadata equal to the lock; CloudFront returns 403
  for both.

**PR C, the console Grafana module, no AWS.** `annotations.py`,
`dashboards.py`, `load.py`, `grafana.ini.tmpl`, tests; a CI job
`grafana-console-tests` on Python 3.9; a ruff per-dir `target-version =
"py39"`.
- Tests: no `cloudwatch` uid and no `__expr__` that references a dropped
  refId remain; every AMP panel survives; the annotation count per record;
  the state sum equals `run_seconds`; link windows; a hostile record is
  escaped; `load.py` refuses a non-loopback URL.
- Local verify ($0): a temporary Compose override mounts only `amp.yaml` and
  the transformed dashboards; the story dashboard on the 2026-10-13 and 8.10
  windows shows no "datasource not found".

**PR D, the `envs/dev-console` root, plan only.**
- `versions.tf`: partial `backend "s3" {}`, aws `~> 5.0`, the lock file.
- `provider.tf`: `default_tags { Project = "cerberus-platform", Stack = "dev-console" }`.
- `main.tf`: `terraform_remote_state` (bucket from `data.aws_caller_identity`);
  `module "nat"` (`../../modules/vpc_nat`, the console route table); role and
  profile `cerberus-console-grafana` (AMP query on the workspace,
  `s3:GetObject` on `<site>/artifacts/*`, the two Cognito reads on the pool,
  `AmazonSSMManagedInstanceCore`); SG `cerberus-console-grafana` (egress tcp
  443; ingress tcp 3000 from the service SG); the instance (t4g.small, AL2023
  arm64 AMI from SSM, console subnet, no key, no public IP, IMDSv2 with hop
  limit 1, shutdown behaviour terminate, `user_data_replace_on_change`,
  `depends_on` the NAT route); `aws_cloudfront_vpc_origin` (port 3000,
  `http-only`, 30 m timeouts); a service-SG wait (poll by tag
  `aws.cloudfront.vpcorigin` for up to 10 minutes; fixes spike finding 1); the
  distribution ("cerberus console session", `PriceClass_100`,
  `redirect-to-https`, all methods, CachingDisabled and AllViewer, the managed
  `SecurityHeadersPolicy`, `wait_for_deployment = true`); the app client
  `cerberus-console-grafana` (`generate_secret = true`, code flow, `openid`,
  callback `/login/generic_oauth`, logout `/login`, 60-minute tokens,
  `prevent_user_existence_errors`); the bundle object; a readiness probe
  (`/api/health` until 200, at most 20 minutes); the `live.json` object.
- `user_data.sh.tftpl`: copy and check the artifacts and the bundle; install
  Grafana to `/opt/grafana` and the plugin; write provisioning and dashboards
  with `python3 -I`; poll Cognito for the client (up to 40 minutes); render
  `grafana.ini` (0640 root:grafana): `http_addr = 127.0.0.1` first,
  `root_url`, `cookie_secure`, random `secret_key` and admin password, login
  form off, the 2 h and 30 min limits, `[auth.generic_oauth]` (auto login,
  PKCE, `openid`, Cognito URLs, `login_attribute_path = sub`,
  `email_attribute_path = join('', [sub, '@cerberus.invalid'])` (F30,
  unverified), `role_attribute_path = 'Viewer'`, `role_attribute_strict`),
  `signout_redirect_url` to Cognito `/logout`, Viewer by default, Explore,
  snapshots and public dashboards off, update checks and the news feed off,
  plugin preinstall off (key name unverified), unified alerting off; a
  hardened systemd unit; run `load.py`; then `http_addr = 0.0.0.0` with basic
  auth off, and restart. Port 3000 opens only after the annotations are
  loaded and basic auth is off.
- Delete `terraform/spikes/vpc-origin/` (F6).
- Verify: `terraform fmt -check -recursive terraform/`; `init -backend=false`
  and `validate`; `bash -n` on a rendered user-data; no 12-digit numbers; the
  owner runs a read-only `make console-plan` (about 15 to 18 to add, nothing
  to change or destroy).

**PR E, `make console-session`, `console-check`, `console-destroy`.**
`orchestration/console_session.sh`, `orchestration/console_check.sh`, the
Makefile targets, and README sections (including the `live.json` contract).
Flow: preflight (identity, a check of 0, empty state, both artifacts present
with matching sha, standing outputs readable, `1 <= MINUTES <= 120`); a y/N
prompt with the cost; plan and apply; print the URL and count down; the trap
tears down.
- Verify: `bash -n`, shellcheck; `make console-check` prints all zeros today.

**PR F, the live check and record (closes 9.2).** A short session first
(`MINUTES=30`), then a full one.
1. Sign in from a clean private window: the story dashboard loads, no
   password form, no admin menu.
2. "0 · Recorded runs" opens the 2026-10-13 and 8.10 windows with data and
   step annotations; the Now, DQ and Clean-up tiles are filled.
3. A Viewer can open Inspect → Query and cannot use Explore.
4. `/api/ds/query` with uid `cloudwatch` fails.
5. Sign out returns to `/login`; the next sign-in asks for the password.
6. Over SSM: `curl -s localhost:3000/api/health`; the plugin uses instance
   credentials.
7. `live.json` is present during the session and absent after.
8. Destroy takes about 11 minutes; `make console-check` returns all 0.
9. Cost Explorer the next day.

Record an Outcome section (wake, destroy and ENI times, session cost), check
off Phases.md 9.2, and add a progress note to plan step 10.

## 7. Owner-run commands

```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
make console-artifacts            # once per Grafana/plugin version; AWS WRITE (after PR A is applied)
make console-check                # read-only; every session count must be 0
make console-session MINUTES=30   # first live check; default 90, max 120; Ctrl-C ends early
# only if a session was interrupted (laptop sleep, crash):
make console-destroy && make console-check
```

## 8. Cost per session

| Item | List price (ADR 0024, 2026-10-27; not rechecked, F27) |
|---|---|
| t4g.small | $0.0168/h |
| NAT gateway | $0.045/h + $0.045/GB |
| Public IPv4 (NAT EIP) | $0.005/h |
| gp3 8 GiB | about $0.0009/h |
| **Hourly** | **about $0.068/h** |

A 90-minute session runs about 2 h in total (about 15 min wake, 90 min,
about 11 min destroy): about $0.14 if NAT partial hours bill as full hours
(unverified). After PR A, S3 traffic goes through the gateway endpoint at $0.
Four demos a month cost about $0.56. An interrupted session costs about
$1.20/day until destroy (F4).

## 9. Risks

1. The service-SG race (spike finding 1): handled by the wait loop.
2. `generic_oauth` needs an email (F30). The synthesised
   `sub@cerberus.invalid` claim is unverified. The fallback is an `email`
   attribute per invited user, which is PII: ask the owner first.
3. Grafana 12+ may install plugins or call grafana.com at start: turn it
   off and confirm in the first session's log over SSM.
4. Hidden 403s on first use: the spike §9 procedure.
5. A stale `live.json` after a dead trap: the `ends` field; the 9.4 reader
   must respect it.
6. An exercise and a session at the same time trip both account checks: do
   not overlap them.
7. CloudFront's 30 s origin timeout on a heavy AMP range query: watch in
   PR F.
8. The AMP plugin reading the instance role through `sigV4AuthType:
   default` is unverified on the host: check in PR F.
9. The hosted-UI cookie gives a silent Grafana sign-in within about 1 h of a
   terminal sign-in: expected.
10. The generator window is approximate (F16): labelled "approx.".
11. `standing-destroy` must wait for the ENIs and the service SG after a
    session (spike L247).
