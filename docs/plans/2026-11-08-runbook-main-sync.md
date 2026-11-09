# Plan: sync the 8.10 runbook (PR #132) with main after PRs #133 and #134

Date: 2026-11-08. Planner: Opus. Branch `8.10-runbook-landscape` (head `0f731fb`, base `bcbf804`). Main is at `3267bc9`. Phases.md 8.10 (do not edit Phases.md). No new ADR. This plan edits the Proposed ADR 0022 amendment that PR #132 adds.

## 1. Question

How should `docs/demo-recording.md` and the ADR 0022 amendment on PR #132 change so they match main after PRs #133 and #134? The take uses this runbook, and its dashboard names, journey look, URL builder, tile behaviour and checks are now out of date.

## 2. Facts (V = verified, U = unverified)

Branch and merge
- V: Only `docs/adr/0022-live-observability-for-a-recorded-run.md` changed on both sides. Main added the two errata at merged L324-339. The branch adds the header line (L16) and the amendment at the end (merged L366-412). `git merge-tree` exits 0 (tree `de96f7c`).
- V: `orchestration/exercise.sh` did not change on main (`git diff bcbf804 3267bc9 --stat` lists no change for it). `orchestration/annotate.sh` grew from 341 to 381 lines.
- V: PR #132 touches 4 files: `Phases.md`, ADR 0022, `docs/demo-recording.md`, `docs/plans/2026-11-07-runbook-landscape.md`.

Dashboards on main (`observability/grafana/dashboards/`)
- V: The titles are "1 · Run Overview: progress, quality, cost" (`cerberus-run-story.json`, uid `cerberus-run-story`), "2 · Run Health: compute and throughput" (`cerberus-run-live.json`, uid `cerberus-run-live`) and "3 · Spark and Cluster Diagnostics" (`spark-on-eks.json`, uid `cerberus-spark-on-eks`). The uids did not change.
- V: Story panel 4 "Pipeline journey" maps value 0 to text `""` and colour `#00000000`. It has `showValue: "never"` and a bottom list legend. The texts are Running, Done and Failed, with Ran (green) on "Quality checks". Row A ("Start servers") is `1 + …`, so it is Running from `from`.
- V: The story grid ends at row 34 (journey `0,10,24,13`; tiles 7-10 at y27 h7). Run Health ends at row 35 (Run log `0,24,24,11`).
- V: Both dashboards have `refresh: "15s"` and `timepicker.refresh_intervals` that include `15s`. That is the bug 10 fix (plan 2026-11-07-dashboard-polish §2).
- V: The hidden variables are `requested` (100000000) and `teardown_s` (780). Panels 7 and 9 use `END = clamp_max(vector(time()), scalar(max(max_over_time(timestamp(up)[${__range_s}s:15s])) + $teardown_s or vector(time())))`.
- V: Cost tile P0 = `SUM(SEARCH('{AWS/Athena,WorkGroup} MetricName="ProcessedBytes" (WorkGroup="cerberus_platform" OR WorkGroup="cerberus_platform_dq")', 'Sum', 60))`, and COST = `$S + $P / 200000000000`.
- V: The "Now" tile (panel 2) reads annotations with the tag `cerberus-now`, and its noValue is "Waiting for the run to start". The texts come from `annotate_now_text` (annotate.sh L132-150): "1/8 Starting the servers (about 15 min)" … "8/8 Deleting the servers (about 13 min)", then "Finished: servers deleted, nothing left running" (L197).
- V: Panel 11 "Spark is doing" shows these names: Creating payments, Saving files (no counter), Reading new payments, Adding to the clean table, Tidying files, Finishing up, Waiting, Not in use now.
- V: The panel 8 "Servers now" legends are `on-demand` and `Spot (spare capacity)`.
- V: The ARN lines are story L518-644 (7) and live L542-586 (3). The runbook still cites L560-686 and L538-582.
- V: annotate.sh line moves: `annotate_dq_verdict` L141 → L171; `annotate_teardown_check` L163 → L194; `annotate_sfn_history` L184 → L219; CLI block L327 → L367.

