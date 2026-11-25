# dev-launch

The per-session delivery edge of the launch-day phase (ADR 0030; plan
`docs/plans/2026-11-25-launch-edge.md`). A fourth root, human-run from the
owner's terminal. CI never plans or applies it (ADR 0030 Decision 2). This
README covers 17.3b only: nothing here is applied yet. Apply and destroy
belong to 17.4 and 17.6.

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

## Unverified

- Whether CloudFront checks the signature before the `/license*` Function.
- Whether the `s3:x-amz-acl` = `bucket-owner-full-control` condition (in the AWS
  cross-account example) is needed on the same-account log bucket policy, and
  whether S3 delivery accepts JSON output. Both to be settled by the 17.6 smoke.
- Delete order and duration of key group, Function and KVS (allow 30 minutes).
