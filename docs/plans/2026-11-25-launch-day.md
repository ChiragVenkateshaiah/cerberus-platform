# Plan: Phase 17, Launch Day — modelling the GTA VI download surge on Cerberus

Date: 2026-11-25 (Wed). Planner: Opus (main session). Mode: plan for a new phase
(Phases.md 17.0–17.10) and ADR 0030. Read against `origin/main` at `3b14ba8`
(#185). Save as `docs/plans/2026-11-25-launch-day.md`. Proposed first branch:
`decision-launch-day`.

Owner request (2026-11-25, summarised): build the GTA VI launch-day download
traffic as Cerberus's **second data domain, now**, ahead of the current
sequencing, while the event is fresh; finish it over the weekend; publish a
LinkedIn article by Sunday 2026-11-29. Everything as IaC. Use the Cerberus
workflow: Sonnet writes, Haiku runs git. **Spend above the $20/month guardrail
is approved for this phase** (owner, 2026-11-25).

## 1. Question

Can Cerberus model a record-breaking game launch end to end, in one weekend,
honestly and within a bounded budget? Two halves:

1. **Delivery plane (Cloud Engineering).** A large build delivered through
   CloudFront with a pre-load window, a release "unlock" and a day-one patch,
   measured: cache hit ratio, origin offload, TTFB p50/p99, request rate at
   the release spike, cost per GB.
2. **Telemetry plane (Data Platform Engineering).** Millions of synthetic
   console clients emitting download telemetry with the real event's shape,
   landed in bronze, promoted to silver, modelled in gold, checked by a
   data-quality suite — Cerberus's second event family, with payments
   untouched.

## 2. Facts (V = verified, U = unverified, to check in the named step)

**The real event** (public reporting; the article cites these, the plan does
not copy their numbers into the data)

- R1 (V). Pre-loads opened 2026-11-10. DE-CIX recorded 33.01 Tbps across its
  exchanges that day, 22.30 Tbps at Frankfurt (gtaboom, DCD, player.one).
- R2 (V). DE-CIX's new high: 33.03 Tbps at 2026-11-18 20:20 CET, the final
  downloads before the 2026-11-19 midnight-local release (gtaboom,
  americanbazaar).
- R3 (V). DE-CIX: these are total exchange peaks, not GTA-only traffic
  (player.one). A Cerberus run must never be compared as if it were.
- R4 (V). Reported download size about 212 GB (gtaboom). Nearly half of
  surveyed UK players expected to pre-load before release day (VMO2 via
  advanced-television).
- R5 (V). Incidents: YouFibre hit a capacity problem and used emergency
  traffic management (player.one); a last-minute PS5 update on release day
  made the network wobble (sdxcentral).

**The repo**

- F1 (V). Region `us-east-1` (`envs/dev-standing/provider.tf` L12).
- F2 (V). Three roots: `dev-standing` ($0 idle), `dev-compute` (per
  exercise), `dev-console` (per session, `make console-session`: preflight,
  y/N, apply, countdown, destroy from an EXIT trap, then `console-check`).
  Phase 17's delivery root copies the `dev-console` lifecycle.
- F3 (V). `console_edge` already shows the edge pattern: private S3 + OAC,
  `PriceClass_100`, a deny on a private prefix (`main.tf` L44–128, L213).
- F4 (V). `exercise.sh`: apply → (generate) → run → collect → destroy from
  an EXIT trap; `--generate`, `--generator-executors`, `--executor-nodes`.
  `submit_job.sh` reads `SILVER_BUCKET`, `SCRIPT_S3_KEY`, `APP_NAME` and
  friends from the environment (`L29–40`).
- F5 (V). `generate_bulk_payments.py` is deterministic by design (ADR 0018):
  every random choice is a hash of (run_id, row id, salt); "now" is an
  argument. Writes `payments_bulk/run_id=/dt=/part-*.json`.
- F6 (V). Payments-specific code (unchanged by this phase): silver dedup on
  `(transaction_id, event_type)`, hardcoded bronze prefixes, `data_quality.py`.
  Gold is dbt on Athena (`transform/dbt/models/marts/`).
- F7 (V). Highest ADR is 0029; highest phase is 16. This phase is **17**,
  its ADR **0030**.
- F8 (V). Phase 9 is 🔨 (9.2, 9.4, 9.6, 9.7 open). Phase 13 (streaming) owns
  the future generalisation of ingestion.
- F9 (V). CloudFront always-free tier: 1 TB out, 10M HTTP(S) requests, 2M
  CloudFront Functions invocations per month. India out beyond the free tier
  is $0.109/GB; US/EU $0.085/GB. The flat-rate Free plan caps at 100 GB and
  1M requests and has no Origin Shield (Premium only).
- U1 (17.3). CloudFront standard logging v2 to S3: delivery latency, cost and
  whether the delivery source must be created in `us-east-1` (it is our
  region anyway).
- U2 (17.4). AWS's CloudFront load-testing guidance: any notification or
  rate the guidance sets for a test of this size. Read before the first
  live run; if a notice is needed, the owner sends it Thursday.
- U3 (17.3). Which VPC subnet the load generator uses (the `vpc` module's
  public subnet lives in `dev-compute` today) — or a dedicated small VPC in
  `dev-launch`.

## 3. Claim and honesty rules

The phase models the launch; it does not replicate it. Every chart and the
article state the **scale ratio** (our measured peak ÷ 33.03 Tbps) and that the
telemetry is synthetic, shaped from public reports. No real ISP, platform-
holder or Rockstar data, names in the data, logos or game imagery. Region and
ISP labels in the data are synthetic (`isp_eu_03`).

## 4. Architecture

```
            ┌──────────── dev-launch (per session, $0 idle) ─────────────┐
 k6 on Spot │ EC2 load gen ──signed cookies──▶ CloudFront (PriceClass_All)│
 (us-east-1)│   seeds build ──▶ S3 build bucket ◀─OAC── Origin Shield     │
 k6 laptop ─┼──(Bengaluru TTFB probe)──▶ Indian edge                      │
            │ CloudFront Function + KeyValueStore: /license (release_at)   │
            │ logging v2 ──▶ launch log bucket ── launch-collect ──┐       │
            └───────────────────────────────────────────────────────┼───────┘
                                                                    ▼
 dev-compute (per exercise): generate_bulk_downloads ─▶ bronze downloads_bulk/
                                                         bronze downloads_cdn/
                             promote_downloads_spark ─▶ silver.download_events (Iceberg)
 dev-standing: dbt (Athena) ─▶ gold marts/downloads/*  ── charts ── article
```

**Delivery plane — `terraform/envs/dev-launch` + `modules/launch_edge`**

- Build bucket, private, OAC only. A synthetic build of **4 GiB = 64 × 64 MiB
  chunks** under `build/<sha256>.bin` (content-addressed, immutable) plus
  `build/manifest.json`; a **512 MiB day-one patch** under `patch/`. Seeded
  in-region by the load generator's user-data (no upload from home).
- CloudFront, **pay-as-you-go** (not the flat-rate Free plan: it caps at
  100 GB and has no Origin Shield). `PriceClass_All` so the Bengaluru probe
  hits an Indian edge. Origin Shield in `us-east-1`. Cache policy: no query
  string, cookie or header in the key; TTL a year for chunks (immutable
  names).
- **Entitlement:** a trusted key group; signed cookies for `/build/*` and
  `/patch/*`. The public key PEM comes into Terraform from a file; the
  private key is generated by the owner with `openssl`, stored as an SSM
  SecureString by an owner-run command, and is **never in git or state**.
- **Release unlock:** a CloudFront Function on `/license*` only, reading
  `release_at` from a CloudFront KeyValueStore: 403 before, 200 JSON after.
  No origin, no cache — it is the request-spike target. This mirrors reality:
  pre-loaded content is useless until the licence unlocks at release.
- **Load generator:** one Graviton Spot instance (network-optimised family;
  size fixed in 17.4 against the byte budget), no SSH, no ingress, egress
  443 only, SSM Session Manager. Instance role: read the one SSM parameter,
  write the build bucket (seeding), read the scenarios. k6 is downloaded
  from GitHub releases with a **pinned version and sha256** (same rule as
  `console-artifacts`).
- **Logging:** CloudFront standard logging v2 to a launch log bucket;
  `launch-collect` copies the session's logs to
  `bronze/downloads_cdn/run_id=<id>/` before the destroy.
- **Guards (all in the session script):** a byte budget computed from the
  scenario before anything runs (refuse if over); a CloudWatch alarm on the
  distribution's `BytesDownloaded` over the session budget → SNS email; a
  session time limit (`MINUTES`, default 120) with destroy from an EXIT
  trap; `launch-check` proves every count is 0 afterwards (distribution,
  function, KVS, key group, instance, SG, buckets, state).

**Scenarios** (`launch/scenarios/*.json`, time compressed: 9 days of
pre-load → 30 minutes)

| Run | What | Clients | Bytes (planned) | Requests |
|---|---|---|---|---|
| A smoke (Fri) | one client, full build + patch, licence 403→200 | 1 | ~5 GB | ~100 |
| B pre-load | 50 clients ramp over 30 min, full build | 50 | ~200 GB | ~3.2k |
| C release | patch for all 50 at T0, 1M licence requests in 10 min, 20 late full downloads | 70 | ~105 GB | ~1M |
| D stampede (optional) | Origin Shield off vs on, cold patch, 50 clients at T0: origin requests compared | 50×2 | ~50 GB | ~6k |
| P probe (laptop) | Bengaluru → Indian edge vs a US-edge hostname, TTFB p50/p99 | 1 | ~2 GB | ~2k |

Total about 360 GB and about 1M requests: inside the 1 TB / 10M free tier
with room for one full re-run.

**Telemetry plane — the `downloads` family**

- **Envelope (ADR 0030 defines it; Phase 13 adopts it for every family):**
  `event_id` (UUIDv7 layout: `occurred_at` ms + hash bits, deterministic),
  `event_family`, `event_type`, `occurred_at`, `ingested_at`,
  `schema_version`, `payload`. Payments is not touched.
- **Event types:** `preload_started`, `chunk_completed` (every ~5 GB of a
  modelled 212 GB title), `stalled`, `retried`, `preload_completed`,
  `license_requested`, `license_granted`, `patch_started`,
  `patch_completed`, `install_completed`, `abandoned`.
- **Payload:** `client_id`, `platform` (ps5|xbox), `region` (24 synthetic,
  one per time zone), `isp` (synthetic), `bytes`, `duration_ms`,
  `throughput_mbps`, `http_status`.
- **Shape (calibrated, not copied):** window 2026-11-10 00:00 UTC to
  2026-11-22 00:00 UTC; pre-load opens day 0 with an opening spike; diurnal
  evening peaks; ~46% of clients pre-load (R4); release at **midnight local
  per region**, so the spike rolls across time zones; a day-one patch at T0
  for everyone (R5); a final-downloads peak the evening before release (R2).
- **The incident, modelled:** each synthetic ISP has a capacity; a second
  pass computes active clients per (isp, minute) and derives throughput and
  stall probability from it, so one under-provisioned ISP congests at release
  and then "traffic management" caps per-client throughput (R5). Fallback if
  the two-pass job is late: a precomputed capacity curve per ISP.
- **Scale:** 2M clients, about 100M events (the Phase 8 harness proved 100M
  in 742 s). Deterministic like ADR 0018.
- **Bronze:** `downloads_bulk/run_id=/dt=/part-*.json` (synthetic) and
  `downloads_cdn/run_id=/` (real CloudFront logs from the delivery runs).
- **Silver:** `promote_downloads_spark.py` → Iceberg `silver.download_events`,
  dedup on `event_id`, incremental per ADR 0017. A **separate job on
  purpose** — accepted debt, retired when Phase 13.5 generalises the silver
  job (ADR 0030 records it).
- **Gold (dbt on Athena, `marts/downloads/`):** `fct_download_sessions`,
  `agg_isp_minute` (active clients, modelled Gbps, stall rate),
  `agg_release_window` (T-60 min to T+6 h per region), `fct_cdn_requests` and
  `agg_cdn_run` (from the real logs: cache hit ratio, origin requests, TTFB
  p50/p99 by edge POP).
- **Data quality** (`observability/launch/data_quality_downloads.py`, about 8
  checks, fail-closed): bronze → silver count reconciliation; `event_id`
  unique; every session's lifecycle valid (no `install_completed` without
  `license_granted`); bytes ≥ 0 and ≤ title size; timestamps inside the
  window; no licence granted before local release; CDN logs present for every
  run; no account ID or ARN in published outputs.

