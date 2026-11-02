# Plan: 9.2 the standing edge (ADR 0024, build step 7)

Date: 2026-11-02. Planner: Opus. Base: `main` at `bcbf804`. No new ADR is needed. This plan adds a dated amendment to ADR 0024 (section 6), because it changes the text of two accepted rules: rule 8 (reserved concurrency) and "managed login".

User decisions (2026-11-02):
- Concurrency: option B. No reserved concurrency; stage throttling of 1 request per second, burst 3; a 60 s negative cache and 5-minute Athena result reuse in the package. The owner may file the free quota request at root later (option C).
- Sign-in pages: the classic hosted UI (`managed_login_version = 1`) on the Essentials tier. Managed login waits for an AWS provider 6.x bump.
- Record: a dated amendment inside ADR 0024 (as in ADR 0018 and ADR 0022), not a new ADR.
- Plan confirmed as written.

## 1. Question

How do we build the standing edge: the site bucket, CloudFront, Cognito, the HTTP API with a JWT authorizer and the command Lambda? It must cost $0 idle, CI must apply it after one local apply, and the visitor-path cost must stay bounded. The account cannot grant ADR 0024's "reserved concurrency of 2".

Why now: 9.3's package (#128) and workgroup (#127) are built. Step 7 is the next step of the demo-console plan. Steps 8 (landing page) and 9 (terminal) need its outputs.

## 2. Facts

Repo:
- F1. ADR 0024 (`docs/adr/0024-demo-console.md`) puts these standing resources in `dev-standing`: an S3 site bucket, and CloudFront with OAC to S3, `/api/*` to the API (no cache, `Authorization` forwarded by an origin request policy) and a response-headers policy (L84-98). It also lists a Cognito pool with self sign-up off and managed login, an HTTP API with a JWT authorizer and throttling, and the command Lambda.
  - Rule 8: "HTTP API throttling (for example 2 requests per second, burst 5; the values are to be set in 9.2), Lambda reserved concurrency of 2, and a 25 s timeout" (L174-176).
  - Rule 9: access logs include the Cognito `sub` (L177-178).
  - Sign-in: managed login with PKCE, a 60-minute token, no refresh in the SPA. "Whether Cognito access tokens validate with `client_id` rather than `aud` is to be confirmed in build" (L182-186).
  - Consequences claim the cost is "hard-bounded by throttling, reserved concurrency, ..." (L291-293).
- F2. The IAM prerequisites plan (`docs/plans/2026-10-27-console-iam-prerequisites.md`) fixes these names:
  - site bucket `cerberus-platform-console-<account_id>`;
  - Lambda `cerberus-console-*`;
  - log groups `/aws/lambda/cerberus-console-*` and `/aws/apigateway/cerberus-console-*` (L81-86).
  - Its outcome section records the Lambda account limit of 10 (L201). Its risk 1 marks `logs:CreateLogDelivery` for HTTP API access logs as unverified (L180).
- F3. `cerberus-ci-apply-console` (`terraform/modules/github_oidc/main.tf` L576-730) has:
  - `s3:*` on the site bucket;
  - IAM management of exactly `cerberus-console-cli` and `cerberus-grafana-read`, with `PutRolePolicy`;
  - `iam:PassRole` of `cerberus-console-cli` to Lambda only;
  - `lambda:*` on `function:cerberus-console-*`;
  - `logs:*` on the two console log-group patterns;
  - CloudFront `CreateDistribution` with `aws:RequestTag/Project`, and the distribution and policy-type Sids;
  - Cognito `CreateUserPool` and pool, client and domain actions, with no `Admin*User`.

  The inline `ManageLineageApi` gives `apigateway:*` on `/apis` and `/apis/*` (L342-349).
- F4. The lineage module is the HTTP API + Lambda pattern (`terraform/modules/lineage/main.tf` L88-260):
  - `archive_file` with `source { content = file(...) }`, Python 3.12, an explicit log group;
  - an `AWS_PROXY` integration with payload 2.0, a `$default` stage with `default_route_settings` throttling and JSON access logs, and an `aws_lambda_permission` on `execution_arn/*/*`;
  - log retention 14 days (`lineage/variables.tf` L36-39).
- F5. `cerberus-console-cli` trusts `lambda.amazonaws.com` and `user/cerberus-admin`. It has one inline policy, `cerberus-console-cli-policy`, with Step Functions reads only on `main` (`terraform/modules/console_roles/main.tf`). #127 adds six Athena, Glue and S3 statements to that same policy. **It has no CloudWatch Logs write.**
- F6. #128 (`9.3-command-set`, commit `7d60861`), in `console/cerberus_console/`:
  - `api.lambda_handler(event, context, *, sources=None)` takes HTTP API v2 events and returns `statusCode` 200/400/404/503 with `cache-control: no-store`;
  - `config.RUNS_DIR` comes from `CERBERUS_RUNS_DIR` at import, and the state machine ARN from `CERBERUS_STATE_MACHINE_ARN`;
  - boto3 is imported lazily in `aws.py`;
  - `TTLCache.get_or_set` does not cache failures ("a failure is raised, not cached");
  - the caches are ListExecutions 30 s and freshness 300 s;
  - `StartQueryExecution` is called with no `ResultReuseConfiguration`;
  - `runs` returns `data.runs` and `data.total`.
