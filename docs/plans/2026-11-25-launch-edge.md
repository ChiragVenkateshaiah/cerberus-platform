# Plan: 17.3b launch edge Terraform

Date: 2026-11-25. Planner: Sonnet.

**Plan 17.3b: dev-launch root and launch_edge module (plan only, no apply)**

NEEDS DECISION: none. ADR 0030 Decisions 2–6, 10 and 12–14 cover every choice below. Build now; apply happens only in 17.4/17.6, after the root IAM paste and after Run A.

**1. Goal.** Write the Terraform for the per-session delivery edge: `terraform/modules/launch_edge` and `terraform/envs/dev-launch`. This is Phase 17.3b. It adds `make launch-plan`, offline tests and CI validation, and nothing is applied.

**2. Facts**
- (V) The console analogue is `modules/console_edge/main.tf`. It uses OAC, a bucket policy, managed cache policies read by data source, and an account-ID bucket suffix.
- (V) The root analogue is `envs/dev-console`. It has a partial `backend "s3" {}`, `terraform_remote_state` on dev-standing, and `default_tags` Project plus Stack. It also has an instance with IMDSv2, `instance_initiated_shutdown_behavior = "terminate"` and `shutdown -h` in user_data. Its init helper is `orchestration/console_init.sh`.
- (V) dev-standing outputs `vpc_id` and `public_subnet_a_id`. The AL2023 AMI alias SSM grant exists in `cerberus-admin-console-host.json`.
- (V) The AWS provider is locked at 5.100.0 in every root, so dev-launch needs a committed `.terraform.lock.hcl` at the same version.
- (V) `terraform-plan.yml` and `terraform-apply.yml` run only in `terraform/envs/dev-standing`. A `terraform/modules/**` change triggers plan, but dev-standing does not instantiate `launch_edge`, so nothing launch-related is planned or applied. `terraform fmt -recursive ../../` does cover the new files. Nothing in CI runs `validate` on dev-launch.
- (U) Provider 5.100 resources for KVS, Function KVS associations and logging v2:
  - `aws_cloudfront_key_value_store`
  - `aws_cloudfrontkeyvaluestore_key`
  - `aws_cloudfront_function` with `key_value_store_associations`
  - `aws_cloudwatch_log_delivery_source`
  - `aws_cloudwatch_log_delivery_destination`
  - `aws_cloudwatch_log_delivery` with `record_fields` and `s3_delivery_configuration`
  Confirm with `terraform providers schema -json | jq` after init, before coding. If a resource is missing, stop and report. Do not bump the provider silently.
- (U) Whether CloudFront signature checks run before the viewer-request Function (Run A proves it). Whether the log path still holds the account ID when a destination prefix is set (the collect check refuses it). Spot `DescribeSpotInstanceRequests` is covered by `ec2:Describe*` in the console-host policy (V), and `CancelSpotInstanceRequests` is in the launch policy (V).

**IAM gaps against `cerberus-admin-launch.json` plus the existing policies**
- Distribution create and update need `aws:RequestTag/Project`. `default_tags` supplies it (V, same as dev-console).
- OAC and cache-policy writes come from `CloudFrontEdgePolicies` and `ConsoleAccount` in the console-edge file. #187 says that file fails to save, so what is attached now is (U). Check it with `aws iam simulate-principal-policy` for `CreateCachePolicy` and `CreateOriginAccessControl`. If they are denied, flag it. Do not edit the console-edge file.
- `CreateRole` and `PutRolePolicy` for `cerberus-launch-*` are covered by the `cerberus-*` IamRoleMgmt (V). `AttachRolePolicy` for AmazonSSMManagedInstanceCore is covered too.
- No other gap found. Every name below must match the launch policy patterns.

**3. Steps (one PR)**

1. **Module skeleton.** In `terraform/modules/launch_edge/` create `main.tf`, `variables.tf`, `outputs.tf`, `function/license.js`, `function/license.test.mjs`. The `account_id` input is for names only.

2. **Buckets.** Both get `force_destroy = true`, a public-access block, SSE-S3, and Project and Stack tags.
   - Build bucket `cerberus-platform-launch-build-<acct>` with a policy:
     - `cloudfront.amazonaws.com` may `s3:GetObject` on `build/*` and `patch/*` only, with `AWS:SourceArn` equal to the distribution.
     - `scenarios/*` is not readable by CloudFront.
   - Log bucket `cerberus-platform-launch-logs-<acct>` with a policy allowing `delivery.logs.amazonaws.com` to `PutObject` under `cdn/*`, with `aws:SourceAccount` and a delivery-source `SourceArn` condition.

