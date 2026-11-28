# Plan: 9.4 the landing page rebuild, "Follow the batch"

Date: 2026-11-28. Base: `origin/main` at `6240f90`.

**No new ADR is needed.** The zero-JavaScript page was a choice of
`docs/plans/2026-11-06-landing-page.md` (sections 4.1 and 5), not an ADR rule.
This plan replaces that choice. The edge CSP stays as it is
(`script-src 'self'`). See "ADR check" for what would need `/decision`.

## Owner decisions (2026-11-28)

- Concept A, "Follow the batch".
- 9.4 shows 3 fixed runs, embedded at build. It links to the live Grafana only
  during a session. It shows recorded Prometheus figures.
- The all-runs explorer stays in Phase 15.
- The featured 100M run is `exercise-20261013T055859Z` (the default; the owner
  did not object).
- 9.6 may be ticked on the current landing page. The new page is checked inside
  9.4.
- PR 1 starts now. This overrides the earlier pause of Phase 9 to 2026-11-30
  (`Phases.md`, Phase 17 note).

## 1. Goal

An audience that will not read the repo sees what Cerberus achieved, and follows
a real batch through bronze, silver and gold. The page that was rejected on
2026-11-12 was text, not interactive (`Phases.md` 9.4).

## 2. Facts

| Fact | Source |
|---|---|
| Featured run: 100,008,511 events, 742.0 s, $0.0037 per million events (estimated), run cost $0.3657 | `observability/scale/runs/exercise-20261013T055859Z.json` |
| 17 run records; 15 have status `SUCCEEDED`. This is the run status, not the data checks: `data_quality.passed` is true in 15, false in 1 and absent in 1; one succeeded run has no checks, and one failed run passed them | `observability/scale/runs/*.json` |
| The 1M and 10M runs of the scale ladder are `exercise-20261015T145812Z` (1,005,920 events) and `exercise-20261009T074853Z` (9,005,590 events). The batch picker uses them | `docs/scale-metrics.md`, the ladder table |
| `live.json` holds `schema`, `url`, `home`, `started`, `ends` | `terraform/envs/dev-console/session.tf` |
| The terminal is live at `terminal/index.html`, invite only | `Phases.md` 9.5 |

## 3. Concept A

```
+--------------------------------------------------------------+
| Cerberus: a payments data platform on AWS                    |
| [100,008,511 events] [742.0 s] [$0.0037 per million, est.]   |
| [15 of 17 runs succeeded]                                       |
+--------------------------------------------------------------+
| Follow the batch        pick: ( 1M ) ( 10M ) (*100M*)        |
|                                                              |
|  (1) Arrive --> (2) Clean --> (3) Model --> (4) Answer       |
|  [time bar: one segment per station, share of the run]       |
|  +--------------------------------------------------------+  |
|  | Station panel                                          |  |
|  |  duration and share of the run                         |  |
|  |  bytes read                                            |  |
|  |  table total after this run                            |  |
|  |  checks, in plain words                                |  |
|  |  why it matters                                        |  |
|  +--------------------------------------------------------+  |
|                                                   [ Next ]   |
+--------------------------------------------------------------+
| Latest run                                                   |
| Scale charts                                                 |
| Live dashboard (link only while a session runs)              |
| Terminal (invite only)                                       |
| > Build progress (fold)                                      |
+--------------------------------------------------------------+
```

Databricks gets one partner-engine sentence at the gold station ("Model"), with
no numbers.

Rejected:

- **B, a scale dial.** It implies clean scaling, which the data does not
  support: the ladder runs ran out of order on different silver sizes.
- **C, a run board.** It is an engineer dashboard and overlaps 15.3.

## 4. Boundary

| In 9.4 | In Phase 15 |
|---|---|
| Same-origin JavaScript and publish support for it | Publishing `observability/showcase/*.json` and fetching it |
| Layout | The all-runs explorer |
| The journey over 3 fixed runs | The interactive scale story |
| The existing charts | SLO and status values |
| `live.json` ends handling | Comparison columns and Databricks media |
| A redaction scan on the built page | The account-ID check, the requests alarm, the flat-rate spike |

Out of scope for both: Phase 17 numbers and `history.json`.

## 5. Data traps (PR 2 and PR 3)

- `observability/showcase/runs.json` has no layer volumes and no check names.
  Read the records in `observability/scale/runs/`.
- `silver.events`, `silver.transactions` and `storage_snapshot.gold.bytes` are
  table totals at collection time, not per run.
