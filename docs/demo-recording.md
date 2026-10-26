# Recording runbook: the live 100M run (Phase 8.10)

Purpose: record the LinkedIn video of one real 100M-event run, from an empty
account to an empty account. This is step 7 of the ADR 0022 build steps
([ADR 0022](adr/0022-live-observability-for-a-recorded-run.md), "Build steps").
The runbook feeds step 8 (the 1M dress rehearsal) and step 9 (the 100M take);
step 10 is the edit and publish. The plan behind it is
[2026-10-26-recording-runbook.md](plans/2026-10-26-recording-runbook.md).

Order: pre-flight, the 1M rehearsal (section 7), fix what it finds, pre-flight
again, then the 100M take. The user runs every command that changes AWS.

Conventions: "estimate" marks a number that is a guess or a projection;
"unverified" marks a claim nobody has run or checked yet. Third-party figures
carry their source. Run every command from the repo root.

> **Commands that change AWS.** Only these three, and only the user runs them.
>
> - `make exercise ARGS="..."` (the rehearsal in section 7, the take in section 5)
> - `make compute-destroy` (the failure path only, section 8)
> - `aws stepfunctions stop-execution --execution-arn arn:aws:states:us-east-1:<account>:execution:cerberus-platform-orchestration:<execution name>`
>   (abort after `starting execution` only, off camera, section 8; the state
>   machine name is `cerberus-platform-orchestration`, exercise.sh L65)
>
> Everything else in this file is read-only or local.

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

The 1M run is the reference for the rehearsal
(`exercise-20261015T145812Z.log`): apply 895 s, generator 96 s, execution
588 s, destroy 693 s, cluster up 2,487 s in total.

The generator step is 1,335 s, but the map, write and commit parts add up to
about 1,250 s. The rest (about 85 s, estimate: 1,335 minus 375 minus 875) is
pod start-up, the manifest and the 17 s count pass. The edit cuts or folds it.

## 2. Pre-flight (read-only, off camera, at most 1 hour before)

Run the checks for the rehearsal and again for the take. Nothing here changes AWS.

1. **Shell environment.** In every shell you use (the `tmux` window, the
   `make demo-forward` shell, the masked-tail shell):

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
   executed (annotate.sh L327), and `annotate_init` is not needed for a GET.
   Use `bash -c`, because the file reads `BASH_SOURCE`. Expected: `token ok: true`.
   Tested here only for the failure path (no token file): it prints the
   `annotation skipped (no token ...)` line and `token ok: false`. The
   success path needs a live Grafana and a token (unverified). To see the
   expiry date, open Administration, Service accounts, `cerberus-exercise`,
   off camera.
4. **Preflight of the exercise.** `make exercise-check` (exercise.sh
   `preflight`, L108; the `--check` branch is L238-241). It is read-only:
   identity, no EKS cluster, empty `dev-compute` state, no running execution.
5. **Athena headroom.**

   ```
   aws athena get-work-group --work-group cerberus_platform --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'
   aws athena get-work-group --work-group cerberus_platform_dq --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'
   ```

   Expected: `26843545600` (25 GiB) and `21474836480` (20 GiB); the defaults are in
   `terraform/modules/athena/variables.tf` L15 and L21. Silver holds
   138,119,860 events now (`exercise-20261015T145812Z.json`, `.silver.events`)
   and about 239M after the take (138.1M now, plus about 1.0M from the rehearsal
   (silver gained 1,005,920 on the 1M run, `exercise-20261015T145812Z.json`),
   plus 100.0M for the take; estimate). At that size the dbt merge is about
   21.0 GiB (about 84% of 25 GiB) and the largest data quality check about
   13.6 GiB (about 68% of 20 GiB), both linear projections from ADR 0022
   L46-51 (20.8 GiB and 13.5 GiB at 237M). One take fits. A
   second does not (section 8, "Retake rule").
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
   `aws ce get-cost-and-usage`: each call costs $0.01. Estimates: rehearsal
   about $0.9-1.2 (unverified, ADR 0022 L140-142), take about $2.50, month
   forecast about $17.2 (ADR 0022 L183-187).
9. **Date.** The ingestion Lambda retires on 2026-10-30. `InvokeIngestion`
   should still succeed afterwards, but that is inferred, not run (ADR 0022
   L239-241). Record before that date.