Runs
- V: 1M check run `rehearsal-1m-20261108T060517Z`, from the local log `observability/scale/exercises/rehearsal-1m-20261108T060517Z.log`: apply 820 s (L236), generator 142 s (L274), `execution SUCCEEDED after 404s` (L276), `data quality PASSED: 0 error(s), 1 warning(s)` (L313), `destroy took 693s` (L6500), `after destroy: EKS 0, NAT 0, EIP 0, running instances 0` (L6501), cluster up 2,235 s (L6502).
- V: The 1M record (untracked in the main tree) has 999,846 events and silver 149,119,415.
- V: `from=1794117917000` is 06:05:17Z, which is the execution stamp. "Finished" is at `1794120176590` (06:42:56.59Z). The gap is 2,259.59 s = 37.66 min. Servers: 2,259.59 / 3,600 × 1.15 = 0.7218. Athena: 8.0956e10 / 2e11 = 0.4048. The total is 1.1266, so the tile shows $1.13. The Athena bytes come from plan 2026-11-08-journey-freeze §2 (a CloudWatch read). PR #134 "Verification" gives 38 min / $1.13 at Finished.
- V: The gap from the last AMP sample to "Finished" is 659.5 s on the 1M run and 785.6 s on the 10M run (journey-freeze §2).
- V: 10M rehearsal `rehearsal-20261107T081206Z`, from its log: apply 905 s (L263), generator 235 s (L309), execution 461 s (L311), destroy 818 s (L6290), clean teardown (L6291), cluster up 2,605 s (L6292).
- V: The 10M record shows 9,999,709 events and silver 148,119,569, a gain of exactly 9,999,709. The 1M gain is 149,119,415 − 148,119,569 = 999,846, also exact. `InvokeIngestion` succeeded on both runs (1.3 s and 1.1 s), so the retired-Lambda path works.
- V: Neither record has a `cost` block yet.
- V: CloudWatch SEARCH finds only metrics with data in the last 14 days (plan 2026-11-07-dashboard-polish §13, note after F5).
- V: CI runs `ruff check .` and `ruff format --check .` with `ruff==0.16.4` (`requirements-dev.txt`, `.github/workflows/code-ci.yml` L33-40). Every fence in the runbook is a bare ```` ``` ````. No fence is `python`.
- U: Does Grafana honour `var-teardown_s=99999` in the URL for a variable with `hide: 2`? The PR #134 numbers come from the API with the value substituted. Build step 4 checks it in the browser.
- Note: "All grey" is at L472 (the shot table).

## 3. Constraints

$0 and no AWS change (the optional browser check in step 4 makes a few CloudWatch `GetMetricData` reads, under $0.01). Do not edit Phases.md, dashboards or scripts. This is a public repo: no account IDs (write `<ACCOUNT_ID>` when one is needed), no emails, no local secret-file paths, no secrets. Write files in natural professional English. Keep bare code fences (the house style); never use `python`. The amendment must stay consistent with the two errata that main already has in ADR 0022.

## 4. Branch update (decision)

Merge, do not rebase and do not force-push. cerberus-git runs:

```
git -C /home/chirag/projects/cerberus-8.10-runbook-landscape fetch origin
git -C /home/chirag/projects/cerberus-8.10-runbook-landscape merge --no-ff origin/main -m "Merge main into 8.10-runbook-landscape (PRs #133 and #134)"
git -C /home/chirag/projects/cerberus-8.10-runbook-landscape push origin 8.10-runbook-landscape
```

Add the session attribution lines to the merge message. There is no expected conflict. If one shows, stop and report. Do the merge before the edits, so the edits get their own commit.

## 5. Edits to `docs/demo-recording.md` (branch line numbers; the merge does not move them)

Naming rule for prose: "Story" / "story" (as a dashboard name) → "Run Overview". "`cerberus-run-live`" / "run-live" (as a name) → "Run Health". Keep the uids in URLs and JSON file paths. The lines involved are L264, 265, 291, 364, 366, 383, 468, 472-481, 614 and 719, plus the rewrites below.

E1. After L12 (end of the intro paragraph), insert a new paragraph:

```
Status on 2026-11-08: the 10M rehearsal ran on 2026-11-07
(`rehearsal-20261107T081206Z`). The dashboard fixes from its replay and from
the 1M check run (section 7, "1M check run") are merged (PRs #133 and #134),
and the runbook follows them
([2026-11-08-runbook-main-sync.md](plans/2026-11-08-runbook-main-sync.md)).
Next: pre-flight, then the 100M take.
```

E2. L229-237. Replace from "Do not set `layout.css.devPixelsPerPx`" to "(check 15)." with:

```
Set the zoom to 80% in this profile (Ctrl+minus twice from 100%, on
`localhost:3000`). Do not set `layout.css.devPixelsPerPx`. Run Overview's grid
ends at row 34 (the journey panel is 13 rows high, `cerberus-run-story.json`).
In F11 on the 1920x1080 monitor at 80% it fits with no scrollbar (plan
2026-11-07-dashboard-polish, section 13, F3; the owner's browser check in
PR #134). Run Health's grid ends at row 35: its Run log fills the bottom rows,
and the shot panels sit above it. Check 15 confirms both before the take.
```

Keep the next sentences ("Sign in to the AWS console … toolbar.").

E3. Insert after L237, before "### Layout: what is on screen":

```
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
```

E4. L254-257. Replace "Keep the mouse off the CloudWatch panels … (check 17)." with:

```
The CloudWatch queries of Run Overview and Run Health carry ARNs with the
account ID as dimensions (`cerberus-run-story.json` L518-644,
`cerberus-run-live.json` L542-586). Those queries are hidden and every shown
series has a label, so a normal tooltip shows no ARN (plan
2026-11-07-dashboard-polish, section 2). An error can: a CloudWatch error such
as AccessDenied puts a warning or error triangle in the panel header, and its
tooltip can print the IAM role ARN. Never hover a panel with a triangle on
camera (check 17).
```

E5. Tabs table, L264-265:
- L264: `| 2 | Story dashboard \`cerberus-run-story\` (URL below) | Everything. Show it first in every phase. | |` → `| 2 | Run Overview \`cerberus-run-story\` (URL below) | Everything. Show it first in every phase. | |`
- L265: `| 3 | Engineers' dashboard \`cerberus-run-live\` (URL below) | Executors, Spot nodes, input bytes/s | |` → `| 3 | Run Health \`cerberus-run-live\` (URL below) | Executors, Spot nodes, input bytes/s | |`

E6. URL builder, L274-293. Replace the whole block, from "**URL builder.**" to "…about 63 minutes." (end of L293), with:

````
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
````

E7. L364, L366, L383 (the pre-test, now history): rename only. "the two dashboards" → "Run Overview and Run Health". "the Story and `cerberus-run-live` dashboards" → "the Run Overview and Run Health dashboards". "on Story and on `cerberus-run-live`" → "on Run Overview and on Run Health".

E8. L468: "Each row lists the screens in order, story first." → "Each row lists the screens in order, Run Overview first."

E9. Shot table:
- L472 "What to show" cell, old: `All grey. Tiles "Quality checks: not finished yet" and "Clean-up: not started yet" (placeholders posted at L268).` New: `Journey: "Start servers" is blue (Running); the other seven rows show no bar yet, only their labels, with the legend Running / Done / Ran at the bottom and no text in the bars. "Now" reads "Waiting for the run to start", then "1/8 Starting the servers (about 15 min)". Tiles "Quality checks: not finished yet" and "Clean-up: not started yet" (placeholders posted at L268).` Screens: `Story` → `Run Overview`.
- L473: `"Servers now" and "Time running" appear once scraped.` → `"Servers now" appears once scraped; "Time since start" counts from the first frame.`
- L474: `"Creating payments".` → `"Now": "2/8 Creating test payments (Spark)"; "Spark is doing": "Creating payments".`
- L475: `"Saving files into bronze — no counter for this part"; executors 0.` → `"Spark is doing": "Saving files (no counter)"; the journey row "↳ Saving files" is blue; executors 0.`
- L477: `Story: "Reading new payments", then …` → `Run Overview: "Spark is doing" reads "Reading new payments", then …`. `run-live:` → `Run Health:`. `End on Story.` → `End on Run Overview.`
- L480: `annotate.sh L141` → `annotate.sh L171`. `Story tile` → `Run Overview tile`.
- L481: `annotate.sh L163` → `annotate.sh L194`. `Story tile` → `Run Overview tile`. Append to the "What to show" cell: ` "Time since start" and "Cost so far (estimate)" keep counting through the clean-up and stop at the cluster's last metrics plus 780 s (hidden variable \`teardown_s\`).`
- Screens columns, every row: `Story` → `Run Overview`, `run-live` → `Run Health`.

E10. L492-496. Replace the paragraph "The cue strings above … "No Spark job running now"." with:

```
The cue strings above are the exact text of `exercise.sh`. Two tiles describe
the moment in plain words. "Now" shows the run's own step notes (tag
`cerberus-now`, `annotate_now_text`, annotate.sh L132-150): "1/8 Starting the
servers (about 15 min)" to "8/8 Deleting the servers (about 13 min)", then
"Finished: servers deleted, nothing left running". "Spark is doing" shows what
Spark itself reports: "Creating payments", "Saving files (no counter)",
"Reading new payments", "Adding to the clean table", "Tidying files",
"Finishing up", "Waiting" or "Not in use now".
```

E11. Section 2, insert a new item 12 after item 11 (after L212):

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
```

E12. Checks table, section 7:
- L632 (check 8): `annotate.sh L184 and following` → `annotate.sh L219 and following`.
- L634 (check 10): `"Servers now" shows the texts "regular" and "spare-capacity (Spot)".` → `"Servers now" shows "on-demand" and "Spot (spare capacity)".`
- L639 (check 15), new row: `| 15 | Fit | Open Run Overview and Run Health in F11 at 80% zoom | Run Overview: every panel visible with no scrollbar, the journey legend (Running, Done, Ran) at the bottom. Run Health: the shot panels visible. The \`_dash.hide*\` flags hide the time picker, variables and links. |`
- L641 (check 17), new row: `| 17 | Error tooltips | Watch every panel of Run Overview and Run Health through the run | No warning or error triangle on any panel. "Cost so far (estimate)" must show none: its earlier triangle was the "items dropped from union(s)" notice, fixed in PR #133 (plan 2026-11-07-dashboard-polish, F5). If one shows, do not hover it on camera; note the panel and the time. |`
- L614: `Use the story URL with` → `Use the Run Overview URL with`.

E13. Insert a new subsection after L669 (end of "Decision point"), before "## 8.":

````
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
````

E14. L719 (cost guard): "An open story tab" → "An open Run Overview tab".

E15. Section 10. L743: `(and the rehearsal record, in the same PR)` → `(and the two rehearsal records, \`rehearsal-20261107T081206Z.json\` and \`rehearsal-1m-20261108T060517Z.json\`, in the same PR)`. Then insert after the numbered list (after L749):

````
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
````

E16. L113-114 (sourcing note): `annotate.sh L327` → `annotate.sh L367`.

## 6. Edits to ADR 0022 (only the Proposed amendment; merged line numbers)

Main's errata (L324-339) stay as they are. Two edits:

A1. Merged L397-398 (Decision), old: `- The Grafana dashboards get a look review in a $0 recorder pre-test, and a\n  separate dashboard-polish PR lands before the rehearsal.` New:

```
- The Grafana dashboards get a look review, and separate dashboard-polish
  PRs land before the take (PRs #133 and #134; they used the 10M rehearsal as
  replay data).
```

A2. After merged L411 ("…now reads 10M."), insert a Consequences bullet:

```
- The 10M rehearsal ran on 2026-11-07 (`rehearsal-20261107T081206Z`), with
  a clean teardown. A 1M check run on 2026-11-08
  (`rehearsal-1m-20261108T060517Z`) tested the dashboard fixes; it is not build
  step 8. The erratum "8.10 journey and freeze" calls it "the 1M rehearsal".
  Both runs confirm the retired ingestion path: `InvokeIngestion` succeeded,
  and the silver gain equalled the generated events exactly.
```

The Status stays Proposed. The header line L16 stays.

## 7. Optional staleness fixes (recommended, same PR; drop any the caller rejects)

O1. Section 1, L61-81. Rename the column "10M rehearsal (estimate)" to "10M rehearsal (2026-11-07)" and fill in the measured values from `observability/scale/exercises/rehearsal-20261107T081206Z.log` and the record: apply 905 s (L263); generator 235 s (L309); execution 461 s (L311); states Ingest 1.3 s, Transform 252.9 s, dbt 137.1 s, Serve 59.3 s (`states[]`); destroy 818 s (L6290); cluster up 2,605 s (L6292). Delete "no run below 100M did" (L65-66). Replace L79-81 with "Measured; check 19 is done."

O2. Section 2, item 5 (L133-148). Change "Silver holds 138,119,860 events now (`exercise-20261015T145812Z.json`…)" to "Silver holds 149,119,415 events after the 1M check run (`rehearsal-1m-20261108T060517Z.json`, `.silver.events`)". Change "After the 10M rehearsal it holds about 148M, and after the take about 248M" to "after the take about 249.1M". Then use these numbers: dbt about 21.9 GiB (87.5% of 25), DQ about 14.2 GiB (71% of 20) (plan 2026-11-07-dashboard-polish §10). Room before the take: 184.8M − 149.1M = about 35.7M. Change "up to four 10M rehearsals in total fit" to "about 35.7M of room is left". Apply the same numbers in section 8, retake rule (L715-718): about 249M → 349M; the dbt figure stays past 25 GiB.

O3. Section 2, item 9 (L178-185). Replace "That is inferred … first run of the retired path." with "Confirmed on 2026-11-07 and 2026-11-08: `InvokeIngestion` succeeded (1.3 s and 1.1 s), and the silver gain equalled `events=` exactly (9,999,709 and 999,846; the two run records). Watch it again in the take."

## 8. Static checks (executor, $0)

```
cd /home/chirag/projects/cerberus-8.10-runbook-landscape
uvx ruff@0.16.4 format --check . && uvx ruff@0.16.4 check .
grep -c '^```python' docs/demo-recording.md                 # 0
git diff origin/main...HEAD | grep '^+' | grep -P '(?<![0-9])[0-9]{12}(?![0-9])'   # no output (13-digit epoch ms are fine)
git diff origin/main...HEAD | grep '^+' | grep -niE '[a-z0-9._-]+@[a-z0-9-]+\.[a-z]{2,}|cred[e]ntials|aws_secret|AKIA'   # no output
grep -nE 'All grey|Time running|Story|L141|L163|L184|L327|L560-686|L538-582|- 120\)|hover a CloudWatch|regular" and' docs/demo-recording.md   # no output
grep -noiE '(^|[^-])(story|run-live)' docs/demo-recording.md   # only uid/URL hits; review each
grep -cF '1 · Run Overview: progress, quality, cost' docs/demo-recording.md   # >= 1 (U+00B7 middle dot, exactly as in the JSON)
grep -cF '2 · Run Health: compute and throughput' docs/demo-recording.md      # >= 1
grep -cF '3 · Spark and Cluster Diagnostics' docs/demo-recording.md           # >= 1
grep -cF 'var-teardown_s=99999' docs/demo-recording.md                         # >= 1
grep -cF 'FROM=$(( $(date +%s) * 1000 ))' docs/demo-recording.md               # 1
sed -n '132p;171p;194p;219p;367p' orchestration/annotate.sh       # the cited functions and the CLI block
sed -n '236p;274p;276p;6500,6502p' /home/chirag/projects/cerberus/observability/scale/exercises/rehearsal-1m-20261108T060517Z.log | sed -E 's/[0-9]{12}/<ACCOUNT_ID>/g'
python3 -c "e=(1794120176590-1794117917000)/1000;print(e,round(e/60,2),round(e/3600*1.15,4),8.0956e10/2e11)"   # 2259.59 37.66 0.7218 0.40478
git diff --stat origin/main...HEAD   # only Phases.md, ADR 0022, demo-recording.md, the two plan files
```

Also check by eye that each edited table row keeps its column count (checks table: 4 columns; shot table: 7 columns).

## 9. Build steps

1. cerberus-git: the merge in section 4, then push.
2. Executor: save this plan as `docs/plans/2026-11-08-runbook-main-sync.md`. Apply E1-E16 and A1-A2 (and O1-O3 if accepted).
3. Executor: run section 8. cerberus-git commits ("Sync the 8.10 runbook with the renamed dashboards and the 1M check run") and pushes. PR #132 stays a draft.
4. Optional, user, browser (under $0.01 in CloudWatch reads, valid until about 2026-11-22): open the E15 URL with `FROM=1794117917000` and `TO=1794120176590`. Expected: 38 min and $1.13, every journey row Done or Ran, no triangle. This checks that the URL can set the hidden `teardown_s`.
5. Opus reviews the branch (Mode 2). The user accepts the amendment, flips it to Accepted and merges with `--merge`.

## 10. Open questions for the user

1. Section 7 items O1-O3: include them in this PR? Recommended yes. The take re-projects headroom from the silver count in item 5, and that count is 11M out of date.
2. Pre-warm query. If the take is after about 2026-11-22, should the runbook add the plan 2026-11-07-dashboard-polish §13 step (one Athena query in each workgroup before the run)? That query changes AWS, so the box at the top of the runbook would need a fourth command. The answer is "No" if the take is before 2026-11-22.

## 11. User decisions (2026-11-08)

1. O1-O3: include them in this PR.
2. The take is before 2026-11-22: no pre-warm step; the runbook only notes the 14-day limit (E11).
3. Plan confirmed.
