# Plan: 9.2 VPC-origin spike (ADR 0024, build step 3)

Date: 2026-10-27. Planner: Opus. No new ADR up front: this is a measurement inside ADR 0024. A new ADR follows only if the gate fails (section 5).

## User decisions (2026-10-27)

1. Gate: the ADR 0024 text. Wake (apply plus the first HTTP 200) must be at most 20 minutes, and teardown must leave nothing billable, in both cycles. Destroy time is recorded as information.
2. Runner: the main Claude session runs the AWS-changing commands with the user's explicit OK, and stops on any 403 or unexpected plan.
3. The plan is confirmed. Branch `9.2-vpc-origin-spike`.

## 1. Question

How long do a CloudFront VPC origin (pointing at a t4g instance in a private subnet) and the distribution that uses it take to create and to destroy in this account? Does the whole path work: CloudFront, then the VPC origin, then an instance SG that allows inbound only from `CloudFront-VPCOrigins-Service-SG`, then an HTTP responder?

Why now: ADR 0024 marks the session wake time "unverified until the 9.2 spike measures it". Its "Revisit if" trigger (more than 20 minutes up, or a teardown that leaves resources) decides between the per-session Grafana and option A. Build steps 4–10 assume the per-session design. The spike is also the live test of 9.2 IAM risk 1 (hidden authorization checks).

## 2. Facts

Repo:
- F1. ADR 0024 Decision: the session instance SG allows inbound only from `CloudFront-VPCOrigins-Service-SG` on the app port. No key pair, no public IP, no SSH. The instance self-terminates (`instance_initiated_shutdown_behavior = terminate` plus a timer). "Revisit if": "more than 20 minutes up, or its teardown leaves resources". The gate is on up time, not create+destroy.
- F2. Demo-console plan §7 step 3 says: "t4g.nano running nginx 'hello' in the console subnet, plus NAT, VPC origin and distribution", and to measure apply, destroy, the WebSocket upgrade, HTTP, and leftover ENIs/SGs. This plan deviates (section 5).
- F3. The VPC module is in `dev-standing`. The private route table has no NAT route by design. NAT exists only in `dev-compute` (`terraform/modules/vpc_nat`).
- F4. Repo roots use an S3 backend whose bucket name contains the account ID. New files carry no account ID (9.2 IAM user decision 1). `default_tags { Project = "cerberus-platform" }` is the repo pattern. The AWS provider is locked at 5.100.0 in both envs. Terraform CLI is v1.16.5 locally.
- F5. CI: `terraform-plan.yml` / `terraform-apply.yml` trigger only on `terraform/modules/**` and `terraform/envs/dev-standing/**`, so CI never plans or applies a `terraform/spikes/` root. But `terraform fmt -check -recursive` covers the whole `terraform/` tree, and `code-ci.yml` runs `ruff check .` and `ruff format --check .` repo-wide.
- F6. `.gitignore` ignores `*.tfstate`, `*.tfstate.*`, `**/.terraform/*` and `*.log`. It does not ignore `*.tfplan` or `.txt` logs.
- F7. Relevant `cerberus-admin` grants: `CloudFrontCreateTagged` (RequestTag), `CloudFrontChangeTagged` (ResourceTag), `CloudFrontReadTagInvalidate`, `ConsoleAccount` (List*), `Ec2Read` (`ec2:Describe*`), `Ec2InstanceTagged`, `Ec2SecurityGroupIngress`, `AmiAlias`, `InstanceProfile` and `PassConsoleRoleToEc2` (`cerberus-console-grafana*`), `Ec2Network` (Create/DeleteSecurityGroup, RevokeSecurityGroupEgress, Create/DeleteTags on `*`), `Ec2RunInstancesForNodeGroups` (RunInstances on `*`), `IamRoleMgmt` (role/cerberus-*), `IamServiceLinked`.
- F8. Not granted: `ec2:GetConsoleOutput` (verified UnauthorizedOperation), `ec2:StopInstances`/`StartInstances`, and `iam:GetRole` on the CloudFront service-linked role.