- F7. The run records are 14 files, 176 KB (`observability/scale/runs/`).
- F8. `terraform-apply.yml` and `terraform-plan.yml` trigger on `terraform/**` plus a list of code paths read by `file()`. `console/**` and `observability/scale/runs/**` are not on the list.
- F9. `.gitignore` L19-21 ignores the `build/` folders of the lambda_ingestion, observability and lineage modules.
- F10. The AWS provider is 5.100.0 and archive is 2.8.0 (`terraform/envs/dev-standing/.terraform/providers`).
  - The 5.100 schema (dumped 2026-11-02) has `aws_cognito_user_pool.user_pool_tier`, `aws_cognito_user_pool_domain.managed_login_version`, `aws_cognito_resource_server` and the CloudFront OAC, response-headers, cache and origin-request policy resources.
  - It has **no `aws_cognito_managed_login_branding`**.

AWS (read-only, `cerberus-admin`, us-east-1, 2026-11-02):
- F11. `lambda get-account-settings`: `ConcurrentExecutions` 10, `UnreservedConcurrentExecutions` 10. Service Quotas `L-B99A9384` "Concurrent executions" is 10.0 and adjustable.
  - `cerberus-admin` is denied `servicequotas:GetAWSDefaultServiceQuota`, `ListRequestedServiceQuotaChangeHistory` and `RequestServiceQuotaIncrease`.
  - `lambda:ListFunctions` and `scheduler:ListSchedules` are also denied.
- F12. No Cognito user pools exist. `cloudfront list-distributions` returns no distributions. The one HTTP API is `cerberus-lineage-collector`. The site bucket does not exist (HeadBucket 404). The Cognito prefix domains `cerberus-console` and `cerberus-platform-console` are not in use (`describe-user-pool-domain` is empty).
- F13. `simulate-principal-policy` on `role/cerberus-ci-apply`:
  - Allowed: `apigateway:POST` on `/apis` and `/apis/{id}/authorizers`; `cloudfront:CreateDistribution` with the `Project` request tag; `CreateOriginAccessControl` and `CreateResponseHeadersPolicy`; `ListCachePolicies`; `cognito-idp:CreateUserPool`, `CreateUserPoolDomain`, `CreateUserPoolClient` and `CreateManagedLoginBranding`; `lambda:CreateFunction`, `AddPermission` and `PutFunctionConcurrency` on `cerberus-console-command`; `iam:PassRole` of `cerberus-console-cli` to Lambda; `iam:PutRolePolicy` on `cerberus-console-cli`; `s3:CreateBucket`, `PutBucketPolicy` and `PutObject` on the site bucket; `logs:CreateLogGroup`, `PutRetentionPolicy` and `TagResource` on both console log groups; `logs:DescribeLogGroups`.
  - Implicit deny: `logs:CreateLogDelivery`, `GetLogDelivery`, `UpdateLogDelivery`, `DeleteLogDelivery`, `ListLogDeliveries`, `PutResourcePolicy` and `DescribeResourcePolicies`; `cognito-idp:CreateResourceServer`, `AdminCreateUser` and `SetUICustomization`; `iam:UpdateAssumeRolePolicy`; `servicequotas:RequestServiceQuotaIncrease`.
- F14. `simulate-principal-policy` on `user/cerberus-admin`: allowed for every create action in F13 that step 7 uses, plus `logs:PutResourcePolicy` and `DescribeResourcePolicies`. **Implicit deny: `logs:CreateLogDelivery`, `GetLogDelivery`, `UpdateLogDelivery`, `DeleteLogDelivery`, `ListLogDeliveries`.**
- F15. `simulate-principal-policy` on `role/cerberus-ci-plan` allows every refresh read step 7 needs: Cognito Describe and Get, CloudFront Get, `apigateway:GET`, Lambda Get and List, `logs:ListTagsForResource`, S3 policy and ownership reads.

