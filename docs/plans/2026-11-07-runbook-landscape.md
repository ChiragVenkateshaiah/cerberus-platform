# Plan: 8.10 runbook update — 10M rehearsal, landscape screen, GNOME recorder

Date: 2026-11-07. Planner: Opus. Base: `main` at `bcbf804`. Phases.md 8.10; ADR 0022 build step 7 (runbook revision).

User decisions (2026-11-07):
- The take stays at 100M, and the cost story stays AWS-only. The rehearsal moves from 1M to 10M; the post may say "we processed 10M as a rehearsal", sourced only from the run record.
- One screen: the BenQ in landscape, 1920x1080, laptop lid closed (the monitor does not support portrait). Recorder: the Ubuntu GNOME built-in screen recorder, not OBS. Recording starts about 5 s before `make exercise` is started.
- The post presents Cerberus and Databricks (NovaLake) as complements, with no head-to-head claim.
- The rehearsal run record is committed in the take's PR (not its own PR).
- A $0 65-minute recorder pre-test runs before the rehearsal.
- Plan confirmed: options A + C + F (section 5).

## 1. Question

How should `docs/demo-recording.md` change for a 10M rehearsal, a single landscape 1920x1080 screen, the GNOME built-in recorder (whole screen, no masks), and a short "Cerberus and Databricks" post section? The runbook's 1M rehearsal, portrait layout, OBS scenes and "record before 2026-10-30" rule are out of date.

## 2. Facts

V = verified by reading; U = unverified.

Run history and sizing
- V. No 10M run exists. The "10M" ladder runs requested 9,000,000 events each (`exercise-20261009T074853Z`, `…101830Z`, `exercise-20261012T111304Z`, `…133620Z` in `observability/scale/runs/`). All four used generator `EXECUTORS=2` (the `run: EVENTS=… EXECUTORS=2` line in each log under `observability/scale/exercises/`). Both 2026-10-12 runs used `spot executor nodes: 1` (log L8).
- V. Clean 9M reference, `exercise-20261012T111304Z.log`: apply 951 s (L232), generator 243 s (L277), execution 506 s (L279), destroy 694 s (L3605), cluster up 2,549 s (L3607). States: Ingest 3.9 s, Transform 295.7 s, dbt 143.5 s, Serve 60.3 s. Silver was about 19M before this run.
- V. The runbook's "1M reference" (`exercise-20261015T145812Z`) used `EXECUTORS=2` and `spot executor nodes: 1` (L8), not the take's flags. No run has used `--generator-executors 8` below 100M.
- V. Generator task counts (`transform/spark/generate_bulk_payments.py`): map stage `spark.range(transactions)` (L265) gets the default parallelism (inferred 8 tasks with 8 one-core executors, matching the 8 tasks at 100M). Write stage `files_per_dt = ceil(events*430/8/134,217,728)` (L304-308; 128 MB default at L176): at 100M ceil(40.05) = 41 → 328 tasks (matches runbook L38); at 10M ceil(4.005) = 5 → 40 write tasks.
- V. `orchestration/exercise.sh` L22-24: four 1-core executors per Spot node, so 8 generator executors need 2 nodes. L247-249: `exec > >(… tee -a "$LOG")`, so the log mirrors the terminal from that point.
- V. RunTransform asks for 16 executors even at 1M (checkpoint L221-222); the autoscaler goes to 4 nodes anyway.

Silver, Athena and budget
- V. Silver holds 138,119,860 events (`exercise-20261015T145812Z.json` `.silver.events`). That run is the latest execution (AWS `list-executions`: 2026-10-15, then 10-13, then 10-12).
- V. Schedule `cerberus-ingest-payments-daily` is `DISABLED` (AWS read).
- V. Athena cutoffs `26843545600` and `21474836480` (AWS `get-work-group`), matching `terraform/modules/athena/variables.tf` L15 and L21.
- V. ADR 0022 L46-53: at 237M, the largest DQ checks are 13.5 GiB and the dbt merge is 20.8 GiB, linear in silver (7.81 × 237/137 = 13.5).
- V. Budget `My Monthly Cost Budget` on 2026-11-07: limit $20, November actual $1.149, forecast $6.927.

