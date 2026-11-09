# Plan: live observability for a recorded 100M-event run

_Made by `cerberus-planner` (Opus) on 2026-10-24 for `/decision`. Saved
verbatim; the user's answers to the open questions are at the end._

## 1. Question

How should a live 100M-event run be made visible on Grafana and on Prometheus views, run locally, ready and rehearsed before the run starts, so the 8.10 demo video can be recorded? It is needed now because 8.10's video is the last open part of Phase 8. Also, a new 100M run fails its data-quality suite unless a fix lands first (see Facts).

## 2. Facts

**Viewing today**
- Grafana runs only in-cluster in `dev-compute`. It is reached by `kubectl port-forward -n monitoring svc/grafana 3000:80` and destroyed with the cluster (ADR 0016; `terraform/modules/eks_observability/outputs.tf`). The chart app is 13.2.3, with the AMP plugin `grafana-amazonprometheus-datasource@3.2.0` (`terraform/modules/eks_observability/variables.tf`). The datasources (uid `amp`, uid `cloudwatch`) are inline Terraform values (`main.tf` around L322).
- Prometheus runs in **agent mode** (`--agent`, `main.tf` L233). It has no local query store and remote-writes to AMP at a 15 s scrape. Grafana has no query UI of its own on AMP. AMP has no native UI.
- ADR 0016 already names "the same JSON loads into a local Grafana (`docker run`) pointed at AMP" for viewing history.
- ADR 0021 (Accepted with changes) chose a local Docker Compose Grafana as the dev loop. It requires datasource and dashboard provisioning to be **portable repo files**. It leaves the shared Grafana host to Phase 9 (9.1): "the two ADRs should end with one Grafana, not two."
- `observability/grafana/dashboards/spark-on-eks.json` has 15 panels in five rows (14 on AMP, one on CloudWatch). One, "Step Functions executions", uses CloudWatch. (Corrected in review on 2026-10-24: the first draft said 17 panels, 16 on AMP.) Refresh is 15 s, range `now-1h`. It has no running-executors panel, no node-count panel, and no bytes-read-so-far panel.

**Access**
- `cerberus-admin` has `aps:QueryMetrics`, `GetSeries`, `GetLabels` and `GetMetricMetadata` on the workspace (`iam/cerberus-admin/policies/cerberus-admin-iam-and-governance.json`, Sid `AmpQuery`).
- `cerberus-admin` **cannot read CloudWatch metrics**. Measured in session: `aws cloudwatch list-metrics --namespace AWS/States` returns AccessDenied, and no `GetMetricData` appears in `iam/`. A local Grafana as `cerberus-admin` will therefore show an error on the Step Functions panel until this changes.
- The local `~/.aws` profile `cerberus-admin` uses static keys (read in session).

**Data and tools**
- AMP retention is 90 days (`terraform/modules/prometheus_workspace/variables.tf`). The 100M run's window, 2026-10-13T06:35:02Z to 06:47:24Z (`observability/scale/runs/exercise-20261013T055859Z.json`), is still in AMP until about 2027-01-11. Its record holds `spark_input_bytes` 52,624,362,642 and peak series 10,370. Dashboards can be checked against real 100M data for $0.
- `orchestration/exercise.sh` runs apply → `update-kubeconfig` → node wait → generator → `start-execution` → poll → collect → destroy, with no pause. `--name PREFIX` sets the execution name. The 8.9 run used `make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2"` (`docs/scale-metrics.md` L372).
- The generator SparkApplication has the same PrometheusServlet config (`transform/spark/spark-application-generate.yaml` L48–54), so the generator phase also shows on the dashboard.
- Last 100M run: generator 1,325 s, run 742 s (RunTransform 511.6 s), cluster up 3,773 s, 16 executors asked, Spot group 2→4 nodes, whole exercise $1.78 (run record; checkpoint 8.9).
- Local machine (session): Ubuntu, GNOME on Wayland, 4 cores, 7 GB RAM. Docker 29.9.1 and Compose v5.6.0 are installed. Image `prom/prometheus:v3.15.0` is already pulled. `grafana/grafana:13.2.3` exists on Docker Hub (checked with `docker manifest inspect`). OBS 32.1.0 ships `clock-source.lua` and `countdown.lua`. ffmpeg 8.0.1 has `drawtext`, `setpts`, `crop` and `scale`.

