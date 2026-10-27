# 22. Live observability for a recorded run: local Grafana on AMP, native Prometheus and Spark UIs by port-forward

Date: 2026-10-24

## Status

Accepted (2026-10-25). Amends [ADR 0016](0016-prometheus-for-eks-spark.md) (the "Viewing: Grafana in-cluster" point of its
Decision) and implements the dev loop of [ADR 0021](0021-pipeline-status-and-alerting.md)
early. The build steps are in
[the plan](../plans/2026-10-24-live-100m-run-observability.md).

Amended 2026-10-25: story dashboard, Spark progress exporter and run annotations (see Amendment below).

Amended by [ADR 0024](0024-demo-console.md) (2026-10-27): a read-only role replaces the mounted keys, and console annotations come from the run records.

## Context

The last open part of Phase 8 is the 8.10 demo video: a public, sped-up
recording of a live 100M-event run. The viewer must be ready and rehearsed
before the run starts.

**Viewing today.** Grafana runs only in-cluster in `dev-compute`. It is
reached by `kubectl port-forward -n monitoring svc/grafana 3000:80` and is
destroyed with the cluster (ADR 0016). It cannot be opened before the apply
or after the destroy. The generator starts right after the apply, so there
is no calm window to set it up. The run dashboard
(`observability/grafana/dashboards/spark-on-eks.json`) has 15 panels in five rows (14 on AMP, one on
CloudWatch). It has
no running-executors panel, no node-count panel and no bytes-read-so-far
panel.

**What "Prometheus UI" can honestly mean here.** Prometheus runs in agent
mode (`--agent`). It has no local query store and remote-writes to AMP at a
15 s scrape. AMP has no native UI, and Grafana has no query UI of its own on
AMP. So the views are the agent's Targets page (live scrape health) and
PromQL on AMP in Grafana Explore. Whether the agent-mode web UI serves a
Targets page is **unverified**; build step 6 checks it at $0.

**What ADR 0021 already wants.** ADR 0021 chose a local Docker Compose
Grafana as the dev loop. It requires datasource and dashboard provisioning
to be portable repo files, and it leaves the shared host to Phase 9 (9.1):
"the two ADRs should end with one Grafana, not two." ADR 0016 already names
"the same JSON loads into a local Grafana (`docker run`) pointed at AMP".

**Two blockers found in session (2026-10-22/24).**

- *The data-quality cutoff.* The workgroup `cerberus_platform_dq` has a
  10 GiB cutoff per query. At 137M silver the largest checks scan 7.81 GiB
  and 6.98 GiB, and they grow linearly. At about 237M, after a new 100M
  run, they reach about 13.5 and 12.1 GiB. Both exceed 10 GiB, so the suite
  fails and the collector exits 3. The shared workgroup `cerberus_platform`
  has a 25 GiB cutoff. The dbt merge is about 20.8 GiB at 237M: it passes
  once, but not on the next 100M.
- *No CloudWatch metrics read.* `cerberus-admin` has `aps:QueryMetrics`,
  `GetSeries`, `GetLabels` and `GetMetricMetadata` on the AMP workspace
  (Sid `AmpQuery`), but `aws cloudwatch list-metrics --namespace
  AWS/States` returns AccessDenied, and no `GetMetricData` appears in
  `iam/`. A local Grafana as `cerberus-admin` would show an error on the
  Step Functions panel.

**Pillars that decide.**

- *Operational Excellence:* reuse ADR 0021's dev loop, built earlier, and
  keep it for Phase 10.
- *Reliability:* the viewer is ready before the cluster exists, survives
  the destroy, and can be rehearsed at $0 against real data. The 100M run of
  2026-10-13 (06:35:02Z to 06:47:24Z) is in AMP until about 2027-01-11
  (90-day retention).
- *Cost:* $0 idle.
- *Security:* localhost-only bindings. Static admin keys are mounted into a
  local container, which is accepted for now.

## Options considered

