# Plan 14.3: replay set and scored harness

## Goal
Roadmap 14.3 (Phases.md L332): a labelled replay set plus an offline scored harness (`make eval`) over the 14.2a review core. It needs no model call and no AWS.

## Facts (sources)
- The review core `review(record, records)` returns `{execution, scale_class, findings[{id,rule,evidence[ids]}], evidence[{id,...}]}`. Source: agents/cerberus_agents/review.py L53-146. It has 8 rules (RULES, L29). It is deterministic.
- The proposals to score are in agents/cerberus_agents/baselines.py: SCALE_CLASSES L11 (100k, 5M, 50M), MIN_PEERS 3, STEP_SLOW_FACTOR 1.5, COST_OUTLIER_FACTOR 2.0, ATHENA_QUEUE_LIMIT_SECONDS 60.0. The 14.2 plan Risks list also names KNOWN_CHECKS (evidence.py) and the execution-name shape.
- The golden reviews in agents/tests/golden/ give current findings. The rules fire on only these records:
  - `20261008T085728Z`: run_failed, dq_errors.
  - `20261009T101830Z`: run_failed, step_slow.
  - `20261012T075045Z`: step_slow, cost_outlier.
  - `20261015T145812Z`: athena_queue (230.5 s, fixed 60 s limit).
  - `demo-7-8-take1`: dq_missing, cost_missing.
  - All other records: no findings.
- The labelled history is in ADR 0025 L39-60, with 6 incidents. Run records are tracked in observability/scale/runs/. Raw logs in observability/scale/exercises/ are git-ignored (.gitignore L64). Do not depend on them.
- The count of 17 records is from the 14.2 plan. My listing showed 15 `exercise-*`/`demo-*` files plus 2 rehearsals, so 17 is consistent. I did not re-count.
- verify.sh L40 runs `pytest agents/tests`. CI code-ci.yml L193 does the same.

## Incident classes: fixture now?
- Failed run, RunDbt (`20261008T085728Z`): YES. The record has status FAILED, DQ errors 2 and no RunServingQuery. Expected: run_failed (failed step RunDbt) and dq_errors. Missing: the role/timestamptz cause is not in the record. That is a 14.5 triage fact, not a 14.3 label.
- Failed run, 1 GiB Athena cutoff (`20261009T101830Z`): PARTLY. Expected: run_failed. The golden also has step_slow. The cause is unverified in ADR 0025 L44. Label only run_failed as required. Mark step_slow as "accepted extra", not an error.
- Glue timeouts (`20261012T075045Z`): PARTLY. The record shows slow RunDbt (step_slow, cost_outlier). The two `OperationTimeoutException` retries are only in the ignored log. Label the symptom (step_slow on RunDbt). Mark the retries as MISSING: needs a masked, tracked log excerpt.
- Spot interruption (`20261012T133620Z`): NO as a found incident. The run SUCCEEDED and the record has no decommission data (keys: no spot field). The review core gives zero findings. Missing: a masked excerpt of the FIS and executor-decommission lines. Until then, label it `expect_found: false, reason: not_visible_in_record`. That counts as a known gap, not a pass. This is the 6th incident the 5-of-6 bar tolerates.
- Athena queue (`20261015T145812Z`): YES. Expected: athena_queue RunDbt 230.5 s.
- Generator commit (`20261013T055859Z`): YES. Expected: no findings ("not found"). The core gives none.
- Clean runs: YES. Use at least 3 from the golden-empty set: `20261007T145442Z`, `20261008T095905Z`, `rehearsal-1m-20261108T060517Z`, `demo-100m-20261108T135119Z`. Pick 4.
- SEARCH index and other ADR write-ups: no tracked record. Skip.