**Measured in session (2026-10-22/24)**
- Budget: $11.46 gross actual (net $0 after credits), forecast $13.71, limit $20. Alerts are at 75%/100% actual and 100% forecast.
- Workgroup `cerberus_platform_dq` cutoff is 10 GiB. At 137M silver the largest checks scan 7.81 GiB and 6.98 GiB, and they grow linearly. At about 237M after a new 100M they reach about 13.5 and 12.1 GiB. **Both exceed 10 GiB**, so the suite fails and the collector exits 3.
- Shared `cerberus_platform` cutoff is 25 GiB. The dbt merge is about 20.8 GiB at 237M: it passes once, but not on the next 100M.
- `cerberus-admin` can read DQ-workgroup queries with `get-query-execution`.

**Unverified (each is checked in a build step)**
- The Prometheus 3 agent-mode web UI serves the Targets, Service discovery and Status pages, but no query page.
- Grafana 13 in a container picks up the mounted `~/.aws` profile through the plugin's `default` auth.
- `GF_PLUGINS_PREINSTALL` installs the plugin.
- The Spark Operator creates a `<app>-ui-svc` (the plan uses the driver pod, so it does not depend on this).
- OBS global hotkeys are limited on Wayland (the plan avoids depending on them).
- A 1M dress-rehearsal exercise costs about $0.9–1.2 (an estimate from the 1M run record and the 137M DQ scan of ~$0.53).

**Lambda retire date**
- The ingestion Lambda's 2026-10-30 retire date only makes it no-op (`ingestion/lambda/handler.py` returns `{"status": "retired"}`). The ASL has no Choice state on the result (`orchestration/state_machine.asl.json.tftpl`), so InvokeIngestion should still succeed after that date. This is inferred, not run.

## 3. Constraints

- $0 idle. Nothing new stands in AWS. The local stack runs only when started.
- `dev-compute` destroy leaves nothing. Any `dev-compute` change rides the next human-run exercise apply.
- CI applies `dev-standing` only. IAM changes to `cerberus-admin` are root-console pastes (the 7.3 path).
- Must fit ADR 0016 (AMP is the single store; agent mode; no Managed Grafana).
- Must fit ADR 0021 (local Compose Grafana is the dev loop; provisioning is portable files; Phase 9 picks the shared host; at most two Phase 10 dashboards).
- Must not take Phase 9.1's host decision.
- Budget: a 100M exercise is about $2.50, taking the month to about $16.2. With a ~$1 rehearsal the month reaches about $17.2. This crosses the 75% ($15) email alert, which is an email only. Credits cover it, so net is $0.
- Laptop limits: 4 cores and 7 GB shared by OBS, Firefox and Grafana.

## 4. Options

**A. Local Compose Grafana on AMP, plus the native UIs by port-forward. Recommended.**
- What it is:
  - Grafana 13.2.3 in Docker Compose on `127.0.0.1:3000`, reading AMP (SigV4) and CloudWatch with the operator's profile.
  - Provisioning lives in repo files, as ADR 0021 requires.
  - A port-forward helper for the agent's own UI (`:9090`, the Targets page) and the live Spark driver UI (`:4040`).
  - The Step Functions console shows the orchestration.
- Cost: idle $0. Per use, AMP query samples are cents at most; the dashboard re-reads every 15 s.
- Effort: about five small PRs.
- What it gives up:
  - Two Grafanas exist until 9.1 (in-cluster and local).
  - The admin's static keys are mounted read-only into a localhost container.
  - "Prometheus" means the agent's scrape view plus PromQL on AMP, not a Prometheus query page.
- Pillars:
  - **Operational Excellence**: it is ADR 0021's dev loop, built earlier and kept by Phase 10.
  - **Reliability**: it is ready before the cluster exists, survives the destroy, and can be rehearsed at $0 against the 2026-10-13 data.
  - **Cost**: $0.

**B. Use today's in-cluster Grafana only.**
- What it is: port-forward after the apply; no build.
- Cost: $0.
- What it gives up:
  - It cannot be opened or rehearsed before the cluster is up.
  - It dies at teardown, so there are no after-run screens.
  - Every dashboard change needs a `dev-compute` apply to test.
  - The generator starts right after the apply, so there is no calm window to set up.
  - It also builds nothing that Phase 9 or 10 keeps.

