# Plan: 8.10 dashboard polish (story + live), refresh fix, 1M check run

Date: 2026-11-07. Planner: Opus. Base: `main` at `bcbf804`. Phases.md 8.10; ADR 0022.

User decisions (2026-11-07):
- Firefox zoom in the recording profile stays at **80%** (not 100%). The story grid is sized for 1920x1080 at 80% zoom (CSS viewport about 2400x1350 in F11). Build step 0 confirms the exact row count R in the browser; until then use the estimate in bug 9.
- Cost tile: **servers + live Athena** (option B2), with the B1 servers-only fallback if the $0 test shows "No data".
- Dashboard ARNs (account ID): **leave them in this PR**; the checklist watches for error tooltips.
- Plan confirmed: A2 + B2, one PR `8.10-dashboard-polish`; runbook URL edits go to PR #132's branch.
- The user's aim: dashboards that look professional and update in real time (every 15 s) while screen-recorded, for all departments.

## 1. Question

How do we fix the 10 reported bugs and the review findings on `cerberus-run-story` and `cerberus-run-live`, so the 1M check run and the 100M take record cleanly?

## 2. Facts (V = verified, U = unverified)

Run and repo
- V: The 10M rehearsal finished. Log `observability/scale/exercises/rehearsal-20261107T081206Z.log`: start 08:12:06Z; apply 905 s (L263), generator 235 s (L309), execution 461 s (L311); destroy 818 s, `after destroy: EKS 0, NAT 0, EIP 0, running instances 0`, cluster up 2,605 s.
- V: Record `observability/scale/runs/rehearsal-20261107T081206Z.json` (untracked in the main tree): silver 148,119,569; 9,999,709 events processed; RunDbt 33 queries 16,461,514,443 B; DQ 67,861,315,104 B; no `cost` block yet (`--cost-only` the next day); states Ingest 1.3 s, Transform 252.9 s, dbt 137.1 s, Serve 59.3 s.
- V: Provisioning is a file provider, `editable: false` (`observability/grafana/provisioning/dashboards/cerberus.yaml`), mount `./dashboards` relative to `compose.yaml`, read-only. Compose project name fixed (`name: cerberus-grafana`), so the same volume is used from any worktree.
- V: Local Grafana 13.2.3 (commit 90ffed05). No image renderer, so no `/render` check.
- V: Neither dashboard sets `timepicker.refresh_intervals`. Story `"refresh": "15s"` (L12); live `"refresh": "15s"`, no `timepicker` block.
- V: Account-ID ARNs: story L560-686 (7 places), live L538-582 (3). Every displayed CloudWatch series has a `label`; the ARN queries are `hide: true`; so no tooltip shows an ARN (from the JSON; on-screen hover U). The ID is already in 30 committed files on `origin/main`.

Bug 10 root cause (V, from source)
- Grafana 13.2.3 pins `@grafana/scenes` 8.13.5. `transformSaveModelToScene.ts` L439-441 builds `SceneRefreshPicker({refresh: oldModel.refresh, intervals: oldModel.timepicker.refresh_intervals})`.
- scenes 8.13.5 `SceneRefreshPicker.tsx`: `DEFAULT_INTERVALS = ['5s','10s','30s','1m','5m','15m','30m','1h','2h','1d']` (no `15s`). `setupIntervalTimer` returns early when `intervals && !intervals.includes(refresh)`, so no timer for `15s`. `updateFromUrl` would round to `10s` but never runs: `services/utils.ts` `syncUrlStateToObject` skips keys where URL equals state.
- Result: no auto-refresh timer; the page changes only on Ctrl+R. `_dash.hideTimePicker` and kiosk are not the cause (`DashboardControls.tsx`, `UrlSyncContextProvider`, `DashboardSceneRenderer.tsx`).
- U: Grafana 13 may load file-provisioned v1 JSON through a v2 conversion path. The browser test settles this.

Annotations as panel data (V, from source)
- grafana `plugins/datasource/grafana/datasource.ts` L81-93: a target with `queryType: "annotations"` calls `getAnnotations` with nested `target: {type: "tags", tags, limit, matchAny}` and returns a DataFrame.
- `xorm_store.go` L447 orders by `a.epoch_end DESC, a.epoch DESC`, so `limit: 1` gives the latest point annotation.
- U: Stat rendering of the string field `text`.

