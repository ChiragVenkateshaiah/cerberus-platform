# Recording runbook: the live 100M run (Phase 8.10)

Purpose: record the LinkedIn video of one real 100M-event run, from an empty
account to an empty account. This is step 7 of the ADR 0022 build steps
([ADR 0022](adr/0022-live-observability-for-a-recorded-run.md), "Build steps").
The runbook feeds step 8 (the 10M dress rehearsal) and step 9 (the 100M take);
step 10 is the edit and publish. The plan behind it is
[2026-10-26-recording-runbook.md](plans/2026-10-26-recording-runbook.md).
The 2026-11-07 revision (10M rehearsal, one landscape 1920x1080 screen, the
GNOME screen recorder, a time-lapse edit, the Databricks post) follows the
ADR 0022 amendment of 2026-11-07 and the plan
[2026-11-07-runbook-landscape.md](plans/2026-11-07-runbook-landscape.md).

Status on 2026-11-08: the 10M rehearsal ran on 2026-11-07
(`rehearsal-20261107T081206Z`). The dashboard fixes from its replay and from
the 1M check run (section 7, "1M check run") are merged (PRs #133 and #134),
and the runbook follows them
([2026-11-08-runbook-main-sync.md](plans/2026-11-08-runbook-main-sync.md)).
Next: pre-flight, then the 100M take.

Order: this runbook merged, the $0 recorder pre-test and dashboard look
review (section 4), the dashboard-polish PR merged (a separate PR, not part of
this one), pre-flight, the 10M rehearsal (section 7), fix what it finds,
pre-flight again, then the 100M take. The user runs every command that changes
AWS. Both runs are recorded whole, in one file each, from the first Enter to
the `after destroy:` line; the edit speeds up the quiet parts (section 6).

Conventions: "estimate" marks a number that is a guess or a projection;
"unverified" marks a claim nobody has run or checked yet. Third-party figures
carry their source. Run every command from the repo root.

> **Commands that change AWS.** Only these three, and only the user runs them.
>
> - `make exercise ARGS="..."` (the 10M rehearsal in section 7, the take in section 5)
> - `make compute-destroy` (the failure path only, section 8)
> - `aws stepfunctions stop-execution --execution-arn arn:aws:states:us-east-1:<account>:execution:cerberus-platform-orchestration:<execution name>`
>   (abort after `starting execution` only, off camera, section 8; the state
>   machine name is `cerberus-platform-orchestration`, exercise.sh L65)
>
> Everything else in this file is read-only or local. One exception to watch:
> the abort is `tmux send-keys -t cerberus-run C-c`. It is a local command, but
> it makes `make exercise` start the teardown (section 8).

## 1. Timeline at a glance

All numbers are from the 2026-10-13 100M run: log
`observability/scale/exercises/exercise-20261013T055859Z.log` (git-ignored,
local only) and run record `observability/scale/runs/exercise-20261013T055859Z.json`.

| Phase | Real time | Source |
|---|---|---|
| Apply (EKS, Spark, observability) | 793 s | log L229 `apply took 793s` |
| Generator, whole step | 1,335 s | log L368 `generator took 1335s` |
| ... map stage (8 tasks) | about 183 s | plan 2026-10-25 section 2 (182.6 s) |
| ... write stage (328 tasks) | about 192 s | plan 2026-10-25 section 2 (06:16:43 to 06:19:55) |
| ... commit, no Spark job running | 875 s | plan 2026-10-25 section 2 (`Elapsed time: 875397 ms`) |
| ... count pass | 17 s | plan 2026-10-25 section 2 |
| Step Functions execution | 746 s | log L370 `execution SUCCEEDED after 746s` |
| ... InvokeIngestion | 4.2 s | run record `states[]` |
| ... RunTransform | 511.6 s | run record `states[]` |
| ... RunDbt | 167.9 s | run record `states[]` |
| ... RunServingQuery | 58.3 s | run record `states[]` |
| Collector (data quality) | about 62 s | log L374 to L409 (06:47:55Z to 06:48:57Z) |
| Metrics flush wait | 60 s | `FLUSH_SECONDS` default, exercise.sh L73-76 |
| Destroy | 732 s | log L3890 `destroy took 732s` |
| Cluster up in total | 3,773 s (about 63 min) | log L3892 |

The nearest real reference for the 10M rehearsal is the 9M run
`exercise-20261012T111304Z` (log `observability/scale/exercises/exercise-20261012T111304Z.log`,
run record `observability/scale/runs/exercise-20261012T111304Z.json`). It used
2 generator executors and 1 Spot node, and silver held about 19M events before
it. It does not use the take's flags (8 executors, 2 nodes).

| Phase | 9M reference | 10M rehearsal (2026-11-07) |
|---|---|---|
| Apply | 951 s (log L232) | 905 s (log L263) |
| Generator, whole step | 243 s (log L277) | 235 s (log L309) |
| Step Functions execution | 506 s (log L279) | 461 s (log L311) |
| ... states | Ingest 3.9 s, Transform 295.7 s, dbt 143.5 s, Serve 60.3 s (run record `states[]`) | Ingest 1.3 s, Transform 252.9 s, dbt 137.1 s, Serve 59.3 s (run record `states[]`) |
| Collector | | 78 s (log L315-L350) |
| Metrics flush wait | | 60 s (log L351-L352; `FLUSH_SECONDS` default) |
| Destroy | 694 s (log L3605) | 818 s (log L6290) |
| Cluster up in total | 2,549 s (log L3607) | 2,605 s (log L6292) |

The 10M column is measured; check 19 is done. The projection it replaced is in
the plan's section 7
([2026-11-07-runbook-landscape.md](plans/2026-11-07-runbook-landscape.md)).

The generator step is 1,335 s, but the map, write and commit parts add up to
about 1,250 s. The rest (about 85 s, estimate: 1,335 minus 375 minus 875) is
pod start-up, the manifest and the 17 s count pass. The edit cuts or folds it.

## 2. Pre-flight (read-only, off camera, at most 1 hour before)

Run the checks for the rehearsal and again for the take. Nothing here changes AWS.

1. **Shell environment.** In every shell you use (the hidden `cerberus-run`
   session and both panes of `cerberus-view`, item 11 and section 5):

   ```
   export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1
   ```

   The Makefile defaults the profile (Makefile L10-11) and `exercise.sh`
   sets both itself (L62-64), but `make demo-forward` runs `kubectl`, whose
   token helper reads them from the environment.
2. **Grafana.** `make grafana-up`, then sign in once in the recording
   browser profile (section 3), off camera.
3. **Annotation token.** Run `make grafana-token` the day before the
   rehearsal and again the day before the take. It deletes the old tokens of
   the service account and makes one with a 30-day expiry
   (`observability/grafana/token.sh` L17, L45-52). Check that the token works
   without showing it:

   ```
   bash -c 'source orchestration/annotate.sh; annotate_http GET "/api/annotations?limit=1"; echo "token ok: $ANNOTATE_OK"'
   ```

   Sourcing only defines functions: the CLI block runs only when the file is
   executed (annotate.sh L367), and `annotate_init` is not needed for a GET.
   Use `bash -c`, because the file reads `BASH_SOURCE`. Expected: `token ok: true`.
   Tested here only for the failure path (no token file): it prints the
   `annotation skipped (no token ...)` line and `token ok: false`. The
   success path needs a live Grafana and a token (unverified). To see the
   expiry date, open Administration, Service accounts, `cerberus-exercise`,
   off camera.
4. **Preflight of the exercise.** `make exercise-check` (exercise.sh
   `preflight`, L108; the `--check` branch is L238-241). It is read-only:
   identity, no EKS cluster, empty `dev-compute` state, no running execution.
   Run it in the hidden session (item 11), because it prints the account ID.
5. **Athena headroom.**

   ```
   aws athena get-work-group --work-group cerberus_platform --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'
   aws athena get-work-group --work-group cerberus_platform_dq --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'
   ```

   Expected: `26843545600` (25 GiB) and `21474836480` (20 GiB); the defaults are in
   `terraform/modules/athena/variables.tf` L15 and L21. Silver holds
   149,119,415 events after the 1M check run
   (`rehearsal-1m-20261108T060517Z.json`, `.silver.events`). After the take it
   holds about 249.1M (estimate: plus 100,008,511, the gain of the 2026-10-13
   run). At that size the dbt merge is about 21.9 GiB (about 87.5% of 25 GiB)
   and the largest data quality check about 14.2 GiB (about 71% of 20 GiB)
   (plan 2026-11-07-dashboard-polish, section 10). Both are linear projections
   from ADR 0022 L46-51 (20.8 GiB and 13.5 GiB at 237M, scaled by silver
   over 237M). One take fits; a second 100M does not (section 8, "Retake
   rule"). The dbt merge is the binding limit: silver must stay at or below
   about 184.8M before the take, which leaves about 35.7M of room (184.8M minus
   149.1M; estimate). The margin is thin: dbt fails if the real growth is 14%
   above linear (25 / 21.9 = 1.14), and the data
   quality scan once outran its projection (105.9 GB against 76 GB,
   checkpoint L195-196). Before the take, re-project with the rehearsal record's
   `states[RunDbt].athena.bytes_scanned`: it is the sum of 33 queries, so it is
   an upper bound on the merge (the largest single query is not recorded).
6. **CloudWatch read.** `aws cloudwatch list-metrics --namespace AWS/States --max-items 1`
   must return a result, not AccessDenied.
7. **Read-only plan of `dev-compute`**, for the rehearsal and again before
   the take:

   ```
   terraform -chdir=terraform/envs/dev-compute plan -input=false -lock=false -var executor_nodes=2
   ```

   Expect "0 to change, 0 to destroy". The adds include
   `module.eks_observability.kubernetes_deployment_v1.spark_progress`
   (`eks_observability/main.tf` L350) and the node label allowlist
   (`metricLabelsAllowlist`, same file L300). Do not save the plan: an EKS
   token in a saved plan expires after about 15 minutes (exercise.sh L262-263).
   Not run for this runbook (it needs AWS credentials and the EKS provider);
   unverified.
8. **Cost.** Read month-to-date and the forecast in the Budgets console
   (`My Monthly Cost Budget`, $20; docs/plan.md L682). It is free. Do not use
   `aws ce get-cost-and-usage`: each call costs $0.01. Estimates: the 10M
   rehearsal about $1.0-1.4 and the take about $2.1-2.5 (the arithmetic is in
   plan 2026-11-07 section 7; ADR 0022 keeps "about $2.50" for the take). On
   2026-11-07 the Budgets console showed November actual $1.15 and a forecast
   of $6.93; after both runs about $10-11 (estimate), below the $15 (75%)
   alert.
9. **Ingestion Lambda (rehearsal watch item).** The Lambda retired on
   2026-10-30: the default in `terraform/modules/lambda_ingestion/variables.tf`
   L14, and `ingestion/lambda/handler.py` L58-67 returns `{"status": "retired"}`
   and writes nothing. The state machine has no Choice on the result
   (`orchestration/state_machine.asl.json.tftpl` L5-13), so `InvokeIngestion`
   should still succeed. Confirmed on 2026-11-07 and 2026-11-08:
   `InvokeIngestion` succeeded (1.3 s and 1.1 s), and the silver gain equalled
   `events=` exactly (9,999,709 and 999,846; the two run records). Watch it
   again in the take: `InvokeIngestion` SUCCEEDED; `RunTransform` reads only `payments_bulk/`
   (`read_bronze` skips a prefix with no new files,
   `transform/spark/promote_payments_spark.py` L240-245); and the silver gain
   equals the generator's `events=` exactly (the pass rule of check 2). If
   `InvokeIngestion` fails, do not take; re-plan.
10. **Laptop and disk.** The lid is closed and the BenQ is the only screen
    (section 3). GNOME Do Not Disturb on; Settings, Power: Screen Blank
    "Never" and Automatic Suspend off; close other apps (the 2026-10-25 memory
    estimate of ADR 0022 L224-227 no longer applies; the
    recorder load is measured in the pre-test, section 4). The recorder saves
    to `~/Videos/Screencasts/`; after the stop, move the file to
    `~/Videos/cerberus-8-10/`, outside the repo (it exists and is empty on
    2026-11-07). Check free disk with `df -h ~/Videos` (169G free on
    2026-11-07). The raw file is about 0.95 Mbit/s, so about 450 MB for 63
    minutes (estimate, from the 418 s file of 2026-10-06).
11. **Hidden run session.** `make exercise` runs in a detached `tmux` session
    that is never on screen. Off camera, before recording:

    ```
    tmux new-session -d -s cerberus-run -c /home/chirag/projects/cerberus
    ```

    Never attach to it while recording. It survives a closed terminal: the
    script traps only INT and TERM (exercise.sh L259-260), so a SIGHUP from a
    closed terminal could otherwise end the run before the teardown. Run the
    preflight there, off camera (it prints the identity, which includes the
    account ID):

    ```
    tmux send-keys -t cerberus-run 'make exercise-check' Enter
    tmux attach -t cerberus-run     # read the result, then detach with Ctrl-b d
    ```
12. **Cost tile, Athena part.** "Cost so far (estimate)" reads the Athena
    bytes with a CloudWatch `SEARCH` expression (`cerberus-run-story.json`,
    panel 9). `SEARCH` finds only metrics that had data in the last 14 days,
    and a metric new to the index can take about 15 minutes to appear. After
    a pause of more than 14 days, the first run shows $0 for Athena until its
    first query lands; this is expected, and the server part counts from the
    start. The final screenshot (section 10) is made later and includes it.
    The last queries ran on 2026-11-08, so a take before about 2026-11-22 is
    not affected. Source: plan 2026-11-07-dashboard-polish, section 13.

## 3. Screens and browser

**Display.** The BenQ GW2780 (HDMI-1) is the only monitor, in landscape at
1920x1080, scale 1 (`monitors.xml` scale 1, `text-scaling-factor` 1.0). The
laptop lid is closed. The monitor cannot rotate. The video is
16:9, 1920x1080, the whole screen.

**Firefox.** Use a separate profile so the settings do not touch your normal
one (the profile does not exist yet):

```
firefox -CreateProfile cerberus-recording   # once
firefox -P cerberus-recording --no-remote
```

Set the zoom to 80% in this profile (Ctrl+minus twice from 100%, on
`localhost:3000`). Do not set `layout.css.devPixelsPerPx`. Run Overview's grid
ends at row 34 (the journey panel is 13 rows high, `cerberus-run-story.json`).
In F11 on the 1920x1080 monitor at 80% it fits with no scrollbar (plan
2026-11-07-dashboard-polish, section 13, F3; the owner's browser check in
PR #134). Run Health's grid ends at row 35: its Run log fills the bottom rows,
and the shot panels sit above it. Check 15 confirms both before the take. Sign
in to the AWS console and to Grafana beforehand. Press F11 for fullscreen. Keep the mouse off the top edge, or Firefox shows its toolbar.

### Dashboards: three layers

The three Grafana dashboards go from the business view to the engineering
detail. Each answers a different audience's question; the uids did not
change, so old links still work.

| Dashboard | uid | For | What it answers |
|---|---|---|---|
| 1 · Run Overview: progress, quality, cost | `cerberus-run-story` | Everyone: business, finance, data users | How far the run is, whether the data passed its checks, what it cost, and that everything is switched off again |
| 2 · Run Health: compute and throughput | `cerberus-run-live` | Platform and data engineers | How many servers and Spark executors run, and how fast data moves |
| 3 · Spark and Cluster Diagnostics | `cerberus-spark-on-eks` | Engineers, when something looks wrong | Spark memory, tasks and stages, pods, and the metrics agent itself |

The video shows dashboards 1 and 2. Dashboard 3 is for troubleshooting and is
not in the shot table. In kiosk mode the link buttons between the layers are
hidden (`_dash.hideLinks`).

### Layout: what is on screen

One GNOME workspace. Firefox in F11 and one maximised (not fullscreen) `ptyxis`
window, so the GNOME top bar and the recording indicator stay reachable, with a
large font, running the `tmux` session `cerberus-view`: the top pane (about
75%) shows the masked log, the bottom pane runs `make demo-forward`. Switch
between the two with Alt+Tab; cut the switcher overlay in the edit. The
recorder records the monitor, so a workspace switch or the Activities overview
is recorded: never switch workspaces while recording.

Never on screen: the `cerberus-run` session and the `make exercise-check`
output; the AWS console Details panel and the account menu (it shows
`<user> @ XXXX-XXXX-XXXX`; masked in the edit, section 6); Prometheus Status
and Configuration; Spark UI Environment and SQL; the Grafana sign-in page,
`.env`, the `make grafana-token` output and Administration, Service accounts.
The CloudWatch queries of Run Overview and Run Health carry ARNs with the
account ID as dimensions (`cerberus-run-story.json` L518-644,
`cerberus-run-live.json` L542-586). Those queries are hidden and every shown
series has a label, so a normal tooltip shows no ARN (plan
2026-11-07-dashboard-polish, section 2). An error can: a CloudWatch error such
as AccessDenied puts a warning or error triangle in the panel header, and its
tooltip can print the IAM role ARN. Never hover a panel with a triangle on
camera (check 17).

**Tabs** (switch with Ctrl+1 to Ctrl+6, keyboard only):

| Tab | Page | Show | Do not show |
|---|---|---|---|
| 1 | Step Functions: `https://us-east-1.console.aws.amazon.com/states/home?region=us-east-1#/statemachines` | After `starting execution`, click into the new execution. Graph view and the step table. | The Details panel (it shows the execution ARN, which has the account ID) and the account menu (masked in the edit) |
| 2 | Run Overview `cerberus-run-story` (URL below) | Everything. Show it first in every phase. | |
| 3 | Run Health `cerberus-run-live` (URL below) | Executors, Spot nodes, input bytes/s | |
| 4 | Grafana Explore, datasource `amp`, refresh 15 s | One query at a time (links below) | |
| 5 | `http://localhost:9090/targets` | The agent's Targets page. The agent has no query page; PromQL goes in tab 4. Plan 2026-10-24 L38 states that agent mode serves Targets; confirm it on the cluster in the rehearsal. | Status, Configuration (the remote-write URL has the workspace ID) |
| 6 | `http://localhost:4040` | Jobs, Stages, Executors | Environment, SQL (they print the S3 paths with the account ID, `spark-application.yaml` L30) |

Press F5 on tab 6 after `make demo-forward` prints `attached  spark driver ...`
for the silver job (forward.sh logs that text on each attach). The forward
re-attaches by itself when the generator driver ends and the silver driver starts.

**URL builder.** Run it right before Enter (step 3 of the take sequence), so
`from` is the run start. "Start servers", "Time since start" and the cost tile
count from it. The placeholders are posted at the apply start (exercise.sh
L268), and the cumulative step rows (`RUNNING_SUM`) need the run start inside
the range (plan 2026-10-25 L215), so `from` must not be later than the Enter.

```
FROM=$(( $(date +%s) * 1000 )); echo "FROM=$FROM"
echo "http://localhost:3000/d/cerberus-run-story?orgId=1&from=$FROM&to=now&refresh=15s&var-requested=100000000&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
echo "http://localhost:3000/d/cerberus-run-live?orgId=1&from=$FROM&to=now&refresh=15s&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
```

Write down the printed `FROM`: the final screenshot needs it (section 10).
Tested here: it prints both URLs with a 13-digit `from=`. The 1M check run used
this form (plan 2026-11-07-dashboard-polish, section 10). Whether Grafana
13.2.3 honours the three `_dash.hide*` flags is unverified; check 15 checks it.

- `refresh=15s` works because both dashboards list `15s` in
  `timepicker.refresh_intervals` (PR #133). Without it, Grafana 13.2.3 started
  no refresh timer at all (plan 2026-11-07-dashboard-polish, bug 10).
- `var-requested` sets the target of the "Payments processed" bar (a hidden
  variable, default 100000000). The take uses 100000000; the 10M rehearsal used
  10000000 and the 1M check run 1000000.
- Use the same `from=` on Run Health. Its Run log panel only lists
  annotations in the time range, and the default range is `now-30m`, while
  the take lasts about 63 minutes.

**Explore links.** No Explore links existed before this runbook (plan
2026-10-24 asked for two or three). Build each with `jq`; the datasource uid
`amp` and type `grafana-amazonprometheus-datasource` are in
`observability/grafana/provisioning/datasources/local.yaml`:

```
explore() { # PROMQL FROM_MS [TO_MS]
  jq -rn --arg q "$1" --arg from "$2" --arg to "${3:-now}" '
    {a: {datasource: "amp",
         queries: [{refId: "A", expr: $q, instant: false, range: true,
                    datasource: {type: "grafana-amazonprometheus-datasource", uid: "amp"}}],
         range: {from: $from, to: $to}}}
    | "http://localhost:3000/explore?schemaVersion=1&orgId=1&panes=" + (tojson | @uri)'
}
explore 'max(cerberus_spark_rows{row="payments_created"})' "$FROM"
```

Tested here: the function prints a URL, and decoding its `panes` value gives
valid JSON with the query intact. Whether Grafana 13.2.3 opens that URL
format is unverified. Check each link at $0 against the 2026-10-13 run
(AMP retention is 400 days, ADR 0024 and
`terraform/modules/prometheus_workspace/variables.tf` L1-5; whether the
2026-10-13 samples were kept is unverified, ADR 0024 L224-225, and this check
shows it), with `from`/`to` as epoch ms for 06:05Z to 06:55Z:

```
date -u -d 2026-10-13T06:05:00Z +%s%3N   # 1791871500000
date -u -d 2026-10-13T06:55:00Z +%s%3N   # 1791874500000
```

For that check call `explore "$QUERY" 1791871500000 1791874500000`. The `cerberus_spark_*`
series did not exist on 2026-10-13 (exporter built 2026-10-25), so the third
and fourth queries return data only in the rehearsal. Queries:

| Purpose | PromQL |
|---|---|
| Nodes by capacity type | `count by (label_eks_amazonaws_com_capacity_type) (kube_node_labels)` |
| Running executors | `count by (application_name) (max by (application_name, application_id, executor_id) (last_over_time(metrics_executor_activeTasks{executor_id!="driver"}[45s])))` |
| Series count | `count({__name__=~"cerberus_spark_.*"})` |
| Rows so far | `max by (row) (cerberus_spark_rows)` |

## 4. GNOME screen recorder, pre-test and dashboard look review

The recorder is the built-in one of GNOME Shell 50.1 (Wayland). It records the
whole monitor: no scenes, no crop, no masks.

- **Start.** Press Print, switch the toggle to video, choose Screen (not
  Selection), then Record. `Ctrl+Shift+Alt+R` opens the same UI in video mode.
  Turn the pointer off.
- **Stop.** Alt+Tab to the maximised terminal (F11 Firefox hides the top bar),
  then click the red indicator in the top bar. Whether `Ctrl+Shift+Alt+R` also stops a
  recording is unverified; the pre-test tries it.
- **Output.** `~/Videos/Screencasts/Screencast From <local date time>.webm`:
  VP8, variable frame rate, about 30 fps on average, written by GStreamer's
  `matroskamux`. The `creation_time` tag is the UTC start. Tested here with
  `ffprobe -v error -show_entries format_tags=creation_time -show_entries stream=width,height -of default=nw=1`
  on the file of 2026-10-06: `creation_time=2026-10-06T07:54:51.340326Z`, an
  area selection of 1920x955. The rehearsal confirms a full-screen capture at
  1920x1080.
- **Limits.** `max-screencast-length` is not a key in the media-keys schema
  here, and the 2026-10-06 file ran 418 s, so there is no 30 s cap. A
  63-minute recording is unverified (the longest seen is 418 s), and so are the
  recorder's CPU load and whether keyboard focus returns to the terminal after
  the recording starts (check 14).
- **Fallback.** If the recorder caps or stutters, use OBS 32.1.0 (installed) at
  1920x1080 with no crop and the NVENC encoder, recording to
  `~/Videos/cerberus-8-10/`. Re-plan only if both fail.

**$0 pre-test, before the rehearsal.** It checks the recorder at full length
and doubles as a look review of Run Overview and Run Health. No cluster is needed.

1. Record 65 minutes of the Run Overview and Run Health dashboards on the
   2026-10-13 window (`from=1791871500000`, `to=1791874500000`, the URLs of
   section 3 with those two values; 06:05Z to 06:55Z). Step through the six
   phases (start and apply, generator, transform, dbt, serve, teardown) and
   dwell about 15 s on each screen, as in the take. Cost: CloudWatch
   `GetMetricData` about $0.02 per hour (plan 2026-10-25 L123).
2. After the stop, run `ffprobe`: it must show 1920x1080 and a duration of at
   least 3,900 s, with an average frame rate of about 30. Note the CPU of
   `gnome-shell` in `top`, off camera.
3. The data of that window is old. The `cerberus_spark_*` series did not exist
   on 2026-10-13, so the panels fed by them show "No data" there; judge those
   in the rehearsal. CloudWatch keeps 1-minute data for about 15 days only
   (ADR 0022 L279-280), so the Step Functions panels may be coarser. Both
   limits are expected, not findings.

**Dashboard look review.** While the recording plays, and afterwards from
frames, check this list for
each of the six phases, on Run Overview and on Run Health. Normalise the
recording first (section 6, step 2) and grab frames from `timed.mkv`:
`ffmpeg -ss T -i timed.mkv -frames:v 1 frame.png`. The raw file has one keyframe,
so every `-ss` on it would decode from the start:

- no "No data" or error panel where a viewer looks (apart from the expected
  gaps above);
- clear titles and units on every panel;
- numbers formatted for a reader: thousands separators, the M suffix,
  durations in minutes and seconds;
- consistent colours across panels and phases;
- no overlapping or cut-off text at 1920x1080;
- no panel that needs scrolling for a shot;
- a readable time axis;
- no account ID or ARN visible.

Write the findings down. They go into a dashboard-polish PR that is merged
before the rehearsal. That PR is separate: this runbook PR edits no dashboard.

## 5. Shot table (the 100M take)

The take command (the user runs it, in the hidden `cerberus-run` session, with
the exact flags of the rehearsal except the size and name):

```
make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2 --name demo-100m"
```

Flag names are from `exercise.sh` (usage header L6-26, parser L83-90): `--yes`,
`--generate`, `--generator-executors`, `--executor-nodes`, `--name`.

**Take sequence.** The recording covers the whole run, in one file: it starts
about 5 s before Enter and stops after the `after destroy:` line, with no stop
or restart in between.

1. Off camera, start `cerberus-run` (section 2, item 11) and run
   `make exercise-check` there.
2. Start `ptyxis` maximised (not fullscreen) and run
   `tmux new-session -s cerberus-view -c /home/chirag/projects/cerberus`. In it,
   run the `export` line of section 2 and the masked-tail account variable
   (below). Then run `tmux split-window -v -l 25%` and `make demo-forward` in
   the bottom pane. First run the `export` line of section 2 in the bottom pane
   too.
3. Run the URL builder (section 3); load tabs 2 and 3 with those URLs.
4. In the top pane, type this line and do not press Enter:

   ```
   T0=$(date +%s); tmux send-keys -t cerberus-run 'make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2 --name demo-100m"' Enter; until LOG=$(find observability/scale/exercises -maxdepth 1 -name 'demo-100m-*.log' -newermt "@$T0" | head -1); [ -n "$LOG" ]; do sleep 1; done; tail -n +1 -F "$LOG" | sed -u "s/$ACCOUNT/<account>/g"
   ```

   The `find -newermt "@$T0"` wait plus the masking `sed` was tested in zsh with
   dummy files: it found only the new log and masked the number in bucket
   names and in `id=` text. It avoids zsh's "no matches found" on an
   unmatched glob.
5. Start the GNOME recording.
6. Wait about 5 s, then press Enter. If the terminal does not have keyboard
   focus after the recording starts, click it first (check 14).
7. Follow the shot table. Do not stop the recording.
8. After the `after destroy:` line, stop the recording, move the file
   (section 6, step 1) and close the Grafana tabs (cost guard).

**Terminals** (two windows; the run session is never visible):

1. `cerberus-run` (hidden `tmux` session): `make exercise ...`. Never on
   camera, because it prints the account ID (84 lines of the 2026-10-13 log
   contain it: the preflight identity at L3, Terraform ids at L138,
   `grafana_role_arn` at L222, and the S3 bucket names in the generator
   lines). The log mirrors the terminal from the point where the script
   redirects its output through `tee` (exercise.sh L247-249).
2. `cerberus-view` in the `ptyxis` window: the masked log (top pane) and
   `make demo-forward` (bottom pane). Start `make demo-forward` before the
   exercise; it waits for the cluster. The masked tail is the pre-typed line
   of step 4. Its account variable comes from:

   ```
   ACCOUNT=$(aws sts get-caller-identity --query Account --output text); [ -n "$ACCOUNT" ] || echo "no account"
   ```

   **Never pipe `make exercise` itself through `sed` or anything else.** A dead
   pipe can kill the script before its teardown (the comment at exercise.sh
   L156-159, found 2026-10-07). The pipe above reads the log file, not the
   script's output.

In the shot table, "Terminal" means the `cerberus-view` window.

Each row lists the screens in order, Run Overview first.

| Phase | Terminal cue (exercise.sh) | Real time (100M) | Screens | What to show | Edit speed | On screen |
|---|---|---|---|---|---|---|
| Before start | the first seconds after the run starts | 3 s | Run Overview | Journey: "Start servers" is blue (Running); the other seven rows show no bar yet, only their labels, with the legend Running / Done / Ran at the bottom and no text in the bars. "Now" reads "Waiting for the run to start", then "1/8 Starting the servers (about 15 min)". Tiles "Quality checks: not finished yet" and "Clean-up: not started yet" (placeholders posted at L268). | 1x | about 3 s |
| Start servers | `spot executor nodes: 2` then `apply took` (L269, L272) | 793 s | Terminal, then Run Overview | Terraform creating EKS; then the "Start servers" marker. "Servers now" appears once scraped; "Time since start" counts from the first frame. | 60x | about 13 s |
| Generate (create) | `generator: 100000000 events` | about 375 s (183 + 192) | Run Overview, Spark UI (Jobs, Executors), Run Health | "Now": "2/8 Creating test payments (Spark)"; "Spark is doing": "Creating payments". The bar stays flat for about 3 minutes in the 8-task map stage, then fills in the 328-task write. | 15x | about 25 s |
| Generate (commit) | no log line | 875 s | Run Overview, Run Health | "Spark is doing": "Saving files (no counter)"; the journey row "↳ Saving files" is blue; executors 0. Caption: "Saving files to S3: 14.6 min, shown 30x faster. No progress signal exists for this step." | about 30x | about 29 s |
| Ingest | `starting execution` (L331) | 4.2 s | Console | Graph view (top bar masked in the edit) | 1-5x | about 3 s |
| Transform | (RunTransform) | 511.6 s | Run Overview, Run Health, Spark UI, Explore, Targets, then Run Overview | Run Overview: "Spark is doing" reads "Reading new payments", then "Adding to the clean table", then "Tidying files"; the second bar fills. Run Health: executors to 16, Spot nodes 2 to 4, input bytes/s. Spark UI Executors. Explore: nodes by capacity type. Targets: `spark-progress` and the driver up. End on Run Overview. | about 10x | about 51 s |
| Model (dbt) | (RunDbt) | 167.9 s | Console, then Run Overview | The journey row (console top bar masked in the edit) | 15x | about 11 s |
| Serve | (RunServingQuery) | 58.3 s | Console, then Run Overview | Console top bar masked in the edit | 15x | about 4 s |
| Quality checks | `collecting metrics` (L362) to `exercise done` (L380) | about 62 s | Console, Run Overview, Terminal | Console all green (top bar masked in the edit). Run Overview tile "Quality checks: PASSED (N checks, 0 errors, 1 warning)" (`annotate_dq_verdict`, annotate.sh L171; N was 26 on 2026-10-13). Terminal `data quality PASSED` line. | 10x | about 6 s |
| Clean-up | `waiting 60s for the last metrics to reach AMP`, then `destroying dev-compute`, `destroy took`, `after destroy: EKS 0, NAT 0, EIP 0, running instances 0` (L170-196) | 792 s to `destroy took` (60 + 732); 799 s to the `after destroy:` line | Terminal, then Run Overview | Run Overview tile "Cluster deleted: EKS 0, NAT 0, Elastic IP 0, running instances 0 (account-wide check)" (`annotate_teardown_check`, annotate.sh L194). "Time since start" and "Cost so far (estimate)" keep counting through the clean-up and stop at the cluster's last metrics plus 780 s (hidden variable `teardown_s`). | 60x | about 13 s |
| Title and end card | | | | Title about 5 s, end card about 6 s | | about 11 s |

Real-time sources: log L229, L368-370, L3890-3892 and run record `states[]`.
The 10M estimates are in section 1. The on-screen total is about 2:49
(estimate: 3+13+25+29+3+51+11+4+6+13 plus the 11 s of cards), close to the
"about 3 min" of the video script in `docs/scale-metrics.md` (checkpoint L243).

**Dwell rule.** One screen holds for about 15 s on screen, which is 150 s of
real time at 10x. Record each screen long enough for that, then cut.

The cue strings above are the exact text of `exercise.sh`. Two tiles describe
the moment in plain words. "Now" shows the run's own step notes (tag
`cerberus-now`, `annotate_now_text`, annotate.sh L132-150): "1/8 Starting the
servers (about 15 min)" to "8/8 Deleting the servers (about 13 min)", then
"Finished: servers deleted, nothing left running". "Spark is doing" shows what
Spark itself reports: "Creating payments", "Saving files (no counter)",
"Reading new payments", "Adding to the clean table", "Tidying files",
"Finishing up", "Waiting" or "Not in use now".

## 6. Post-production (ffmpeg 8.0.1)

Every command below was run on a synthetic 40 s 1920x1080 VP8 file (made as in
step 5) with `h264_nvenc`; the commands are in zsh.

1. Move the raw file and read the start time:

   ```
   mv ~/Videos/Screencasts/"Screencast From <date time>.webm" ~/Videos/cerberus-8-10/raw.webm
   REC_START=$(date -u -d "$(ffprobe -v error -show_entries format_tags=creation_time -of default=nw=1:nk=1 raw.webm)" +%s)
   ```

   Map a log time to an offset in the recording:
   `echo $(( $(date -u -d 2026-10-26T10:12:36Z +%s) - REC_START ))`. Tested
   with a dummy time. The recording starts about 5 s before Enter, so the
   first log line sits near offset 5.
2. Normalise the raw file. This is mandatory: the recorder writes one keyframe
   per recording (every `-ss` would decode from the start) and a variable frame
   rate. `-g 60` gives a keyframe every 2 s.

   ```
   ffmpeg -i raw.webm -vf "fps=30" -c:v h264_nvenc -preset p5 -cq 20 -g 60 -pix_fmt yuv420p -an timed.mkv
   ```

   Optional: a second copy with the real elapsed time burned in, only to find
   offsets while scrubbing (do not cut segments from it). The text is a
   filter argument, so `\:` is required:

   ```
   F=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
   ffmpeg -i raw.webm -vf "fps=30,drawtext=fontfile=${F}:text='%{pts\:hms}':x=20:y=20:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6" -c:v h264_nvenc -preset p5 -cq 20 -g 60 -pix_fmt yuv420p -an scrub.mkv
   ```

   In zsh write `${F}` with the braces: `$F:text` is read as a history
   modifier and the filter then fails with "Either text, a valid file...".
3. **Time-lapse.** The whole run is one file. Speed up the quiet parts (cluster
   apply, waits, teardown) and keep the key moments at 1x, as the shot table
   says. Per segment, A is the start offset in seconds, D the real duration,
   K the speed factor (for example 8 or 16). The speed label (`drawtext`) goes
   on sped-up segments only:

   ```
   F=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
   ENC="-an -c:v h264_nvenc -preset p5 -cq 20 -pix_fmt yuv420p"
   # quiet segment: A=0 D=32 K=16, no mask
   MASK=""
   ffmpeg -ss 0 -t 32 -i timed.mkv -vf "${MASK}setpts=(PTS-STARTPTS)/16,fps=30,drawtext=fontfile=${F}:text='16x':x=w-text_w-40:y=40:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6" ${=ENC} seg_quiet.mp4
   # key moment at 1x: no speed change, no label (a console segment, so masked)
   MASK="drawbox=x=0:y=0:w=iw:h=120:color=black:t=fill,"
   ffmpeg -ss 32 -t 6 -i timed.mkv -vf "${MASK}setpts=(PTS-STARTPTS),fps=30" ${=ENC} seg_key.mp4
   ```

   The first command made a 2.0 s segment from 32 s (32 / 16), and the second
   a 6.0 s segment; frames from both showed the "16x" label on the first only
   and the black bar on the second only. `setpts` divides the timestamps and
   `fps=30` after it drops the extra frames. In `ENC`, zsh needs `${=ENC}` to
   split the words (in bash write `$ENC`). The mask height `120` is a
   placeholder: measure H in the rehearsal from
   `ffmpeg -ss T -i timed.mkv -frames:v 1 frame.png`; sample the colour from
   the bar if black stands out. For other segments set `MASK=""`. An optional
   punch-in, used sparingly: `crop=960:540:X:Y,scale=1920:1080`.

   The dashboards refresh every 15 s, so at 16x a refresh shows about every
   second (15 / 16 = 0.94 s on screen). At the 30x and 60x of the shot table a
   refresh shows two to four times a second; whether that looks calm is
   unverified (check 21).
4. Cards:

   ```
   ffmpeg -f lavfi -i color=c=0x111217:s=1920x1080:d=6:r=30 -vf "drawtext=fontfile=${F}:text='TEXT':x=(w-text_w)/2:y=(h-text_h)/2:fontsize=72:fontcolor=white" ${=ENC} card.mp4
   ```

   The end card shows the events, the run time and the data quality result
   from the run record (`events_processed`, `run_seconds`, `data_quality`).
   Add the cost per million events only after `--cost-only` has run the next
   day (the closing log line, exercise.sh L380).
5. Join with the concat demuxer and check:

   ```
   printf "file 'card.mp4'\nfile 'seg_quiet.mp4'\nfile 'seg_key.mp4'\n" > list.txt   # list every file in order
   ffmpeg -f concat -safe 0 -i list.txt -c copy final.mp4
   ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,pix_fmt,r_frame_rate -of default=nw=1 final.mp4
   ```

   Tested here with a synthetic source made by
   `ffmpeg -f lavfi -i testsrc2=s=1920x1080:r=30 -t 40 -c:v libvpx -g 100000 -b:v 1M test.webm`
   (NVENC was available, so `h264_nvenc` ran): normalise, the 16x segment, the
   masked 1x segment, a 6 s card, concat. `ffprobe` returned `h264`,
   1920x1080, `yuv420p`, 30/1, and the joined length was 14.0 s (6 + 2 + 6).
   Expected on the real file: the same codec, size, pixel format and rate.
6. LinkedIn limits. These come from third-party pages and may be out of
   date; check LinkedIn Help on the publish day: MP4, up to 5 GB, at least
   3 s, a maximum length of 10 to 15 minutes (the sources differ), aspect
   ratio between 1:2.4 and 2.4:1 (16:9 fits), 30 fps recommended. Sources:
   https://blog.sendspark.com/linkedin-video-specs,
   https://www.tella.com/blog/linkedin-video-specs-size-length,
   https://knowledge.hubspot.com/social/image-size-requirements-for-social-posts.
   Captions are optional: the feed autoplays muted.
7. Run a pipeline test (steps 2 to 5) on the synthetic file now, and on the
   rehearsal recording after the rehearsal.
8. Before export, step through every console segment and check that no account
   ID is visible (the console top bar, the account menu, ARNs).
9. Scope: the video is the live run only. The $0 results walk-through from
   #107 is not added.

## 7. Rehearsal (ADR 0022 step 8) and its checks

The rehearsal uses the take's flags, with 10M events. It runs only after the
pre-test and the dashboard-polish PR (section 4):

```
make exercise ARGS="--yes --generate 10000000 --generator-executors 8 --executor-nodes 2 --name rehearsal"
```

Run it through the section 5 wrapper (the hidden `cerberus-run` session and the
pre-typed line, with `rehearsal-*.log` in place of `demo-100m-*.log`). Use the
Run Overview URL with `&var-requested=10000000`. Record the whole run, from Enter to
the `after destroy:` line, in one file, with the GNOME recorder (section 4).
The run record is `observability/scale/runs/rehearsal-<stamp>.json`; it is
committed in the take's PR, not in its own.

Expect about 38-50 min of cluster time and about $1.0-1.4 (estimates, plan
2026-11-07 section 7). The post may say "we processed 10M as a rehearsal" only
from the run record (`events_processed`).

| # | Check | How | Pass rule |
|---|---|---|---|
| 1 | Generator bar | Explore: `max(cerberus_spark_rows{row="payments_created"})` | Equals `events=` in the `[generate] done` line of the log. The bar shows one decimal (panel 1, `decimals: 1`, suffix M). |
| 2 | Added rows | Explore: `max_over_time(cerberus_spark_rows{row="added_to_clean_table"}[1h])`; then `jq .events_processed observability/scale/runs/rehearsal-*.json` | Equal, and equal to the generator's `events=`. With the Lambda retired there are no Lambda events, so the silver gain matches the generated count exactly. For context, on the 1M run silver gained 1,005,920 against 999,833 generated (`exercise-20261015T145812Z`), because the Lambda still added events then. |
| 3 | Step regions | List the annotations (below) and compare with `jq '.states[]|[.state,.seconds]' observability/scale/runs/rehearsal-*.json` | Durations match `states[].seconds` within 1 s. Each marker appears within 15 s of the state change watched live. |
| 4 | Result tiles | Read the DQ and Clean-up tiles | They equal the collector's `data quality PASSED` line and the `after destroy:` line. |
| 5 | CloudWatch delay | Note when the Transform row turns blue, against the `RunTransform` marker | Record the delay (estimate 1-3 min, plan 2026-10-25 L126; unverified). |
| 6 | Pods | `kubectl -n monitoring get pods -l app=spark-progress-exporter`; `kubectl -n spark-jobs get pods -l spark-role=driver` | Exporter Running; no driver Pending. (`app` label: `eks_observability/main.tf` L354.) |
| 7 | Series count | Explore: `count({__name__=~"cerberus_spark_.*"})` | Below about 200 (plan 2026-10-25). |
| 8 | Fail-open (rehearsal only, never the take) | `make grafana-down` during RunTransform, wait 60 s, `make grafana-up` | The run carries on. `grep -c "annotation skipped" <log>` returns 1 (the message is `annotation skipped (...)`, annotate.sh `annotate_warn`). Step Functions states missed in the gap are posted after the restart (the history reader keeps a seen-file, annotate.sh L219 and following). Direct step posts made in the gap are lost, which is expected. Does the browser session survive the restart: unverified. |
| 9 | Stage retries | While the silver driver runs: `curl -s localhost:4040/api/v1/applications \| jq -r '.[0].id'`, then `curl -s localhost:4040/api/v1/applications/<id>/stages \| jq '[.[]\|select(.attemptId>0)]\|length'` | Returns 0. Afterwards, grep the driver log for retries (the pattern is unverified). Basis: `observability/spark_progress/CAPTURE.md`, "Known limits". |
| 10 | Node labels | Explore: nodes by capacity type | Returns `ON_DEMAND` and `SPOT`. "Servers now" shows "on-demand" and "Spot (spare capacity)". |
| 11 | Dev-compute plan | Section 2, item 7, before the apply | "0 to change, 0 to destroy". |
| 12 | Spark UI text | Open Jobs and Stages on `localhost:4040` while the generator and silver drivers run | No bucket name in the job descriptions (for example "Listing leaf files and directories ... s3a://cerberus-platform-bronze-<account>/"). If one shows, show Executors only. Unverified. |
| 13 | Recorder | `ffprobe` on the raw file | 1920x1080; duration about the wall time of the run; average about 30 fps; no visible stutter. |
| 14 | Focus | Press Enter after the recording starts | The keypress reaches the terminal. If not, click the terminal first and change step 6 of the take sequence. |
| 15 | Fit | Open Run Overview and Run Health in F11 at 80% zoom | Run Overview: every panel visible with no scrollbar, the journey legend (Running, Done, Ran) at the bottom. Run Health: the shot panels visible. The `_dash.hide*` flags hide the time picker, variables and links. |
| 16 | Account ID | Grab a frame at each console shot (`ffmpeg -ss T -i timed.mkv -frames:v 1 frame.png`, after section 6 step 2; the raw file has one keyframe) | Find every place the dashed ID or an ARN shows; record the `drawbox` height and any extra box needed. |
| 17 | Error tooltips | Watch every panel of Run Overview and Run Health through the run | No warning or error triangle on any panel. "Cost so far (estimate)" must show none: its earlier triangle was the "items dropped from union(s)" notice, fixed in PR #133 (plan 2026-11-07-dashboard-polish, F5). If one shows, do not hover it on camera; note the panel and the time. |
| 18 | Terminal legibility | A frame of the masked log at 1080p | The text is readable. |
| 19 | Timing | Record apply, generator, execution and destroy times | Update section 1; re-run the headroom projection (section 2, item 5) with `states[RunDbt].athena.bytes_scanned`. |
| 20 | Lambda watch | Section 2, item 9 | `InvokeIngestion` SUCCEEDED and the silver gain equals `events=`. |
| 21 | Time-lapse look | Cut one quiet segment at 16x and one at 60x from the rehearsal file (section 6, step 3) | The refresh of the dashboards looks calm at both speeds; the speed label is readable. |

Also check the items of plan 2026-10-24, step 8, that still apply: both
port-forwards attach and 4040 re-attaches for the silver job; data quality
passes; the teardown is clean. Checks 13 to 18 replace the recorder, video-size,
layout and mask-height items of that list.

**List the annotations of a run (check 3).** Off camera, after the run:

```
EXEC=rehearsal-<stamp>
bash -c 'source orchestration/annotate.sh; annotate_http GET "/api/annotations?limit=100&tags=run:'"$EXEC"'"; jq -r ".[]|[(.time/1000|floor|todate),(if .timeEnd and .timeEnd!=.time then \"\((.timeEnd-.time)/1000|floor) s\" else \"point\" end),.text]|@tsv" <<<"$ANNOTATE_BODY"'
```

Every annotation carries the tag `run:<execution name>` (`annotate_step`,
annotate.sh). The jq part was tested on a sample body here; the full command
needs the token and Grafana (not run).

The run record has no `state_timings` field (that is the collector's variable
name); the per-state seconds are in `states[].seconds`, and start and end times
come only from `aws stepfunctions get-execution-history`.

**Decision point.** If the exporter fails in the rehearsal, switch to the R4
panel (prepared in step 6d) and check it again before step 9 (plan 2026-10-25
L361).

### 1M check run (2026-11-08)

A short run with the take's flags tested the dashboard fixes live (PRs #133
and #134). It is not the dress rehearsal; that was the 10M run of 2026-11-07.

- Run `rehearsal-1m-20261108T060517Z`: `--generate 1000000
  --generator-executors 8 --executor-nodes 2 --name rehearsal-1m`. Record
  `observability/scale/runs/rehearsal-1m-20261108T060517Z.json` (committed
  with the take): 999,846 events, silver 149,119,415, data quality passed
  (0 errors, 1 warning).
- Log (`observability/scale/exercises/rehearsal-1m-20261108T060517Z.log`,
  local only): apply 820 s (L236), generator 142 s (L274), execution 404 s
  (L276), destroy 693 s (L6500), `after destroy: EKS 0, NAT 0, EIP 0, running
  instances 0` (L6501), cluster up 2,235 s (L6502).
- Range: `from=1794117917000` (06:05:17Z, the run start). The "Finished" note
  (tag `cerberus-now`) is at `1794120176590` (06:42:56.6Z): 2,259.6 s, or
  37.66 min.
- Cost tile at "Finished": servers 2,259.6 s / 3,600 x $1.15 = $0.7218, plus
  Athena 8.0956 x 10^10 bytes x $5 per 10^12 = $0.4048, total $1.1266. The
  tile shows $1.13. This is the tile's estimate; the bill comes from
  `--cost-only`.
- From the cluster's last AMP sample to "Finished": 660 s on this run and
  786 s on the 10M rehearsal. `teardown_s` (780 s) is set close to the longer
  one.

Sources: the log and record above; plan 2026-11-08-journey-freeze, sections 2
and 8; PR #134, "Verification".

With the final-screenshot URL of section 10 (`from=1794117917000`,
`to=1794120176590`), Run Overview reads 38 min and $1.13. This works only
while the Athena metrics are younger than 14 days (until about 2026-11-22).

## 8. Failure and abort

- **Abort.** From the visible pane, run `tmux send-keys -t cerberus-run C-c`
  once, and wait. Do not attach to `cerberus-run` on camera. Terraform stops cleanly, then the trap exits with code 130 and
  runs the teardown. A second Ctrl-C during the apply can leave resources
  outside the state, which the destroy cannot remove. From the teardown start
  (the `waiting 60s` line), Ctrl-C is ignored (exercise.sh L161, L259-260).
  Never use `--keep`. Never kill the `cerberus-run` session during a run.
- **Abort after `starting execution`.** The execution keeps running in AWS
  after the script exits. Stop it (the third command in the box at the top),
  off camera, then run the verify block. Stop it at once from a second shell,
  while the teardown runs; do not wait for the teardown to finish (RunDbt can
  finish during the teardown of about 13 minutes). Fill `<account>` off camera
  with `$(aws sts get-caller-identity --query Account --output text)`. A running execution also makes the
  next `make exercise-check` stop on "execution(s) already RUNNING"
  (exercise.sh L144-149). The `RunTransform` and `RunDbt` states use
  `ecs:runTask.sync` with timeouts of 4,500 s and 2,700 s
  (`orchestration/state_machine.asl.json.tftpl` L39, L74), so an unstopped
  execution can go on changing Athena tables for that long. That Step
  Functions stops the ECS task of a `.sync` state when the execution stops is
  from the AWS documentation, unverified here.
- **`DESTROY FAILED`** (exercise.sh L180). The user runs `make compute-destroy`
  (this changes AWS; it is a plain `terraform destroy`, so it asks for
  confirmation: type `yes`), then the verify block below.
- **Verify block** (read-only):

  ```
  aws eks list-clusters
  aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available
  aws ec2 describe-addresses
  aws ec2 describe-instances --filters Name=instance-state-name,Values=pending,running
  terraform -chdir=terraform/envs/dev-compute state list    # expect no output
  make exercise-check
  ```

- **Data quality failed** (collector exit 3; log line `DATA QUALITY FAILED`).
  The teardown still runs and the run record is written. Do not retake;
  investigate.
- **Retake rule.** A retake is allowed only if the run fails before the
  `generator: 100000000 events` line (apply or node wait). Once the generator
  starts, a failure can leave part of a run in bronze under its `run_id`
  (dynamic partition overwrite, `generate_bulk_payments.py` L320 and L337;
  the `[generate] done` line is only grepped at the end, `generate_bulk.sh`
  L94). Let the teardown finish, stop, and re-plan. Even a clean second 100M
  takes silver from about 249M to about 349M (estimate), and the dbt merge
  would be about 30.6 GiB, past the 25 GiB cutoff (linear from 21.9 GiB at
  249M, ADR 0022 L46-51). A second 10M rehearsal is allowed: about 35.7M of
  room is left (section 2, item 5).
- **Cost guard.** An open Run Overview tab polls CloudWatch `GetMetricData` every
  15 s, about $0.02 per viewing hour (estimate, plan 2026-10-25 L123, J1). After the take, close the tabs or run `make grafana-down`. Run
  `--cost-only` the next day.

## 9. Security

- Never show the Grafana sign-in page, `observability/grafana/.env`, the output
  of `make grafana-token`, or Administration, Service accounts.
- `.env` is git-ignored (`.gitignore` L44-46 and L66). Check with
  `git check-ignore -v observability/grafana/.env`.
- The account ID is already public in this repo (exercise.sh L65), so masking
  it is hygiene, not secrecy. It still shows in: the `make exercise` terminal
  (use the masked tail in `cerberus-view`; `make exercise` runs in the hidden session), the S3 bucket names
  (`terraform/modules/s3_medallion/main.tf` L9-19; they appear in the
  generator lines), the Spark UI Environment and SQL tabs (do not open
  them), the AWS console account menu and the execution ARN on the details
  page (masked in the edit, section 6 step 3; do not open the Details panel), and
  Prometheus Status, Configuration (do not open it).
- Recordings stay outside the repo (`~/Videos/cerberus-8-10/`). The raw
  recording contains unmasked frames. Keep it in `~/Videos/cerberus-8-10/`.
  Never upload or commit it.

## 10. After the take

1. Commit the run record (and the two rehearsal records, `rehearsal-20261107T081206Z.json` and `rehearsal-1m-20261108T060517Z.json`, in the same PR) in a PR like #98 (the records in
   `observability/scale/runs/`; the exercise log is git-ignored, so it stays local).
2. Run `--cost-only` the next day:
   `uv run -q --no-project --with boto3 python observability/scale/collect_run_metrics.py --execution demo-100m-<stamp> --cost-only`
   (the form the script prints, exercise.sh L380).
3. Do step 10 of plan 2026-10-24 (edit, publish, link in 8.10, follow-ups in
   the checkpoint "Later" list).

**The final screenshot.** After the run, "Time since start" and "Cost so far
(estimate)" stop at the cluster's last AMP sample plus 780 s (hidden
variable `teardown_s`; ADR 0022, "Erratum (8.10 journey and freeze,
2026-11-08)"). The real gap was 660 s and 786 s on the two rehearsals, so a
live view after the run can read about 2 minutes high or low. For exact
numbers, end the range at the "Finished" note and lift the cap. `from` is the
take's `FROM` from the URL builder. If it is lost, use the run start from the
execution name, as below.

```
EXEC=demo-100m-<stamp>
s=${EXEC##*-}; FROM=${FROM:-$(date -u -d "${s:0:8} ${s:9:2}:${s:11:2}:${s:13:2}" +%s000)}
bash -c 'source orchestration/annotate.sh; annotate_http GET "/api/annotations?limit=1&tags=cerberus-now&tags=run:'"$EXEC"'"; jq -r ".[0]|[.time,.text]|@tsv" <<<"$ANNOTATE_BODY"'
TO=<the time printed above>
echo "http://localhost:3000/d/cerberus-run-story?orgId=1&from=$FROM&to=$TO&var-requested=100000000&var-teardown_s=99999&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
```

The printed text must be "Finished: servers deleted, nothing left running".
With `to` at "Finished", the tiles end exactly there, and `teardown_s=99999`
stops the cap from ending them earlier. Use no `refresh` on this URL. Tested
here: the stamp parsing (in bash and zsh, it gives 1794117917000 for the 1M
run) and the jq part on a sample body. The annotation query needs Grafana and
the token (not run).

## 11. The post: Cerberus and Databricks as complements

Rule: no head-to-head timing or cost claim. The two projects differ in engine,
data shape, scale and billing, and Databricks Free Edition gives no bill and no
billing API. Each platform shows its own strength.

**Cerberus facts** (cite each record). The 100M run: 100,008,511 events,
execution 742 s, run cost $0.37, $0.0037 per million events, whole exercise
$1.78 (checkpoint L178-187; `exercise-20261013T055859Z.json`). The take's own
record replaces these. The 10M rehearsal: from its record only. Strengths:
scale, and the cost per event on self-run EKS that goes back to $0.

**NovaLake facts** (`ChiragVenkateshaiah/novalake` at commit `4947291`):
about 5M events, 101 models, `PASS=218 WARN=4 ERROR=0`, `fct_transactions`
2,138,809 rows (README L32); a pilot of about 1.01M events end to end in about
8 minutes (ADR 0011 L60-64); a Python UDF about 2.6x slower that pushes the
rest of the plan out of Photon (`docs/09-spark-optimization.md` L242-247 and
L722-723); built from 2026-06-24 to 2026-07-29 on serverless compute (README
L27, L34). Strengths: no cluster to run, delivery speed, the Photon insight.
Not available: the stage-2 duration and any cost data (Free Edition; not re-checked here).

**Fair test.** Cerberus Phase 11.5 (planned): the same input on both engines,
with run time and cost per million events (Phases.md L207).

**Suggested framing.** "Cerberus shows what a self-managed AWS platform costs
per event at 100M. NovaLake shows how fast serverless Databricks takes
messy events to tested gold tables: 101 dbt models with zero errors in about
five weeks, with no cluster to run. The like-for-like comparison is Cerberus
Phase 11."