10. **Laptop.** GNOME Do Not Disturb on; Settings, Power: Screen Blank
    "Never" and Automatic Suspend off; close other apps (the memory budget is in
    ADR 0022 L202-229: about 4.2-5.4 GiB of 7.1 GiB, estimate). Record to
    `~/Videos/cerberus-8-10/`, outside the repo (create it first). Check free
    disk with `df -h ~/Videos`; the raw file size for 63 minutes is unverified.
11. **`tmux`.** Run `make exercise` inside `tmux`. The script traps only
    INT and TERM (exercise.sh L259-260), so a closed terminal sends SIGHUP and
    could end the run before the teardown.

## 3. Screens and browser

**Display.** The BenQ GW2780 (HDMI-1, 1920x1080) is the only active monitor;
the laptop screen (eDP-1) is connected but off. A 1350-px-tall viewport does
not fit a landscape 1080-px screen. So:

- Settings, Displays: set the BenQ to **Portrait** for the capture, and turn
  the laptop screen on. The BenQ shows the browser; the laptop screen shows
  OBS and the terminals.
- The video is 4:5, 1080x1350.

**Firefox.** Use a separate profile so the zoom does not touch your normal one:

```
firefox -CreateProfile cerberus-recording   # once
firefox -P cerberus-recording --no-remote
```

In that profile, open `about:config` and set `layout.css.devPixelsPerPx` to
`1.25`. Firefox has no 125% zoom step (its steps go ...110, 120, 133...), and
this gives about 864x1080 CSS pixels in the 1080x1350 crop. Unverified: the
rehearsal checks that the dashboards fit. Sign in to the AWS console and to
Grafana beforehand. Press F11 for fullscreen. Keep the mouse off the top edge,
or Firefox shows its toolbar.

**Tabs** (switch with Ctrl+1 to Ctrl+6, so OBS hotkeys are not needed):

| Tab | Page | Show | Do not show |
|---|---|---|---|
| 1 | Step Functions: `https://us-east-1.console.aws.amazon.com/states/home?region=us-east-1#/statemachines` | After `starting execution`, click into the new execution. Graph view and the step table. | The Details panel (it shows the execution ARN, which has the account ID) |
| 2 | Story dashboard `cerberus-run-story` (URL below) | Everything. Show it first in every phase. | |
| 3 | Engineers' dashboard `cerberus-run-live` (URL below) | Executors, Spot nodes, input bytes/s | |
| 4 | Grafana Explore, datasource `amp`, refresh 15 s | One query at a time (links below) | |
| 5 | `http://localhost:9090/targets` | The agent's Targets page. The agent has no query page; PromQL goes in tab 4. Plan 2026-10-24 L38 states that agent mode serves Targets; confirm it on the cluster in the rehearsal. | Status, Configuration (the remote-write URL has the workspace ID) |
| 6 | `http://localhost:4040` | Jobs, Stages, Executors | Environment, SQL (they print the S3 paths with the account ID, `spark-application.yaml` L30) |

Press F5 on tab 6 after `make demo-forward` prints `attached  spark driver ...`
for the silver job (forward.sh logs that text on each attach). The forward
re-attaches by itself when the generator driver ends and the silver driver starts.

**URL builder.** Run it right before `make exercise`. The `from=` is absolute
because the placeholders are posted at the apply start (exercise.sh L268) and
the cumulative step rows (`RUNNING_SUM`) need the run start inside the range
(plan 2026-10-25 L215):

```
FROM=$(( ($(date +%s) - 120) * 1000 ))
echo "http://localhost:3000/d/cerberus-run-story?orgId=1&from=$FROM&to=now&refresh=15s&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
echo "http://localhost:3000/d/cerberus-run-live?orgId=1&from=$FROM&to=now&refresh=15s&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
```

Tested here: it prints both URLs with a 13-digit `from=` two minutes in the
past. Whether Grafana 13.2.3 honours the three `_dash.hide*` flags is
unverified (no Grafana was running); the rehearsal checks it.

- The rehearsal adds `&var-requested=1000000` to the story URL, so the bar
  is full at 1M (the variable `requested` is hidden and defaults to 100000000).
