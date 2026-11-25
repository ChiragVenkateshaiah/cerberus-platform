# dev-launch

The per-session delivery edge of the launch-day phase (ADR 0030; plan
`docs/plans/2026-11-25-launch-edge.md`). A fourth root, human-run from the
owner's terminal. CI never plans or applies it (ADR 0030 Decision 2). This
README covers 17.3b and the 17.4 tooling around it (below). Nothing here is
applied by CI; the owner runs the session (17.6).

## What it builds (`modules/launch_edge`)

- Two private buckets: build (`build/`, `patch/` served by CloudFront through
  OAC, `scenarios/` private) and logs (`cdn/`).
- One CloudFront distribution, `PriceClass_200`, no Origin Shield. Every
  behaviour, the default one too, needs a signed cookie from the key group.
  `/build/*` and `/patch/*` use the `cerberus-launch-chunks` cache policy.
  `/license*` runs a viewer-request Function.
- A public key (`name_prefix`, `create_before_destroy`) and a key group. The
  default key is a committed public PEM whose private half was discarded, so
  PREWARM holds no usable key.
- A KeyValueStore with `release_at` (epoch seconds, default far-future
  sentinel) and the Function `cerberus-launch-license`: 403 before
  `release_at`, 200 after, 403 on any error.
- CloudFront standard logging v2 to the log bucket under `cdn/`, JSON, with an
  explicit field allowlist (no client IP, cookie, referer or user agent).
- The load generator (`load_gen.tf`): one-time Spot, off unless
  `create_load_gen=true`. Its role holds no managed policy; see the file header.

The AWS default certificate's minimum TLS version cannot be raised. A higher
minimum needs a custom domain and certificate, which this phase does not add.

## Usage (owner)

```
export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
make launch-function-test   # offline: the Function and static checks
make launch-plan            # READ-ONLY: init, then plan with no load generator
```

`make launch-plan` starts with `orchestration/launch_init.sh`, which passes the
state backend as `-backend-config` flags (the bucket name holds the account
ID). It needs the `cerberus-admin-launch` policy pasted by root (17.3a).

## Launch session tooling (17.4)

```
make launch-baseline        # once, before Run A: November Usage through 11-24 (read-only)
make launch-session SCENARIO=bcd MINUTES=95 ARGS=--dry-run   # prints the plan, calls nothing
make launch-session SCENARIO=a                 # a live session; PREWARM=1 or HOLD=1 keep the edge up
make launch-collect RUN_ID=<id>                # CDN logs to bronze, repeatable (HOLD runs only)
make launch-destroy                            # stage 1 and stage 2, needs no shell state
make launch-check                              # 0 for every launch resource
make launch-test                               # offline pytest, stubs on PATH
```

`launch/` holds the scenarios, the k6 script, `plan_bytes.py` (layer 1),
`ledger.py` (the $25 rule; the CLI is the contract with 17.5) and
`cdn_fields.json` (the one log-field allowlist). The instance runs k6 itself
from user data (pinned version and sha256, an nftables quota at planned bytes
x 1.10). Its role has one extra statement: `PutObject` on `results/*` of the
build bucket (owner decision pending). The private key exists only in a tmpfs
directory during a live session.

What each run downloads (exact bytes: chunk requests x 64 MiB, plus the licence
response bodies of 17 B for 200 and 18 B for 403; headers, TLS and the manifest are
inside the 10% of the budget):