## Steps (small PRs)
**PR 1: format and loader.** Files: agents/eval/__init__.py, agents/eval/cases/*.json, agents/eval/cases.py, agents/tests/test_eval_cases.py.
- Case JSON: `{case_id, record: "<run file name>" | {mutation}, label: {expect: [{rule, step?}], expect_absent: [rule], expect_none: bool, accepted_extra: [rule], required_evidence: [{rule, fields}]}, source: "<ADR/plan ref>", gap: null|"<what is missing>"}`.
- Real records are referenced by file name, not copied. Synthetic variants are `{base, set: {path: value}, note}` with a documented mutation. For example: a clean record with queue_seconds set to 59 and to 61, to test the limit edge.
- Cases: 5 real incidents, 1 gap case (Spot), 4 clean, about 6 synthetic boundary variants.
- Acceptance: the loader checks the schema. Every referenced record exists. No account-ID pattern (`\d{12}`) is in the cases. No unknown rule id appears in a label.

**PR 2: scorer, answerers, report.** Files: agents/eval/score.py, agents/eval/answerers.py, agents/eval/__main__.py, tests.
- Answerer interface: `answer(review_obj, case) -> {claims: [{rule, step?, evidence: [ids]}]}`. 14.4 plugs in a model answerer here.
- `echo_answerer` turns the findings into claims. `bad_answerer` adds a claim with an invented id (e99) and drops evidence.
- Metrics:
  - per-rule precision and recall;
  - incidents found (x of 6, with the Spot gap shown);
  - clean-run false findings (a count, bar at most 1);
  - cited-claim validity (every claim cites at least 1 id, and each id is in review.evidence);
  - determinism (3 repeats, the dumps bytes match, the spread is shown).
- Acceptance: echo scores pass the ADR bar. bad_answerer fails cited-validity and the test asserts this. The same input gives the same bytes.

**PR 3: threshold sweep.** Files: agents/eval/sweep.py, docs/eval/sweep-report.{md,json}.
- It overrides the constants in-process on a copy, never on disk. Grid: STEP_SLOW 1.25/1.5/2.0/3.0, COST 1.5/2.0/3.0, queue 30/60/120/200 s, scale-class bounds (current vs. one shifted). It reports found, false findings and margin per value.
- The report is sorted and has no clock. A test fails if the committed report differs from a fresh run. The test also asserts that baselines.py is unchanged.
- The report says that n is small. A change to a constant is a human edit with its own PR.

**PR 4: wiring.** Files: Makefile (`eval:` with PYTHONPATH=agents:console, like `mcp`), orchestration/verify.sh (add a `check "agents eval"` step that runs the eval and exits non-zero below the bar), .github/workflows/code-ci.yml (one step, as it is just python), agents/README.md.
- Acceptance: `make eval` writes docs/eval/report.{md,json} (deterministic) and exits 0. `make verify` includes it.

## Verify
`make verify`, then `make eval` twice and `git diff --exit-code docs/eval` to check for drift. Run `pytest agents/tests` also.

## Owner steps
None. All offline, $0, nothing runs when idle.

## Risks and unverified
- The n is about 10 and every real label is derived from golden output. The label is circular for rules that were tuned on the same records. Say so in the report. Do not claim a real recall number.
- Circular labels, stated plainly: the labels come from the same records the rules and thresholds were tuned on. The harness shows that the rules still behave as tuned. It does not measure recall, and no real recall figure is claimed.
- The Spot and Glue-retry incidents cannot be found from records today. The 5 of 6 bar passes only if the other five are found. The Failed-1GiB step_slow extra needs an accepted_extra rule, so it is not counted as a false positive.
- The queue limit (60 s) is scored against one real point (230.5 s). The sweep cannot tune it with confidence.
- Peers: the scale-class sweep depends on the record set. Adding records changes the baselines.
- 14.2 plan note: KNOWN_CHECKS and the execution-name shape are tested only through the tools. PR 1 must add a case with an unknown check name (expect: skipped). I did not verify what the core does with it.

## Wait for 14.4/14.7
- Model answers, the model-vs-model comparison, 3-repeat spread on model text, the Haiku-vs-Sonnet decision and AI cost (the ADR's about $0.60 estimate) wait for 14.4 and 14.7.
- Masked log excerpts for Glue timeouts and Spot need the owner or 14.5 to produce them.

## Open questions
1. Are the two log-only incidents (Glue timeouts, Spot) allowed to score "not found" until masked excerpts exist? Recommended: yes, keep them as visible gap cases. Do not fake a pass.
2. Should the bar fail `make verify` or only warn? Recommended: fail on the ADR bar and on cited-claim validity below 100%. Warn only on sweep drift.

## Owner answers (2026-11-21)
1. Yes. The two log-only incidents (Glue timeouts, Spot) stay visible gap cases and score "not found" until masked excerpts exist.
2. Yes. `make verify` fails on the ADR 0025 bar and on cited-claim validity below 100%. Sweep drift only warns.