3. **Edge**
   - OAC `cerberus-launch-oac`.
   - Custom cache policy `cerberus-launch-chunks`: TTL 1 year, no query string, cookie or header, no compression.
   - `/license*` uses the managed CachingDisabled policy, read by data source as console_edge does.
   - Distribution `PriceClass_200`, no Origin Shield, HTTP/2 and 3, default certificate, one S3 origin.
   - Behaviours `/build/*`, `/patch/*` and `/license*` all use `trusted_key_groups = [key group]`, GET and HEAD, and `redirect-to-https`.
   - `/license*` carries the Function association (viewer-request) and the no-cache policy. It needs the S3 origin only to be valid, because the Function answers every request.
   - The default behaviour is also signed, with caching disabled. Recommended: everything is signed, so there is no unsigned path.

4. **Key.** `aws_cloudfront_public_key` uses `name_prefix = "cerberus-launch-"` with `create_before_destroy`. A fixed name would collide on replace.
   - The key group is `cerberus-launch-keys`.
   - `var.public_key_pem` defaults to a committed PEM whose private half the executor discards at generation. Generate it in a scratch dir, commit only the `BEGIN PUBLIC KEY` block, then delete the private file.
   - A test greps the repo for `PRIVATE KEY` and fails if found.

5. **KVS and Function**
   - KVS `cerberus-launch-release`, with one key `release_at` written by Terraform as epoch seconds. This replaces the import-from-S3 route.
   - `var.release_at_epoch` defaults to the sentinel `4102444800`, with a validation that it is above 0. It never uses `timestamp()`.
   - Function `cerberus-launch-license`, runtime `cloudfront-js-2.0`, `publish = true`.
   - `license.js` logic: `kvs.get('release_at')` inside try/catch. A missing key, a non-numeric value or an error all return 403 (fail closed). `now < release_at` returns 403 JSON. Otherwise it returns 200 JSON with `cache-control: no-store`.

6. **Logging v2** (all in us-east-1, names `cerberus-launch-*`)
   - Source on the distribution, type `ACCESS_LOGS`.
   - Destination S3 at `<log bucket>/cdn`, output format JSON.
   - Delivery with an explicit `record_fields` allowlist:
     - Include: `timestamp(ms)`, `x-edge-request-id`, `x-edge-location`, `x-edge-result-type`, `x-edge-response-result-type`, `sc-status`, `sc-bytes`, `cs-method`, `cs-uri-stem`, `time-taken`, `time-to-first-byte`, `cs-protocol`.
     - Exclude `c-ip`, `x-forwarded-for`, `c-port`, `cs(Cookie)`, `cs(Referer)`, `cs(User-Agent)`.
   - A test fails if the list contains any excluded name.
   - Field names are checked against the AWS standard-logs reference. Correction: the v2 field is `timestamp(ms)`, not `timestamp`.
   - The path is `.../cdn/<DistributionId>/<yyyy>/<MM>/<dd>/<HH>`, with no account ID. Correction: the delivery sets `s3_delivery_configuration { suffix_path = "{DistributionId}/{yyyy}/{MM}/{dd}/{HH}" }`, no hive paths.