## 5. Phase 17 tasks

Tiers and loop per `.claude/commands/workflow.md`. Every AWS write is
owner-run; the executor prepares the exact command. Each task ends with
`make verify` and a PR by `cerberus-git` (Haiku).

| # | Task | Tier | Agents | Done when |
|---|---|---|---|---|
| 17.0 | Phases.md gets Phase 17 (added 2026-11-25, numbered 17 so 10–16 keep their numbers; runs now, ahead of 9.4/9.6/9.7 by owner decision); this plan into `docs/plans/`; README status line | T | executor → git | PR merged |
| 17.1 | ADR 0030 "Launch day: a second event family and a per-session delivery edge": claim and honesty rules (§3); the envelope; separate silver job as debt; `dev-launch` lifecycle; pay-as-you-go vs flat-rate; Origin Shield; `PriceClass_All`; signed cookies and key handling; the cost exception (§6); WAF considerations | D | `/decision` (Opus plans and reviews), executor writes | ADR Accepted by owner |
| 17.2 | `generate_bulk_downloads.py` (deterministic, two-pass congestion, roster-free), its SparkApplication YAML, unit tests on a 10k-event local sample (lifecycle, determinism, shape) | C | planner → executor → reviewer → git | tests pass; sample committed under `data/samples/downloads/` |
| 17.3 | `modules/launch_edge` + `envs/dev-launch`: buckets, OAC, distribution, Origin Shield, key group, CloudFront Function + KVS, logging v2, load-gen instance + role + SG, alarm + SNS. Verify U1, U3 | S | planner → executor → reviewer (`escalate: opus-security`, owner decides) → git | `make launch-plan` (owner) clean; tfsec/fmt pass |
| 17.4 | `launch/`: scenarios A–D and P, k6 scripts, `plan_bytes.py` byte guard, `session.sh` (copy of `console_session.sh` lifecycle), `collect.sh`, `check.sh`; Make targets `launch-plan`, `launch-session` (`SCENARIO=`, `MINUTES=`), `launch-collect`, `launch-check`, `launch-destroy`. Verify U2 | C | planner → executor → reviewer → git | dry run prints the plan and byte total; shellcheck passes |
| 17.5 | `promote_downloads_spark.py` (Iceberg, `event_id` dedup, incremental); `launch_exercise.sh` wrapper reusing `dev-compute` and `submit_job.sh` env vars (`make launch-exercise`, `ARGS="--generate 100000000"`); dbt `marts/downloads/` + schema tests; the DQ suite | C | planner → executor → reviewer → git | dbt compile + tests on CI profile; DQ unit tests |
| 17.6 | **Live (owner):** Fri smoke (Run A + 1M-event telemetry); Sat Runs B, C, (D), P, then the 100M telemetry exercise; `launch-collect`; `launch-check` = 0 | — | owner runs; `cerberus-live-verifier`-style read-only check by a Sonnet agent | run records in `observability/launch/runs/`; all counts 0 |
| 17.7 | Results: `docs/launch-day-results.md` + charts in `docs/img/launch/` (traffic curve vs release per time zone, ISP congestion heatmap, cache hit ratio and origin offload, TTFB by edge, Shield on/off, cost per GB and per million events, the scale ratio) | C | executor → reviewer → git | every number traced to a run record or gold query |
| 17.8 | LinkedIn article `articles/linkedin/2026-11-29-launch-day.md` (§9). Not `/write-article` (that is the Wednesday series) | T | executor drafts → owner edits → git | owner publishes on LinkedIn |
| 17.9 | Teardown proof and cost read: `launch-check`, `exercise-check`, Cost Explorer on Mon 2026-11-30 (lags ~24 h), actuals into the results doc | T | owner + executor | actual cost recorded |
| 17.10 | Well-Architected pass + ADR (after the weekend); hand-offs: envelope → Phase 13.1, silver debt → 13.5, results → Phase 15 showcase | D | `/decision` | ADR Accepted |

