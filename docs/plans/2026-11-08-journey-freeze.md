# Plan: 8.10 follow-up: journey without "Waiting", and the time and cost tiles stop at the end of the run

Date: 2026-11-08. Planner: Opus. Base: `main` at `87d5fde`. Phases.md 8.10 (existing subtask; do not edit Phases.md). ADR 0022 gets a one-line erratum. No new ADR.

User decisions (2026-11-08): labels = never + legend; teardown_s = 780; add the screenshot line to PR #132 (separate step, not in this PR); plan confirmed.

## 1. Question

Two fixes to `observability/grafana/dashboards/cerberus-run-story.json`, needed before the 100M take and the LinkedIn screenshot:
- **G1:** remove the grey "Waiting" bars and the cut-off labels from the journey (panel 4).
- **G2:** stop "Time since start" (panel 7) and "Cost so far (estimate)" (panel 9) at the end of the run. While the run is going, they must still grow on every refresh.

## 2. Facts (V = verified, U = unverified)

- V: The 1M run started at 06:05:17Z (`from=1794117917000`). "Delete servers started" 06:31:16Z. The "Finished" `cerberus-now` annotation is at `1794120176590` (06:42:56.6Z). Elapsed 2,259.6 s = 37.66 min.
- V: The last AMP sample `max(max_over_time(timestamp(up)[7200s:15s]))` is about 40 s after "Delete servers started" (the destroy removes `helm_release.prometheus` early). Gap from last AMP sample to "Finished" (D): 659.5 s (1M), 785.6 s (10M).
- V: Servers to Finished: 2,259.6 / 3600 x $1.15 = $0.7218. Athena (CloudWatch ProcessedBytes) = 8.0956e10 B = $0.4048. Freeze with D = 780 reads $1.1266 at Finished, $1.1651 frozen later.
- V: SSE cannot read annotations (`unknown query type`), so an annotation-based freeze is not possible server-side.
- V: Panel 4 Waiting comes from value 0 (B `or vector(0)`, X1-X5 `FILL(...,0)`); mapping `"0": Waiting #8e8e8e` in defaults and in the "Quality checks" override. Row C returns an empty frame until `saving_files`; with `or on() vector(0)` it returns 0s from the start.
- V (Grafana main source): `showValue: "auto"` cuts labels (`txt.slice(0, maxChars)`), only `"never"` removes them. A 9-char `#RRGGBBAA` colour passes through unchanged, so `#00000000` draws nothing. Mapping text `""` stays empty. The legend drops empty labels.
- V: The JSON round-trips exactly with `json.dumps(d, indent=2) + "\n"`. `build.py` must not be re-run.

## 3. Constraints

$0, no AWS change, no Terraform / exercise.sh / annotate.sh change. File-provisioned dashboard, Grafana 13.2.3. Patch script only. No new account IDs, ARNs or emails. Cost model ($1.15/h, Athena / 2e11) unchanged; only the end of the time base changes (ADR 0022 erratum line).

## 4. Chosen design

- G1: map 0 to text `""` and colour `#00000000`; row C gets `or on() vector(0)` so all 8 rows exist from the first frame; `showValue: "never"` plus a bottom list legend.
- G2: `end = min(time(), last_up_sample + teardown_s)`, hidden variable `teardown_s` = 780. Live while the agent sends metrics and through the teardown allowance, then frozen. Before the agent exists, falls back to `time()`. Exact screenshot: `to=<Finished ms>&var-teardown_s=99999`.

## 5. ADR 0022 erratum

Append after L332 "...(Phase 9).", in the same bullet and indentation:

```
  Erratum (8.10 journey and freeze, 2026-11-08): after the run, "Time since
  start" and the cost tile stop at the cluster's last AMP sample plus 780 s
  for the destroy (hidden variable `teardown_s`; measured 660 s on the 1M and
  786 s on the 10M rehearsal), so they no longer grow after the clean-up. The
  rate and the Athena term are unchanged.
```

## 6. Patch script (run from the worktree root; script lives in the scratchpad)