7. **Load generator** (module `load_gen.tf`, or in the env)
   - `var.create_load_gen` defaults to `false` (PREWARM: no instance, count 0). Variables: `minutes` (1–120), `shutdown_margin_minutes` (default 45, 17.4 may change it), `instance_type` (a Graviton network-optimised default, (U), 17.4 fixes the size).
   - Role `cerberus-launch-loadgen`, instance profile of the same name, SG `cerberus-launch-loadgen`.
   - SG: no ingress; egress tcp 443 only. VPC DNS is not filtered by an SG (the repo's own comment says so). If k6 needs another resolver, add tcp/udp 53 egress and say so.
   - Role policy:
     - `ssm:GetParameter` on exactly `parameter/cerberus/launch/<one name>`. The parameter is created outside Terraform.
     - S3 `PutObject` on `build/*` and `patch/*` of the build bucket.
     - S3 `GetObject` and `ListBucket` on `scenarios/*`.
     - AmazonSSMManagedInstanceCore.
   - Spot instance: `instance_market_options { market_type = "spot" }`, IMDSv2 required with hop limit 1, `instance_initiated_shutdown_behavior = "terminate"`, `associate_public_ip_address = true`, subnet from `standing.public_subnet_a_id`.
   - `user_data.sh.tftpl` stays minimal: `shutdown -h +<minutes+margin>`, env file, and an empty hook directory. The k6 pin is left to 17.4 (variables `k6_version` and `k6_sha256` default empty and unused).

8. **Env `terraform/envs/dev-launch`**
   - `versions.tf`: aws `~> 5.0`, partial `backend "s3" {}`.
   - `provider.tf`: us-east-1, tags Project and Stack=`dev-launch`.
   - `main.tf`: remote state of dev-standing, `module "launch_edge"`, no secret anywhere.
   - `outputs.tf`: `domain_name`, `distribution_id`, `key_group_id`, `build_bucket`, `log_bucket`, `instance_id`, `kvs_arn`.
   - `variables.tf`, `README.md`, and the committed lock file.
   - `orchestration/launch_init.sh` is cloned from `console_init.sh`, with key `envs/dev-launch/terraform.tfstate`.

9. **Make**
   - 17.3b adds `launch-plan` (read-only: init, then `plan -var create_load_gen=false`) and `launch-function-test`.
   - `launch-session`, `launch-destroy`, `launch-check` and `launch-collect` belong to 17.4. The destroy needs stage 1 and the parameter delete, which this PR has no tooling for.

10. **CI**
    - Add a no-AWS job to `code-ci.yml`: `terraform init -backend=false`, `validate` for dev-launch, and the node test.
    - Add paths `terraform/envs/dev-launch/**`, `terraform/modules/launch_edge/**`, `orchestration/launch_init.sh`.
    - Add to `orchestration/verify.sh`: a dev-launch `terraform validate` (skipped when terraform or the registry is unavailable) and the node test (skipped without node).
    - Do not touch `terraform-apply.yml` or `terraform-plan.yml`. Acceptance: `git diff main -- .github/workflows/terraform-*.yml` is empty.

11. **Node test** (`node --test`, no network). It loads `license.js`, strips the `import cf from 'cloudfront'` line, and runs it in `vm` with a stub KVS. Cases:
    - before release: 403
    - at exactly `release_at`: 200
    - after release: 200 JSON
    - key missing: 403
    - empty value or non-numeric: 403
    - `kvs.get` throws: 403

**4. Verify.** Run these:
- `make verify`
- `terraform fmt -check -recursive terraform`
- `terraform -chdir=terraform/envs/dev-launch init -backend=false && terraform -chdir=terraform/envs/dev-launch validate`
- `make launch-function-test`
- `make launch-plan` (owner-run, read-only) once `cerberus-admin` is available. Expect about 25 adds with `create_load_gen=false`, and none for the instance, role or SG when gated off.
- `grep -rn "PRIVATE KEY" terraform` returns nothing.
- Account-number scan via `verify.sh`.
- The CloudFront resource count and the tag test (Stack=`dev-launch` on everything taggable).

**5. Owner steps.** None write to AWS in this PR. Read-only: `make launch-plan`. The root paste of `cerberus-admin-launch.json` is 17.3a, due Thursday, and is a precondition for 17.4/17.6. Check that the console-edge policy has OAC and cache-policy create rights before the first apply.

**6. Risks**
- Provider resource gaps, see the (U) list in section 2.
- A CloudFront Function association on a behaviour with no real origin. It is valid, but check it in `validate` and plan.
- `create_before_destroy` on the public key combined with the key group update.
- Key-group and Function delete order, and delete time, are (U), about 30 minutes.
- The log-path account ID is (U).
- Spot capacity for the chosen type.
- `aws_instance` `instance_market_options` may need the Spot service-linked role. `CreateServiceLinkedRole` exists (V).
- The SSM SecureString under the default key needs no extra KMS grant (U).
- `shutdown -h` is the only backstop if the trap dies.
- Free-tier overrun is cents (ADR).

**7. Open questions.** None.

## Main-session corrections (they win)

- "After Run A" in the NEEDS DECISION line is wrong: Run A is itself an apply.
  The apply needs the root paste. ADR 0030 becomes Accepted after Run A passes
  (owner answer, 2026-11-25). The $40 ceiling is the November account total.
- The live OAC, cache-policy and distribution permissions were simulated
  read-only on 2026-11-25 (17.3a) and are allowed.
- Egress adds udp and tcp 53 only if ADR Decision 6's per-client DNS needs it.
- The AWS default certificate's TLS minimum cannot be raised; say so in the
  README rather than adding a domain.
- Opus security review (2026-11-25), these win over the plan:
  1. The load-gen role does not attach AmazonSSMManagedInstanceCore (it reads
     any SSM parameter). It has an inline policy: `ssmmessages` channel
     actions, `ssm:UpdateInstanceInformation`, and `ssm:GetParameter` on the
     one parameter ARN.
  2. The instance and its volumes carry `Project=cerberus-platform` at
     RunInstances, or terminate and StartSession are denied.
  3. One-time Spot, `spot_instance_type = one-time`, interruption behaviour
     `terminate`. `ec2:StopInstances` is denied.
  4. `iam:ListInstanceProfiles` and `ec2:AssociateIamInstanceProfile` are
     denied: the instance profile has a fixed name, set at launch.
  5. The log-bucket policy is in Terraform for the chosen prefix, with
     `aws:SourceAccount` and `aws:SourceArn`, so AWS does not append its own
     statement.
- Executor notes (2026-11-25): `public_key_pem` defaults to null and the
  module falls back to the committed `default_public_key.pem` with `file()`
  (a variable default cannot call `file()`). `DescribeConfigurationTemplates`
  was denied for `cerberus-admin`; the field names were then checked against the AWS reference (`timestamp(ms)` corrected, `suffix_path` added).