AWS (read-only, 2026-10-27):
- F9. NAT gateways 0, EKS clusters 0, instances 0, CloudFront distributions 0, VPC origins 0.
- F10. `cerberus-platform-private-a` is us-east-1a / use1-az1 / 10.0.16.0/20; `private-b` is us-east-1b / use1-az2. The private route table has only `local` and the S3 gateway prefix list: no egress from the private subnets today.
- F11. Default NACL only, allow-all both directions (VPC origin return path needs ephemeral ports outbound; this holds).
- F12. The VPC has 0 ENIs. Its SGs are `default` and `cerberus-orchestration-runner`. No `CloudFront-VPCOrigins-Service-SG` yet.
- F13. The service-linked role does not exist yet; the first CreateVpcOrigin creates it.
- F14. The AL2023 arm64 AMI root is 8 GiB gp3, DeleteOnTermination true, IMDSv2. This verifies ADR 0024's "8 GiB (unverified)"; option A's idle disk is 8 × $0.08 = $0.64/month at list price.
- F15. t4g.nano and t4g.small are offered in use1-az1 and use1-az2.

AWS docs (read 2026-10-27):
- F16. VPC origin creation "can take up to 15 minutes". Delete time is not documented (unverified).
- F17. CloudFront creates `CloudFront-VPCOrigins-Service-SG` with the VPC origin; an inbound rule referencing it can be added only after the VPC origin exists. The group is AWS-managed and should not be edited. Whether it is deleted with the last VPC origin is not documented (measure it).
- F18. For an EC2 origin, the distribution's origin domain is the instance's private IP DNS name; the instance must be running first. The VPC needs an IGW (present) but it is not used for routing. use1-az3 is not supported.
- F19. No additional cost for VPC origins; the service ENI's private IPv4 has no charge.

## 3. Constraints

- Budget about $0.10. Nothing left billing. The 2-hour self-terminate timer is the backstop for the only hourly-billed resource.
- `dev-compute` and `dev-standing` states are not touched; the spike adds resources into the standing VPC but not into either state.
- CI applies nothing here. The spike root is human-run (or main-session-run with the user's OK), with local state.
- Public repo: no account ID, IDs, domain names or ARNs in committed files. Logs and plans stay gitignored.
- Must not contradict ADR 0024; the deviations from its plan's step 3 wording are named in section 5 and change no decision.

## 4. Options

A. Throwaway root `terraform/spikes/vpc-origin/`, local state, no NAT, stdlib Python responder, existing `private-a` subnet, two cycles (chosen). Under $0.02; about 8 small files; 1.5–2 h wall clock. No NAT timing (NAT builds in parallel, off the critical path); the console subnet is tested in step 4.

B. Same plus NAT and nginx from dnf: about $0.10, adds a billable leftover risk for no gate-relevant number.

C. AWS CLI script: unreliable destroy ordering; not the step 10 shape.

D. A minimal `envs/dev-console` with an S3 backend now: needs the account-ID bucket name, and a half-built root sits in `envs/` before step 10 defines it.

## 5. Recommendation

Option A.
- The gate measures the critical path of a session: instance running, VPC origin Deployed, distribution Deployed, first 200. NAT and Grafana boot run in parallel.
- No egress is needed: AL2023 ships `python3`.
- Two cycles: cycle 1 includes first-time account setup (the service-linked role and service SG); cycle 2 is what each later session sees.
- Terraform gives per-resource timing lines and an ordered destroy.
- A no-policy role and instance profile `cerberus-console-grafana-spike` retire the PassRole/instance-profile part of IAM risk 1 now.

Named deviations from demo-console plan step 3 (ADR 0024 text unchanged): 1) no NAT; 2) a Python stdlib responder, not nginx; 3) the existing `private-a` subnet, not the console subnet; 4) `terraform/spikes/vpc-origin/` with local state, not `envs/dev-console`; 5) t4g.nano, as in the plan.