**A. Local Compose Grafana on AMP, plus the native UIs by port-forward.**
Grafana 13.2.3 in Docker Compose on `127.0.0.1:3000`, reading AMP (SigV4) and
CloudWatch with the operator's profile. Provisioning is repo files. A helper
forwards the agent's own UI (`:9090`) and the live Spark driver UI
(`:4040`). The Step Functions console shows the orchestration. Idle cost is
$0; AMP query samples are cents at most. It gives up three things: two Grafanas
exist until 9.1; the admin's static keys are mounted read-only into a
localhost container; and "Prometheus" means the agent's scrape view plus
PromQL on AMP, not a query page.

**B. Use today's in-cluster Grafana only.** No build, $0. It cannot be
opened or rehearsed before the cluster is up, it dies at teardown (no
after-run screens), every dashboard change needs a `dev-compute` apply to
test, and it builds nothing that Phase 9 or 10 keeps.

**C. A wider local stack.** A local Prometheus server, PromLens behind
`aws-sigv4-proxy`, Loki/Tempo, a Kubernetes UI and k9s. A second query path
or store contradicts ADR 0016 (AMP is the single store). Loki and Tempo have
no log or trace producers wired. PromLens's query tree is unreadable at
10-20x speed. A Kubernetes UI repeats what `kubectl` and Grafana already
show. It adds tools without new evidence, and it needs more RAM on a 7 GB
laptop.

**D. A managed viewer.** Amazon Managed Grafana is $9 a month fixed, which
ADR 0016 and ADR 0021 rejected. Grafana Cloud adds a vendor account and an
API key, and is not local. Rejected.

**What a Canadian data/cloud hiring manager weighs.** Real numbers they can
check: executors scaling 1 to 16, Spot nodes 2 to 4, MB/s read, a run time
from Step Functions, cost per million events from Cost Explorer, and data
quality passing. They also value IaC (the video can open on `terraform apply`
creating EKS and end on destroy to $0) and reproducibility (one
`make exercise` command, run records in git). The Spark UI and the
Prometheus Targets page are native tools they recognise. Extra dashboards are
decoration. A recognisable stack used correctly beats a wide one.

## Decision

**Option A.**

- Docker Compose Grafana 13.2.3 with the AMP plugin 3.2.0, bound to
  `127.0.0.1`. It signs in with an admin password from a git-ignored `.env`.
  There is no anonymous access.
- Datasources and dashboards are provisioned from `observability/grafana/`.
  They use the same uids as in-cluster (`amp`, `cloudwatch`), so one
  dashboard JSON works in both.
- A new run dashboard, `cerberus-run-live.json`, with about 7 large panels,
  all real metrics: Spark executors running, nodes by capacity type, active
  tasks, input bytes/s, "input read so far" (the collector's method, the sum
  of per-executor peak `totalInputBytes`, so it matches the run record),
  node CPU busy, and Step Functions executions.
- `make grafana-up` and `make grafana-down`, and `make demo-forward` (agent
  `:9090` and the current Spark driver `:4040`, both on localhost).
- kube-state-metrics exports the node label `eks.amazonaws.com/capacityType`
  (a `dev-compute` change, applied by the next exercise).
- Step Functions is shown in its own console.
- Two prerequisites:
  - The `cerberus_platform_dq` cutoff goes to 20 GiB. It is one line,
    CI-applied, and uses the pattern proven in #103. At about 237M the
    largest check uses about 68% of 20 GiB. Making the checks incremental is
    the better long-term fix, but it changes suite code just before a
    once-only recorded run, so it stays a follow-up.
  - A read-only CloudWatch metrics grant for `cerberus-admin`
    (`cloudwatch:GetMetricData`, `GetMetricStatistics`, `ListMetrics`;
    `Resource "*"`). The user pastes the policy from the root console (the
    7.3 path) and has confirmed they will. Phase 9 (9.1) decides where
    Grafana's CloudWatch data comes from later.