- Use the same `from=` on `cerberus-run-live`. Its Run log panel only lists
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
(AMP keeps it until about 2027-01-11, ADR 0022 L65-66), with
`from`/`to` as epoch ms for 06:05Z to 06:55Z:

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

## 4. OBS on Linux

OBS 32.1.0 is installed, with `obs-nvenc.so` and `linux-pipewire.so` present.

- Settings, Video: base and output resolution 1080x1350, 30 fps.
- Settings, Output, Advanced, Recording: format MKV, then Remux to MP4 when
  done (or Hybrid MP4 if OBS offers it). Encoder NVIDIA NVENC H.264, rate
  control CQP about 20, keyframe interval 2 s, preset P5, profile high.
  Recording path `~/Videos/cerberus-8-10/`. No audio.
- Fallback if NVENC fails: x264 `veryfast`, about 14% of the CPU in the
  ADR 0022 test (L217-221).
- Approve the PipeWire portal prompts in the rehearsal, not on the day.

Scenes:

| Scene | Source | Notes |
|---|---|---|
| Browser | PipeWire screen capture of the portrait BenQ, cropped to the top 1080x1350 | The main scene |
| Console | Same source, plus a black Color Source over the AWS console top bar | The top bar shows the account menu. Measure the bar height in the rehearsal. |
| Terminal | Window capture of the masked-log terminal (`ptyxis`), large font, dark theme | Scale to the canvas width. Never capture the terminal that runs `make exercise`. |

Switch scenes by clicking in OBS. Global hotkeys are limited on Wayland
(ADR 0022 L236-237), so the runbook does not depend on them.

## 5. Shot table (the 100M take)

The take command (the user runs it, in `tmux`, with the exact flags of the
rehearsal except the size and name):

```
make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2 --name demo-100m"
```

Flag names are from `exercise.sh` (usage header L6-26, parser L83-90): `--yes`,
`--generate`, `--generator-executors`, `--executor-nodes`, `--name`.

**Take sequence.**

1. Open `tmux`; run the `export` line of section 2 in every shell.
2. `make exercise-check`.
3. `make demo-forward` (second terminal; it waits for the cluster).
4. Run the URL builder (section 3); load tabs 2 and 3 with those URLs.
5. Start the OBS recording.
6. In `tmux`, run the take command above.
7. When the log file appears, start the masked tail (terminal 3 below).
8. Follow the shot table.
9. After the `after destroy:` line, stop OBS and close the Grafana tabs (cost guard).

**Terminals** (three, none on the BenQ):

1. `tmux`: `make exercise ...`. Never on camera, because it prints the
   account ID (84 lines of the 2026-10-13 log contain it: the preflight
   identity at L3, Terraform ids at L138, `grafana_role_arn` at L222, and
   the S3 bucket names in the generator lines).
2. `make demo-forward`. Start it before the exercise; it waits for the cluster.
3. The masked log, the only terminal OBS shows. Start it once the exercise
   has printed its first line (the log name carries the start time; the
   newest log is the current one, for the rehearsal and the take):

   ```
   ACCOUNT=$(aws sts get-caller-identity --query Account --output text); [ -n "$ACCOUNT" ] || echo "no account"
   LOG=$(ls -t observability/scale/exercises/*.log | head -1)
   tail -n +1 -F "$LOG" | sed -u "s/$ACCOUNT/<account>/g"
   ```

   Tested here with a dummy file: the sed replaces the account number in
   bucket names and in `id=` text. **Never pipe `make exercise` itself
   through `sed` or anything else.** A dead pipe can kill the script before
   its teardown (the comment at exercise.sh L156-159, found 2026-10-07).
   The pipe above reads the log file, not the script's output.

Each row lists the screens in order, story first.