Gate (ADR 0024 "Revisit if", as written; user decision 1):
- PASS if, in both cycles: wake (apply `real` + seconds to the first HTTP 200) is at most 20 min; after destroy no instance, distribution, VPC origin, spike SG, spike role or profile remain; service ENIs are gone within 30 min.
- The service SG and the service-linked role staying behind is expected and $0: recorded, not a failure. Destroy time is recorded either way.
- If it FAILS: do not edit ADR 0024. Write a new ADR 0025 (Proposed) that re-opens option A (stopped instance, $0.64/month verified). It needs the user's consent, `ec2:StopInstances`/`StartInstances` for `cerberus-admin`, and a renumbering of ADR 0024's planned "ADR 0025" WA pass.

## 6. ADR outline

None if the gate passes. If it fails: `docs/adr/0025-console-grafana-host-stopped-instance.md`, Proposed, amending 0024, with the measured numbers as Context, with its own plan.

## 7. Build steps (one PR, branch `9.2-vpc-origin-spike`, Phases.md 9.2)

### Step 1. Files (executor)

`terraform/spikes/vpc-origin/`:
- `versions.tf`: `required_version >= 1.5`; `hashicorp/aws ~> 5.0`. No backend block, with a comment: local state on purpose; spike; human-run; never in CI; no account-specific bucket name in a new file. Commit `.terraform.lock.hcl` (expect 5.100.0).
- `provider.tf`: region `us-east-1`, `default_tags { tags = { Project = "cerberus-platform" } }` (required by the IAM tag conditions). No `profile`.
- `main.tf` (names `cerberus-vpc-origin-spike` unless stated; header comment cites ADR 0024 step 3 and this plan):
  - `data "aws_vpc"` by tag `Name = cerberus-platform-vpc`; `data "aws_subnet"` by tag `Name = cerberus-platform-private-a`, with a `lifecycle { postcondition { condition = self.availability_zone_id != "use1-az3" ... } }`.
  - `data "aws_ssm_parameter"`: `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`.
  - `aws_iam_role "cerberus-console-grafana-spike"`: trust `ec2.amazonaws.com`, no policies; `aws_iam_instance_profile` with the same name.
  - `aws_security_group`: in the VPC, with a description and no inline ingress or egress blocks (the provider revokes the default allow-all egress; step 3 verifies zero egress rules).
  - `aws_instance`: `t4g.nano`, AMI from SSM, `private-a`, the spike SG and instance profile; `associate_public_ip_address = false`, no `key_name`; `metadata_options { http_endpoint = "enabled", http_tokens = "required", http_put_response_hop_limit = 1 }`; `instance_initiated_shutdown_behavior = "terminate"`; `user_data = templatefile("user_data.sh.tftpl", { responder_b64 = base64encode(file("responder.py")), self_terminate_minutes = 120 })`; `user_data_replace_on_change = true`. No `encrypted`/KMS key.
  - `aws_cloudfront_vpc_origin`: `vpc_origin_endpoint_config { name, arn = aws_instance.arn, http_port = 80, https_port = 443, origin_protocol_policy = "http-only", origin_ssl_protocols { items = ["TLSv1.2"], quantity = 1 } }`, `timeouts { create = "30m", update = "30m", delete = "30m" }`.
  - `data "aws_security_group" "cloudfront_vpc_origins"`: filters `vpc-id` and `group-name = CloudFront-VPCOrigins-Service-SG*`, `depends_on = [aws_cloudfront_vpc_origin.this]`.
  - `aws_vpc_security_group_ingress_rule`: tcp 80, `referenced_security_group_id` = the data SG, description "CloudFront VPC origin only".
  - `aws_cloudfront_distribution`: `enabled = true`, `comment = "cerberus vpc-origin spike"`, `price_class = "PriceClass_100"`, `wait_for_deployment = true`, `cloudfront_default_certificate = true`, no geo restriction; origin `domain_name = aws_instance.private_dns` with `vpc_origin_config { vpc_origin_id = aws_cloudfront_vpc_origin.this.id }`; default behavior GET/HEAD/OPTIONS, `viewer_protocol_policy = "redirect-to-https"`; managed policy IDs hardcoded in `locals` with a docs link: CachingDisabled `4135ea2d-6df8-44a3-9df3-4b5a84be39ad`, AllViewer `216adef6-5c7f-47e4-b989-5492eafa07d3`; `depends_on = [aws_vpc_security_group_ingress_rule.from_cloudfront]`.