```python
import json

P = "observability/grafana/dashboards/cerberus-run-story.json"
src = open(P).read()
d = json.loads(src)
assert json.dumps(d, indent=2) + "\n" == src
pan = {p["id"]: p for p in d["panels"]}
assert sorted(pan) == list(range(1, 12)) and len(d["panels"]) == 11

old = "Colours: green = done, blue = running, grey = waiting, red = failed."
assert old in d["description"]
d["description"] = d["description"].replace(
    old,
    "Colours: green = done, blue = running, red = failed; a step that has not started shows no bar.",
)

assert all(v["name"] != "teardown_s" for v in d["templating"]["list"])
d["templating"]["list"].append(
    {
        "type": "textbox",
        "name": "teardown_s",
        "label": "teardown_s",
        "query": "780",
        "hide": 2,
        "skipUrlSync": False,
        "current": {"text": "780", "value": "780"},
        "options": [{"selected": True, "text": "780", "value": "780"}],
    }
)

END = "clamp_max(vector(time()), scalar(max(max_over_time(timestamp(up)[${__range_s}s:15s])) + $teardown_s or vector(time())))"

t = pan[7]["targets"][0]
assert t["expr"] == "(time() - ${__from:date:seconds}) / 60"
t["expr"] = "(" + END + " - ${__from:date:seconds}) / 60"
pan[7]["description"] = (
    "Counts from the dashboard start time, which the runbook sets to the run start. "
    "After the run it stops at the cluster's last metrics plus 13 min for the clean-up (hidden variable teardown_s, 780 s; "
    "measured 660 s and 786 s on the 2026-11-08 and 2026-11-07 rehearsals), so a past run can read about 2 min high or low. "
    "For the exact value, set the dashboard end time to the 'Finished' note."
)

s = [x for x in pan[9]["targets"] if x["refId"] == "S"][0]
assert s["expr"] == "(time() - ${__from:date:seconds}) / 3600 * 1.15"
s["expr"] = "(" + END + " - ${__from:date:seconds}) / 3600 * 1.15"
old = "servers = hours since the dashboard start x $1.15 an hour"
assert old in pan[9]["description"]
pan[9]["description"] = pan[9]["description"].replace(
    old,
    "servers = hours from the dashboard start to now (after the run: to the cluster's last metrics plus teardown_s, 780 s) x $1.15 an hour",
)

p4 = pan[4]
c = [x for x in p4["targets"] if x["refId"] == "C"][0]
pre, suf = "max_over_time((", ")[${__range_s}s:${__interval}])"
assert c["expr"].startswith(pre) and c["expr"].endswith(suf) and "vector(0)" not in c["expr"]
c["expr"] = (
    "max_over_time((("
    + c["expr"][len(pre) : -len(suf)]
    + ") or on() vector(0))[${__range_s}s:${__interval}])"
)
HIDE = {"text": "", "color": "#00000000", "index": 0}
m = p4["fieldConfig"]["defaults"]["mappings"][0]["options"]
assert m["0"]["text"] == "Waiting"
m["0"] = dict(HIDE)
ov = [o for o in p4["fieldConfig"]["overrides"] if o["matcher"]["options"] == "Quality checks"][0]
om = ov["properties"][0]["value"][0]["options"]
assert om["0"]["text"] == "Waiting"
om["0"] = dict(HIDE)
assert p4["options"]["showValue"] == "auto"
p4["options"]["showValue"] = "never"
p4["options"]["legend"] = {"showLegend": True, "displayMode": "list", "placement": "bottom"}
p4["description"] = (
    "One row per step. A bar starts when its step starts: blue = running, green = done "
    "(Quality checks: green = ran; the verdict is in its own tile), red = failed. Start servers counts from the dashboard start time. "
    "Start servers, Create test payments and Saving files come from Kubernetes (15 s). The other rows come from AWS metrics "
    "and can lag 1-3 min. Needs the dashboard range to start at the run start."
)

open(P, "w").write(json.dumps(d, indent=2) + "\n")
```

## 7. Static checks

- `jq empty` on the JSON; `jq '[.panels[].id]|length'` is 11; `jq '.templating.list|map(.name)'` is `["requested","teardown_s"]`.
- `git diff --stat` shows only the dashboard, ADR 0022 and the plan file `docs/plans/2026-11-08-journey-freeze.md`.
- `git diff origin/main -- observability | grep -E '^\+.*([0-9]{12}|arn:)'` returns nothing.

## 8. Verification ($0; the 1M run, `from=1794117917000`)

API (executor), POST /api/ds/query with `${__range_s}` = (to - from)/1000, `${__interval}` = 15s, `$teardown_s` = 780 substituted. Token read without echo. Hidden refIds return no frames; check COST.

| `to` | UTC | Time since start (raw -> shown) | COST (shown) |
|---|---|---|---|
| 1794118217000 | 06:10:17 | 5.0 -> 5 min | 0.0958 -> $0.10 |
| 1794119100000 | 06:25:00 | 19.72 -> 20 min | 0.3779 -> $0.38 |
| 1794119700000 | 06:35:00 | 29.72 -> 30 min (live during destroy) | Athena added |
| 1794120176590 | Finished | 37.66 -> 38 min | 1.1266 -> $1.13 |
| now | after | 39.67 -> 40 min (frozen) | 1.1651 -> $1.17 |
| now, `teardown_s=660` | after | 37.67 -> 38 min | about $1.13 |

Panel 4 at 06:10:17: refIds A, B, C, X1-X5 each return 1 frame; A all 1, others all 0. At Finished every row ends at 2. No `error` and no `notices`.

Browser (user), kiosk, `from=1794117917000`, 80% zoom: 8 row labels visible at 06:10:17 with only "Start servers" blue and no grey; at Finished, bars start at each step's start, no text in bars, legend Running/Done/Ran, tiles 38 min and $1.13; at `to=now&refresh=15s` tiles stay at 40 min / $1.17; hover on empty area shows blank; no scrollbar.

## 9. Risks

- Source checks were on Grafana main, not v13.2.3; the browser check confirms.
- If the 100M destroy takes longer than 780 s + 40 s, the last frame reads low by the excess; use `var-teardown_s` or `to=Finished`.
- If the agent stops for more than 13 min mid-run, the tiles freeze early (unlikely; k8s restarts it).
- The legend shows both "Done" and "Ran" in green.
- "Check for new payments" goes straight 0 -> 2 (the Lambda takes 1 s inside one 60 s period); already true today.

## Dashboard names (2026-11-08)

The user renamed the three dashboards. The uids are unchanged, so no URL breaks.

- `cerberus-run-story`: "1 · Run Overview: progress, quality, cost"
- `cerberus-run-live`: "2 · Run Health: compute and throughput"
- `cerberus-spark-on-eks`: "3 · Spark and Cluster Diagnostics"

The link buttons are now "2 · Run Health →" (dashboard 1), "1 · Run Overview →" and "3 · Spark and Cluster Diagnostics →" (dashboard 2), and "2 · Run Health →" (dashboard 3).