**C. A wider local stack.**
- What it is: a local Prometheus server, PromLens behind `aws-sigv4-proxy`, Loki/Tempo, Headlamp or the Kubernetes dashboard, and k9s.
- Cost: $0 idle, but more RAM on a 7 GB laptop.
- What it gives up:
  - A second query path or store contradicts ADR 0016 (AMP is the single store).
  - Loki and Tempo have no log or trace producers wired.
  - PromLens's query tree is unreadable at 10–20× speed.
  - A Kubernetes UI repeats what `kubectl` and Grafana already show.
  - It adds tools without new evidence, which is decoration.

**D. Managed viewer (Amazon Managed Grafana, or Grafana Cloud free tier).**
- Amazon Managed Grafana is $9/month fixed, rejected by ADR 0016 and ADR 0021.
- Grafana Cloud adds a vendor account and an API key, and is not local.
- Rejected.

**What a Canadian data/cloud hiring manager weighs.**
- They value real numbers they can check: executors scaling 1→16, Spot nodes 2→4, MB/s read, a run time from Step Functions, cost per million events from Cost Explorer, and data quality passing.
- They also value IaC (the video can open on `terraform apply` creating EKS and end on destroy to $0) and reproducibility (one `make exercise` command, run records in git).
- The Spark UI and the Prometheus Targets page are native tools they recognise. Extra dashboards are decoration.
- A recognisable stack used correctly beats a wide one.

## 5. Recommendation

**Choose Option A, with three additions:**

1. **One focused run dashboard, sized for a 4:5 frame.** About 7 large panels, all real metrics:
   - Spark executors running.
   - Nodes by capacity type, so On-Demand vs Spot shows.
   - Active tasks.
   - Input bytes/s.
   - "Input read so far" for the job. It uses the collector's own method (sum of per-executor peak `totalInputBytes`), so it matches the run record (52.6 GB at 100M).
   - Node CPU busy.
   - Step Functions executions.
2. **The DQ cutoff raised to 20 GiB (option A of the two raised).**
   - It is one line, CI-applied, and uses the pattern already proven in #103.
   - At about 237M the largest check uses about 68% of 20 GiB.
   - Making the checks incremental (option B) is the right long-term fix. It changes suite code just before a once-only recorded run, so it stays a backlog follow-up.
   - 20 GiB holds about one more 100M step (about 19.2 GiB at 337M). Record that limit.
3. **A read-only CloudWatch metrics grant for `cerberus-admin`** (`cloudwatch:GetMetricData`, `GetMetricStatistics`, `ListMetrics`; `Resource "*"`, read-only).
   - Without it the dashboard's Step Functions panel shows an error locally.
   - Phase 9's command set reads the same data, so the grant is not thrown away.

Why A wins:
- It is the only option that is ready and rehearsed before any cost.
- It survives teardown.
- It builds what ADR 0021 and Phase 9 keep (portable provisioning, a local dev loop).
- It shows only real metrics.
- It costs nothing idle.
- The cost is two Grafanas until 9.1, which 9.1 already must settle.

## 6. ADR outline

**Number:** next free is **0022** (`ls docs/adr` ends at 0021). 8.11's Well-Architected ADR shifts from the pencilled 0022 to **0023**. Update checkpoint.md "Next up" item 2.

**Title:** "22. Live observability for a recorded run: local Grafana on AMP, native Prometheus and Spark UIs by port-forward"

**Status:** Proposed.

**Context**
- The goal: a public, sped-up recording of a live 100M run for 8.10.
- Today's viewer appears only after the apply and dies at destroy (ADR 0016).
- ADR 0021 already wants a portable local Compose Grafana.
- What "Prometheus UI" can honestly mean here: an agent has no query page and AMP has none. So the views are the agent's Targets page (live scrape health) and PromQL on AMP in Grafana Explore.
- What a reviewer finds credible vs decoration (section 4).
- The two blockers found in session:
  - The DQ cutoff, with the measured numbers and the projection.
  - `cerberus-admin` has no CloudWatch metrics read (measured AccessDenied).
- Pillars that decide:
  - Operational Excellence: reuse ADR 0021's dev loop.
  - Reliability: ready before cost, survives teardown, rehearsable on real data.
  - Cost: $0 idle.
  - Security: localhost-only bindings; mounted admin keys accepted for now.