- `outputs.tf`: `domain_name`, `distribution_id`, `vpc_origin_id`, `instance_id`, `service_sg_id`.
- `user_data.sh.tftpl` (bash, `set -euo pipefail`): `shutdown -h +${self_terminate_minutes}`; decode the responder to `/opt/spike/responder.py`; `systemd-run --unit=spike-responder --property=Restart=always /usr/bin/python3 -I /opt/spike/responder.py 80`. No dnf, no network.
- `responder.py`: stdlib only, Python 3.9-compatible, passes the repo ruff config. `ThreadingHTTPServer` on `0.0.0.0:<argv port>`. `GET /` returns 200 `cerberus vpc-origin spike ok\n`. `GET /ws` with `Upgrade: websocket` returns 101 with `Sec-WebSocket-Accept = base64(sha1(key + 258EAFA5-E914-47DA-95CA-C5AB0DC85B11))`, sends one text frame `hello`, then closes. Anything else 404. Never echo request data.
- `check.sh` (read-only; `set -euo pipefail`; uses `AWS_PROFILE`/`AWS_REGION`), printing `key value` lines: the four `exercise.sh` counts (EKS, NAT pending/available, EIPs, running instances); distributions `length(DistributionList.Items || \`[]\`)`; VPC origins; spike instances not terminated (tag Name); the spike SG; the service SG (and its rule counts if present); ENIs in the VPC with a breakdown by `InterfaceType` and `Description`; the spike instance's `PublicIpAddress` and `MetadataOptions.HttpTokens`; the spike SG rules; whether role and profile `cerberus-console-grafana-spike` exist. Option `--watch-enis <interval> <max>` loops until the VPC ENI count is 0, printing elapsed seconds.
- `probe.sh <domain>` (read-only, curl only): polls `https://<domain>/` every 10 s up to 1,200 s, printing elapsed seconds to the first 200 and the code transitions; checks the body; `/nope` must be 404; WebSocket: `curl --http1.1 -sS -i -N --max-time 5 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' https://<domain>/ws` must contain `HTTP/1.1 101` and `Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`. PASS/FAIL per check.
- `README.md`: what the spike measures, that it is not a root, the commands from step 3, teardown and abort. Delete the whole directory in step 10's PR, after `envs/dev-console` exists.

Root `.gitignore`: add `*.tfplan` and `terraform/spikes/*/logs/`.

Verify (executor, $0, no AWS changes): `terraform fmt -check -recursive terraform/`; `terraform init && terraform validate` in the spike dir; `ruff check terraform/spikes && ruff format --check terraform/spikes`; `shellcheck` on both scripts if installed; `bash -n` on a hand-rendered user data; local responder test on 127.0.0.1:8080 with the 200 body, 404 and 101 Accept value; `grep -rnE '[0-9]{12}' terraform/spikes` returns nothing. Then an Opus review.

### Step 2. Pre-flight (read-only)

```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
cd terraform/spikes/vpc-origin && mkdir -p logs
./check.sh | tee logs/check-before-1.txt      # expect every count 0
terraform plan -out=spike.tfplan | tee logs/plan-1.txt
```

The plan must show exactly 7 to add: role, instance profile, SG, instance, VPC origin, ingress rule, distribution. Otherwise stop.

### Step 3. Cycle N = 1, then N = 2

Status poll (read-only, in parallel):
```
while :; do printf '%s vpco=%s dist=%s\n' "$(date -u +%T)" \
  "$(aws cloudfront list-vpc-origins --query 'VpcOriginList.Items[].Status' --output text)" \
  "$(aws cloudfront list-distributions --query 'DistributionList.Items[].Status' --output text)"; sleep 20; done | tee logs/poll-N.txt
```