- A dress rehearsal at 1M before the 100M take. The user confirmed it. Its
  cost, about $0.9-1.2, is **unverified**: it is an estimate from the 1M run
  record and the 137M DQ scan of about $0.53.
- Rejected: options B, C and D; PromLens and `aws-sigv4-proxy`; a local
  Prometheus server or remote-read; Loki/Tempo, Kubernetes UIs and k9s.
- **Amends ADR 0016 (Decision, "Viewing: Grafana in-cluster"):** the local
  Grafana becomes the primary viewer. The in-cluster Grafana stays until 9.1 decides whether to remove
  it.
- **Implements ADR 0021's dev loop early.** It does not choose the shared
  host; that stays with 9.1.

**Build steps** (details, checks and the shot table are in
[the plan](../plans/2026-10-24-live-100m-run-observability.md), section 7):

1. This ADR, the plan file and the checkpoint note.
2. DQ cutoff 20 GiB (`terraform/modules/athena/variables.tf`, CI-applied).
3. CloudWatch metrics read for `cerberus-admin` (root-console paste).
4. Local Grafana stack (Compose, provisioning files, make targets).
5. Run dashboard `cerberus-run-live.json`, checked on the 2026-10-13 window.
6. `make demo-forward` and the node label; check the agent-mode UI.
   The 2026-10-25 amendment (below) inserts steps 6a-6f after this step:
   - 6a. Amendment, plan file, Phases.md and the checkpoint note.
   - 6b. Local Spark capture at $0 (`observability/spark_progress/capture.sh`, fixtures).
   - 6c. Exporter (`exporter.py`, pytest) and Terraform in `eks_observability/main.tf`.
   - 6d. Story dashboard `cerberus-run-story.json`, checked on the 2026-10-13 history.
   - 6e. Run annotations (`orchestration/annotate.sh`, `make grafana-token`) and their $0 test.
   - 6f. Runbook input, folded into step 7.
7. Recording runbook, `docs/demo-recording.md`.
8. Dress rehearsal at 1M.
9. The 100M recording run.
10. Edit and publish; link the video in 8.10.

Steps 1-6 cost $0 and come before any cluster. Steps 7-10 keep their
numbers. The 8.11 Well-Architected ADR becomes **ADR 0023**; this ADR takes 0022.

## Consequences

**Good**

- *Reliability:* ready and testable at $0 before any cluster, and the views
  survive teardown.
- *Operational Excellence:* Phase 10 adds its dashboards to the same stack,
  and 9.1 can point any host at the same files.
- *Cost:* $0 idle. Nothing new stands in AWS. A 100M exercise is about $2.50
  (an estimate: $1.78 last time, plus larger DQ and dbt scans) and a
  rehearsal about $1 (unverified, above). With both, the month's forecast
  reaches about $17.2 against a $20 limit. This crosses the 75% ($15) email alert,
  which is an email only. Credits cover it, so net is $0.

**Given up**

- Two Grafanas until 9.1.
- *Security:* static admin keys in a local container (read-only mount,
  localhost). A read-only role (9.2 builds one for the console) could replace them
  through the plugin's assume-role setting, with no dashboard change; 9.1
  decides.
- Datasource auth differs in two places (Terraform values vs a provisioning
  file), a small drift risk.
- No live "events processed" counter exists. The event total comes from the
  collector at the end. (Superseded by the 2026-10-25 amendment below.)
- Cost per million comes a day later (`--cost-only`).

**Laptop load (measured 2026-10-25)**

- *Laptop:* Intel i5-7300HQ (4 cores, 4 threads, up to 3.5 GHz), 7.1 GiB
  RAM (5.1 GiB available with no browser open; desktop, terminal and Claude
  use about 2.0 GiB), 16 GiB swap on NVMe. GPUs: NVIDIA GTX 1050 Ti (driver
  580.178.04) and Intel HD 630. ffmpeg has `h264_nvenc`, `h264_qsv` and
  `h264_vaapi`.