| Phase | Terminal cue (exercise.sh) | Real time (100M; 1M) | Screens | What to show | Edit speed | On screen |
|---|---|---|---|---|---|---|
| Before start | the first seconds after the run starts | 3 s | Story | All grey. Tiles "Quality checks: not finished yet" and "Clean-up: not started yet" (placeholders posted at L268). | 1x | about 3 s |
| Start servers | `spot executor nodes: 2` then `apply took` (L269, L272) | 793 s; 895 s | Terminal, then Story | Terraform creating EKS; then the "Start servers" marker. "Servers now" and "Time running" appear once scraped. | 60x | about 13 s |
| Generate (create) | `generator: 100000000 events` | about 375 s (183 + 192) | Story, Spark UI (Jobs, Executors), run-live | "Creating payments". The bar stays flat for about 3 minutes in the 8-task map stage, then fills in the 328-task write. | 15x | about 25 s |
| Generate (commit) | no log line | 875 s | Story, run-live | "Saving files into bronze — no counter for this part"; executors 0. Caption: "Saving files to S3: 14.6 min, shown 30x faster. No progress signal exists for this step." | about 30x | about 29 s |
| Ingest | `starting execution` (L331) | 4.2 s; 3.8 s | Console | Graph view | 1-5x | about 3 s |
| Transform | (RunTransform) | 511.6 s; 234.3 s | Story, run-live, Spark UI, Explore, Targets, then Story | Story: "Reading new payments", then "Adding to the clean table", then "Tidying files"; the second bar fills. run-live: executors to 16, Spot nodes 2 to 4, input bytes/s. Spark UI Executors. Explore: nodes by capacity type. Targets: `spark-progress` and the driver up. End on Story. | about 10x | about 51 s |
| Model (dbt) | (RunDbt) | 167.9 s; 286.7 s | Console, then Story | The journey row | 15x | about 11 s |
| Serve | (RunServingQuery) | 58.3 s; 56.3 s | Console, then Story | | 15x | about 4 s |
| Quality checks | `collecting metrics` (L362) to `exercise done` (L380) | about 62 s | Console, Story, Terminal | Console all green. Story tile "Quality checks: PASSED (N checks, 0 errors, 1 warning)" (`annotate_dq_verdict`, annotate.sh L141; N was 26 on 2026-10-13). Terminal `data quality PASSED` line. | 10x | about 6 s |
| Clean-up | `waiting 60s for the last metrics to reach AMP`, then `destroying dev-compute`, `destroy took`, `after destroy: EKS 0, NAT 0, EIP 0, running instances 0` (L170-196) | 792 s to `destroy took` (60 + 732); 799 s to the `after destroy:` line | Terminal, then Story | Story tile "Cluster deleted: EKS 0, NAT 0, Elastic IP 0, running instances 0 (account-wide check)" (`annotate_teardown_check`, annotate.sh L163). | 60x | about 13 s |
| Title and end card | | | | Title about 5 s, end card about 6 s | | about 11 s |

Real-time sources: log L229, L368-370, L3890-3892, run record `states[]` and
`exercise-20261015T145812Z.json`. The 1M cue `starting execution` and
`collecting metrics` exist in both runs. The on-screen total is about 2:49
(estimate: 3+13+25+29+3+51+11+4+6+13 plus the 11 s of cards), close to the
"about 3 min" of the video script in `docs/scale-metrics.md` (checkpoint L243).

**Dwell rule.** One screen holds for about 15 s on screen, which is 150 s of
real time at 10x. Record each screen long enough for that, then cut.

The cue strings above are the exact text of `exercise.sh`. The Story "Now"
tile shows the activity name without a prefix. The names come from the
dashboard JSON: "Creating payments", "Saving files into bronze — no counter
for this part", "Reading new payments", "Adding to the clean table", "Tidying
files", "Finishing up", "Waiting", "No Spark job running now".

## 6. Post-production (ffmpeg 8.0.1)

1. Note the OBS start time (wall clock, UTC). Map a log time to an offset
   in the recording: `echo $(( $(date -u -d 2026-10-26T10:12:36Z +%s) - OBS_START ))`,
   where `OBS_START=$(date -u -d <start> +%s)`. Tested with a dummy time.
2. Optional, but useful: burn the real elapsed time into the raw file first
   (the text is a filter argument, so `\:` is required):

   ```
   F=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
   ffmpeg -i raw.mkv -vf "drawtext=fontfile=${F}:text='%{pts\:hms}':x=20:y=20:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6" -c:v h264_nvenc -preset p5 -cq 20 -pix_fmt yuv420p -an timed.mkv
   ```

   In zsh write `${F}` with the braces: `$F:text` is read as a history
   modifier and the filter then fails with "Either text, a valid file...".