Ingestion Lambda
- V. Retired on 2026-10-30: the default in `terraform/modules/lambda_ingestion/variables.tf` L14; `ingestion/lambda/handler.py` L58-67 returns `{"status": "retired"}` and writes nothing; the ASL `InvokeIngestion` has no Choice on the result (`orchestration/state_machine.asl.json.tftpl` L5-13).
- V. `promote_payments_spark.py` `read_bronze` L240-245 skips a prefix with no new files.
- U. No execution has run since 2026-10-30, so the retired path has never run end to end.

Desktop and recorder
- V. `gnome-shell --version`: GNOME Shell 50.1, Wayland.
- V. Keybindings: `show-screenshot-ui ['Print']`, `show-screen-recording-ui ['<Ctrl><Shift><Alt>R']`.
- V. `max-screencast-length` is not a key in `org.gnome.settings-daemon.plugins.media-keys` here; no schema has a screencast-length key.
- V. Past recordings in `~/Videos/Screencasts/` are named `Screencast From YYYY-MM-DD HH-MM-SS.webm` (local time). ffprobe of the 2026-10-06 file: VP8, matroskamux (GStreamer 1.28.2), variable frame rate (avg about 30 fps), 949,870 bit/s, 418 s long (so no 30 s cap), one keyframe in 418 s, `creation_time` tag = the UTC start. That file is 1920x955 (an area selection); the rehearsal must confirm a full-screen 1920x1080 capture.
- U. A 63-minute recording (longest seen: 418 s). U. Why software VP8 and its CPU load. U. Whether keyboard focus returns to the terminal after recording starts. U. Whether `Ctrl+Shift+Alt+R` stops a running recording.
- V. Display: one monitor `HDMI-1 1920x1080`; `monitors.xml` scale 1; `text-scaling-factor` 1.0. Firefox 154.0 (snap); only profile `ydnz9ecu.default`, so `cerberus-recording` does not exist yet.
- V. `df -h ~/Videos`: 169G free. `~/Videos/cerberus-8-10/` exists and is empty.
- V. ffmpeg has `h264_nvenc` and `libvpx`. `tmux` and `ptyxis` are installed.

Dashboard fit
- V. `cerberus-run-story.json` ends at grid row 27: 27×30 + 26×8 = 1,018 px. `cerberus-run-live.json` ends at row 32 = 1,208 px; its top 24 rows are 904 px; Run log is y 24-32. Grid constants (30 px rows, 8 px margin) and kiosk padding are U.
- V. `cerberus-run-story.json` L560-686 and `cerberus-run-live.json` L538-582 carry ARNs with the account ID as CloudWatch dimensions. U: whether hover tooltips show them.
- V. `observability/demo/forward.sh` prints only port and pod names (L70-139).

Other repo facts
- V. AMP retention is 400 days (`terraform/modules/prometheus_workspace/variables.tf` L1-5; ADR 0024 L219-225; commit 74f31a5). The runbook L227 still says "until about 2027-01-11". U: whether old samples were kept (ADR 0024 L224).
- V. ADR 0022 fixes the details this update changes: Decision L142-144 "A dress rehearsal at 1M" ($0.9-1.2); build step L170 "8. Dress rehearsal at 1M."; Laptop load L219-227 (encoder test; "the recording runbook … sets OBS to NVENC"; memory estimate includes OBS); Unverified list L238-240 (OBS hotkeys, 1M cost); amendment L330 "first proven in the 1M rehearsal". The ADR does not mention portrait or 1080x1350 (only plan errata `docs/plans/2026-10-24-…` L300, `2026-10-26-…` L111).
- V. `Phases.md` L145 says "dress rehearsal at 1M". Branches `9.2-standing-edge`, `9.3-command-set`, `9.4-landing-page` edit Phases.md on 9.x lines only.