- `storage_snapshot.silver_payments.bytes` can be 0. Never show it.
- No record field holds a gold row count or a bronze event total.
- The free text in a data check (`about`, `detail`) is never printed.
- The ladder runs ran out of order (10M, then 100M, then 1M) on different silver
  sizes (`docs/scale-metrics.md`).
- The 1M run's `RunDbt` time of 286.7 s includes 230.5 s of Athena queue time
  (`docs/scale-metrics.md`).
- The run cost is an estimate: a day-average rate times the run time, plus the
  run's own Athena queries. It excludes setup, the data generator, the data checks
  and teardown. The check suite is outside the run: $0.50 on the featured 100M
  exercise, against a run cost of $0.3657 (`docs/scale-metrics.md`).
- The newest 100M run is `demo-100m-20261108T135119Z`, not the featured run. It
  stays in the latest-run strip.

## 6. Steps (one PR each)

### PR 1 (9.4a): the script, the live link and publish support

Safe to publish alone: the current page stays, with two changes a visitor sees.
Paths are under `console/cerberus_landing/` unless said.

1. `static/site.js`: only the live dashboard link. It fetches `live.json` (same
   origin, `cache: "no-store"`) and checks it the way
   `console/cerberus_live_check/report.py` `parse_live` does. It shows the link,
   labelled invited sign-in, only if `ends` is in the future, `url` is https and
   `home` starts with exactly one `/`. It checks again every 60 s and hides the
   link when the session ended, or the file is missing or malformed. No
   hard-coded host, no `innerHTML`, no `eval`, no inline handler. The link is
   hidden in the HTML, so a reader without JavaScript sees nothing dead.
2. `build.py`: allow only one empty, relative `<script src ... defer>` on the
   page. Scripts stay banned in SVG and inline. The script gets a content-hash
   name and counts in the build id.
3. `page.py`: set `TERMINAL_HREF` (invite only). `content.toml`: fix the copy
   about the sign-in link and about JavaScript.
4. `publish.py` (`MANAGED`) and `console/publish_site.sh`: upload the script
   before `index.html` as `text/javascript`, immutable, and check its headers.
   `live.json`, `healthz.txt` and `terminal/` stay protected. No folder mirror
   and no bulk delete.
5. Tests: update the landing CSP, build, publish, accessibility and link tests;
   add `console/tests/js/landing.test.js` and
   `console/tests/test_landing_js_scan.py`.
6. `orchestration/verify.sh` and `code-ci.yml`: syntax check and tests for the
   console scripts. `console/README.md` and the `Makefile` help text.

### PR 2 (9.4b): the journey data

- `console/cerberus_landing/journey.py` and
  `console/tests/test_landing_journey.py`.
- A fixed list of 3 executions. Numeric fields only.
- Check names come from an allowlist. Strip the `[dt=...]` suffix. An unknown
  name is counted, not printed.
- A missing value shows as "not recorded".
- Done when each value equals its record field, and hostile fixtures leak
  nothing.

### PR 3 (9.4c): the new page

- All panels are in the HTML. The script only shows and hides them. The page is
  readable without JavaScript and has no dead button.
- Buttons have `aria-controls` and a selected state, work from the keyboard,
  respect reduced motion, have 44 px targets and a phone layout.
- A build-time inline SVG time bar with no `style` attribute (load the dataviz
  skill first).
- On screen: the "estimated" label, the cost exclusions, "total after this run",
  the run date, the record link and the Athena queue time.
- `scan_text` (`showcase.py`) is clean on the built page. Output under 150 KB.
- The owner approves a local preview on desktop and phone **before** the merge.

### PR 4 (9.4d): close 9.4

Tick 9.4 in `Phases.md` after the live check, with this coverage note:

| 9.4 item | Covered by |
|---|---|
| Architecture | The station strip and the existing SVG (fold) |
| Phase status | The build progress fold |
| Latest run | The latest-run strip |
| Grafana panels | A link, from `live.json` only |
| Prometheus panels | Recorded figures |
| Terminal panel | A link |

## 7. Verify (every PR)

- `make verify`.
- `make console-site && make console-site-preview`, then open the preview: no CSP
  error in the browser console.

## 8. ADR check

Stop and use `/decision` before any of these:

- an embedded terminal, a Grafana iframe or anonymous access;
- a runtime read of AWS or AMP from the page;
- a third-party library, font or tracker;
- a custom domain.