**Decision**
- Docker Compose Grafana 13.2.3 with the AMP plugin 3.2.0, bound to `127.0.0.1`. It signs in with an admin password from a git-ignored `.env`. There is no anonymous access.
- Datasources and dashboards are provisioned from `observability/grafana/`. They use the same uids as in-cluster (`amp`, `cloudwatch`), so one dashboard JSON works in both.
- A new run dashboard, `cerberus-run-live.json`.
- `make grafana-up` / `grafana-down`, and `make demo-forward` (agent `:9090`, current Spark driver `:4040`, both on localhost).
- kube-state-metrics exports the node label `eks.amazonaws.com/capacityType`.
- Step Functions is shown in its own console.
- Prerequisites:
  - DQ workgroup cutoff 20 GiB.
  - A CloudWatch metrics read grant for `cerberus-admin`.
- Rejected:
  - Options B, C and D.
  - PromLens and `aws-sigv4-proxy`.
  - A local Prometheus server or remote-read.
  - Loki/Tempo, Kubernetes UIs, k9s.
- **Amends ADR 0016 (Viewing):** the local Grafana becomes the primary viewer. The in-cluster Grafana stays until 9.1 decides whether to remove it.
- **Implements ADR 0021's dev loop early;** does not choose the shared host.

**Consequences**
- Good:
  - Ready and testable at $0 before any cluster.
  - Views survive teardown.
  - Phase 10 adds its dashboards to the same stack.
  - 9.1 can point any host at the same files.
- Given up:
  - Two Grafanas until 9.1.
  - Static admin keys in a local container (read-only mount, localhost). 9.2's read-only role replaces them through the plugin's assume-role setting, with no dashboard change.
  - Datasource auth differs in two places (Terraform values vs a provisioning file), a small drift risk.
  - No live "events processed" counter exists. The event total comes from the collector at the end.
  - Cost per million comes a day later (`--cost-only`).
- Follow-ups:
  - Shared workgroup at about 83% of 25 GiB after this run; the next 100M fails dbt.
  - DQ at 20 GiB holds about one more 100M.
  - Incremental DQ checks.
- Revisit if:
  - 9.1 picks a host that cannot read the files.
  - The DQ checks become incremental (then lower the cutoff again).

## 7. Build steps

All steps are under **Phases.md 8.10**. Proposed Phases.md text for 8.10:

> 8.10 Results write-up + demo video. ADR 0022 (live observability: local Grafana, native Prometheus/Spark UIs); DQ cutoff 20 GiB; dress rehearsal at 1M; live 100M run recorded

Leave 8.11 as is (now ADR 0023). Steps 1–6 cost $0 and come before any cluster.

**1. ADR 0022 (Proposed), plan file, checkpoint note.**
- One PR: the ADR, this plan, and checkpoint "Next up" (8.11 → ADR 0023).
- Verify: the user accepts the ADR, and the status flips to Accepted in the same PR or a follow-up.

**2. DQ cutoff 20 GiB.**
- `terraform/modules/athena/variables.tf`: set `dq_bytes_scanned_cutoff_bytes` default `21474836480`.
- Update the description with the measured 7.81 / 6.98 GiB at 137M, the about 13.5 / 12.1 GiB projection at 237M, and the about 19.2 GiB limit at 337M.
- CI applies it on merge.
- Verify: `aws athena get-work-group --work-group cerberus_platform_dq --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'` returns 21474836480.

**3. CloudWatch metrics read for `cerberus-admin`.**
- Add a Sid with `cloudwatch:GetMetricData`, `GetMetricStatistics` and `ListMetrics` on `*` to `iam/cerberus-admin/policies/cerberus-admin-orchestration.json`.
- The user pastes the new policy version from the root console.
- Verify:
  - `aws cloudwatch list-metrics --namespace AWS/States --max-items 1` succeeds.
  - Check the policy stays under the 6,144-character managed-policy limit before the paste.

**4. Local Grafana stack.**
- Add:
  - `observability/grafana/compose.yaml` (`grafana/grafana:13.2.3`, `127.0.0.1:3000`, `~/.aws` mounted read-only, `AWS_PROFILE=cerberus-admin`, `AWS_SDK_LOAD_CONFIG`/`AWS_SHARED_CREDENTIALS_FILE` set to the mount, plugin pinned 3.2.0).
  - `observability/grafana/provisioning/datasources/local.yaml` (uids `amp`, `cloudwatch`, region us-east-1, `sigv4Service: aps`).
  - `observability/grafana/provisioning/dashboards/cerberus.yaml`, pointing at the existing `dashboards/` directory.
  - `.env.example`.
  - Make targets `grafana-up` / `grafana-down`.