| Run | What | Requests | Bytes (decimal GB) |
|---|---|---|---|
| A | 1 client: full build (64 chunks), licence 403, wait for the release, licence 200, patch (8 chunks) | 74 | 4.832 |
| B | pre-load: 50 clients each download the full build, started over 30 min; B never waits for the release | 3,200 | 214.748 |
| C | at T0: patch for 50 clients, 1,000,000 licence requests (shared iterations, paced at 1,667 per s at most), 20 late full builds; one gate licence request | 1,001,681 | 112.760 |
| D | a second patch set (`patch2`, distinct from C's) for 50 clients at T0, then a warm repeat by 1 client (a second k6 run) | 409 | 27.380 |
| P | 1 client, the first 30 build chunks, manifest read through the edge (laptop) | 31 | 2.013 |

`bcd` is 354.889 GB (B + C + D) and, with P, 356.902 GB of 400 GB. The build is 64
distinct random chunks `build/<sha256>.bin` and `build/manifest.json`; the patches are
8 chunks each, `patch/<sha256>.bin` with `patch/manifest.json` and
`patch/manifest-2.json`. The instance generates, hashes, uploads (`launch/seed.py`) and
k6 reads the local manifests; the laptop checks and probe P read the manifest through
the signed edge. Request counts of every run are written to `run.json`
(`k6_requests`, an integer, plus `k6_requests_by_type`, `k6_complete` and the
session's own `curl_requests`) before stage 2, for `cdn_logs_complete`.

Timeline and checks:

- Cookies expire at mint + `MINUTES` (ADR 0030 Decision 4; never longer). The
  run deadline counts from the mint. The minimum, the default (the minimum) and the
  maximum of `MINUTES` and the release offset are derived from the scenario files by
  `launch/scenario.py` (boot, seed, ramp, licence rate and bytes over the link; all
  unverified estimates in `launch/scenarios/sets.json`). Today: a 44, b 67, c 50, d 43,
  bcd 88, p 36 minutes; the maximum is 120 (bcd: release at +53 min, after B ends plus
  5 min). A smaller `MINUTES` is refused before any call. `RELEASE_OFFSET_MINUTES`
  may only be later than the derived value, and raises the minimum.
- Apply order (ADR 0030 Decision 4): apply 1 has the public PEM and the default
  `release_at`, no instance; wait for `Deployed`; mint the cookies; put the
  parameter; apply 2 has the same PEM, the explicit `release_at` (now + offset) and
  the instance. T0 is fixed after `Deployed`, so the wait does not eat the schedule.
  The wait for the release in k6 is a sleep, not a poll, so it sends no request.
- The 403 on `/license` before T0 alone does not prove the signature: the
  Function answers 403 before `release_at` for any request. The session also
  checks, after seeding, that a request without a cookie is 403 and that a
  signed cookie on the build manifest is 200.
- `plan_bytes` month-to-date comes from the ledger only on a first live run:
  the distribution does not exist yet, so CloudWatch cannot be read.
- Layer 4 stops above the instance budget plus the probe P bytes x 1.10 (both
  use the one distribution), and also after 5 unreadable minutes in a row.
- A 403 never causes an extra request except the bounded licence retries (30 tries,
  2 s apart, counted as `licence_retry`); a chunk that fails is counted in
  `chunk_errors` and is not asked again.
- `run.json` starts with `"cdn_logs_collected": false`. `launch-collect` sets it
  to `true` (atomic write) after the manifest is in bronze; this is the
  contract with 17.5.
- `make launch-test` runs the real k6 (`K6_BIN` or `k6` on PATH) against a local
  HTTP stub of the edge, and skips those tests when k6 is absent.

## Unverified

- Whether CloudFront checks the signature before the `/license*` Function.
- Whether the `s3:x-amz-acl` = `bucket-owner-full-control` condition (in the AWS
  cross-account example) is needed on the same-account log bucket policy, and
  whether S3 delivery accepts JSON output. Both to be settled by the 17.6 smoke.
- Delete order and duration of key group, Function and KVS (allow 30 minutes).
- The nftables quota, the CloudFront log field names, per-client DNS through the
  VPC resolver, and the 30-minute shutdown margin: Run A proves them.
- The JMESPath names in `launch_check.sh` against live list output.
- k6 flags and behaviour on the instance (arm64 build, `dns` options with the real
  CloudFront names): tested with k6 2.4.0 linux-amd64 against a local stub only.
- The per-scenario timeline numbers (boot and seed, release offset, run length,
  slack), and whether CloudFront checks the signature before the Function.
- Whether seeding 64 MiB chunks (urandom, sha256, upload) runs at the assumed 25 MB/s.