NovaLake (`ChiragVenkateshaiah/novalake` at commit `4947291`; read only)
- V. README L32: about 5,000,000 events, `fct_transactions` = 2,138,809 rows, 101 models, `PASS=218 WARN=4 ERROR=0`. README L27: Databricks Free Edition, serverless compute. README L34: `v0.0` 2026-06-24 to `v0.9` 2026-07-29.
- V. ADR 0011 L60-64: a ~1.01M-event pilot end to end (generation, Bronze ingest, `dbt run`/`dbt test`) in about 8 minutes.
- V. `docs/09-spark-optimization.md` L722-723: UDF about 2.6x slower warm-to-warm (2.105 s vs 0.806 s); L242-247: `BatchEvalPython` pushes the rest of the plan out of Photon.
- Stage-2 duration not recorded (checkpoint L167); no cost data (Free Edition, no billing API, checkpoint L163).
- V. Cerberus Phase 11.5: "Measured comparison: same input on both engines, run time and cost per million events" (Phases.md L207).

## 3. Constraints

- $20/month and $0 idle; no new AWS resource. `dev-compute` still destroys to nothing; `exercise.sh`'s EXIT trap is unchanged.
- Never pipe `make exercise` itself (exercise.sh L156-159).
- CI applies `dev-standing` only; this PR changes no Terraform.
- ADR 0022 fixes the 1M rehearsal and names OBS, so a dated amendment is needed (section 6), not a new ADR.
- ADR 0024 removes the in-cluster Grafana only after the take; not touched here.

## 4. Options

Generator flags for the 10M rehearsal:
- A. Keep the take's flags (`--generator-executors 8 --executor-nodes 2`). Tests the exact take setup; about $0.05 more than 1 node (estimate); a size never run with 8 executors. **Chosen.**
- B. 2 executors, 1 node (proven 9M config). Does not rehearse the take's generator (plan 2026-10-26 erratum (e)).