## 6. Budget

Owner approved spend above the $20/month guardrail for this phase.
**Ceiling: $40.** Expected: **$8–15.**

| Item | Basis | Expected |
|---|---|---|
| CloudFront data out + requests | ~360 GB, ~1M requests, inside the free tier (F9) | $0 |
| CloudFront Functions + KVS | ~1M invocations, inside 2M free | $0 |
| Origin Shield | billed per request reaching the shield; a few thousand | < $0.50 |
| S3 build + logs | ~5 GiB for a few days, deleted at destroy | < $0.50 |
| Load-gen Spot | 3 sessions × ~2 h | $1–3 |
| `dev-compute` exercises | 1M smoke + 100M run + one re-run, cluster ~$0.40/h | $3–6 |
| Athena, dbt, CloudWatch, SNS | small scans, a few alarms | < $2 |
| Contingency | a failed destroy found late, a re-run | ~$5 |

Stop rules: the byte guard refuses any session over 400 GB; the
`BytesDownloaded` alarm fires at 450 GB; at **$25** of month-to-date spend
attributable to Phase 17 the owner stops and destroys. Free-tier overrun
worst case is bounded by the guard: each extra 100 GB costs about $8.50 (US)
or $10.90 (India). Owner action today: raise the account Budget alert to $40
for November (console, by hand).