3. Per segment (A is the start offset in seconds, D the real duration, S the
   speed). Every sped-up segment carries its speed label:

   ```
   ffmpeg -ss A -t D -i timed.mkv -vf "setpts=(PTS-STARTPTS)/S,fps=30,drawtext=fontfile=${F}:text='shown Sx faster':x=(w-text_w)/2:y=h-120:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.6" -an -c:v h264_nvenc -preset p5 -cq 20 -pix_fmt yuv420p segNN.mp4
   ```

4. Cards:

   ```
   ffmpeg -f lavfi -i color=c=0x111217:s=1080x1350:d=6:r=30 -vf "drawtext=fontfile=${F}:text='TEXT':x=(w-text_w)/2:y=(h-text_h)/2:fontsize=72:fontcolor=white" -an -c:v h264_nvenc -preset p5 -cq 20 -pix_fmt yuv420p card.mp4
   ```

   The end card shows the events, the run time and the data quality result
   from the run record (`events_processed`, `run_seconds`, `data_quality`).
   Add the cost per million events only after `--cost-only` has run the next
   day (the closing log line, exercise.sh L380).
5. Join with the concat demuxer and check:

   ```
   printf "file 'card.mp4'\nfile 'seg01.mp4'\n" > list.txt   # list every file in order
   ffmpeg -f concat -safe 0 -i list.txt -c copy final.mp4
   ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,pix_fmt,r_frame_rate -of default=nw=1 final.mp4
   ```

   Tested here with synthetic input (a 40 s `testsrc2` file, a 15x segment, a
   6 s card, concatenated): `h264_nvenc` worked and `ffprobe` returned
   `h264`, 1080x1350, `yuv420p`, 30/1. Expected on the real file: the same.
6. LinkedIn limits. These come from third-party pages and may be out of
   date; check LinkedIn Help on the publish day: MP4, up to 5 GB, at least
   3 s, a maximum length of 10 to 15 minutes (the sources differ), aspect
   ratio between 1:2.4 and 2.4:1 (4:5 fits), 30 fps recommended. Sources:
   https://blog.sendspark.com/linkedin-video-specs,
   https://www.tella.com/blog/linkedin-video-specs-size-length,
   https://knowledge.hubspot.com/social/image-size-requirements-for-social-posts.
   Captions are optional: the feed autoplays muted.
7. Run a 10-second pipeline test (steps 3 to 5) on the rehearsal recording.
8. Scope: the video is the live run only. The $0 results walk-through from
   #107 is not added.

## 7. Rehearsal (ADR 0022 step 8) and its checks

The rehearsal uses the take's flags, with 1M events:

```
make exercise ARGS="--yes --generate 1000000 --generator-executors 8 --executor-nodes 2 --name rehearsal"
```

Use the story URL with `&var-requested=1000000`. Record it with OBS as in
section 4. The run record is `observability/scale/runs/rehearsal-<stamp>.json`.