Main:
```
# cycle 2 only: ./check.sh | tee logs/check-before-2.txt ; terraform plan -out=spike.tfplan | tee logs/plan-2.txt
( time terraform apply spike.tfplan ) 2>&1 | tee logs/apply-N.txt                  # [changes AWS]
./probe.sh "$(terraform output -raw domain_name)" | tee logs/probe-N.txt
./check.sh | tee logs/check-up-N.txt
terraform plan -destroy -out=destroy.tfplan | tee logs/plan-destroy-N.txt         # expect 7 to destroy
( time terraform apply destroy.tfplan ) 2>&1 | tee logs/destroy-N.txt              # [changes AWS]
./check.sh --watch-enis 30 1800 | tee logs/check-after-N.txt
grep -hE '(Creation|Destruction) complete after|^real' logs/apply-N.txt logs/destroy-N.txt
```

Check-up must show `PublicIpAddress` null, `HttpTokens` required, one ingress rule on the spike SG (tcp 80 from the service SG), zero egress rules, the service SG present. Check-after must show spike instance, SG, role, profile, distribution and VPC origin at 0, and VPC ENIs at 0 within 30 min; record whether the service SG still exists. Run cycle 2 only if cycle 1 completed with no 403 and a clean teardown. Time box: 60 min per cycle.

### Step 4. Final verify (read-only)

`./check.sh` all zeros except the service SG (record) and the service-linked role `AWSServiceRoleForCloudFrontVPCOrigin` (expected to remain; $0). `terraform state list` empty, then `rm terraform.tfstate*`. Cost Explorer the next day.

### Step 5. Record (executor), then Opus review, then PR

- An "Outcome" section in this plan: per cycle, instance / VPC origin / ingress rule / distribution create times; apply `real`; seconds to the first 200; wake; distribution destroy; VPC origin delete; destroy `real`; ENI clear time; HTTP PASS; WebSocket 101 PASS; service SG after; 403s met; the gate verdict. Minutes:seconds only; no IDs, domains or ARNs.
- `docs/plans/2026-10-27-demo-console.md`: §7 step 3 note on the five deviations with a link to this plan; §8 mark the first two bullets measured and "The AL2023 arm64 root size" verified (8 GiB gp3).
- Phases.md 9.2 progress line: "VPC-origin spike done 2026-MM-DD (#PR): wake X min, destroy Y min".
- `iam/cerberus-admin/README.md`: an entry only if a policy changed.
- ADR 0024: no edit if the gate passes.

## 8. Expected timings and cost

| Phase | Expectation | Source |
|---|---|---|
| Role, profile, SG, instance running | about 1 min | planner expectation |
| VPC origin to Deployed | up to 15 min | F16 |
| Distribution to Deployed | unknown; often minutes | unverified |
| First 200 after apply | under 1 min | expectation |
| Distribution destroy (disable, wait, delete) | unknown | — |
| VPC origin delete | unknown | — |

Cost (list prices, 2026-10-27): t4g.nano $0.0042/h at most 2 × ~55 min ≈ $0.008; 8 GiB gp3 ≈ $0.002; CloudFront requests in the free tier; VPC origin, ENI, SG, IAM $0; no NAT, EIP or public IPv4. Total under $0.02, also in the worst case (the instance self-terminates at 120 min; the distribution and VPC origin have no idle fee).

## 9. Risks

Hidden IAM 403s. Procedure:
1. Stop. Do not retry with root or another profile. Do not widen first.
2. Destroy what exists (`terraform plan -destroy -out=destroy.tfplan && terraform apply destroy.tfplan`), or use the abort path.
3. Record the denied action, the resource ARN and any condition. Redact the account ID before committing.
4. Look up the action's resource types and condition keys in the Service Authorization Reference.
5. Draft the narrowest change to `cerberus-admin-console-edge.json` (4,216 of 6,144) or `-host.json` (2,363 of 6,144), keeping every tag condition. Simulate one statement. Root paste. README history entry. Retry.
6. Never drop an `aws:RequestTag`/`aws:ResourceTag` condition, grant `cloudfront:*` or `ec2:*` on `*`, or attach an AWS managed admin policy.