- Do not touch the in-cluster Terraform.
- Verify:
  - Both datasources pass "Save & test" (AMP OK, CloudWatch metrics OK).
  - `spark-on-eks.json` set to 2026-10-13 06:10–06:50Z shows data in every panel, including Step Functions.
  - `docker stats` shows Grafana well under 500 MiB.

**5. Run dashboard `observability/grafana/dashboards/cerberus-run-live.json`.**
- Large panels, 15 s refresh, range `now-30m`, laid out for an about 864×1080 browser window.
- PromQL is checked against the 2026-10-13 window before commit:
  - Executors: `count by (spark_app) (metrics_executor_activeTasks{executor_id!="driver"})`.
  - Nodes: `count by (label_eks_amazonaws_com_capacity_type) (kube_node_labels)`. It returns data only after step 6's label change, so for the history check use `count(kube_node_info)`.
  - Executor pods: `count(kube_pod_info{namespace="spark-jobs",pod=~".*-exec-.*"})`.
  - Input read so far: per-executor peak of `metrics_executor_totalInputBytes_bytes_total`, summed.
  - Input bytes/s, active tasks, node CPU busy: as in today's dashboard.
  - Step Functions panel (CloudWatch).
- Also save 2–3 Explore queries as links in the runbook. Explore is the "PromQL on AMP" screen.
- Verify on the 2026-10-13 window:
  - Peak executors is 16.
  - Peak nodes is 5 (1 system + 4 Spot).
  - Input read for `cerberus-promote-payments` is about 52.6 GB, matching `spark_input_bytes` 52,624,362,642 in the run record.
  - Panels are readable at 4:5.

**6. Native UIs and a node label.**
- Add `observability/demo/forward.sh` and `make demo-forward`:
  - Wait for `svc/prometheus-server` in `monitoring`, then port-forward `9090:80`.
  - Loop: find the Running pod with `spark-role=driver` in `spark-jobs`, port-forward `4040:4040`, and re-attach when the driver changes (generator, then silver job).
  - Bind to localhost only; exit cleanly on Ctrl-C.
- In `terraform/modules/eks_observability/main.tf`, set the kube-state-metrics subchart `metricLabelsAllowlist` for nodes to `[eks.amazonaws.com/capacityType]` (dev-compute; applied by the next exercise).
- Verify:
  - `shellcheck` passes.
  - `terraform validate` passes.
  - `docker run --rm -p 127.0.0.1:9090:9090 prom/prometheus:v3.15.0 --agent --config.file=/etc/prometheus/prometheus.yml` shows which pages agent mode serves. This settles the unverified UI claim at $0. If there is no Targets page, drop that screen from the runbook.

**7. Recording runbook.**
- New `docs/demo-recording.md` (the user asked for it). Content: setup, then the shot table below, then post-production.
- Setup before `make exercise`:
  - `make grafana-up`, then sign in.
  - Run `make exercise-check`.
  - Close other apps (7 GB RAM).
  - Use one Firefox window sized about 864×1080 with fixed tabs:
    1. Step Functions state machines: `https://us-east-1.console.aws.amazon.com/states/home?region=us-east-1#/statemachines`
    2. Grafana `cerberus-run-live`
    3. Grafana Explore (PromQL on AMP)
    4. `http://localhost:9090/targets`
    5. `http://localhost:4040`
  - Switch with Ctrl+1..5. This avoids OBS scene hotkeys, which may not work globally on Wayland (unverified).
  - OBS canvas 1080×1350 at 30 fps. Browser capture (PipeWire) on the top about 1080×1080. A terminal strip at the bottom shows the `exercise.sh` log, plus `watch -n5 kubectl get nodes -L eks.amazonaws.com/capacityType` once the cluster is up.
  - Approve the portal permission prompts in the rehearsal, not on the day.
- Shot order (real time; dwell 2–3 min per screen so each lasts 6–9 s at 20×):