| # | Check | How | Pass rule |
|---|---|---|---|
| 1 | Generator bar | Explore: `max(cerberus_spark_rows{row="payments_created"})` | Equals `events=` in the `[generate] done` line of the log. The bar shows one decimal (panel 1, `decimals: 1`, suffix M). |
| 2 | Added rows | Explore: `max_over_time(cerberus_spark_rows{row="added_to_clean_table"}[1h])`; then `jq .events_processed observability/scale/runs/rehearsal-*.json` | Equal. The count includes Lambda events: on the 1M run silver gained 1,005,920 against 999,833 generated (run records `exercise-20261015T145812Z`). |
| 3 | Step regions | List the annotations (below) and compare with `jq '.states[]|[.state,.seconds]' observability/scale/runs/rehearsal-*.json` | Durations match `states[].seconds` within 1 s. Each marker appears within 15 s of the state change watched live. |
| 4 | Result tiles | Read the DQ and Clean-up tiles | They equal the collector's `data quality PASSED` line and the `after destroy:` line. |
| 5 | CloudWatch delay | Note when the Transform row turns blue, against the `RunTransform` marker | Record the delay (estimate 1-3 min, plan 2026-10-25 L126; unverified). |
| 6 | Pods | `kubectl -n monitoring get pods -l app=spark-progress-exporter`; `kubectl -n spark-jobs get pods -l spark-role=driver` | Exporter Running; no driver Pending. (`app` label: `eks_observability/main.tf` L354.) |
| 7 | Series count | Explore: `count({__name__=~"cerberus_spark_.*"})` | Below about 200 (plan 2026-10-25). |
| 8 | Fail-open (rehearsal only, never the take) | `make grafana-down` during RunTransform, wait 60 s, `make grafana-up` | The run carries on. `grep -c "annotation skipped" <log>` returns 1 (the message is `annotation skipped (...)`, annotate.sh `annotate_warn`). Step Functions states missed in the gap are posted after the restart (the history reader keeps a seen-file, annotate.sh L184 and following). Direct step posts made in the gap are lost, which is expected. Does the browser session survive the restart: unverified. |
| 9 | Stage retries | While the silver driver runs: `curl -s localhost:4040/api/v1/applications \| jq -r '.[0].id'`, then `curl -s localhost:4040/api/v1/applications/<id>/stages \| jq '[.[]\|select(.attemptId>0)]\|length'` | Returns 0. Afterwards, grep the driver log for retries (the pattern is unverified). Basis: `observability/spark_progress/CAPTURE.md`, "Known limits". |
| 10 | Node labels | Explore: nodes by capacity type | Returns `ON_DEMAND` and `SPOT`. "Servers now" shows the texts "regular" and "spare-capacity (Spot)". |
| 11 | Dev-compute plan | Section 2, item 7, before the apply | "0 to change, 0 to destroy". |
| 12 | Spark UI text | Open Jobs and Stages on `localhost:4040` while the generator and silver drivers run | No bucket name in the job descriptions (for example "Listing leaf files and directories ... s3a://cerberus-platform-bronze-<account>/"). If one shows, show Executors only. Unverified. |

Also check the items of plan 2026-10-24, step 8: both port-forwards attach and
4040 re-attaches for the silver job; OBS shows about 0 skipped frames; data
quality passes; the teardown is clean; the 10-second ffmpeg test gives
1080x1350; the `devPixelsPerPx` layout fits 1350 px; the console mask height
is measured.

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

## 8. Failure and abort

- **Abort.** Press Ctrl-C once, in the `tmux` pane that runs `make exercise`,
  and wait. Terraform stops cleanly, then the trap exits with code 130 and
  runs the teardown. A second Ctrl-C during the apply can leave resources
  outside the state, which the destroy cannot remove. From the teardown start
  (the `waiting 60s` line), Ctrl-C is ignored (exercise.sh L161, L259-260).
  Never use `--keep`. Never close the `tmux` session during a run.
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
  takes silver from about 239M to about 339M (estimate), and the dbt merge
  would be about 29.8 GiB, past the 25 GiB cutoff (linear from 21.0 GiB at
  239M, ADR 0022 L46-51).
- **Cost guard.** An open story tab polls CloudWatch `GetMetricData` every
  15 s, about $0.02 per viewing hour (estimate, plan 2026-10-25 L123, J1). After the take, close the tabs or run `make grafana-down`. Run
  `--cost-only` the next day.

## 9. Security

- Never show the Grafana sign-in page, `observability/grafana/.env`, the output
  of `make grafana-token`, or Administration, Service accounts.
- `.env` is git-ignored (`.gitignore` L44-46 and L66). Check with
  `git check-ignore -v observability/grafana/.env`.
- The account ID is already public in this repo (exercise.sh L65), so masking
  it is hygiene, not secrecy. It still shows in: the `make exercise` terminal
  (use the masked tail), the S3 bucket names
  (`terraform/modules/s3_medallion/main.tf` L9-19; they appear in the
  generator lines), the Spark UI Environment and SQL tabs (do not open
  them), the AWS console account menu and the execution ARN on the details
  page (use the console mask and do not open the Details panel), and
  Prometheus Status, Configuration (do not open it).
- Recordings stay outside the repo (`~/Videos/cerberus-8-10/`).

## 10. After the take

1. Commit the run record in a PR like #98 (the record in
   `observability/scale/runs/`; the exercise log is git-ignored, so it stays local).
2. Run `--cost-only` the next day:
   `uv run -q --no-project --with boto3 python observability/scale/collect_run_metrics.py --execution demo-100m-<stamp> --cost-only`
   (the form the script prints, exercise.sh L380).
3. Do step 10 of plan 2026-10-24 (edit, publish, link in 8.10, follow-ups in
   the checkpoint "Later" list).