| Where | Possible 403 | Handling |
|---|---|---|
| `CreateVpcOrigin` | The provider sends no `Tags` in the create call, so the RequestTag condition fails | Do not loosen. Stop and ask the user. Options: another provider version, or a create-then-tag grant pair. |
| `CreateVpcOrigin` | An undocumented EC2/ELB read or `iam:CreateServiceLinkedRole` | Describe* and CreateServiceLinkedRole are granted. Any other action: steps 3–5. |
| `CreateDistribution(WithTags)` | A `vpcorigin` permission to attach an origin | Steps 3–5, scoped to `vpcorigin/*` with the ResourceTag condition |
| `RunInstances` with an instance profile | `iam:PassRole`, `ec2:AssociateIamInstanceProfile` | Names match. Extra actions scoped to `instance/*` with the tag condition. |
| Destroy | `UpdateDistribution` or `DeleteVpcOrigin` with a missing ResourceTag | Check `list-tags-for-resource` first; if present, steps 3–5. |

Other risks: VPC origin over 30 min or a provider timeout (re-apply to refresh or destroy; record as a gate fail); service SG not found at the data read (re-run); responder down with no console output (timings still valid; destroy, fix, re-run; `ec2:GetConsoleOutput` only if needed); `DeleteVpcOrigin` "in use" right after the distribution delete (re-run the destroy); service SG or ENIs persisting in the standing VPC ($0, but would block a future `standing-destroy`; record for step 10); lost local state (abort path); do not run during an `exercise.sh` run.

Abort path (AWS CLI, changes AWS; check field names with `--output json` first):

```
D=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='cerberus vpc-origin spike'].Id" --output text)
aws cloudfront get-distribution-config --id "$D" > logs/dc.json
jq '.DistributionConfig.Enabled=false | .DistributionConfig' logs/dc.json > logs/dc-off.json
aws cloudfront update-distribution --id "$D" --if-match "$(jq -r .ETag logs/dc.json)" --distribution-config file://logs/dc-off.json
aws cloudfront wait distribution-deployed --id "$D"
aws cloudfront delete-distribution --id "$D" --if-match "$(aws cloudfront get-distribution --id "$D" --query ETag --output text)"
V=$(aws cloudfront list-vpc-origins --query "VpcOriginList.Items[?Name=='cerberus-vpc-origin-spike'].Id" --output text)
aws cloudfront delete-vpc-origin --id "$V" --if-match "$(aws cloudfront get-vpc-origin --id "$V" --query ETag --output text)"
aws ec2 terminate-instances --instance-ids $(aws ec2 describe-instances --filters Name=tag:Name,Values=cerberus-vpc-origin-spike Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text)
# after the instance is terminated and the VPC origin is gone:
aws ec2 delete-security-group --group-id $(aws ec2 describe-security-groups --filters Name=group-name,Values=cerberus-vpc-origin-spike --query 'SecurityGroups[0].GroupId' --output text)
aws iam remove-role-from-instance-profile --instance-profile-name cerberus-console-grafana-spike --role-name cerberus-console-grafana-spike
aws iam delete-instance-profile --instance-profile-name cerberus-console-grafana-spike
aws iam delete-role --role-name cerberus-console-grafana-spike
./check.sh
```

Do not touch `CloudFront-VPCOrigins-Service-SG` (AWS-managed).

## 10. What gets committed

`terraform/spikes/vpc-origin/` (`versions.tf`, `provider.tf`, `main.tf`, `outputs.tf`, `user_data.sh.tftpl`, `responder.py`, `check.sh`, `probe.sh`, `README.md`, `.terraform.lock.hcl`), the `.gitignore` lines, this plan with its Outcome, the demo-console plan notes, the Phases.md line, and the IAM README only if a policy changed. Never committed: state, `*.tfplan`, `logs/`, IDs, domain names, ARNs, the account ID.

