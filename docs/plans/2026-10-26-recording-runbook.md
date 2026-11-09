# Plan: recording runbook (step 7, ADR 0022 amendment build)

Date: 2026-10-26. Planner: cerberus-planner (Opus). Status: confirmed by the user on 2026-10-26.

ADR amendment needed: no. The runbook carries out ADR 0022 step 7 (docs/adr/0022-live-observability-for-a-recorded-run.md L167). The new operational rule "no retake after the generator writes" (F4) follows from the ADR's own Follow-ups (L245-247).

Branch: `phase-8-10-recording-runbook` from `main` (0099c58, after PR #119 merged). Docs only. $0. No AWS writes.

## User decisions (2026-10-26)

1. Display: the BenQ runs in Portrait (Settings → Displays) for the capture; the laptop screen is on for OBS and the terminals. Video is 4:5, 1080x1350.
2. Rehearsal flags: the rehearsal uses the take's flags: `make exercise ARGS="--yes --generate 1000000 --generator-executors 8 --executor-nodes 2 --name rehearsal"` (verify flag names against orchestration/exercise.sh).
3. Video scope: the LinkedIn video is the live run only (about 2:45). The $0 results walk-through from #107 is not concatenated.

## Findings that change the brief

- F1: one active logical monitor (BenQ GW2780, HDMI-1, 1920x1080 landscape); the laptop eDP-1 is connected but off. A 1350-px-tall viewport needs portrait. Firefox fullscreen (F11) on the portrait BenQ; OBS crops the top 1080x1350.
- F2: Firefox has no 125% zoom step (…110, 120, 133…). Use a separate Firefox profile with about:config `layout.css.devPixelsPerPx` = `1.25` → 864x1080 CSS px. Unverified; the rehearsal checks it.
- F3: the account ID shows in many places: the exercise log prints it 84 times on the 100M run (observability/scale/exercises/exercise-20261013T055859Z.log: preflight identity L3, Terraform ids L105/L138, `grafana_role_arn` output L222, S3 bucket names in generator upload lines); bucket names (terraform/modules/s3_medallion/main.tf L9-19); Spark UI Environment and SQL tabs (transform/spark/spark-application.yaml L30); the AWS console account menu and the execution ARN on the details page. The ID is already public in the repo (orchestration/exercise.sh L65; public repo), so this is hygiene, not secrecy. Fix: do not show the `make exercise` terminal; show a second terminal running `tail -n +1 -F <log> | sed -u "s/$ACCOUNT/<account>/g"` with ACCOUNT read silently from `aws sts get-caller-identity --query Account --output text`. Never pipe `make exercise` through sed: a dead pipe can kill the script before its teardown (exercise.sh L163-167 comment, the 2026-10-07 finding).
- F4: no retake after `[generate] done`. A new generator run gets a new run_id, so the failed run's bronze stays; even a clean second 100M takes silver from ~239M to ~339M, making the dbt merge ~29.7 GiB > the 25 GiB cutoff (linear from ADR 0022 L50: 20.8 GiB at 237M). Any failure after the generator writes → let the teardown finish, stop, re-plan. Failure before `[generate] done` can be retaken.
- F5: the run record has no `state_timings` field (collector internal name). It has `states[].seconds` (e.g. RunTransform 511.6, RunDbt 167.9 in observability/scale/runs/exercise-20261013T055859Z.json). Per-state start/end only from `get-execution-history`.
- F6: no Explore links exist yet (plan 2026-10-24 step 5 asked for 2-3); the runbook adds them.
- F7: an open dashboard costs money: the story tab polls CloudWatch GetMetricData every 15 s, about $0.02 per viewing hour (estimate, plan 2026-10-25 §4b J1). After the take close the tabs or `make grafana-down`.

## Files

1. New: `docs/demo-recording.md`.
2. Edit: `docs/plans/2026-10-24-live-100m-run-observability.md` — erratum after section 7 step 7 (text below).
3. Edit: `docs/plans/2026-10-25-run-story-dashboard.md` — erratum after "Step 8 (the 1M rehearsal) gains these checks" list (text below).
4. Edit: `Phases.md` L143-150 (8.10): add "recording runbook (`docs/demo-recording.md`)".
5. New: `docs/plans/2026-10-26-recording-runbook.md` — this plan, verbatim.
6. Do not edit checkpoint.md or the ADR.

Style: natural professional English, same register as observability/grafana/README.md and observability/spark_progress/CAPTURE.md. `##` sections, tables for shots and checks, fenced commands. Mark every estimate "estimate" and every unchecked claim "unverified". Cite the run record or log line for each number. Verify every line number and log text cited here against the repo before writing; fix any that differ.

## Section outline

0. Header. Purpose (Phases.md 8.10, ADR 0022 steps 7-9), order (1M rehearsal, then the 100M take), user runs every AWS-changing command. A "Commands that change AWS" box listing only `make exercise …` and `make compute-destroy` (failure path only).

1. Timeline at a glance, from the 2026-10-13 100M run (log exercise-20261013T055859Z.log, record exercise-20261013T055859Z.json): apply 793 s (L229); generator 1,335 s (L368) — map ~183 s, write ~192 s, commit 875 s, count pass 17 s (plan 2026-10-25 §2); execution 746 s (L370): InvokeIngestion 4.2, RunTransform 511.6, RunDbt 167.9, RunServingQuery 58.3 (record `states`); collector ~62 s (L374-409); flush 60 s; destroy 732 s (L3890); total 3,773 s (L3892). 1M reference exercise-20261015T145812Z.log: apply 895 s, generator 96 s, execution 588 s, destroy 693 s, total 2,487 s.

2. Pre-flight (verify-only, off camera, at most 1 h before):
   - `export AWS_PROFILE=cerberus-admin AWS_REGION=us-east-1` in every shell (Makefile L10-11 default; exercise.sh L60-63; demo-forward shell needs it for the kubectl token).
   - `make grafana-up`; sign in before recording.
   - Token: `make grafana-token` the day before both rehearsal and take (replaces old tokens, 30-day expiry; observability/grafana/token.sh L17, L45-52). Check without showing it: `( source orchestration/annotate.sh; annotate_http GET '/api/annotations?limit=1'; echo "token ok: $ANNOTATE_OK" )` — sourcing only defines functions; the CLI block runs only when executed (annotate.sh L325). Verify annotate_http/ANNOTATE_OK names and whether annotate_init must be called first; adjust. Expiry date under Administration → Service accounts → cerberus-exercise, off camera.
   - `make exercise-check` (read-only preflight, exercise.sh L93-139).
   - Athena headroom: `aws athena get-work-group --work-group cerberus_platform --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'` → 26843545600; `cerberus_platform_dq` → 21474836480 (terraform/modules/athena/variables.tf). Silver now 138,119,860 events (exercise-20261015T145812Z.json .silver.events), ~239M after the take. dbt merge projection ~21 GiB (~84% of 25), largest DQ check ~13.6 GiB (~68% of 20), linear from ADR 0022 L46-51. One take fits; a second does not (F4).
   - CloudWatch read: `aws cloudwatch list-metrics --namespace AWS/States --max-items 1`.
   - Read-only dev-compute plan (rehearsal and again before take): `terraform -chdir=terraform/envs/dev-compute plan -input=false -lock=false -var executor_nodes=2`; expect "0 to change, 0 to destroy"; adds include `module.eks_observability.kubernetes_deployment_v1.spark_progress` and `metricLabelsAllowlist` (eks_observability/main.tf L300, L350). Don't save the plan (EKS token expires ~15 min, exercise.sh L262-263).
   - Cost: MTD and forecast in Budgets console (`My Monthly Cost Budget`, $20), free. Not `ce get-cost-and-usage` ($0.01/call). Estimates: rehearsal ~$0.9-1.2 (unverified), take ~$2.50, month forecast ~$17.2 (ADR 0022 L140-142, L183-187).
   - Date: ingestion Lambda retires 2026-10-30; InvokeIngestion should still succeed after, but inferred (ADR L239-241). Prefer recording before then.
   - Laptop: GNOME Do Not Disturb on; Power → Screen Blank Never, Automatic Suspend off; close other apps (memory budget ADR L202-229); record to `~/Videos/cerberus-8-10/`, outside the repo.
   - Run `make exercise` inside `tmux` (SIGHUP not trapped, exercise.sh L259-260), so closing a terminal cannot end the run before teardown.

3. Screens and browser:
   - Display: BenQ in Portrait for capture; laptop screen for OBS and terminals.
   - Firefox: separate profile (`firefox -P cerberus-recording --no-remote`) with `layout.css.devPixelsPerPx=1.25`, signed in to AWS console and Grafana beforehand, fullscreen F11. Keep the mouse off the top edge.
   - Tabs (Ctrl+1..6): 1 Step Functions state machines page (`https://us-east-1.console.aws.amazon.com/states/home?region=us-east-1#/statemachines`), click into the new execution at "starting execution", show Graph view and step table only, never the Details panel; 2 story dashboard; 3 cerberus-run-live; 4 Grafana Explore (datasource `amp`, refresh 15 s); 5 `http://localhost:9090/targets` (agent has no query page; PromQL in tab 4); 6 `http://localhost:4040` Jobs/Stages/Executors only, not Environment or SQL; F5 after demo-forward prints "attached spark driver" for the silver job (verify that text in observability/demo/forward.sh).
   - URL builder right before `make exercise` (absolute from= because placeholders post at apply start, exercise.sh L268, and RUNNING_SUM needs run start in range, plan 2026-10-25 L215):
     ```
     FROM=$(( ($(date +%s) - 120) * 1000 ))
     echo "http://localhost:3000/d/cerberus-run-story?orgId=1&from=$FROM&to=now&refresh=15s&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
     echo "http://localhost:3000/d/cerberus-run-live?orgId=1&from=$FROM&to=now&refresh=15s&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks"
     ```
     Rehearsal adds `&var-requested=1000000` to the story URL. Same from= on run-live because its Run log is onlyInTimeRange with default now-30m and the take is ~63 min.
   - Explore links (F6): build with `jq @uri` and Grafana 13's `/explore?schemaVersion=1&panes=…` format, datasource uid `amp` (verify uid in provisioning). Check each at $0 on 2026-10-13 06:05-06:55Z before the rehearsal (mark unverified until then). Queries: `count by (label_eks_amazonaws_com_capacity_type) (kube_node_labels)`; `count by (application_name) (max by (application_name, application_id, executor_id) (last_over_time(metrics_executor_activeTasks{executor_id!="driver"}[45s])))`; `count({__name__=~"cerberus_spark_.*"})`; `max by (row) (cerberus_spark_rows)`.

4. OBS on Linux (32.1; obs-nvenc.so and linux-pipewire.so present): Settings → Video base and output 1080x1350, 30 fps. Output → Advanced → Recording: MKV then Remux (or Hybrid MP4 if offered); NVIDIA NVENC H.264, CQP ~20, keyframe 2 s, preset P5, profile high; path ~/Videos/cerberus-8-10/; no audio. Fallback x264 veryfast (~14% CPU, ADR L217-221). Approve PipeWire portal prompts in the rehearsal. Scenes: Browser (PipeWire screen capture of portrait BenQ, cropped to top 1080x1350); Console (same source + black Color Source over the AWS top bar, height measured in rehearsal); Terminal (window capture of the masked-log terminal, ptyxis, large font, dark, scaled to canvas width). Switch scenes by clicking in OBS (Wayland global hotkeys limited, ADR L236-237).

5. Shot table (columns: phase, terminal cue with exercise.sh line, real duration 100M; 1M, screens in order story first, what to show, edit speed, seconds on screen):
   - Before start: ~3 s at 1x; story all grey, tiles "not finished yet"/"not started yet" (exercise.sh L268).
   - Start servers: cue `spot executor nodes: 2` → `apply took`; 793 s. Terminal (Terraform creating EKS), then Story ("Start servers" marker; Servers now/Time running appear once scraped). Start `make demo-forward` before the exercise; it waits. 60x, ~13 s.
   - Generate (create): cue `generator: 100000000 events`; ~375 s. Story ("Now: Creating payments"; bar flat ~3 min in the 8-task map stage, then fills in the 328-task write), Spark UI Jobs/Executors, run-live. 15x, ~25 s.
   - Generator commit: 875 s, no Spark job (plan 2026-10-25 L20). Story ("Saving files…" activity), run-live (executors 0). Caption: "Saving files to S3: 14.6 min, shown 30x faster. No progress signal exists for this step." ~30x, ~29 s.
   - Ingest: cue `starting execution`; 4.2 s. Console Graph view. 1-5x, ~3 s.
   - Transform (RunTransform 511.6 s, main segment): Story (Reading new payments → Adding to the clean table → Tidying files; second bar fills); run-live (executors to 16, Spot nodes 2→4, input bytes/s); Spark UI; Explore (nodes by capacity type); Targets (spark-progress and driver up); Story for the end. ~10x, ~51 s.
   - Model (dbt): 167.9 s; Console then Story journey; 15x, ~11 s.
   - Serve: 58.3 s; Console then Story; 15x, ~4 s.
   - Quality checks: cue `collecting metrics` → `exercise done`; ~62 s. Console all green, Story DQ tile "Quality checks: PASSED (N checks, 0 errors, 1 warning)" (annotate.sh L150-170; 26 checks on 2026-10-13), Terminal `data quality PASSED` line. 10x, ~6 s.
   - Clean-up: cue `waiting 60s` → `destroying dev-compute` → `destroy took` → `after destroy: EKS 0, NAT 0, EIP 0, running instances 0` (exercise.sh L170-196); 792 s. Terminal then Story (Clean-up tile "Cluster deleted: …", annotate.sh L178-185). 60x, ~13 s.
   - Title and end card ~5 + 6 s. Target ~2:45 (close to #107's "about 3 min").
   - Dwell rule: one screen ≈ 15 s on screen = 150 s real at 10x.
   Verify every cue string against exercise.sh and annotate.sh; use the exact text.

6. Post-production (ffmpeg 8.0.1): note OBS start time; map log UTC times to recording offsets; optional burn of real elapsed time first (`drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='%{pts\:hms}'`, h264_nvenc). Per segment: `ffmpeg -ss A -t D -i raw.mkv -vf "setpts=(PTS-STARTPTS)/S,fps=30,drawtext=…'shown Sx faster'…" -an -c:v h264_nvenc -preset p5 -cq 20 -pix_fmt yuv420p segNN.mp4`; every sped-up segment carries its speed label. Cards: `-f lavfi -i color=c=0x111217:s=1080x1350:d=6` + drawtext; end card uses events, run time and DQ result from the run record; cost per million only after `--cost-only` the next day (exercise.sh L380). Join with concat demuxer (`-f concat -safe 0 -i list.txt -c copy`). Check with ffprobe: 1080x1350, h264, yuv420p, 30 fps. LinkedIn limits (third-party sources; check LinkedIn Help on publish day): MP4, up to 5 GB, ≥3 s, 10-15 min max (sources differ), aspect 1:2.4 to 2.4:1 (4:5 fits), 30 fps recommended. Sources: https://blog.sendspark.com/linkedin-video-specs, https://www.tella.com/blog/linkedin-video-specs-size-length, https://knowledge.hubspot.com/social/image-size-requirements-for-social-posts. Captions optional (feed autoplays muted). 10 s pipeline test in the rehearsal (plan 2026-10-24 step 8). Live run only; no results walk-through concat.

7. Step 8 rehearsal checklist (table: check, how, pass rule). Command: `make exercise ARGS="--yes --generate 1000000 --generator-executors 8 --executor-nodes 2 --name rehearsal"`.
   1. Generator bar: Explore `max(cerberus_spark_rows{row="payments_created"})` equals `[generate] done … events=` in the log (bar shows one decimal, panel 1 `decimals: 1`).
   2. Added rows: `max_over_time(cerberus_spark_rows{row="added_to_clean_table"}[1h])` equals `jq .events_processed observability/scale/runs/rehearsal-*.json` (includes Lambda events: on the 1M run silver gained 1,005,920 vs 999,833 generated).
   3. Step regions: list off camera via annotate.sh helpers and `/api/annotations?tags=run:<exec>&limit=100` (verify the tag format in annotate.sh); durations match `states[].seconds` within 1 s, and each marker appears within 15 s of the state change watched live (F5).
   4. Result tiles: DQ and Clean-up tiles equal the collector line and the `after destroy:` line.
   5. CloudWatch delay: note when the Transform row turns blue vs the RunTransform marker.
   6. Pods: `kubectl -n monitoring get pods -l app=spark-progress-exporter` Running (verify the label in eks_observability/main.tf); `kubectl -n spark-jobs get pods -l spark-role=driver` none Pending.
   7. Series: `count({__name__=~"cerberus_spark_.*"})` < ~200.
   8. Fail-open (rehearsal only, never the take): `make grafana-down` mid-RunTransform, wait 60 s, `make grafana-up`. Pass: run carries on; `grep -c "annotation skipped" <log>` returns 1 (verify the message text in annotate.sh). SFN states missed in the gap are posted after restart (history reader with seen-file, annotate.sh L192-232); direct step posts in the gap are lost (expected). Browser session survives restart (unverified).
   9. Stage retries: while the silver driver runs, `curl -s localhost:4040/api/v1/applications/<id>/stages | jq '[.[]|select(.attemptId>0)]|length'` returns 0; afterwards best-effort grep of the driver log (pattern unverified). Basis: CAPTURE.md "Known limits".
   10. Node labels: Explore by capacity type returns ON_DEMAND and SPOT; "Servers now" shows the regular/Spot text (verify exact text in the story JSON).
   11. Read-only dev-compute plan before the apply (section 2).
   Plus plan 2026-10-24 step 8 items: both forwards attach and 4040 re-attaches; OBS ~0 skipped frames; DQ passes; teardown clean; 10 s ffmpeg test gives 1080x1350; devPixelsPerPx layout fits 1350 px; console mask height measured.
   Decision point: if the exporter fails, switch to R4 and recheck before step 9 (plan 2026-10-25 L361).

8. Failure and abort: Ctrl-C in the tmux pane → exit 130 → EXIT trap runs teardown; Ctrl-C ignored from the destroy on (exercise.sh L160-172, L259-260). Never `--keep`. Never close the tmux session mid-run. `DESTROY FAILED` (L180): `make compute-destroy` (user, AWS change), then the verify block. Verify block (read-only): `aws eks list-clusters`; `aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available`; `aws ec2 describe-addresses`; `aws ec2 describe-instances --filters Name=instance-state-name,Values=pending,running`; `terraform -chdir=terraform/envs/dev-compute state list` empty. DQ failed (rc 3): teardown still runs, record written; do not retake; investigate. Retake rule (F4). Cost guard (F7); `--cost-only` the next day.

9. Security: never show Grafana sign-in, `.env`, `make grafana-token` output, or Administration → Service accounts. `.env` git-ignored (.gitignore L44-46, L66); check `git check-ignore -v observability/grafana/.env`. Account ID: masked terminal, console mask, Spark UI tab limits, no Prometheus Status → Configuration (remote-write URL). Recordings outside the repo.

10. After the take: commit run record and log as usual (a PR like #98), `--cost-only` next day, step 10 (plan 2026-10-24 step 10).

## Errata text

- docs/plans/2026-10-24-live-100m-run-observability.md, after step 7:
  > **Erratum (7, 2026-10-26)**, from writing `docs/demo-recording.md`: (a) the only active screen is 1920x1080, so a 1080x1350 viewport needs the monitor in portrait, with Firefox `layout.css.devPixelsPerPx` = 1.25 (Firefox has no 125% zoom step); (b) tabs are 1 Step Functions, 2 story, 3 `cerberus-run-live`, 4 Explore, 5 Targets, 6 Spark UI; (c) the terminal strip becomes a separate OBS scene that shows a masked `tail` of the log, never `make exercise` itself, which prints the account ID; (d) speeds are per segment (60x apply and destroy, 15x generator write, about 30x commit, about 10x RunTransform), not a flat 30x/15x; (e) the rehearsal uses the take's flags (`--generator-executors 8 --executor-nodes 2`); (f) the video is the live run only.
- docs/plans/2026-10-25-run-story-dashboard.md, after the step 8 list:
  > **Erratum (7, 2026-10-26):** the run record has no `state_timings` field (that is the collector's variable name). Compare the J5 regions with `states[].seconds` and the execution history. Also add: no retake after `[generate] done` (the dbt merge would pass 25 GiB at about 339M silver).

## Review checklist

- All ten sections present; commands match the repo (Makefile targets, exercise.sh log texts and lines, annotate.sh function names).
- Every number has its source; estimates labelled.
- No AWS-changing command outside the box.
- Story URL: absolute from=, to=now, four flags; rehearsal adds var-requested=1000000.
- Masked tail, no pipe on make exercise; tmux required.
- All rehearsal checks with command and pass rule; Grafana stop rehearsal-only.
- Retake rule and teardown verify block present; --keep never used.
- Security covers password, token, .env, account ID (terminal, console, Spark UI), recording path.
- LinkedIn limits marked third-party.
- Both errata added; checkpoint.md and ADR untouched.
- Natural English, not STE.

## Review errata (2026-10-26)

Changes made to `docs/demo-recording.md` after the Opus round-1 review. The plan text above stays as confirmed.

1. Retake boundary: a retake is allowed only before the `generator: 100000000 events` line, not before `[generate] done` (F4, section 8). A failed generator can leave part of a run in bronze. The 2026-10-25 plan erratum now says "no retake after the generator starts".
2. Abort after `starting execution` leaves the Step Functions execution RUNNING. Section 8 adds the stop step, the "Commands that change AWS" box gets `aws stepfunctions stop-execution`, and the verify block ends with `make exercise-check`.
3. Ctrl-C: press once and wait; a second Ctrl-C during the apply can leave resources outside the state.
4. Silver after the take is about 239M (138.1M + about 1.0M rehearsal + 100.0M), dbt merge about 21.0 GiB, largest DQ check about 13.6 GiB; the retake case is about 339M and 29.8 GiB.
Minor: the shot-table tile texts, the teardown Ctrl-C wording, the `make compute-destroy` confirmation, the masked tail commands, rehearsal check 12 (Spark UI text), and a numbered take sequence.
