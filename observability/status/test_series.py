"""Tests for series.py, driven by the committed run records.

No AWS and no network. Run: pytest observability/status
"""

import json
import math
from pathlib import Path

import pytest
import series

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
RUNS = sorted((ROOT / "observability" / "scale" / "runs").glob("*.json"))
CATALOGUE = json.loads((ROOT / "observability" / "queries" / "status.json").read_text())

FAILED_RUN = "exercise-20261008T085728Z"


def load(name):
    return json.loads((ROOT / "observability" / "scale" / "runs" / f"{name}.json").read_text())


def by_key(rows):
    """{(name, frozenset(labels)): value}; fails on a repeated series."""
    out = {}
    for name, labels, value in rows:
        key = (name, frozenset(labels.items()))
        assert key not in out, f"repeated series {key}"
        out[key] = value
    return out


def get(rows, name, **labels):
    return by_key(rows)[(name, frozenset(labels.items()))]


def test_there_are_17_records():
    assert len(RUNS) == 17


@pytest.mark.parametrize("path", RUNS, ids=lambda p: p.stem)
def test_every_record_converts(path):
    rows = series.end_series(json.loads(path.read_text()))
    by_key(rows)
    # 6 fixed + 2 repeated started + 3 DQ + 2 per step; 1 more on success
    expected = 6 + 2 + 3 + 2 * len(series.STEPS) + (1 if rows[0][2] == 1 else 0)
    assert len(rows) == expected


def test_steps_equal_asl_task_states():
    asl = series.ASL.read_text()
    # Independent of the parser: a Task state is a 4-space-indented key whose
    # first line inside is "Type": "Task".
    import re

    found = re.findall(r'^    "(\w+)": \{\n\s+"Type": "Task"', asl, re.M)
    assert series.STEPS == found
    assert series.STEPS == ["InvokeIngestion", "RunTransform", "RunDbt", "RunServingQuery"]


def test_emitted_series_equal_catalogue_both_ways():
    emitted = {}
    for path in RUNS:
        for name, labels, _ in series.end_series(json.loads(path.read_text())):
            emitted.setdefault(name, set()).add(tuple(sorted(labels)))
    for name, labels, _ in series.start_series("x", "2026-11-20T10:00:00Z"):
        emitted.setdefault(name, set()).add(tuple(sorted(labels)))
    catalogue = {m["name"]: tuple(sorted(m["labels"])) for m in CATALOGUE["metrics"]}
    assert {n: next(iter(ls)) for n, ls in emitted.items()} == catalogue
    assert all(len(ls) == 1 for ls in emitted.values())


def test_failed_run():
    rows = series.end_series(load(FAILED_RUN))
    assert get(rows, "cerberus_run_status") == 0
    assert get(rows, "cerberus_run_step_failed", step="RunDbt") == 1
    for step in ("InvokeIngestion", "RunTransform", "RunServingQuery"):
        assert get(rows, "cerberus_run_step_failed", step=step) == 0
    assert math.isnan(get(rows, "cerberus_step_duration_seconds", step="RunServingQuery"))
    assert get(rows, "cerberus_step_duration_seconds", step="RunDbt") == 341.3
    assert get(rows, "cerberus_dq_errors") == 2
    assert get(rows, "cerberus_dq_warnings") == 1
    assert get(rows, "cerberus_dq_passed") == 0
    assert get(rows, "cerberus_run_duration_seconds") == 571.6
    assert get(rows, "cerberus_run_events_processed") == 1051434


def test_unknown_dq_is_nan():
    rows = series.end_series(load("demo-7-8-take1-20261006T075445"))
    for name in ("cerberus_dq_passed", "cerberus_dq_errors", "cerberus_dq_warnings"):
        assert math.isnan(get(rows, name))
    assert get(rows, "cerberus_run_status") == 1


def test_unknown_events_is_nan():
    record = load(FAILED_RUN)
    del record["events_processed"]
    assert math.isnan(get(series.end_series(record), "cerberus_run_events_processed"))