Sources: [CloudFront VPC origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html), [VPC origins announcement](https://aws.amazon.com/about-aws/whats-new/2024/11/amazon-cloudfront-vpc-origins), [AWS News Blog: VPC origins](https://aws.amazon.com/blogs/aws/introducing-amazon-cloudfront-vpc-origins-enhanced-security-and-streamlined-operations-for-your-applications).

## Outcome (2026-10-27)

Run by the main session with the user's OK, profile `cerberus-admin`, two cycles. Gate verdict: **PASS in both cycles.** Wake was at most 20 minutes, teardown left nothing billable, and the VPC ENIs cleared within 30 minutes. No 403 appeared anywhere. Times are minutes:seconds.

Deviation: cycle 2 needed a second apply. The first apply failed at the service-SG data read ("no matching EC2 Security Group found") after the VPC origin was created. The group existed when the re-plan ran about 1 minute later, tagged `aws.cloudfront.vpcorigin=enabled` (observed by a manual CLI read, not logged). The group from cycle 1 had been deleted, so CloudFront creates a new one for each new VPC origin, and the read raced that creation (finding 1). A re-plan showed exactly 2 to add (the ingress rule and the distribution), and the re-apply completed them.

| Measure | Cycle 1 (first VPC origin in the account) | Cycle 2 |
|---|---|---|
| Pre-check | All zeros; plan 7 to add | Plan 7 to add |
| Role / SG / profile create | 0:02 / 0:06 / 0:08 | 0:02 / 0:05 / 0:08 |
| Instance create | 0:16 | 0:19 |
| VPC origin create | 8:05 | 2:08 |
| Service-SG data read | 0:01 | Failed on the first apply; found on the re-apply |
| Ingress rule create | 0:01 | 0:02 (re-apply) |
| Distribution create | 3:12 | 11:33 (re-apply) |
| Apply wall clock | 11:51 | 2:43 (failed) plus 11:39 (re-apply) |
| First 200 after apply | 0:01 | 0:06 |
| Body, `/nope` 404, WebSocket 101, Sec-WebSocket-Accept | All PASS | All PASS |
| Wake | about 11:52 | about 15:35 wall clock, including a gap of about 1:00 between the two applies; 14:28 for the two applies plus the probe |
| Check-up | No public IP; IMDSv2 required; spike SG 1 ingress (tcp 80 from the service SG), 0 egress; service SG present (0 ingress, 1 egress) | Same |
| Distribution destroy | 3:18 | 3:18 |
| Ingress rule destroy | 0:02 | 0:01 |
| VPC origin delete | 6:56 | 7:02 |
| Instance destroy | 0:22 | 0:23 |
| SG / profile / role destroy | 0:01 / 0:01 / 0:01 | 0:02 / 0:02 / 0:01 |
| Destroy wall clock | 10:44 | 10:52 |
| VPC ENIs at 0 after destroy | 1:06 | 1:07 |
| Service SG after destroy | Present at destroy end and while the ENIs cleared; deleted by AWS within about 2:21 of destroy end | Present at destroy end; absent on a later 2026-10-27 read |
| 403s met | None | None |

After cycle 2 the Terraform state was empty and the local state files were removed. Only the service-linked role remains ($0, AWS-managed). CloudFront deletes the service SG a few minutes after the last VPC origin, so it does not block a `standing-destroy`. A standing destroy must still wait for the ENIs and the SG to clear after a session teardown (step 10).

Findings for step 10 (`envs/dev-console`):

1. The service-SG lookup races the VPC origin. Every session creates a fresh VPC origin and CloudFront creates a new service SG for it (it is not reused), so design a retry or wait, or look the group up by the `aws.cloudfront.vpcorigin` tag after a wait.
2. The variance is large: VPC origin 8:05 against 2:08, distribution 3:12 against 11:33. The critical path is the VPC origin and the distribution in series, about 11 to 14 minutes. Budget about 15 minutes for the wake and show a "warming up" state on the landing page.
3. Teardown takes about 11 minutes (distribution delete about 3:18, then VPC origin delete about 7 minutes). A session teardown should run in the background and be verified later.
4. The AL2023 arm64 root is 8 GiB gp3 (already F14).
5. Cost: the two cycles ran about 50 minutes of t4g.nano in total, under $0.01 at list price. Confirm in Cost Explorer the next day.
