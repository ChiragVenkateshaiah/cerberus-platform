# dev-console

The per-session live Grafana of the demo console (ADR 0024, build step 10;
plan `docs/plans/2026-11-12-console-session.md`). A third root, with the
`dev-compute` contract: human-run from the owner's terminal, never planned or
applied by CI, and `destroy` leaves nothing billable.

A session is one `t4g.small` (no key, no public IP) in the console subnet, a
NAT gateway on the console route table, a CloudFront VPC origin with its own
distribution, a Cognito app client, and a `live.json` at the site bucket root.
The instance runs Grafana from the pinned tarball, with the AMP datasource
only. A visitor signs in through Cognito and sees the recorded runs as a Viewer.

Run it only through `make console-session` (see "Usage" below). It checks the
account first and destroys from an EXIT trap. Do not apply this root by hand.

## Files

- `versions.tf`, `provider.tf`, `variables.tf`, `outputs.tf`: root setup. The
  S3 backend is partial (the bucket name holds the account ID).
- `main.tf`: remote state of `dev-standing`, the NAT (`modules/vpc_nat` on the
  console route table), the instance role, the security group, the instance.
- `edge.tf`: VPC origin, the service-SG wait, the distribution, the Cognito client.
- `session.tf`: the bundle, the readiness probe, `live.json`.
- `user_data.sh.tftpl`: the boot script. `wait_service_sg.sh` and `probe.sh`
  are the two `local-exec` scripts.

## Usage (owner)

```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
make console-check                 # READ-ONLY: every session count must be 0
make console-plan                  # READ-ONLY: expect 20 to add, nothing else
make console-session MINUTES=30    # AWS WRITE: default 90, 1 to 120; ARGS=--yes skips the prompt
# only after an interrupted session (laptop sleep, crash):
make console-destroy && make console-check
```

`console-plan`, `console-session` and `console-destroy` all start with the
same init (`orchestration/console_init.sh`): it reads the account ID with
`sts get-caller-identity` and passes the backend settings as `-backend-config`
flags, because the state bucket name holds the account ID.

`console-session` (`orchestration/console_session.sh`) checks the preflight
(identity, `console_check.sh` at zero, empty state, both artifacts staged with
the pinned sha256, `1 <= MINUTES <= 120`), shows the plan, asks y/N with the
cost (about $0.068/hour), applies, prints the URL and the end time, and counts down. The
URL goes to your terminal only. Ctrl-C ends the session early. An EXIT trap
runs the destroy (with a `-refresh=false` retry, because the service-SG data
source no longer matches once the VPC origin is gone), waits up to 30 minutes
for the VPC origin's network interfaces, then runs `console_check.sh`.

`console-destroy` is the same teardown without a session, for a trap that
died. A dead trap bills the NAT and its IP at about $1.20/day until destroy;
the instance ends itself at boot + minutes + 45.

Press Ctrl-C once only: a second one stops terraform without saving state.
The destroy itself runs in its own session, so Ctrl-C cannot reach it.

## Needs from other steps

- PR A applied (S3 gateway endpoint on the console route table, the artifacts
  deny).
- PR B applied: `make console-artifacts` has staged the Grafana and plugin
  packages. The boot script fetches them by the keys and sha256 in
  `observability/grafana/console/artifacts.json`.
- Outputs of `dev-standing`: `vpc_id`, `public_subnet_a_id`,
  `prometheus_workspace_arn`, `prometheus_endpoint`, `console_subnet_id`,
  `console_route_table_id`, `console_site_bucket_name`, `console_user_pool_id`,
  `console_auth_domain`. All exist.

## How the pieces fit

- **No cycle.** The instance is created first. The VPC origin needs its ARN,
  the distribution needs the origin, and the Cognito client needs the
  distribution's domain. The instance reads its client at boot (it polls up to
  40 minutes for `cerberus-console-grafana`), so the secret never reaches S3,
  tags or user data.
- **Service-SG waits.** `CloudFront-VPCOrigins-Service-SG` appears after the
  VPC origin and can race it (spike finding 1), and an earlier session's group
  lingers a few minutes after its origin is gone. `wait_service_sg.sh` runs
  twice (the 20th resource): `WANT=0` before the VPC origin waits for no such
  group, `WANT=1` after it waits for exactly one. Both poll by the
  `aws.cloudfront.vpcorigin` tag for up to 10 minutes; the data source reads
  the group after that. Never edit that group.
- **Self-terminate.** The first user-data line is `shutdown -h +<minutes+45>`
  and `instance_initiated_shutdown_behavior` is `terminate`.
- **Port 3000 opens last.** Grafana first listens on loopback with basic auth,
  `load.py` posts the annotations, then the config is rendered again with
  `0.0.0.0` and basic auth off, and Grafana restarts.
- **Readiness probe.** `probe.sh` (curl, on the machine running Terraform)
  polls `https://<distribution>/api/health` until 200, at most 20 minutes.
  `live.json` is written only after it passes, with
  `Cache-Control: no-cache, max-age=0`. After a dead trap the file stays with
  `ends` in the past, so a reader must hide it once `ends` has passed.
- **Bundle.** `archive_file` zips the console module files, the repo
  dashboards, `amp.yaml`, a generated dashboards provider and the run records
  to `artifacts/session/bundle-<sha256>.zip`. Destroy removes it.

## Unverified (checked in the first live session, PR F)

- `insecure_value` of the SSM AMI parameter and AL2023's `python3` being 3.9.
- The tag value `enabled` is not relied on (only the tag key).
- Grafana's binary name in the tarball, and the grafana.ini key names marked
  "unverified" in `observability/grafana/console/grafana.ini.tmpl`.
- The AMP plugin reading the instance role through `sigV4AuthType: default`.