def test_success_writes_last_success_and_failure_does_not():
    ok = series.end_series(load("exercise-20261008T095905Z"))
    names = {n for n, _, _ in ok}
    assert "cerberus_last_success_timestamp_seconds" in names
    assert get(ok, "cerberus_last_success_timestamp_seconds") == get(
        ok, "cerberus_run_finished_timestamp_seconds"
    )
    bad = series.end_series(load(FAILED_RUN))
    assert "cerberus_last_success_timestamp_seconds" not in {n for n, _, _ in bad}


def test_success_has_all_steps_zero():
    rows = series.end_series(load("exercise-20261008T095905Z"))
    for step in series.STEPS:
        assert get(rows, "cerberus_run_step_failed", step=step) == 0
        assert not math.isnan(get(rows, "cerberus_step_duration_seconds", step=step))


def test_started_series_repeat_at_end():
    record = load(FAILED_RUN)
    rows = series.end_series(record)
    start = series.start_series(FAILED_RUN, record["start"])
    for name, labels, value in start:
        assert get(rows, name, **labels) == value
    assert get(rows, "cerberus_run_started_timestamp_seconds") == 1791450813.494


def test_start_series():
    rows = series.start_series("e1", "2026-11-20T10:00:00Z")
    assert rows == [
        ("cerberus_run_started_timestamp_seconds", {}, 1795168800.0),
        ("cerberus_execution_started_timestamp_seconds", {"execution": "e1"}, 1795168800.0),
    ]


def test_failed_step_order():
    base = {"status": "FAILED", "states": [{"state": "InvokeIngestion"}, {"state": "RunTransform"}]}
    assert series.failed_step(base) == "RunTransform"
    assert series.failed_step({**base, "failed_state": "RunDbt"}) == "RunDbt"
    assert series.failed_step({"status": "FAILED", "states": []}) is None
    assert series.failed_step({**base, "status": "SUCCEEDED", "failed_state": "RunDbt"}) is None


def test_unknown_failed_step_sets_all_zero():
    record = {**load(FAILED_RUN), "states": []}
    rows = series.end_series(record)
    for step in series.STEPS:
        assert get(rows, "cerberus_run_step_failed", step=step) == 0
        assert math.isnan(get(rows, "cerberus_step_duration_seconds", step=step))


def test_parse_steps_ignores_non_task_and_template_syntax():
    text = (
        '{"States": {"A": {"Type": "Task", "X": ${list}, "Y": "${s}"},'
        ' "B": {"Type": "Succeed"}, "C": {"Type": "Task"}}}'
    )
    assert series.parse_steps(text) == ["A", "C"]


def test_naive_iso_means_utc():
    assert series.epoch("2026-11-20T10:00:00") == series.epoch("2026-11-20T10:00:00+00:00")


@pytest.mark.parametrize("status", ["ABORTED", "TIMED_OUT"])
def test_abort_and_timeout_without_failed_state_name_no_step(status):
    record = {**load(FAILED_RUN), "status": status}
    assert series.failed_step(record) is None
    rows = series.end_series(record)
    assert get(rows, "cerberus_run_status") == 0
    for step in series.STEPS:
        assert get(rows, "cerberus_run_step_failed", step=step) == 0


def test_abort_with_failed_state_names_it():
    record = {**load(FAILED_RUN), "status": "ABORTED", "failed_state": "RunTransform"}
    assert get(series.end_series(record), "cerberus_run_step_failed", step="RunTransform") == 1


def test_dq_missing_fields_are_nan():
    record = {**load(FAILED_RUN), "data_quality": {"errors": 3}}
    rows = series.end_series(record)
    assert math.isnan(get(rows, "cerberus_dq_passed"))
    assert get(rows, "cerberus_dq_errors") == 3
    assert math.isnan(get(rows, "cerberus_dq_warnings"))
    record["data_quality"] = {"passed": None}
    assert math.isnan(get(series.end_series(record), "cerberus_dq_passed"))