Hiding secrets with a whole-screen recorder:
- C. Hidden run session plus a mask in the edit: `make exercise` runs in a detached tmux session `cerberus-run`, started by `tmux send-keys` from the visible terminal, which shows only the masked log tail and `make demo-forward`. The console top bar is covered in post with ffmpeg `drawbox`. $0. The raw file contains the account ID but stays local. **Chosen.**
- D. Hide the console nav bar with Firefox `userContent.css` (fragile AWS DOM selector).
- E. Drop the console shots (contradicts ADR 0022's Decision).

Firefox scaling:
- F. devPixelsPerPx default (1.0 here). Story (1,018 px) fits a 1,080 px viewport (estimate). **Chosen.**
- G. Keep 1.25: viewport 1536x864 CSS px; Story's last row (y 23-27) falls off.

## 5. Recommendation

A + C + F. A is the point of a rehearsal. C keeps the run safe (outside any visible window; tmux protects it from SIGHUP) and keeps ADR 0022's console shots; masking in post does the job of OBS's colour source. F is the only setting that fits Story in 1080 px; phone legibility comes from big stat values, colours and edit captions; an optional crop punch-in in post covers close-ups.

## 6. ADR 0022 dated amendment (outline)

Header: add after L14: "Amended 2026-11-07: 10M rehearsal, landscape capture and the GNOME recorder (see Amendment below)."

Section `## Amendment (2026-11-07): 10M rehearsal, landscape capture and the GNOME recorder`, Status: Proposed (2026-11-07), flips to Accepted when the user accepts it in the PR.

Context:
- The rehearsal (Decision "A dress rehearsal at 1M"; build step 8) moves to 10M with the take's flags: 8 generator executors have only run at 100M (the 1M reference used 2 executors and 1 node); 10M gives a second publishable data point; the headroom allows it.
- The only screen is a landscape 1920x1080 monitor with the lid closed; portrait is not possible.
- OBS is replaced by GNOME Shell 50.1's built-in recorder: whole monitor, no scenes or crop; VP8 WebM with variable frame rate on this machine.
- The ingestion Lambda no-ops since 2026-10-30; the rehearsal is the first orchestrated run after that date.

Decision:
- Build step 8 becomes "Dress rehearsal at 10M": `--generate 10000000 --generator-executors 8 --executor-nodes 2 --name rehearsal`.
- Recorder: GNOME screen recorder, full screen, 16:9 1920x1080 output.
- Secrets stay off screen by layout: the run sits in a detached tmux session; the console top bar is masked in the edit with ffmpeg `drawbox`.
- The OBS settings and "sets OBS to NVENC" no longer describe the recorder; NVENC stays the encoder for the edit.

Consequences:
- Rehearsal cost about $1.0-1.4 (estimate), replacing $0.9-1.2.
- After the take, silver about 248M; dbt merge about 21.8 GiB (87% of 25); largest DQ about 14.1 GiB (71% of 20). A second 100M still does not fit (dbt about 30.6 GiB).
- Given up: live masking (the raw file has the account ID and must stay outside the repo); the OBS memory guess and NVENC capture test in "Laptop load" no longer apply; recorder CPU load and the 63-minute length are unverified until the $0 pre-test and the rehearsal.
- The 2026-10-25 amendment's "first proven in the 1M rehearsal (step 8)" now reads 10M.
- Portrait and 1080x1350 were never in this ADR; they change only in the runbook.

## 7. Numbers (estimates)

Athena headroom: linear projection through zero from ADR 0022 L46-51, scaled by silver/237M.
- Silver now 138,119,860. Rehearsal adds 1,005,920 × 10 = 10,059,200 → 148,179,060 (slight overestimate: with the Lambda retired the gain should be the generator count, about 10.0M). Take adds 100,008,511 (the 2026-10-13 gain) → 248,187,571; factor 248.19/237 = 1.0472.

| Point | Silver | dbt merge (20.8 × f) | % of 25 GiB | Largest DQ (13.5 × f) | % of 20 GiB |
|---|---|---|---|---|---|
| After rehearsal | 148.2M (f 0.6252) | 13.0 GiB | 52% | 8.4 GiB | 42% |
| After take | 248.2M (f 1.0472) | 21.8 GiB | 87% | 14.1 GiB | 71% |
| 100M retake | 348.2M (f 1.4692) | 30.6 GiB | 122%, fails | 19.8 GiB | 99%, no margin |
| Second 10M rehearsal, then take | 258.2M (f 1.0894) | 22.7 GiB | 91% | 14.7 GiB | 74% |

- dbt is the binding limit: silver can reach 25/20.8 × 237 = 284.86M before the take's merge fails, so silver before the take must stay at or below 184.8M: 46.7M of room, so up to four 10M rehearsals in total fit.
- A 100M retake fits only if the run fails before the `generator:` line (unchanged).
- Margin: dbt fails if true growth is 15% above linear (25/21.78 = 1.148). The DQ scan once outran projection (105.9 GB vs 76 GB, checkpoint L195-196). Before the take, re-project with the rehearsal record's `states[RunDbt].athena.bytes_scanned` (sum of 33 queries, an upper bound on the merge; the largest single query is not recorded).

10M rehearsal timing: apply 793-951 s; generator about 2-4 min (map about 18 s; write 40 tasks; commit about 90-110 s if it scales with bytes or files, 875 s at 100M; the 9M runs took 203-244 s with 2 executors); execution 550-750 s (9M: 506-536 s at 19-37M silver; 1M: 588 s at 138M); collector 60-80 s; flush 60 s; destroy 690-920 s. Cluster up about 38-50 min.

10M rehearsal cost:
- Non-Athena $0.61-0.97: day rate per CE cluster-hour $1.338/h on 2026-10-15 ((1.854337 − 1.20034)/0.489) and $1.380/h on 2026-10-13 ((1.781607 − 0.574015)/0.875), use about $1.36/h; CE cluster-hours read 0.71-0.84 of logged up time (0.489/0.691, 0.875/1.048; checkpoint L263-264), so 0.64-0.83 h up gives about 0.45-0.70 CE h.
- DQ scan $0.36: silver part 62.6 GB × 148.18/138.12 = 67.2 GB, plus about 4.4 GB of new bronze (10% of about 43.8 GB, the 100M run's 105.9 GB minus its silver part 62.6 × 137.11/138.12 = 62.1 GB); about 71.6 GB at $5/TB.
- Run queries: 15.44 GB × 148.18/138.12 = 16.6 GB, about $0.08.
- Total about $1.0-1.4. The record's `cost.run_usd` (execution time plus run Athena, `collect_run_metrics.py` L357-364): about $1.36 × 600/3600 + $0.08 ≈ $0.31, about $0.03 per million.
- Athena on 2026-10-15 was $1.20, but only about $0.39 belongs to the run; the rest is inferred to be the same-day `--full` audit (#103/#104), not verified.
- Take re-estimate: non-Athena $1.21 (2026-10-13 actual); DQ (62.6 × 248.19/138.12 + 43.8) = 156 GB → $0.78; run queries 15.98 GB × 248.19/137.11 = 28.9 GB → $0.14; about $2.1-2.5. Keep ADR 0022's "about $2.50".
- Month: forecast $6.93 + about $1.2 + about $2.3 ≈ $10-11, below the $15 (75%) alert.

## 8. Changes to `docs/demo-recording.md`

Header (L3-15): L6 "(the 1M dress rehearsal)" → "(the 10M dress rehearsal)"; L10 "the 1M rehearsal" → "the 10M rehearsal"; add a line citing the ADR 0022 amendment (2026-11-07) and this plan (`docs/plans/2026-11-07-runbook-landscape.md`). AWS-changing commands box unchanged, plus a note: an abort is now `tmux send-keys -t cerberus-run C-c` (local, but it starts the teardown).

§1 Timeline: keep the 100M table. Replace L51-53 (1M reference) with (a) the nearest real reference, the 9M `exercise-20261012T111304Z` numbers (2 generator executors, 1 node, about 19M silver) and (b) a "10M rehearsal (estimate)" row with the section 7 timings, cluster up about 38-50 min.

§2 Pre-flight:
- Item 1: shells are "the hidden `cerberus-run` session and both panes of `cerberus-view`".
- Item 5: section 7 numbers (about 248M; 21.8 GiB, 87%; 14.1 GiB, 71%); "up to four 10M rehearsals fit"; the 15% dbt margin.
- Item 8: rehearsal about $1.0-1.4, take about $2.1-2.5 (estimates, with the arithmetic reference); replace "month forecast about $17.2" with "on 2026-11-07, November actual $1.15, forecast $6.93 (Budgets); about $10-11 after both (estimate)".
- Item 9: rehearsal watch item. The Lambda retired 2026-10-30 and returns `{"status": "retired"}` (handler.py L58-67; variables.tf L14). The rehearsal is the first execution since 2026-10-15 and the first after retirement. Watch: `InvokeIngestion` SUCCEEDED; RunTransform reads only `payments_bulk/` (read_bronze L240-245); silver gain equals the generator's `events=` exactly (check 2 pass rule changes to match). If InvokeIngestion fails, do not take; re-plan. Delete "Record before that date."
- Item 10: lid closed, BenQ only; keep Do Not Disturb and power settings; the recorder saves to `~/Videos/Screencasts/`, move the file to `~/Videos/cerberus-8-10/` after the stop; 169G free (2026-11-07); raw about 0.95 Mbit/s → about 450 MB for 63 min (estimate); drop the OBS memory term.
- Item 11 → "Hidden run session." Off camera before recording: `tmux new-session -d -s cerberus-run -c /home/chirag/projects/cerberus`. Never attach while recording. Survives a closed terminal (exercise.sh L259-260 traps only INT/TERM). Run `make exercise-check` there off camera with `tmux send-keys -t cerberus-run 'make exercise-check' Enter`, then `tmux attach -t cerberus-run`, read, detach with `Ctrl-b d` (the check prints the identity, which includes the account ID).

§3 Screens and browser (rewrite):
- Display: BenQ GW2780 (HDMI-1), landscape 1920x1080, scale 1, only monitor, lid closed. Video 16:9 1920x1080. Delete the Portrait and laptop-screen bullets.
- Firefox: keep the `cerberus-recording` profile commands (it does not exist yet). Do not set `layout.css.devPixelsPerPx`; default gives 1.0 here. Reason: Story is about 1,018 px and fits 1,080 px at 1.0, not at 1.25 (864 px), where the KPI row is lost. `cerberus-run-live` (1,208 px) fits at neither; its shot panels are in the top 904 px and its Run log is below the fold, which no shot uses. The rehearsal checks the fit.
- New subsection "Layout: what is on screen": one GNOME workspace; Firefox in F11 and one fullscreen `ptyxis` window with a large font, running tmux session `cerberus-view` (top pane about 75% masked log, bottom pane `make demo-forward`). Switch with Alt+Tab; cut the switcher overlay in the edit. The recorder records the monitor, so a workspace switch or the Activities overview is recorded: never switch workspaces while recording. Never on screen: the `cerberus-run` session and `make exercise-check` output; the AWS console Details panel and the account menu (shows `<user> @ XXXX-XXXX-XXXX`, masked in the edit, §6); Prometheus Status and Configuration; Spark UI Environment and SQL; the Grafana sign-in page, `.env`, `make grafana-token` output, Administration › Service accounts; hover tooltips on Story/run-live CloudWatch panels (queries carry ARNs; whether tooltips show them is U; keep the mouse off the panels).
- Tabs table: tab 1 "Do not show" adds the account menu (masked in the edit); "so OBS hotkeys are not needed" → "keyboard only".
- URL builder: the rehearsal adds `&var-requested=10000000` (bar full at 10.0M).
- Explore links: "AMP keeps it until about 2027-01-11, ADR 0022 L65-66" → "AMP retention is 400 days (ADR 0024; `prometheus_workspace/variables.tf` L1-5). Whether the 2026-10-13 samples were kept is unverified (ADR 0024 L224); the $0 link check shows it."

§4 becomes "GNOME screen recorder" (replaces OBS):
- GNOME Shell 50.1, Wayland. Start: Print → video toggle → Screen (not Selection) → Record; `Ctrl+Shift+Alt+R` opens the same UI in video mode. Pointer off.
- Stop: Alt+Tab to the terminal (F11 Firefox hides the top bar), click the red indicator in the top bar. Whether `Ctrl+Shift+Alt+R` stops a recording is U; test in the pre-test.
- Output: `~/Videos/Screencasts/Screencast From <local date time>.webm`, VP8, variable frame rate, about 30 fps average; `creation_time` tag is the UTC start.
- Limits: no `max-screencast-length` key in this version; 418 s verified; 63 min U.
- $0 pre-test before the rehearsal (user decision): record 65 minutes of the Story and run-live dashboards on the 2026-10-13 window, with no cluster. Then `ffprobe` must show 1920x1080 and duration ≥ 3,900 s; avg frame rate about 30; note `gnome-shell` CPU in `top`, off camera, after the stop. Cost: CloudWatch `GetMetricData` about $0.02/h (plan 2026-10-25 L123).
- Fallback: if the recorder caps or stutters, OBS 32.1.0 (installed) at 1920x1080, no crop (the old §4 minus crop and scenes). Re-plan only if both fail.

§5 Shot table (the take). Take sequence replaces steps 1-9:
1. Off camera, start `cerberus-run` (§2 item 11) and run `make exercise-check` there.
2. Start `ptyxis` fullscreen and `tmux new-session -s cerberus-view`. Run the `export` line and the masked-tail account variable. Then `tmux split-window -v -l 25%` and run `make demo-forward` in the bottom pane.
3. URL builder; load tabs 2-3.
4. In the top pane, pre-type without Enter:
   ```
   T0=$(date +%s); tmux send-keys -t cerberus-run 'make exercise ARGS="--yes --generate 100000000 --generator-executors 8 --executor-nodes 2 --name demo-100m"' Enter; until LOG=$(find observability/scale/exercises -maxdepth 1 -name 'demo-100m-*.log' -newermt "@$T0" | head -1); [ -n "$LOG" ]; do sleep 1; done; tail -n +1 -F "$LOG" | sed -u "s/$ACCOUNT/<account>/g"
   ```
   The `find -newermt "@$T0"` wait plus the masking sed was tested in zsh with dummy files (found only the new log and masked the ID); it avoids zsh's "no matches found" on an unmatched glob.
5. Start the GNOME recording.
6. Wait about 5 s, then press Enter (click the terminal first if focus is not there; the rehearsal checks this).
7. Follow the shot table.
8. After `after destroy:`, stop the recording, move the file, close the Grafana tabs.
- Terminals list: the run session is never visible; the view session has the masked log (top) and forward (bottom). Keep the account-ID note and the masking snippet (source of step 4).
- Shot table: column "Real time (100M; 1M)" → "Real time (100M)", remove the 1M values (10M estimates live in §1). "Terminal" means the `cerberus-view` window. Console rows add "(top bar masked in the edit)". Dwell rule and cue strings unchanged.

§6 Post-production (ffmpeg 8.0.1):
1. Move the raw file and get the start time: `mv ~/Videos/Screencasts/"Screencast From <…>.webm" ~/Videos/cerberus-8-10/raw.webm`; `REC_START=$(date -u -d "$(ffprobe -v error -show_entries format_tags=creation_time -of default=nw=1:nk=1 raw.webm)" +%s)`. The log-time offset formula uses `REC_START` in place of `OBS_START`.
2. Normalise (now mandatory): `ffmpeg -i raw.webm -vf "fps=30[,drawtext …%{pts\:hms}…]" -c:v h264_nvenc -preset p5 -cq 20 -g 60 -pix_fmt yuv420p -an timed.mkv`. Reason: one keyframe per recording (every `-ss` would decode from the start) and variable frame rate. `-g 60` gives a keyframe every 2 s. drawtext burn-in stays optional. Keep the zsh `${F}` note.
3. Segment command: prepend `${MASK}` to the filter chain. Console segments `MASK="drawbox=x=0:y=0:w=iw:h=H:color=black:t=fill,"` (measure H in the rehearsal from `ffmpeg -ss T -i timed.mkv -frames:v 1 frame.png`; colour may be sampled from the bar). Others `MASK=""`. Optional punch-in `crop=960:540:X:Y,scale=1920:1080`, sparingly.
4. Cards: `s=1920x1080`.
5. Concat and ffprobe: expected `h264`, 1920x1080, `yuv420p`, 30/1. Re-test with a synthetic VP8 source: `ffmpeg -f lavfi -i testsrc2=s=1920x1080:r=30 -t 40 -c:v libvpx -g 100000 -b:v 1M test.webm`.
6. LinkedIn: "4:5 fits" → "16:9 fits (1:2.4 to 2.4:1)"; keep sources and caveat.
7. Pipeline test: on the synthetic file now, and on the rehearsal file.
8. Before export: step through every console segment and check no account ID is visible.

§7 Rehearsal:
- Command `make exercise ARGS="--yes --generate 10000000 --generator-executors 8 --executor-nodes 2 --name rehearsal"`, via the §5 wrapper with `rehearsal-*.log`. Story URL `&var-requested=10000000`. Record with the GNOME recorder (§4).
- About 38-50 min of cluster time and about $1.0-1.4 (estimates). The post may say "we processed 10M as a rehearsal" only from the run record (`events_processed`). The record is committed in the take's PR (user decision).
- Check 2 pass rule: silver gain = `events_processed` = the generator's `events=` (no Lambda events with the Lambda retired). Keep the 1M history as context.
- New checks: 13 Recorder (`ffprobe` 1920x1080, duration ≈ wall time, avg ≈ 30 fps, no visible stutter); 14 Focus (Enter after recording starts reaches the terminal); 15 Fit (Story shows all four KPI tiles with no scroll at 1.0; run-live shot panels visible); 16 Account ID (grab a frame at each console shot, find every place the dashed ID or an ARN shows, record the `drawbox` height and any extra box); 17 Tooltips (off camera, hover a Story CloudWatch panel, see whether the ARN shows); 18 Terminal legibility (frame of the masked log at 1080p); 19 Timing (record apply, generator, execution, destroy; update §1; re-run the headroom projection with `states[RunDbt].athena.bytes_scanned`); 20 Lambda watch (§2 item 9).
- Replace the "Also check" line: delete "OBS shows about 0 skipped frames", "1080x1350", "devPixelsPerPx layout fits 1350 px", "console mask height is measured"; point to checks 13-18. Check 8 (fail-open) unchanged.

§8 Failure and abort: abort from the visible pane with `tmux send-keys -t cerberus-run C-c`, once; do not attach to `cerberus-run` on camera. "Never close the `tmux` session" → "never kill `cerberus-run`". Retake rule: "239M → 339M, 29.8 GiB from 21.0 GiB at 239M" → "248M → 348M, about 30.6 GiB from 21.8 GiB at 248M"; add "A second 10M rehearsal is allowed. Up to four rehearsals in total fit (§2 item 5)."

§9 Security: "use the console mask" → "masked in the edit, §6 step 3". Add: "The raw recording contains unmasked frames. Keep it in `~/Videos/cerberus-8-10/`. Never upload or commit it."

§10 After the take: add "(and the rehearsal record, in the same PR)".

§11 (new) "The post: Cerberus and Databricks as complements" (natural professional English):
- Rule: no head-to-head timing or cost claim. The runs differ in engine, data shape, scale and billing; Free Edition gives no bill and no billing API. Each platform shows its own strength.
- Cerberus facts (cite each record): 100M = 100,008,511 events, execution 742 s, run $0.37, $0.0037 per million, whole exercise $1.78 (checkpoint L178-187; `exercise-20261013T055859Z.json`); the take's own record replaces these. The 10M rehearsal: from its record only. Strengths: scale, and cost per event on self-run EKS that goes back to $0.
- NovaLake facts (`ChiragVenkateshaiah/novalake` at `4947291`): about 5M events, 101 models, `PASS=218 WARN=4 ERROR=0`, `fct_transactions` 2,138,809 rows (README L32); a ~1.01M-event pilot end to end in about 8 min (ADR 0011 L60-64); a Python UDF about 2.6x slower that pushes the rest of the plan out of Photon (`docs/09-spark-optimization.md` L242-247, L722-723); built 2026-06-24 to 2026-07-29 on serverless (README L27, L34). Strengths: no cluster to run, delivery speed, Photon insight. Not available: stage-2 duration, any cost data.
- Fair test: Cerberus Phase 11.5 (planned): the same input on both engines, run time and cost per million (Phases.md L207).
- Suggested framing: "Cerberus shows what a self-managed AWS platform costs per event at 100M. NovaLake shows how fast serverless Databricks gets a governed lakehouse to production quality. The like-for-like comparison is Phase 11."

Other files:
- `docs/adr/0022-…md`: the amendment (section 6); do not edit the original text.
- `Phases.md` L145: "dress rehearsal at 1M" → "dress rehearsal at 10M (ADR 0022 amendment 2026-11-07)".
- Unchanged: older plan files (historical), `checkpoint.md` (`/end-day` owns it), `docs/scale-metrics.md` (no OBS/portrait text).

## 9. Build steps (one PR)

1. cerberus-git: `git -C /home/chirag/projects/cerberus fetch origin`; `git -C /home/chirag/projects/cerberus worktree add ../cerberus-8.10-runbook-landscape -b 8.10-runbook-landscape origin/main`. The main tree stays untouched.
2. Executor writes `docs/plans/2026-11-07-runbook-landscape.md` (this plan), the runbook changes (section 8), the ADR 0022 amendment as Proposed, and the Phases.md L145 change.
3. $0 local tests in the scratchpad, not the repo: the wait/mask loop with dummy logs in zsh; the full ffmpeg chain on a synthetic 40 s 1920x1080 VP8 `test.webm` (normalise, a masked segment, a card, concat; ffprobe gives `h264 1920x1080 yuv420p 30/1`); `ffprobe … format_tags=creation_time` on an existing screencast.
4. Verify: `grep -nE "OBS|1080x1350|[Pp]ortrait|devPixelsPerPx.*1\.25|4:5|--generate 1000000 |var-requested=1000000\b|2027-01-11|17\.2" docs/demo-recording.md` gives no hits except the deliberate OBS fallback; re-run every section 7 number with `awk`; check every cited line exists with `sed -n`; `git diff --stat origin/main` lists only the four files.
5. cerberus-git opens the draft PR; Opus reviews; the user accepts the amendment, flips it to Accepted, merges with `--merge`.
6. After the merge: the $0 recorder pre-test, the 10M rehearsal (user runs it), fixes, then the take.

## 10. Risks

- The recorder caps, stops or stutters at 40-63 min (software VP8 on a 4-core i5 next to Firefox and Grafana). The $0 65-min pre-test catches it; OBS is the fallback.
- The raw file holds the account ID; a missed console frame would publish it. Mitigation: frame review before export. Severity low (the ID is already public in `exercise.sh` L65).
- First execution after the Lambda retirement; the no-op pass is inferred.
- 8 generator executors at 10M have never run.
- The linear Athena projection: 15% dbt margin; the DQ scan has outrun projections before.
- Recording focus or keybinding behaviour (check 14).

## 11. Open questions

Answered 2026-11-07; see User decisions at the top.
