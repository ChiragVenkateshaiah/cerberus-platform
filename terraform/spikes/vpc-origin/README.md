# VPC-origin spike (9.2)

A throwaway measurement, not a real root. It times how long a CloudFront VPC
origin and its distribution take to create and destroy, and proves the path
CloudFront -> VPC origin -> instance SG -> HTTP responder on a `t4g.nano` in a
private subnet. Context: ADR 0024 build step 3 and
[the plan](../../../docs/plans/2026-10-27-vpc-origin-spike.md), which also holds
the gate and the Outcome.

State is local (no backend, on purpose). CI never plans or applies this
directory. Run it from your own terminal, or from the main Claude session
with your explicit OK. Delete the whole directory in the step 10 PR, after
`envs/dev-console` exists.

## Files

- `versions.tf`, `provider.tf`, `main.tf`, `outputs.tf`: the Terraform root.
- `user_data.sh.tftpl`, `responder.py`: the instance's stdlib-only responder.
- `check.sh`: read-only state check (`--watch-enis INTERVAL MAX` waits for
  the VPC's ENIs to clear).
- `probe.sh DOMAIN_OR_BASE_URL`: polls for the first 200, then checks the
  body, `/nope` (404) and the WebSocket upgrade (101).

## Run

```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
cd terraform/spikes/vpc-origin && mkdir -p logs
./check.sh | tee logs/check-before-1.txt        # every count 0
terraform init
terraform plan -out=spike.tfplan | tee logs/plan-1.txt   # exactly 7 to add
( time terraform apply spike.tfplan ) 2>&1 | tee logs/apply-1.txt   # changes AWS
./probe.sh "$(terraform output -raw domain_name)" | tee logs/probe-1.txt
./check.sh | tee logs/check-up-1.txt
terraform plan -destroy -out=destroy.tfplan | tee logs/plan-destroy-1.txt
( time terraform apply destroy.tfplan ) 2>&1 | tee logs/destroy-1.txt  # changes AWS
./check.sh --watch-enis 30 1800 | tee logs/check-after-1.txt
```

If destroy needs a re-run, record the sum of both `real` times and keep both
logs (`destroy-N.txt`, `destroy-N-retry.txt`).

Run a second cycle the same way (logs `-2`). Stop on any 403 or unexpected
plan; do not retry with another profile. `logs/` and `*.tfplan` are
gitignored.

## Teardown and abort

Normal teardown is the `terraform plan -destroy` and `apply` pair above. If
state is lost or destroy is stuck, use the AWS CLI abort path in section 9 of
the plan. Do not touch `CloudFront-VPCOrigins-Service-SG`: it is AWS-managed,
and CloudFront may leave it (and the service-linked role) behind at no cost. The group is deleted a few minutes after the last VPC origin (measured); the role remains.
The instance also terminates itself after 120 minutes.

## Known race

The `aws_security_group` data read for `CloudFront-VPCOrigins-Service-SG` can
run before CloudFront has created or replaced that group, and then fails with
"no matching EC2 Security Group found". It happened in cycle 2, after the VPC
origin was created. Do not destroy. Run `terraform plan -out=spike.tfplan`
again: it should show only the ingress rule and the distribution to add. Apply
that plan and record both apply times. Step 10 must handle this race in
`envs/dev-console`.