## 7. Schedule (IST; owner runs remote sessions with `/start-day` … `/end-day`)

| Day | Work | Owner by hand |
|---|---|---|
| Wed 25 | 17.0 PR; 17.1 `/decision` → ADR 0030 Proposed | accept ADR 0030; raise Budget alert; activate nothing else |
| Thu 26 | 17.2 generator; 17.3 Terraform (Tier S review) | generate key pair, SSM put-parameter; send load-test notice if U2 says so |
| Fri 27 | 17.4 session tooling; 17.5 silver/dbt/DQ; **smoke**: Run A + 1M telemetry | `make launch-plan`, `make launch-session SCENARIO=a`, `make launch-exercise ARGS="--generate 1000000"` |
| Sat 28 | **live**: Runs B, C, (D), P; 100M telemetry; collect; check | `make launch-session SCENARIO=bcd`, laptop probe, `make launch-exercise ARGS="--generate 100000000"`, `make launch-check` |
| Sun 29 | 17.7 results + charts; 17.8 article; publish by evening | edit and publish on LinkedIn |
| Mon 30 | 17.9 cost read | Cost Explorer |

**Cut lines if behind** (in this order): drop Run D; drop the two-pass
congestion model for the capacity-curve fallback; telemetry at 10M instead of
100M; CDN logs analysed from CloudWatch metrics instead of the lakehouse.
Never cut: the byte guard, the EXIT-trap destroy, `launch-check`, the honesty
rules.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Runaway download bill | byte guard, alarm, time limit, signed cookies (nobody else can pull) |
| Distribution delete slow (disable then delete) | session budget includes ~15 min; `launch-destroy` retries with `-refresh=false` like `console-destroy` |
| Log delivery late (U1) | `collect.sh` polls up to 20 min; else re-run collect Sunday before the bucket destroy |
| Private key leak | generated and kept locally, SSM SecureString, never in state; account-number scan in `make verify` extended to PEM headers |
| Load test flagged as abuse (U2) | read the guidance Thursday; low rates from one instance; notice if needed |
| Spark two-pass job slow at 100M | test at 1M/10M first; fallback curve |
| Article overclaims | §3 rules; reviewer checks every number against `docs/launch-day-results.md` |

## 9. Article

Title direction: "Modelling GTA VI's launch-day download surge on AWS, at
1/N scale" (N measured on Saturday). Shape: the event in one paragraph with
cited sources (R1–R5); the two-plane architecture diagram; three findings with
charts (release spike rolling across time zones; one ISP congesting and being
traffic-managed; Origin Shield and immutable chunks keeping origin load flat);
cost per GB and per million events; what it would take at real scale (multi-
CDN, ISP embedded caches, peering at exchanges); repo link. Own charts and
diagram only. Owner publishes.

## 10. Open, for the owner

1. Phase 9's open items (9.2 close-out, 9.4, 9.6, 9.7) pause until Monday —
   confirm. Phase 17.0 records the reversal of the 2026-11-08 sequencing.
2. ADR 0030 goes through `/decision`, which is the workflow's one Opus step.
   Keep it, or let the Sonnet executor draft and the reviewer review this once?
3. Ceiling $40 and the $25 stop rule — confirm.

## 11. Next steps

1. Owner answers §10.
2. Today: `/workflow 17.0`, then `/decision 17.1`.
3. Thursday: `/workflow 17.2` and `/workflow 17.3` in parallel worktrees.