- *Grafana:* `grafana/grafana:13.2.3` with
  `GF_PLUGINS_PREINSTALL=grafana-amazonprometheus-datasource@3.2.0`, on
  `127.0.0.1`, no datasources or dashboards. The plugin directory lists
  `grafana-amazonprometheus-datasource`, so the preinstall works. The image
  is 1.94 GB on disk and is ready in about 2 s. Over about a minute of repeated page and API
  loads (12 `docker stats` samples) it used 346-364 MiB of RAM (slowly
  rising) and 1.7-2.1% of one core. RAM with live AMP queries every 15 s
  is not measured.
- *Encoder:* a 30 s test of 1080x1350 at 30 fps (ffmpeg `testsrc2`). With
  `libx264 veryfast` it used 18.7 CPU-seconds (about 0.6 of a core, about
  14% of the CPU). With `h264_nvenc` it used 3.3 CPU-seconds (about 0.06 of
  a core after the roughly 1.5 CPU-second test source, about 1.5% of the
  CPU). The recording runbook (step 7) sets OBS to NVENC.
- *Estimated total while recording (estimate, not measured):* desktop about
  2.0 GiB (measured) + Firefox with 5 tabs about 1.5-2.5 GiB (guess) + OBS
  with NVENC about 0.3-0.5 GiB (guess) + Grafana about 0.35 GiB (measured,
  no datasources) = about 4.2-5.4 GiB of 7.1 GiB.
- *Conclusion:* a local Grafana does not noticeably slow the laptop. An EC2
  host would move only the Grafana container (about 0.35 GiB), because
  Firefox and OBS stay local. So EC2 is not needed for the recording. A
  hosted public demo stays Phase 9's question (9.1, 9.2).

**Unverified, each checked in a build step**

- The Prometheus 3 agent-mode web UI serves a Targets page (step 6).
- Grafana 13 in a container picks up the mounted `~/.aws` profile through
  the plugin's `default` auth (step 4).
- OBS global hotkeys are limited on Wayland; the runbook avoids depending on
  them (step 8).
- The 1M rehearsal cost (above).
- After 2026-10-30 the ingestion Lambda only no-ops, and the ASL has no
  Choice state on its result, so InvokeIngestion should still succeed. This
  is inferred, not run.

**Follow-ups**

- The shared workgroup is at about 83% of 25 GiB after this run; the next
  100M fails dbt.
- DQ at 20 GiB holds about one more 100M (about 19.2 GiB at 337M).
- Incremental DQ checks.
- A read-only Grafana role (9.2 builds one for the console; 9.1 decides);
  remove the in-cluster Grafana in 9.1.

**Revisit if**

- 9.1 picks a host that cannot read the provisioned files.
- The DQ checks become incremental (then lower the cutoff again).

## Amendment (2026-10-25): story dashboard, Spark progress exporter and run annotations

Status: Accepted (2026-10-25). The plan is
[2026-10-25-run-story-dashboard.md](../plans/2026-10-25-run-story-dashboard.md).
The user accepted it on 2026-10-25 (step 6a).

### Context

- The audience now includes non-engineers (finance, product, leadership).
  They need to read the 100M video without Spark knowledge.
- No records metric exists in AMP. A read-only `label/__name__/values` call
  over 2026-10-13 05:55-06:50Z returned 1,224 names, and none is a Spark
  records metric. The Spark status REST API on the driver's `:4040` is live.
- The bytes proxy overshoots. The silver job read 52,624,362,642 bytes and
  the generator wrote 43,261,265,435 bytes, so bytes read ends near 122%.
  The generator reads 0 bytes. Its commit (`FileFormatWriter` elapsed
  875397 ms, 14.6 minutes with no Spark job running) has no progress
  signal. The cause (S3A rename) is inferred, not verified.