Other facts
- V: Athena publishes `ProcessedBytes` with a WorkGroup-only dimension for `cerberus_platform` and `cerberus_platform_dq`; both have `publish_cloudwatch_metrics_enabled = true` (`terraform/modules/athena/main.tf` L83, L113).
- V: Exporter series carry `spark_app` (`terraform/modules/eks_observability/main.tf` L164-171, job `spark-progress` L208-216). Generator activities `creating_payments`, `saving_files`, `finishing` (`observability/spark_progress/exporter.py` L95-109).
- V: Annotation points: `exercise.sh` L268 (Start servers started), L284, L336, L347/351-352 (Step Functions history polled every 15 s), L175, L202-203, L376. `annotate.sh` posts each state as `<State> started` (L191-193).
- V: `--name` is not validated (`exercise.sh` L90, L100); name is `$PREFIX-$STAMP`; `rehearsal-1m-20261108T...Z` is within Step Functions' 80-character limit; no script assumes the `exercise-` prefix.

Cost rate (bug 6)
- V: 2026-10-13: day $1.781607, Athena $0.574015, `eks_cluster_hours` 0.875, `usd_per_cluster_hour` 1.3801. 2026-10-15: day $1.854337, Athena $1.20034, 0.489 h, 1.3374. Cluster up 3,773 s (10-13), 2,487 s (10-15).
- Derived: non-Athena per observed up-hour $1.207592 / 1.048 h = **$1.15/h** (10-13, the take's flags); $0.653997 / 0.691 h = $0.95/h (10-15). The tile's $1.72 = $1.207592 / 0.704 h of node time (plan 2026-10-25 L59; ADR 0022 L319-321). $1.34-1.38/h is per Cost Explorer EKS cluster-hour, which reads 17-29% low (checkpoint L263). Each rate gives $1.21 for 10-13 with its own time base.

## 3. Constraints

- $0 idle; nothing new in AWS. Dashboard queries cost cents per hour (CloudWatch `GetMetricData` $0.01 per 1,000 metrics, ADR 0024 L208-209).
- No `dev-compute` or Terraform change. `exercise.sh` teardown untouched; all new logic in `annotate.sh`.
- ADR 0022 (2026-10-25 amendment, "Cost tile") gets an erratum.
- ADR 0024 L210-213: console Grafana is AMP-only and replays annotations from run records. The new `cerberus-now` tag is replayable. The CloudWatch Athena term needs a console fallback later.
- Story must fit 1920x1080 at 80% browser zoom (user decision), F11, kiosk. No new account ID in committed lines.

## 4. Options

A. "Now" text source: A1 CloudWatch per-integration math (1-3 min lag; rejected). **A2 (chosen):** the run's own annotations, new tag `cerberus-now`, read by a stat panel; 15 s latency; $0; replayable.

B. Cost tile: B1 servers only at $1.15/h × time since run start, label "Athena added a day later". **B2 (chosen):** B1 plus live Athena = CloudWatch `ProcessedBytes` (Sum, both workgroups) × $5 per 10^12 B via a server-side expression; fall back to B1 if the $0 test shows "No data" before the first query.

## 5. Recommendation

A2 + B2. Refresh fix via `timepicker.refresh_intervals`; no URL change needed for it. One PR `8.10-dashboard-polish` from `origin/main` in a new worktree; change only the two dashboards, `annotate.sh`, a one-paragraph ADR 0022 erratum, and this plan file. Runbook edits go on PR #132's branch (URL builder `FROM` = now; the story height; the 1M check section). Leave `Phases.md` alone (PR #132 edits the same 8.10 lines).

## 6. Root cause and exact change, per bug

Story panel ids are the current ones. New id 11 ("Spark is doing").

**Bug 1. Start servers waits until about 08:23.**
- Cause: target A = `time() >= min(kube_node_created @ end())`; no kube-state metrics until the observability release is up near the end of the apply. After the agent dies (destroy + 5 min), `@ end()` is empty and the row turns back to Waiting (same hidden bug in rows B and C, finding 11).
- Change, panel 4 target A: `1 + max_over_time((clamp_max(sum(kube_pod_status_phase{namespace="spark-jobs",pod="cerberus-generate-bulk-payments-driver",phase=~"Running|Succeeded|Failed"}), 1) or vector(0))[${__range_s}s:${__interval}])`. Running from the dashboard `from` (= run start) until the generator driver starts, then Done (sticky). Description: "Start servers counts from the dashboard start time."

**Bug 2. "Now" says "No Spark job running now" during dbt.**
- Cause: panel 2 reads only the exporter; dbt, Lambda, Athena, DQ and destroy have no Spark series.
- Change, `annotate.sh`:
  - New `annotate_now TEXT TIME_MS` posts tags `cerberus-now`, `run:<run>` and `ANNOTATE_EXTRA`; it does not post `cerberus`, so the Run log and markers are unchanged.
  - New `annotate_now_text NAME` (a `case`): `Start servers started` → "1/8 Starting the servers (about 15 min)"; `Generate started` → "2/8 Creating test payments (Spark)"; `InvokeIngestion started` → "3/8 Checking for new app payments (Lambda)"; `RunTransform started` → "4/8 Cleaning payments into the clean table (Spark)"; `RunDbt started` → "5/8 Building business tables (dbt)"; `RunServingQuery started` → "6/8 Answering a business question (Athena)"; `Pipeline run SUCCEEDED` → "7/8 Checking data quality (Athena)"; `Pipeline run FAILED|TIMED_OUT|ABORTED` → "Pipeline <status>: deleting the servers next"; DQ verdict → "Quality checks done: deleting the servers next"; `Delete servers started` → "8/8 Deleting the servers (about 13 min)"; teardown check all 0 → "Finished: servers deleted, nothing left running"; otherwise or teardown failed → "Clean-up FAILED: check the console"; any other name → nothing.
  - Call `annotate_now` from inside `annotate_step`, `annotate_dq_verdict`, `annotate_teardown_check` and `annotate_teardown_failed`. In `annotate_sfn_history`, call it only after `echo "$id" >>"$ANNOTATE_SEEN_FILE"`: it overwrites `ANNOTATE_OK`, and the loop's `$ANNOTATE_OK || break` must keep testing the step post.
  - `exercise.sh` unchanged. `--replay` produces the same annotations.
- Change, panel 2 "Now": stat, x0 y5 w12 h3 (re-grid per bug 9), datasource `{"type":"grafana","uid":"-- Grafana --"}`, one target `{"refId":"A","datasource":{"type":"grafana","uid":"-- Grafana --"},"queryType":"annotations","name":"now","enable":true,"iconColor":"blue","target":{"type":"tags","tags":["cerberus-now"],"limit":1,"matchAny":false}}`; options `reduceOptions {values: true, limit: 1, fields: "/^text$/", calcs: ["lastNotNull"]}`, `textMode "value"`, `valueSize 28`; `noValue "Waiting for the run to start"`; regex mappings `FAILED` → red, `^Finished` → green, others fixed blue.
- New panel 11 "Spark is doing": x12 y5 w6 h3. Move the old N0-N7 targets here, each `max(last_over_time(cerberus_spark_activity{activity="..."}[45s]) == 1)` (45 s window as live panel 1). N1 legend "Saving files (no counter)"; N7 legend "Not in use now"; textMode name; title/value size 18/22.

**Bug 3. Stale "152 K" payments per second.**
- Cause: range query reduced with `lastNotNull`; when the driver ends the last non-null point from minutes earlier shows.
- Change, panel 3 (x18 y5 w6 h3): instant target (`instant: true, range: false`) `max(clamp_min(deriv(cerberus_spark_rows[1m]), 0)) or vector(0)`; value mapping `0` → "—", colour `#8e8e8e`; `textMode "value"`.

**Bug 4. Truncated "Wai" and a short blue piece on "Saving files".**
- Cause: target C = driver Running AND `activeJobs == 0` AND `allJobs > 0`, which flickers to 1 between Spark jobs; the short 0 segment truncates its label.
- Change, target C (null before saving, so the row is blank): `max_over_time((2 * (clamp_max(sum(kube_pod_status_phase{namespace="spark-jobs",pod="cerberus-generate-bulk-payments-driver",phase="Succeeded"}) > 0, 1) or on() max(cerberus_spark_activity{spark_app="cerberus-generate-bulk-payments",activity="finishing"})) or on() max(cerberus_spark_activity{spark_app="cerberus-generate-bulk-payments",activity="saving_files"}))[${__range_s}s:${__interval}])`; legend "↳ Saving files".
- Target B (Generate): wrap the existing expression in `max_over_time((...)[${__range_s}s:${__interval}])` so Done stays after the agent dies.
- Rename rows to match "Now": Start servers, Create test payments, ↳ Saving files, Check for new payments, Clean payments (Spark), Build business tables (dbt), Answer a business question, Quality checks.

**Bug 5. "Time running" counts from the first server.**
- Change, panel 7: title "Time since start", instant target `(time() - ${__from:date:seconds}) / 60`, legend "since the run started", unit `m`, decimals 0. Description: "Counts from the dashboard start time, which the runbook sets to the run start."

**Bug 6. $1.72.**
- Change, panel 9 "Cost so far (estimate)": datasource `-- Mixed --`. Targets: `S` AMP instant `(time() - ${__from:date:seconds}) / 3600 * 1.15`, hide; `P0` / `Q0` CloudWatch `AWS/Athena` `ProcessedBytes`, Sum, period 60, matchExact, `{"WorkGroup":"cerberus_platform"}` / `{"WorkGroup":"cerberus_platform_dq"}`, hide; `P` / `Q` `__expr__` reduce `sum`, `settings {mode: "replaceNN", replaceWithValue: 0}`; `COST` `__expr__` math `$S + ($P + $Q) * 5e-12`; override displayName "servers + Athena queries".
- Description cites the 10-13 record ($1.207592 / 1.048 h) and $5 per 10^12 B, and says the TB-vs-TiB question is open (docs/scale-metrics.md L488-492).
- B1 fallback: target S only, label "servers only; Athena added a day later".
- ADR 0022 L319-321: append "Erratum (8.10 polish, 2026-11-07): ..." with the three-rate explanation.

**Bug 7. Purple lines and region bar.**
- Cause: the dashboard annotation "Run steps" (`annotations.list[1]`, tag `cerberus`, enabled, purple) draws every point and region on the state timeline.
- Change: delete that entry; keep the built-in one (disabled). Remove "the markers come from the run's own notes" from the panel 4 description.

**Bug 8. Plain "No data" before the cluster.**
- Servers now (8): both targets get `or on() (0 * count(last_over_time(kube_node_info[${__range}])))` (shows 0 after the destroy); `noValue "Waiting for servers"`; legends "on-demand" / "Spot (spare capacity)".
- Data read (10): `noValue "Not started yet"`.
- Time since start and Cost always have a value.
- DQ and Clean-up (5, 6) become stats like Now, with tags `cerberus-dq` / `cerberus-teardown`; `noValue "Not started yet"`; regex mappings `PASSED|Cluster deleted` → green, `FAILED|NOT RUN|STILL RUNNING` → red, `not finished yet|not started yet` → `#8e8e8e`.
- Live dashboard: `noValue "Waiting for servers"` on panels 3 and 6; `"Waiting for Spark"` on panels 4 and 5. Whether timeseries panels show `noValue` is U.

**Bug 9. Empty bottom space.**
- Cause: the browser zoom was 80% (user decision: keep it). At 80%, the F11 CSS viewport is about 2400x1350, so 27 rows (38×27−8 = 1,018 px) leave space.
- Change: re-grid the story to fill R rows at 80%. Estimate R = floor((1350 − 16 + 8) / 38) = 35 rows (U; build step 0 measures). Keep the layout order: bar; Now / Spark is doing / Payments per second; journey (8 rows, Teardown row removed); DQ + Clean-up side by side; the four tiles (Time since start, Servers now, Cost so far, Data read). Scale heights proportionally to fill R; larger value sizes on the tiles (about 36+).
- Final R from build step 0: the largest R with `top + 38R − 8 ≤ innerHeight − 8`.

**Bug 10. Auto-refresh.**
- Change: in both JSONs, `"timepicker": {"hidden": false, "refresh_intervals": ["5s","10s","15s","30s","1m","5m"]}`. URL keeps `refresh=15s`.

Other findings
- 11. Journey rows revert to Waiting after the agent stops: fixed by the sticky `max_over_time` in A, B, C.
- 12. The bar never turns green (generator writes slightly under the request: 999,833 at 1M; 9,999,709 at 10M): panel 1 threshold step 100 → 99.
- 13. Teardown row always grey "See Clean-up result": remove X6, its filter entry and override.
- 14. Story title says "100M": set to "Cerberus: payments pipeline, live".
- 15. Live dashboard: description "4:5 (about 864x1080)" → landscape 1920x1080; re-grid to fit the same R rows at 80% (panels 1, 2, 7 in the top row; 3 and 6; 4 and 5; Run log at the bottom); title "Tasks completed / s" → "Spark tasks finished per second".
- 16. ARN exposure: no tooltip path shows an ARN. Residual risk: a CloudWatch AccessDenied error tooltip can print the IAM ARN; add it to the checklist. Removing IDs is out of scope (user decision).

## 7. ADR

No new ADR. One erratum paragraph under ADR 0022's 2026-10-25 amendment "Cost tile" bullet (L316-321): time base now the run start at $1.15/h, with the CE-rate note; Athena added live from CloudWatch; "Now" and the two result tiles read run annotations (tag `cerberus-now`, `cerberus-dq`, `cerberus-teardown`), which ADR 0024's annotation rebuild replays. Consequence: the cost tile needs ADR 0024's AMP-only fallback on the console (Phase 9).

## 8. Build steps (one PR `8.10-dashboard-polish`)

0. Measure ($0, browser, user): recording profile at 80%, F11, current story kiosk URL. In the console: `[innerWidth, innerHeight, devicePixelRatio]`, `document.querySelector('[data-viz-panel-key="panel-10"]')?.getBoundingClientRect().bottom`, `panel-1` `.top`. Set R per bug 9.
1. Worktree: `git worktree add ../cerberus-8.10-dashboard-polish -b 8.10-dashboard-polish origin/main`; `ln -s /home/chirag/projects/cerberus/observability/grafana/.env observability/grafana/.env` (git-ignored, `.gitignore` L66; never stage it).
2. Refresh fix only (bug 10), both JSONs. Verify with the browser test (9.3) before anything else.
3. `annotate.sh` (bug 2). Verify: `bash -n`; then `orchestration/annotate.sh --replay rehearsal-20261107T081206Z` (read-only AWS, local Grafana write; the user runs it); expect `cerberus-now` annotations (GET `/api/annotations?tags=cerberus-now&limit=20` via `annotate_http`).
4. Story JSON (bugs 1, 3-9, findings 11-14), then live JSON (finding 15).
5. ADR 0022 erratum and this plan file.
6. Grafana switch for testing (user runs): `make grafana-down` in the main tree, `make grafana-up` in the worktree (same project and volume). Run section 9 tests. Switch back after the merge.
7. PR #132 branch (separate): URL builder `FROM=$(( $(date +%s) * 1000 ))` built right before Enter; the story row count R; replace "check 17 hover" with the error-tooltip check; add the 1M check section; note 80% zoom in the recording profile.

## 9. Tests

9.1 Static ($0): `jq empty` on both; `jq '[.panels[]|.gridPos.y+.gridPos.h]|max'` ≤ R; no overlap (pairwise jq); unique ids; `.timepicker.refresh_intervals | index("15s")` not null; `git diff origin/main | grep -E '^\+.*[0-9]{12}'` (expected hit: the 200000000000 divisor in the cost tile); `bash -n orchestration/annotate.sh`.

9.2 Provisioning reload ($0): the file provider polls (U, about 10 s) or restart the container. Read-only API check without printing the secret: `curl -s --config <(printf 'user = "admin:%s"\n' "$(grep -m1 '^GF_SECURITY_ADMIN_PASSWORD=' observability/grafana/.env | cut -d= -f2-)") http://127.0.0.1:3000/api/dashboards/uid/cerberus-run-story | jq '.dashboard.timepicker, .dashboard.version'`.

9.3 Refresh proof (about $0.002): DevTools → Network, filter `ds/query`, count POSTs for 60 s. Links:
- A: `http://localhost:3000/d/cerberus-run-story?orgId=1&from=1791871500000&to=now&refresh=15s&kiosk&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks`
- B: A with `refresh=10s`; C: A without `&_dash.hideTimePicker`; D: A without `&kiosk`.
- Prediction (from source, not run): before the fix A, C, D send no batches and B sends one every 10 s; after step 2, A sends one every 15 s. If B also fails, stop and re-plan. Also: Alt+Tab away and back (hidden tab skips ticks and refreshes on return).

9.4 Phase replay ($0, after step 3): story with `from=1794039120000` and these `to`:

| `to` | UTC | Expected "Now" |
|---|---|---|
| 1794039600000 | 08:20 | 1/8, Start servers Running |
| 1794040200000 | 08:30 | 2/8 |
| 1794040440000 | 08:34 | 4/8 |
| 1794040620000 | 08:37 | 5/8 |
| 1794040710000 | 08:38:30 | 6/8 |
| 1794040830000 | 08:40:30 | 7/8 |
| 1794041400000 | 08:50 | 8/8 |
| 1794041820000 | 08:57 | Finished, all tiles green |

At the last `to`, journey rows stay Done. At `to=1794040620000` (dbt), "Payments per second" shows "—". At `from=1794039120000&to=1794040200000`, the cost tile is not "No data" (decides B2 vs B1).

## 10. The 1M check run

- Command: `make exercise ARGS="--yes --generate 1000000 --generator-executors 8 --executor-nodes 2 --name rehearsal-1m"`. Story URL adds `&var-requested=1000000`; build the URL with `FROM` = now right before Enter. Firefox at 80% zoom, F11.
- Cost (estimate): servers 2,300-2,600 s × $0.95-1.15/h = $0.61-0.83; Athena at 148M (DQ 67.9 GB + dbt 16.5 GB + serve 0.16 GB = 84.5 GB × $5/TB) about $0.42; total about $1.0-1.3. November stays about $10-12 (estimate), under the $15 alert.
- Headroom: silver 148.12M → about 149.12M → about 249.1M after the take; dbt merge 20.8 × 249.1/237 = 21.9 GiB (87.5% of 25); DQ 13.5 × 249.1/237 = 14.2 GiB (71% of 20) (linear, ADR 0022 L46-51). Re-project from the 1M record.
- Checklist during the run:
  1. "Start servers" is Running from the first frame.
  2. "Now" changes within about 15 s at each step; dbt reads "5/8 Building business tables (dbt)"; destroy reads 8/8; ends "Finished".
  3. "Payments per second" shows "—" in dbt, Serve, DQ, destroy and the generator commit.
  4. "↳ Saving files": blank, then Running, then Done; no "Wai", no blue blip.
  5. "Time since start" matches the terminal elapsed time within 1 min.
  6. Cost ends near $1.0-1.3; compare with `--cost-only` the next day.
  7. No purple lines or bar.
  8. Before the nodes: "Waiting for servers" / "Not started yet"; after the destroy: Servers now 0/0.
  9. No scrollbar; nothing cut at the bottom (story).
  10. `ds/query` batches every 15 s in DevTools (off camera); no Ctrl+R in the whole run.
  11. Journey rows stay Done after the agent dies.
  12. The bar turns green at about 1.0M.
  13. The live dashboard fits; no "No data" text.
  14. No red error corner on any CloudWatch panel; if one shows, do not hover it on camera.
  15. Before a recorded run, if the last run is older than 14 days, run any Athena query in both `cerberus_platform` and `cerberus_platform_dq` (see the note after F5 in section 13).

## 11. Risks

- Sticky subqueries look back one range width; a previous run inside that window before `from` would show Done early (unlikely with runs hours apart).
- Annotation-stat rendering, SSE "no data" behaviour and `noValue` on timeseries are U until 9.4.
- Bug 9's fit depends on the 80% zoom; step 0 measures.
- "Now" relies on the 15 s Step Functions poll; if Grafana hangs (curl 28), annotations stop for the run (`annotate.sh` L88) and "Now" freezes; the terminal stays authoritative.

## 12. Open questions

Answered 2026-11-07; see User decisions at the top.

Sources: scenes v8.13.5 `SceneRefreshPicker.tsx`, `services/utils.ts`, `UrlSyncContextProvider.ts`; grafana v13.2.3 `transformSaveModelToScene.ts`, `DashboardControls.tsx`, `DashboardSceneRenderer.tsx`, `plugins/datasource/grafana/datasource.ts`, `pkg/services/annotations/annotationsimpl/xorm_store.go`; Grafana community thread 41600; grafana issues #83691, #97759.

## 13. 2026-11-08 replay test findings

A browser test (Grafana 13.2.3, Firefox at 80% zoom, 1914x954 viewport, replay of the 10M rehearsal) found four problems. All four are fixed in the dashboard JSON.

- F1 (bug): the regex value mappings never matched. Grafana wraps a pattern that does not start with "/" as `new RegExp('^' + pattern + '$')`, so "PASSED|Cluster deleted" meant `^PASSED` or `Cluster deleted$`, and "^Finished" became `^^Finished$`. "Now" stayed blue, and the Data quality and Clean-up tiles stayed grey. Fix: every regex pattern in `cerberus-run-story.json` is now in slash form: `/FAILED|TIMED_OUT|ABORTED/` and `/^Finished/` for "Now"; `/FAILED|NOT RUN|STILL RUNNING/`, `/PASSED|Cluster deleted/` and `/not finished yet|not started yet/` for the two result tiles. The red mapping now comes first. `TIMED_OUT` and `ABORTED` were added to "Now" because `annotate.sh` posts "Pipeline <status>: deleting the servers next" for those statuses too. Each pattern was checked against every text `annotate.sh` can post; no failure text contains "PASSED", "Cluster deleted" or a text starting with "Finished". `cerberus-run-live.json` has no regex mappings.
- F2 (layout): the long texts in panels 5 and 6 wrapped and the second line was clipped. Both panels now use `valueSize` 22 (title size stays 18). Measured with Noto Sans as a stand-in for Inter, the longest text (85 characters) is about 854 px wide at 22 px, which fits in a w12 panel at 1914 px (about 940 px). At 26 px it would be about 1010 px.
- F3 (layout): the story dashboard was about 20-30 px too tall for the 954 px viewport. The journey panel went from h14 to h13, and panels 5-10 moved up by one row unit. The grid now ends at row 34 instead of 35.
- F4 (live dashboard): the "Input read so far" stat panel drew its sparkline under the value, and the long legend name overlapped it. Its `graphMode` is now "none".
- F5 (2026-11-08, bug): the "Cost so far (estimate)" tile showed a warning icon. Grafana joins the series of a server-side math expression by label, and the two Athena series had different `WorkGroup` labels, so `$P + $Q` dropped both items ("2 items dropped from union(s)"). The value was right, but the notice showed in the recording. Fix: one code-mode CloudWatch query, `SUM(SEARCH('{AWS/Athena,WorkGroup} MetricName="ProcessedBytes" (WorkGroup="cerberus_platform" OR WorkGroup="cerberus_platform_dq")', 'Sum', 60))`, sums both workgroups into one series with no labels, so `$S + $P / 200000000000` matches. The search schema `{AWS/Athena,WorkGroup}` matches the same metrics as the old `matchExact` queries. Checked against the replay data: the cost values are identical to six decimals (0.153333, 0.561474 and 1.256893), and the response has no notices or errors. Before the first Athena query the tile shows the server part (0.153333), not "No data".

CloudWatch SEARCH finds only metrics that had data in the last 14 days, and a metric that is new to the index can take up to about 15 minutes to appear. If a workgroup has had no Athena query for 14 days, the Athena part of the cost tile can read 0 early in a run. Before a recorded run, if the last run is older than 14 days, run any Athena query in both cerberus_platform and cerberus_platform_dq. Replays work only for runs younger than 14 days; the 60-second period already limits them to 15 days.