External (read 2026-11-02):
- F16. Lambda reserved concurrency: "You can reserve up to the Unreserved account concurrency value minus 100." Reserving costs nothing. So reserving 2 needs an account limit of at least 102 ([Lambda reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html)).
- F17. Lambda quotas: the default concurrent executions quota is 1,000. "New AWS accounts have reduced concurrency and memory quotas ... AWS raises these quotas automatically based on your usage." A request is possible through Service Quotas, but **approval and timing are unknown** ([Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)).
- F18. Cognito feature plans: new pools default to Essentials. "Managed login is available in the Essentials and Plus tiers. The classic hosted UI is available in all feature tiers." Lite "includes ... the classic hosted UI". **This closes the §8 item: Lite does not include managed login** ([feature plans](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-sign-in-feature-plans.html)).
- F19. Cognito pricing: Lite and Essentials both have 10,000 free MAU for direct sign-in, and the free tier does not expire. Above it, Essentials is $0.015 per MAU and Lite starts at $0.0055 ([pricing](https://aws.amazon.com/cognito/pricing/)).
- F20. "When an app client doesn't have a style assigned, your managed login pages for that app client are nonfunctional until you create a new style or switch the domain branding version" ([DeleteManagedLoginBranding](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_DeleteManagedLoginBranding.html)). With F10, managed login (version 2) cannot be made to work in Terraform on provider 5.100.
- F21. The HTTP API JWT authorizer checks "`aud` or `client_id` ... API Gateway validates `client_id` only if `aud` is not present". It also says: "There is no standard mechanism to differentiate JWT access tokens from ... ID tokens ... we recommend that you configure your routes to require authorization scopes" ([JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)). **This closes the §8 item: set the audience to the app client ID. A route scope is needed to refuse ID tokens.**
- F22. HTTP API access logging: the caller needs `logs:CreateLogDelivery`, `PutResourcePolicy`, `UpdateLogDelivery`, `DeleteLogDelivery`, `CreateLogGroup`, `DescribeResourcePolicies`, `GetLogDelivery` and `ListLogDeliveries` on `*` ([HTTP API logging](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging.html)). Whether this is enforced is **unverified**: the lineage stage has access logs and CI manages it, but it was created in 6.4b, before `cerberus-admin`'s least-privilege policies (7.3). `$context.authorizer.claims.{property}` and `$context.authorizer.error` are valid log variables ([logging variables](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging-variables.html)).
- F23. CloudFront strips `Authorization` by default. It can be forwarded by "an origin request policy that forwards all viewer headers", or by naming it in an origin request policy or the cache key ([CloudFront custom headers](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/add-origin-custom-headers.html)). An older Knowledge Center article says an origin request policy cannot carry `Authorization` ([KC](https://repost.aws/knowledge-center/cloudfront-authorization-header)). **The two sources conflict, so this is unverified until the live check.**
- F24. Athena query result reuse works within one workgroup and supports Iceberg tables in Glue. The maximum age is up to 7 days. The caller needs S3 read on the previous result. AWS says reuse "can ... reduce costs in terms of the number of bytes scanned". **Whether a reused query has a zero charge, or one on `$snapshots` metadata tables, is unverified** ([result reuse](https://docs.aws.amazon.com/athena/latest/ug/reusing-query-results.html)).

## 3. Constraints

- $0 idle. Budget $20/month, forecast about $17.2 (ADR 0024).
- CI applies `dev-standing` only. The first apply of new resource types runs locally as `cerberus-admin`. `cerberus-ci-apply` cannot widen itself. `cerberus-admin` changes need a root paste.
- `dev-compute` is not touched. Nothing the 8.10 take uses changes before the take (section 7, "Dependencies").
- No trust change: CI lacks `iam:UpdateAssumeRolePolicy`, and none is needed (F5).
- Public repo: no account ID in new files (`var.account_id` or `data.aws_caller_identity`; `<ACCOUNT_ID>` in docs). No emails, secrets, tokens or passwords. Cognito users are created by the owner by hand, never in the repo. The verify steps keep tokens in shell variables and never print them.
- ADR 0024 is followed except rule 8 and "managed login", which the amendment changes by name. ADR 0013 (lineage API) and ADR 0011 (two CI roles) are not contradicted.
- Tools: `TMPDIR=$HOME/.cache/tfspiketmp` for terraform; `uvx ruff@0.16.4`.

## 4. Options

### 4.1 Lambda concurrency (the open item)

- **A. Ask for a free quota increase, then reserve 2.** The owner files a Service Quotas request at the root console (`cerberus-admin` cannot, F11) for concurrent executions of at least 102 (ask for 1,000, the default, F17). Then `reserved_concurrent_executions = 2`.
  - Idle $0; per use $0 (F16).
  - Effort: one root action, then waiting for an AWS decision of unknown timing and outcome (F17). Until it is granted, step 7 is blocked: `terraform apply` with 2 fails while the limit is below 102.
  - Gives a hard per-function ceiling of 2 containers. The console can never starve the pipeline's Lambdas (ingestion, lineage collector, freshness probe), which share the account's pool.
  - Gives up: the repo no longer applies in a fresh account. A third concurrent visitor command gets throttled.
- **B. No reserved concurrency. Stage throttling plus in-function bounds (recommended, chosen).**
  - `$default` stage throttling at 1 request per second, burst 3.
  - The account limit of 10 is the ceiling.
  - Two package changes: a 60 s negative cache on the freshness query, so a failing Athena is not re-queried on each retry; and Athena result reuse (`MaxAgeInMinutes = 5`), so containers share one result instead of one billed query each.
  - `reserved_concurrent_executions` stays a module variable, default unreserved (`-1`), so 2 is a one-line change later.
  - Idle $0. Per use: section 10.
  - Effort: about 30 lines of Python and tests. No wait and no root action.
  - Gives up: there is no per-function ceiling. At the throttle, slow `status` calls (Athena up to the 12 s deadline) can hold several of the 10 slots. In the worst case, a signed-in abuser crowds out other visitors (the throttle is shared) and briefly other Lambdas.
- **C. B now, A later.** The same as B, plus the owner files the free quota request now (optional). If it is granted (limit at least 102), set the variable to 2 in a later one-line PR. This is B plus a revisit trigger, not a separate design.

Pillars in tension:
- *Cost vs Reliability.* A bounds the function. B bounds the request rate and the Athena spend. Both give a cost ceiling. A also protects the pipeline Lambdas, but it fails closed on an AWS decision we do not control.
- *Operational Excellence.* B keeps "clone, apply, works" for any account. A ties the repo to this account's quota history.
- *Security.* The visitor path is invitation-only (JWT). Abuse needs an invited account, so throttling plus invites is proportionate. The Budgets alerts at 75% and 100% are the backstop.

### 4.2 Sign-in pages

- **Classic hosted UI (`managed_login_version = 1`), pool tier `ESSENTIALS` set explicitly (recommended, chosen).** Works in Terraform on 5.100 with no extra resource. PKCE code flow works the same way. $0 under 10,000 MAU (F19). Gives up: the newer managed-login look. Moving later is two lines (domain version plus a branding resource) once the provider is on 6.x.
- Managed login (version 2) on 5.100. Needs a style per app client, or the pages are "nonfunctional" (F20). Terraform 5.100 cannot create one (F10). A style created with the CLI by hand is drift outside Terraform. Rejected.
- AWS provider 6.x bump first. This gets `aws_cognito_managed_login_branding`, but the bump touches every module's plan in both roots, including `dev-compute`. That is out of scope before 8.10 and not needed for the Done-when.
- Tier Lite. Same $0 at this scale, but it would lock out managed login later. Not chosen.

### 4.3 API access logs (the `CreateLogDelivery` gap, F13, F14, F22)

- **Apply first, paste only if refused (recommended).** Keep the access log with the Cognito `sub` (rule 9). If the local apply fails on the stage with an access-log permission error, the owner pastes one Sid (section 8, A1), and the apply runs again. All resources are new, so a half-applied state is safe. CI gets the same Sid only if the local apply proves it is needed: CI changes a stage's log settings only when they change.
- Paste first. One root session even if it is not needed, and a grant on `*` that may be unused.
- Drop access logs and log the `sub` in the Lambda. No root paste, but 401 and 429 requests (abuse signals) would leave no record, and rule 9 would change. Fallback only.

## 5. Recommendation

**4.1 B (with C's optional quota request), 4.2 classic hosted UI on Essentials, 4.3 apply first.** Why B wins:
- It is the only option that does not block step 7 on an AWS decision.
- The cost bound comes from three things we control: the stage throttle, the invite-only JWT, and shared Athena results. Reserved concurrency mostly protects the pipeline Lambdas from an abusive invited visitor, and that risk is small, short and visible in the access log.

Design (one new module, `terraform/modules/console_edge`, one `main.tf` with numbered sections like `lineage`):

1. **Site bucket** `cerberus-platform-console-${var.account_id}`:
   - public access block (all four), `BucketOwnerEnforced`, SSE-S3, no versioning, `force_destroy = true` (contents are rebuilt by 9.4's publish);
   - a bucket policy allowing only `cloudfront.amazonaws.com` `s3:GetObject` on `/*`, with `StringEquals AWS:SourceArn = <distribution ARN>`;
   - one managed object `healthz.txt` ("ok", `text/plain`), the probe for the OAC check. 9.4 never touches it. 9.4 owns `index.html` and the rest; Terraform manages no other objects.
2. **CloudFront:**
   - OAC `cerberus-console-site` (S3, `always`, `sigv4`).
   - Response-headers policy `cerberus-console-security-headers`:
     - CSP (override): `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' https://<prefix>.auth.us-east-1.amazoncognito.com; form-action 'self' https://<prefix>.auth.us-east-1.amazoncognito.com; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; upgrade-insecure-requests`;
     - HSTS 1 year, `nosniff`, `X-Frame-Options DENY`, `Referrer-Policy no-referrer`;
     - a custom `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
     - The Cognito host is built from `var.cognito_domain_prefix`, a string, so there is no dependency cycle. 9.5 may need to relax `style-src` for xterm.js; it changes this one place.
   - Distribution:
     - `default_root_object = "index.html"`, `PriceClass_100`, IPv6 on, `http2and3`, default certificate, tags from `default_tags`;
     - default behaviour to S3: redirect-to-https, GET/HEAD, `Managed-CachingOptimized`, the response-headers policy;
     - ordered behaviour `/api/*` to the HTTP API origin (`<api_id>.execute-api.us-east-1.amazonaws.com`, https-only, TLSv1.2): all 7 methods, `Managed-CachingDisabled`, `Managed-AllViewerExceptHostHeader` (forwards `Authorization`, F23; not `AllViewer`, which sends the CloudFront `Host` and breaks API Gateway), the same response-headers policy.
     - Managed policies are read with data sources by name (`aws_cloudfront_cache_policy` and `aws_cloudfront_origin_request_policy`), not hard-coded IDs. CI and plan can list them (F13, F15).
     - No standard logging: it needs an ACL-enabled bucket. Viewer TLS minimum cannot be raised with the default certificate. Record both as known limits.
3. **Cognito:**
   - `aws_cognito_user_pool` `cerberus-console`:
     - `user_pool_tier = "ESSENTIALS"`, `deletion_protection = "ACTIVE"` (a forced replacement fails loudly instead of deleting the hand-made users);
     - `admin_create_user_config { allow_admin_create_user_only = true }` (self sign-up off);
     - username sign-in, case-insensitive, no required or auto-verified attributes, so no email is needed;
     - `account_recovery_setting` admin-only, `mfa_configuration = "OFF"`, password policy minimum 12 with all four classes, temporary password valid 7 days.
   - `aws_cognito_user_pool_domain`: `domain = var.cognito_domain_prefix` (default `cerberus-console`, free on 2026-11-02, F12), `managed_login_version = 1`.
   - `aws_cognito_user_pool_client` `cerberus-console-spa`:
     - `generate_secret = false`, `allowed_oauth_flows_user_pool_client = true`, `allowed_oauth_flows = ["code"]`, `allowed_oauth_scopes = ["openid"]`, `supported_identity_providers = ["COGNITO"]`;
     - `callback_urls = ["https://<cf domain>/terminal/"]`, `logout_urls = ["https://<cf domain>/"]`;
     - access, ID and refresh tokens 60 minutes (refresh minimum), `token_validity_units` in minutes, `auth_session_validity = 3`;
     - `enable_token_revocation = true`, `prevent_user_existence_errors = "ENABLED"`, `explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]`. This is the minimum surface: no SRP or password API for scripts. It is unverified that the classic hosted UI works with this set; the fallback adds `ALLOW_USER_SRP_AUTH` (risk 3).
   - PKCE is sent by the client. Cognito has no "require PKCE" switch (unverified); the SPA (9.5) always sends S256.
4. **HTTP API** `cerberus-console-api`:
   - no CORS: CloudFront makes `/api` same-origin;
   - JWT authorizer: `identity_sources = ["$request.header.Authorization"]`, `issuer = "https://${aws_cognito_user_pool.this.endpoint}"`, `audience = [client id]` (F21);
   - `AWS_PROXY` integration, payload 2.0;
   - one route `POST /api/command`, `authorization_type = "JWT"`, `authorization_scopes = ["openid"]`. Cognito ID tokens carry no `scope` claim, so they are refused (F21);
   - `$default` stage, `auto_deploy`, `default_route_settings` throttling `var.throttle_rate_limit = 1` and `var.throttle_burst_limit = 3`;
   - JSON access log to `/aws/apigateway/cerberus-console-api` (30 days, the audit window for a month of invites), with fields `requestId`, `requestTime`, `routeKey`, `status`, `authError` (`$context.authorizer.error`), `sub` (`$context.authorizer.claims.sub`), `integrationStatus`, `integrationLatency`, `responseLength` and `sourceIp`.
5. **Lambda** `cerberus-console-command`:
   - `archive_file` with dynamic `source` blocks over `fileset(<repo>/console/cerberus_console, "*.py")` → `cerberus_console/<f>`, and `fileset(<repo>/observability/scale/runs, "*.json")` → `runs/<f>`. `output_file_mode = "0644"`, output under `${path.module}/build/`.
   - A `lifecycle { precondition }` that `api.py` is in the package file set, so an empty zip can never deploy.
   - Python 3.12 (boto3 from the runtime), `arm64`, 256 MB, timeout 25 s (rule 8), handler `cerberus_console.api.lambda_handler`.
   - Environment: `CERBERUS_RUNS_DIR = "/var/task/runs"` and `CERBERUS_STATE_MACHINE_ARN = var.state_machine_arn`.
   - `reserved_concurrent_executions = var.command_reserved_concurrency` (default `-1`; the description says "set 2 only when the account limit is at least 102").
   - Role: the existing `cerberus-console-cli`, by ARN.
   - Log group `/aws/lambda/cerberus-console-command`, 14 days (the project norm).
   - Logs grant: a second inline policy, `cerberus-console-cli-logs` (in `console_edge`, on `var.console_cli_role_name`): `logs:CreateLogStream` and `logs:PutLogEvents` on `${log_group.arn}:*` only. No `AWSLambdaBasicExecutionRole`, which allows `CreateLogGroup` on `*`. A separate policy keeps step 7 off #127's `cerberus-console-cli-policy`, so there is no merge conflict. CI may do it (`PutRolePolicy`, F13).
   - `aws_lambda_permission` with `source_arn = "${execution_arn}/*/POST/api/command"`.
6. **Package changes (PR 7a):**
   - `aws.py`: `TTLCache` gains an optional `negative_ttl`. The freshness reader uses 60 s: a failure is stored and re-raised as `Unavailable` until it expires.
   - `StartQueryExecution` passes `ResultReuseConfiguration={"ResultReuseByAgeConfiguration": {"Enabled": True, "MaxAgeInMinutes": config.RESULT_REUSE_MINUTES}}` with `RESULT_REUSE_MINUTES = 5` (equal to `FRESHNESS_TTL`). The role already reads `console/*` (#127), which reuse needs (F24).
   - `run <id>` history stays uncached. It is free (no Athena), and the throttle bounds it.

Deviations from the demo-console plan, to name in the PR:
1. No reserved concurrency (the amendment).
2. Classic hosted UI, not managed login (the amendment).
3. The Lambda logs grant is a second inline policy, not a statement in `console_roles`.
4. Workflow path filters change (section 7).

## 6. ADR outline

No new ADR (user decision). A dated **Amendment (2026-11-02): rate bounds and sign-in pages for the standing edge** in `docs/adr/0024-demo-console.md`, as in ADR 0018 (2026-10-09) and ADR 0022 (2026-10-25). Add one Status line: "Amended 2026-11-02: no reserved concurrency; classic hosted UI (see Amendment below)." The original Decision text stays.

- **Context:**
  - The account limit is 10 and adjustable, measured 2026-10-27 and re-read 2026-11-02 (F11). Reserving needs the limit minus 100 (F16). New accounts get reduced quotas that rise with usage, with unknown timing (F17). `cerberus-admin` cannot file a request.
  - Provider 5.100 has no managed-login branding resource (F10), and managed login without a style does not work (F20).
  - The JWT authorizer checks `client_id` when `aud` is absent, and cannot tell ID tokens from access tokens without a scope (F21).
- **Decision:**
  1. No reserved concurrency. `command_reserved_concurrency` stays a variable, default unreserved.
  2. Stage throttling of 1 request per second, burst 3, replaces rule 8's example values.
  3. In-function bounds: ListExecutions 30 s, freshness 300 s, a 60 s negative cache, and Athena result reuse for 5 minutes.
  4. The classic hosted UI (`managed_login_version = 1`) on the Essentials tier, until the AWS provider moves to 6.x.
  5. The audience is the app client ID, and the route requires the `openid` scope.
- **Consequences:**
  - Good: `terraform apply` works in any account. The worst month at the throttle is about $3.4 with result reuse, about $7.7 without (section 10). No root action is needed.
  - Given up: no per-function ceiling. A signed-in abuser can crowd out other visitors (one shared throttle) and, during slow Athena calls, use several of the account's 10 slots shared with the pipeline Lambdas. The classic sign-in look.
  - Revisit if: the account limit reaches at least 102 (set 2); the provider is on 6.x (managed login); invites go beyond a handful (already a 0024 trigger).
  - It also closes two "To confirm in build" items (Lite has no managed login; access tokens validate by `client_id`).

## 7. Build steps (Phases.md 9.2, demo-console plan §7 step 7)

### Dependencies and the 8.10 take

- Step 7 adds only new resources. The changes to existing objects are a new inline policy on `cerberus-console-cli` (the take does not use that role) and two workflow path filters. Any `dev-standing` apply also carries the known Faker-layer churn, which replaces the layer of `cerberus-ingest-payments`, the take's `InvokeIngestion` Lambda. **So never apply during an exercise.**
- The Lambda zip needs #128's package files, and #128's `test_tables_match_iam.py` reads #127's variable. **Merge order: 8.10 take recorded → #127 → #128 (with 7a) → 7b.** Step 7 therefore applies after the take. Writing the code and the docs PR (7.0) can start now.

### PR 7.0: ADR 0024 amendment and this plan (docs only, branch `9.2-standing-edge-adr`)

- Files: `docs/adr/0024-demo-console.md` (Status line and Amendment section), `docs/plans/2026-11-02-standing-edge.md` (this plan), `docs/plans/2026-10-27-demo-console.md` (§7 step 7: a "Changed in" note with the link; §8: mark the Cognito Lite item and the JWT `client_id` item as verified, with F18 and F21).
- Verify: Opus review. The user accepts, and the Status note is dated. It touches nothing in AWS, so it can merge before 8.10.

### PR 7a: package bounds (Python, no AWS)

Add to #128's branch `9.3-command-set` before #128 leaves draft, so the package lands once.
- `console/cerberus_console/config.py`: `FRESHNESS_NEGATIVE_TTL = 60` and `RESULT_REUSE_MINUTES = 5`, with comments citing ADR 0024's amendment.
- `console/cerberus_console/aws.py`: `TTLCache(ttl, clock, negative_ttl=0)` stores `(now, _FAILED)` on exception and re-raises `Unavailable` while it is fresh. The original exception is raised on the first failure only. The freshness reader passes the negative TTL and `ResultReuseConfiguration`. The Step Functions reader keeps `negative_ttl=0`.
- `console/tests/test_aws_cache.py` (new), with a fake clock and a fake Athena client:
  - a failing query is started once in 60 s, then again after 61 s;
  - a success is cached 300 s;
  - `start_query_execution` receives `ResultReuseConfiguration` with `MaxAgeInMinutes == 5`.
- `console/README.md`: the cost row for `status` says "at most one billed query per 5 minutes across containers when Athena reuses the result (unverified for a zero charge)".
- Verify: `uvx ruff@0.16.4 check .`, `uvx ruff@0.16.4 format --check .`, `uvx --with pytest==9.1.1 pytest console -q`.

### PR 7b: the standing edge (branch `9.2-standing-edge`, stacked on `9.3-command-set`; retarget to `main` after #128 merges)

Files:
1. `terraform/modules/console_edge/main.tf` (sections 1-5 in section 5), `variables.tf` and `outputs.tf`.
   - Variables: `account_id`, `region` (default `us-east-1`), `console_cli_role_arn`, `console_cli_role_name`, `state_machine_arn`, `cognito_domain_prefix` (`cerberus-console`), `throttle_rate_limit` (1), `throttle_burst_limit` (3), `command_reserved_concurrency` (-1), `lambda_timeout_seconds` (25), `lambda_memory_mb` (256), `token_validity_minutes` (60), `log_retention_days` (14), `access_log_retention_days` (30).
   - The header comment cites ADR 0024 and its amendment, $0 idle, and the names fixed by the IAM plan.
2. `terraform/envs/dev-standing/main.tf`: `module "console_edge"` with `data.aws_caller_identity.current.account_id`, `module.console_roles.console_cli_role_arn` and `console_cli_role_name`, and `module.step_functions.state_machine_arn`. No literal account ID.
3. `terraform/envs/dev-standing/outputs.tf` (what 9.4 and 9.5 need):
   - `console_url` (`https://<domain>`);
   - `console_distribution_id` (9.4's invalidation);
   - `console_site_bucket_name` (9.4's sync);
   - `console_user_pool_id` (the owner's `admin-create-user`);
   - `console_client_id`;
   - `console_auth_domain` (`https://<prefix>.auth.us-east-1.amazoncognito.com`);
   - `console_api_path` (`/api/command`);
   - `console_callback_url`.
4. `.gitignore`: `terraform/modules/console_edge/build/`.
5. `.github/workflows/terraform-plan.yml` and `terraform-apply.yml`: add `console/cerberus_console/**` and `observability/scale/runs/**` to `paths`, with a comment. Without them, a new run record or a package fix merges but never reaches the Lambda (F8). Effect: each run-record PR now triggers one plan and one apply that update the Lambda code.
6. `docs/plans/2026-10-27-demo-console.md` §7 step 7: a progress note after the live check. `Phases.md` 9.2: "Standing edge applied YYYY-MM-DD (#PR)". `console/README.md`: one "Deployed as" line (Lambda name, route).
7. Only if A1 happens: `iam/cerberus-admin/policies/cerberus-admin-console-edge.json` gets a `HttpApiLogDelivery` Sid (`logs:CreateLogDelivery, GetLogDelivery, UpdateLogDelivery, DeleteLogDelivery, ListLogDeliveries` on `*`; about 170 counted characters on 4,216 of 6,144), plus a `iam/cerberus-admin/README.md` "Changes since 7.3" entry. The same Sid goes in `cerberus-ci-apply-console` (4,143 of 6,144), which then also needs the local apply (it already happens).

Executor verify ($0, no AWS change):
- `TMPDIR=$HOME/.cache/tfspiketmp terraform fmt -check -recursive terraform/`
- `terraform validate` with `init -backend=false` in a scratch copy of `envs/dev-standing`.
- `git diff main -- terraform .github | grep -E '[0-9]{12}'` returns nothing.
- `unzip -l terraform/modules/console_edge/build/*.zip` after a local plan: 11 `cerberus_console/*.py` files and 14 (or 15 after 8.10) `runs/*.json` files, and no `tests/` or `__pycache__/`.

Local plan expectation (the gate before A2). **Stop if anything else appears, and do not use `-target`:**
- About 22 to add, all under `module.console_edge`: 6 S3 (bucket, public access block, ownership, SSE, policy, `healthz.txt`), 3 CloudFront (OAC, headers policy, distribution), 3 Cognito (pool, client, domain), 6 API (API, authorizer, integration, route, stage, access-log group), 4 Lambda (function, log group, permission, `cerberus-console-cli-logs`). The executor states the exact count in the PR.
- 0 to change and 0 to destroy, apart from the known Faker-layer churn (layer replaced, `cerberus-ingest-payments` updated in place).

## 8. Exact AWS commands for the user to approve

All with `export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1`, after #127 and #128 are merged, 7b is rebased on `main`, and no exercise is running.

**A2. Local first apply** (creates the edge; about 5-10 minutes for the CloudFront deployment):
```
cd terraform/envs/dev-standing
TMPDIR=$HOME/.cache/tfspiketmp terraform plan -out="$HOME/.cache/tfspiketmp/edge.tfplan"
TMPDIR=$HOME/.cache/tfspiketmp terraform show -no-color "$HOME/.cache/tfspiketmp/edge.tfplan" | grep -E '^  # |^Plan:'
TMPDIR=$HOME/.cache/tfspiketmp terraform apply "$HOME/.cache/tfspiketmp/edge.tfplan"
```

**A1. Only if A2 fails on the stage with an access-log permission error.** Root console: IAM → Policies → `cerberus-admin-console-edge` → Edit → paste the rendered file with the `HttpApiLogDelivery` Sid (render with `sed "s/<ACCOUNT_ID>/$ACCT/g"` as in the IAM plan) → Save as default version. Then run A2 again from a fresh `plan -out`.

**A3. The owner's check account and the token check** (a Cognito write; tokens stay in shell variables; never paste them into chat or files):
```
O() { TMPDIR=$HOME/.cache/tfspiketmp terraform -chdir=terraform/envs/dev-standing output -raw "$1"; }
POOL=$(O console_user_pool_id); CLIENT=$(O console_client_id); AUTH=$(O console_auth_domain); SITE=$(O console_url); CB=$(O console_callback_url)
read -rs TMPPW && aws cognito-idp admin-create-user --user-pool-id "$POOL" --username console-check \
  --temporary-password "$TMPPW" --message-action SUPPRESS >/dev/null; unset TMPPW
VER=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
CH=$(printf %s "$VER" | openssl dgst -binary -sha256 | basenc --base64url | tr -d '=')
echo "$AUTH/oauth2/authorize?response_type=code&client_id=$CLIENT&redirect_uri=$CB&scope=openid&code_challenge_method=S256&code_challenge=$CH"
# Open the URL, sign in as console-check, set the new password. The browser lands on
# $CB?code=... (an S3 403 page is expected before 9.5). Copy only the code value.
read -rs CODE
AT=$(curl -s -X POST "$AUTH/oauth2/token" -d grant_type=authorization_code -d client_id="$CLIENT" \
  -d code="$CODE" -d redirect_uri="$CB" -d code_verifier="$VER" | jq -r .access_token)
curl -s -X POST "$SITE/api/command" -H "Authorization: Bearer $AT" -H 'content-type: application/json' \
  -d '{"argv":["runs"]}' | jq '{ok, total: .data.total, rows: (.data.runs | length)}'
curl -s -X POST "$SITE/api/command" -H "Authorization: Bearer $AT" -H 'content-type: application/json' \
  -d '{"argv":["status"]}' | jq '{ok, gold: .data.gold.bytes_scanned}'
unset AT CODE VER
```
Keep `console-check` as the owner's account for 9.5. Disable it with `admin-disable-user` when it is not needed.

**A4. Merge 7b.** The CI apply on `main` must show no `console_edge` changes (only the Faker churn).

Optional (option C, does not block): root console → Service Quotas → AWS Lambda → "Concurrent executions" → Request increase to 1,000. Free.

## 9. Verify (agent, read-only unless marked)

After A2:
```
SITE=...; curl -s -o /dev/null -w '%{http_code}\n' -X POST "$SITE/api/command" -d '{"argv":["runs"]}'   # 401
curl -s -o /dev/null -w '%{http_code}\n' "$SITE/api/command"                                            # 404 (no GET route) or 401
curl -sI "$SITE/healthz.txt" | grep -iE '^(HTTP|content-security-policy|strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy)'   # 200 + all six
curl -s -o /dev/null -w '%{http_code}\n' "https://cerberus-platform-console-${ACCT}.s3.amazonaws.com/healthz.txt"   # 403 (OAC only)
aws cognito-idp describe-user-pool --user-pool-id "$POOL" --query 'UserPool.[UserPoolTier,AdminCreateUserConfig.AllowAdminCreateUserOnly,DeletionProtection,MfaConfiguration]' --output text   # ESSENTIALS True ACTIVE OFF
aws cognito-idp describe-user-pool-client --user-pool-id "$POOL" --client-id "$CLIENT" --query 'UserPoolClient.[AccessTokenValidity,AllowedOAuthFlows,AllowedOAuthScopes,ExplicitAuthFlows]'
aws apigatewayv2 get-stage --api-id "$API" --stage-name '$default' --query 'DefaultRouteSettings.[ThrottlingRateLimit,ThrottlingBurstLimit]' --output text   # 1 3
aws apigatewayv2 get-routes --api-id "$API" --query 'Items[].[RouteKey,AuthorizationType,AuthorizationScopes]'   # POST /api/command JWT [openid]
aws lambda get-function-configuration --function-name cerberus-console-command --query '[Runtime,Architectures[0],MemorySize,Timeout,Environment.Variables.CERBERUS_RUNS_DIR]' --output text   # python3.12 arm64 256 25 /var/task/runs
aws lambda get-function-concurrency --function-name cerberus-console-command   # {} (unreserved)
aws iam simulate-principal-policy --policy-source-arn "arn:aws:iam::${ACCT}:role/cerberus-console-cli" \
  --action-names logs:PutLogEvents logs:CreateLogGroup --resource-arns "arn:aws:logs:us-east-1:${ACCT}:log-group:/aws/lambda/cerberus-console-command:log-stream:x" \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text   # PutLogEvents allowed, CreateLogGroup denied
```
After A3:
- `runs` returns `ok: true`, `total` 14 (or 15), and `rows` equal to `total`.
- `status` returns `ok: true`. Record `bytes_scanned`.
- An ID token in place of `$AT` gets 401 or 403, not 200 (scope check). Run it with the ID token from the same exchange; do not print it.
- Access log, with no values printed:
  ```
  aws logs filter-log-events --log-group-name /aws/apigateway/cerberus-console-api --limit 20 \
    | jq -r '.events[].message | fromjson | [.status, (.sub | length > 0)] | @tsv'
  ```
  Expect 401 lines with `false` and 200 lines with `true`.
- Optional throttle order check: 10 unauthenticated POSTs in a burst. If some return 429, the throttle runs before the authorizer (this closes the cost question in section 10).
- CI: the PR plan (`cerberus-ci-plan`) after A2 shows only the Faker churn. After A4, the CI apply shows no `console_edge` diff, and the Lambda zip hash is stable between laptop and runner, as for `lineage`.

## 10. Cost

Idle: **$0** (estimate, not a bill reading):
- S3: one 2-byte object;
- CloudFront, the HTTP API, Cognito (under 10,000 MAU, F19) and Lambda have no fixed fee;
- the log groups are empty;
- the IAM policy is free.

Per use (list prices; CloudFront and Lambda are not rechecked today, so recheck against Cost Explorer after the first month):
- A record command (`runs`, `run`, `cost`, `dq`, `slo`, `help`): API $0.000001, plus Lambda (invocation $0.0000002, plus about 0.2 s × 0.25 GB at arm64 $0.0000133/GB-s), plus CloudFront about $0.000001. That is about **$0.000003**, inside the Lambda and CloudFront free tiers at demo volumes.
- `status`, uncached: plus Athena at most 10 MB billed, about $0.00005 (#127/#128 plan F25). With reuse, at most one billed query per 5 minutes across all containers (unverified for a zero charge, F24).
- A 30-minute demo of about 50 commands: about **$0.0002**.

Worst month (a signed-in visitor scripting at the throttle, 1 rps all month, 2.59M requests):
- API $2.59, Lambda requests about $0.32 after the free 1M, duration within the 400k GB-s free tier, CloudFront within the free 10M requests;
- Athena at most $0.43 with reuse, or at most $4.75 without (the #128 review figure);
- **about $3.4 to $7.7.**

Whether 401 responses are billed, and whether throttling applies before the authorizer, are unverified. The same 1 rps ceiling caps both cases if the throttle applies first. The Budgets alerts (75% and 100% actual, 100% forecast) are the backstop.

## 11. Risks

1. **`Authorization` through CloudFront** (F23 conflict). Symptom: 401 through `$SITE`, but 200 when the same token goes to `https://<api>.execute-api.us-east-1.amazonaws.com/api/command`. Fallback: a custom cache policy with `Authorization` in the cache key and TTLs 0/0/1 (CI has `cloudfront:*` on `cache-policy/*` and `CreateCachePolicy`). One CI cycle.
2. **`logs:CreateLogDelivery`** (F13, F14, F22). Handled by A1. CI needs the Sid only if A2 needed it.
3. **The hosted UI with `ALLOW_REFRESH_TOKEN_AUTH` only** (unverified). If sign-in fails, add `ALLOW_USER_SRP_AUTH` (SRP sends no plaintext password). One line, CI-applied.
4. **The Cognito prefix is taken at apply time** (checked free on 2026-11-02). Change `cognito_domain_prefix`; the CSP follows it.
5. **Shared Lambda concurrency** (the amendment's "given up"). The console and the pipeline Lambdas share 10. Do not run demos during an exercise. Option C's quota request removes it.
6. **The execute-api endpoint is reachable directly.** It has the same JWT and throttle. It cannot be disabled while CloudFront uses it (there is no custom domain).
7. **Default certificate:** the minimum viewer TLS cannot be raised, and there is no CloudFront access log. Both go to 9.7's Well-Architected pass.
8. **Records drive Lambda updates:** each run-record merge now updates the Lambda through CI, and each apply also carries the Faker churn. Intended; the take is not affected after it is recorded.
9. **`deletion_protection = ACTIVE`** blocks `make standing-destroy` until it is flipped. Documented in the module comment.

## 12. Open questions for the user

Answered 2026-11-02; see User decisions at the top. Optional, no answer needed: file the free Lambda quota request at root (option C).

Sources: [Lambda reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html), [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html), [Cognito feature plans](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-sign-in-feature-plans.html), [Cognito pricing](https://aws.amazon.com/cognito/pricing/), [Managed login branding](https://docs.aws.amazon.com/cognito/latest/developerguide/managed-login-branding.html), [DeleteManagedLoginBranding](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_DeleteManagedLoginBranding.html), [HTTP API JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html), [HTTP API logging](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging.html), [HTTP API logging variables](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging-variables.html), [CloudFront custom headers and Authorization](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/add-origin-custom-headers.html), [Knowledge Center: CloudFront Authorization header](https://repost.aws/knowledge-center/cloudfront-authorization-header), [Athena result reuse](https://docs.aws.amazon.com/athena/latest/ug/reusing-query-results.html).