| When (terminal cue) | Screen | What it proves |
|---|---|---|
| `make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2 --name demo-100m"` starts | terminal (Terraform apply) | IaC: EKS from zero |
| after `kubectl wait` passes | run `make demo-forward` in a second terminal; tab 4 Targets | Prometheus scraping driver, operator, nodes |
| `generator: 100000000 events` | tab 2, then tab 5 (Spark UI Jobs) | 8 executors writing 100M events |
| `starting execution demo-100m-…` | tab 1: open the execution, Graph view | orchestration starts |
| RunTransform running | tab 2 (executors → 16, Spot nodes 2→4, input MB/s), tab 5 (Executors tab), tab 3 (one PromQL query) | autoscaling, Spot, throughput |
| RunDbt, RunServingQuery | tab 1 | dbt and Athena steps |
| `execution SUCCEEDED` | tab 1 (all green), then terminal (collector, data quality passed) | correctness |
| destroy and account check finish | terminal | $0 after |

- Crop out the AWS console's top bar, which shows the account.
- Post-production:
  - First add the elapsed real time with `drawtext=text='%{pts\:hms}'` on the raw file.
  - Cut, then speed up each segment with `setpts` (about 30× for the apply and generator, about 15× for the run).
  - Scale or crop to 1080×1350, aiming for 60–90 s.
  - End card: events, run time and data quality from the run record. Add cost per million only after `--cost-only` the next day.
- Verify: the runbook is followed end to end in step 8.

**Erratum (7, 2026-10-26)**, from writing `docs/demo-recording.md`: (a) the only active screen is 1920x1080, so a 1080x1350 viewport needs the monitor in portrait, with Firefox `layout.css.devPixelsPerPx` = 1.25 (Firefox has no 125% zoom step); (b) tabs are 1 Step Functions, 2 story, 3 `cerberus-run-live`, 4 Explore, 5 Targets, 6 Spark UI; (c) the terminal strip becomes a separate OBS scene that shows a masked `tail` of the log, never `make exercise` itself, which prints the account ID; (d) speeds are per segment (60x apply and destroy, 15x generator write, about 30x commit, about 10x RunTransform), not a flat 30x/15x; (e) the rehearsal uses the take's flags (`--generator-executors 8 --executor-nodes 2`); (f) the video is the live run only.

**8. Dress rehearsal at 1M** (about $0.9–1.2, an estimate).
- Command: `make exercise ARGS="--yes --generate 1000000 --name rehearsal"`, recorded with OBS per the runbook.
- Verify:
  - Every tab shows live data.
  - The capacityType label appears.
  - Both port-forwards attach, and 4040 re-attaches for the silver job.
  - OBS stats show about 0 skipped frames.
  - DQ passes and the teardown check is clean.
  - A 10-second ffmpeg pipeline test produces a 1080×1350 file.
- Fix any finding in a small PR before step 9. Commit the run record as usual.

**9. The 100M recording run.**
- Same command as the runbook's first row.
- Verify:
  - SUCCEEDED.
  - DQ passed (largest check under 20 GiB; record the bytes per check with `get-query-execution`).
  - Teardown is clean.
  - The run record is committed in a PR like #98.
  - Run `--cost-only` the next day.
  - Record the dbt merge bytes against the 25 GiB cutoff.

**10. Edit and publish.**
- Produce the final cut.
- Link it in 8.10's section in #107 and check off 8.10.
- Mark #107 ready and merge with `--merge`.
- Add the follow-ups to checkpoint "Later":
  - Shared workgroup headroom.
  - DQ 20 GiB limit.
  - Incremental DQ checks.
  - Read-only Grafana role in 9.2.
  - Remove the in-cluster Grafana in 9.1.

## 8. Open questions for the user

1. **Dress rehearsal at 1M (about $1, estimated), or a $0 rehearsal only?** The $0 option checks dashboards against the 2026-10-13 data plus the local agent-mode check. The recommendation is the 1M rehearsal. The 100M take costs about $2.50 and about 35 minutes, and the live-only parts (port-forwards, node label, OBS on Wayland, Spark UI re-attach) cannot be checked any other way.
2. **Can you do the root-console policy paste for CloudWatch read (step 3)?** If not, drop the Step Functions panel from the local dashboards and rely on the Step Functions console tab. The rest of the plan is unchanged.

## User answers (2026-10-24)

1. **1M dress rehearsal:** yes (the recommended option).
2. **Root-console paste for CloudWatch read:** yes, the user will paste it (the recommended option).