- Step Functions per-integration metrics exist in CloudWatch
  (`ServiceIntegrationsStarted/Succeeded/Failed`) but lag 1-3 minutes
  (unverified). CloudWatch keeps the 2026-10-13 1-minute data only until
  about 2026-10-28.
- The data-quality verdict and the account-wide teardown check live only in
  `orchestration/exercise.sh`.
- Grafana 13.2 offers organization annotations (`POST /api/annotations`), an
  Annotations list panel and annotation display on state timelines.
- The generator wrote 100,002,421 events. Silver added 100,008,511, which
  includes 6,090 Lambda events from `payments/`
  (`observability/scale/runs/exercise-20261013T055859Z.json`).
- Changing the job code or the transform YAML means rebuilding the runner
  image (`orchestration/runner/entrypoint_transform.sh`). That puts the
  once-only run at risk.

### Decision

- **Exporter (R1).** A stdlib-Python exporter in `dev-compute` (namespace
  `monitoring`) reads the Spark status REST API and serves a small fixed set
  of `cerberus_spark_*` series. A new agent scrape job reuses
  `spark_driver_relabel`. It needs no job, YAML or image change. The
  fallback (R4) is a labelled proxy: "Data read so far (GB)" and "Spark
  tasks finished".
- **Story dashboard.** A new `cerberus-run-story.json`, with live colours
  from existing metrics (J1): AMP pod phase and CloudWatch metric math on the
  three integration ARNs. `cerberus-run-live.json` stays the engineers' view.
- **Run annotations (J5).** `exercise.sh` posts annotations to the local
  Grafana for the DQ verdict (from the collector exit code and the run
  record), the account-wide teardown check, and step start and end times
  (apply, generator, Step Functions states from the execution history,
  destroy).
- **J5 is fail-open.** Localhost only, a 3 s timeout, one warning line per
  run, always returns 0, and `--no-annotate` turns it off. It does not change
  the run's success logic.
- **Credentials.** A Grafana service account with the Editor role and a
  30-day token, made by `make grafana-token` and stored in the git-ignored
  `observability/grafana/.env`. `exercise.sh` reads only that key. The admin
  password is not used. Editor as the least allowed role is unverified; step
  6e checks it.
- **Cost tile.** "Cost so far" is a labelled estimate: elapsed x $1.15/h.
  The rate is derived here from the 2026-10-13 run record: ($1.781607 -
  $0.574015) / 1.048 h. The repo does not contain it.
  Erratum (6d, 2026-10-25): the rate is corrected to $1.72/h. The $1.15/h rate
  divided by the 3,773 s exercise time, which includes apply and destroy;
  $1.207592 over 0.704 h of node time gives $1.72/h.
- Rejected: J2 (Grafana Live, memory only) and J3 (ADR 0021's publisher
  built early; Phase 10, and it needs an ADR 0021 change).
- Build steps 6a-6f go between steps 6 and 7. Steps 7-10 keep their numbers.

### Consequences

- The "No live events processed counter" line above is replaced by: a
  live counter from Spark's status API, updated per finished task; none
  during the generator commit; first proven in the 1M rehearsal (step 8).
- The DQ verdict and the clean-up check now appear on Grafana as
  annotations. The terminal and the run record stay authoritative.
- Step Functions steps get exact times without the CloudWatch delay.
- Given up:
  - one more in-cluster component;
  - a small fail-open change to `exercise.sh`;
  - annotations live in the Grafana volume, not in git;
  - an Editor-scoped token on disk (git-ignored, 30-day expiry);
  - the cost tile is an estimate.
- The "extra dashboards are decoration" line in Context is answered: this is
  a front page for another audience, and every number on it is sourced.
- Phase 10.2's publisher may later replace the verdict annotation with
  `cerberus_dq_passed` in AMP, and 10.3 may move the journey to
  `cerberus_step_duration_seconds`.
- With Phase 10's two dashboards, the local stack reaches about five
  dashboards, which is ADR 0021's revisit point.
