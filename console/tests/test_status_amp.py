"""`status` and its AMP section (10.5a/10.5b): layout, fallbacks, JSON, the offline path."""

import json
from datetime import UTC, datetime

import fakes
import pytest
from fakes import series

from cerberus_console import commands, config, grammar, records
from cerberus_console.sources import Sources

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
EPOCH = NOW.timestamp()
HEAD = "Pipeline status (from Prometheus)"


@pytest.fixture
def runs(tmp_path):
    return fakes.materialize_runs(tmp_path / "runs")


def run(sources):
    ctx = commands.Context(sources, records.load(sources.runs_dir), NOW)
    return commands.run(grammar.parse_argv(["status"]), ctx)


def healthy(**over):
    results = {
        "latest_status": [series(1.0)],
        "latest_failed_step": [],
        "latest_started": [series(EPOCH - 7200)],
        "latest_finished": [series(EPOCH - 3600)],
        "last_success": [series(EPOCH - 3600)],
        "latest_run_seconds": [series(540.4)],
        "latest_step_seconds": [series(12.34, "RunDbt"), series(100.0, "RunSpark")],
        "latest_events": [series(1_000_000.0)],
        "latest_dq_passed": [series(1.0)],
        "latest_dq_errors": [series(0.0)],
        "latest_dq_warnings": [series(2.0)],
        "newest_finished_execution": [series(EPOCH - 3600, execution="exercise-1")],
        "run_success_share_90d": [series(0.75)],
        "runs_90d": [series(8.0)],
    }
    results.update(over)
    return results


def with_amp(runs, results):
    return Sources(runs, amp_factory=lambda: fakes.FakeAmp(results))


def pipeline_text(text):
    return text.split("\n\nLatest execution")[0]


def test_the_amp_section_is_first_and_the_old_sections_follow(runs):
    src = fakes.aws_sources(runs)
    src.amp_factory = lambda: fakes.FakeAmp(healthy())
    data, text = run(src)
    order = [text.index(h) for h in (HEAD, "Latest execution", "Gold freshness", "Newest run")]
    assert order == sorted(order) and text.startswith(HEAD)
    assert data["execution"]["status"] == "RUNNING"
    assert data["newest_record"]["available"] is True


def test_layout_rows_use_the_entry_labels(runs):
    data, text = run(with_amp(runs, healthy()))
    block = pipeline_text(text)
    for label in (
        "Last run",
        "Last run started",
        "Last run finished",
        "Last good data",
        "Last run duration",
        "Events handled",
        "Data checks",
        "Data check errors",
        "Data check warnings",
        "Runs that passed (90 days)",
        "Runs in 90 days",
        "Newest finished run",
        "Time per step",
    ):
        assert label in block, label
    assert "Last run" in block and ": passed" in block
    assert "What broke" not in block
    assert "2026-11-02 10:00 UTC (2 h 0 min ago)" in block
    assert "2026-11-02 11:00 UTC (1 h 0 min ago)" in block
    assert "540 s" in block and "1,000,000" in block
    assert "75%" in block and "exercise-1" in block
    assert data["pipeline"]["last_run"] == "passed"
    assert data["pipeline"]["data_checks"] is True


def test_the_labels_come_from_the_query_file_not_from_the_code(runs, monkeypatch):
    from cerberus_console import queries

    doc = queries.load()
    for q in doc["queries"]:
        if q["name"] == "latest_events":
            del q["label"]  # no label: the name is the fallback
        if q["name"] == "latest_run_seconds":
            q["label"] = "How long it took"
    monkeypatch.setattr(queries, "load", lambda *a, **k: doc)
    _, text = run(with_amp(runs, healthy()))
    assert "How long it took" in text and "latest_events" in text
    assert "Last run duration" not in text


def test_a_failed_run_shows_what_broke(runs):
    results = healthy(
        latest_status=[series(0.0)],
        latest_failed_step=[series(1.0, "RunDbt")],
        latest_dq_passed=[series(0.0)],
    )
    data, text = run(with_amp(runs, results))
    block = pipeline_text(text)
    assert ": failed" in block and "What broke" in block and "RunDbt" in block
    assert "Data checks" in block and ": failed" in block.split("Data checks")[1]
    assert data["pipeline"]["what_broke"] == ["RunDbt"]


def test_an_empty_failed_step_while_the_run_passed_prints_nothing(runs):
    data, text = run(with_amp(runs, healthy(latest_failed_step=[series(1.0, "")])))
    assert "What broke" not in text and data["pipeline"]["what_broke"] == []


def test_failed_with_no_step_says_unknown(runs):
    _, text = run(with_amp(runs, healthy(latest_status=[series(0.0)])))
    assert "What broke" in text and "unknown" in text


def test_nan_data_checks_say_not_run_and_hide_errors_and_warnings(runs):
    results = healthy(
        latest_dq_passed=[series(None)],
        latest_dq_errors=[series(None)],
        latest_dq_warnings=[series(None)],
    )
    data, text = run(with_amp(runs, results))
    block = pipeline_text(text)
    assert "not run" in block
    assert "Data check errors" not in block and "Data check warnings" not in block
    assert data["pipeline"]["data_checks"] is None


def test_time_per_step_shows_nan_as_not_reached(runs):
    results = healthy(latest_step_seconds=[series(None, "RunQuality"), series(5.0, "RunDbt")])
    data, text = run(with_amp(runs, results))
    row = next(line for line in text.splitlines() if "RunQuality" in line)
    assert "not reached" in row
    assert {"step": "RunQuality", "seconds": None} in data["pipeline"]["steps"]


def test_time_per_step_is_capped_at_12_rows(runs):
    steps = [series(float(i), f"Step{i:02d}") for i in range(30)]
    data, text = run(with_amp(runs, healthy(latest_step_seconds=steps)))
    assert text.count("Step") == 12
    assert "(18 more not shown)" in text
    assert len(data["pipeline"]["steps"]) == config.STATUS_STEP_ROWS == 12


def test_amp_down_is_unavailable_for_that_section_only(runs):
    src = fakes.aws_sources(runs)
    src.amp_factory = lambda: fakes.ExplodingAmp()
    data, text = run(src)
    assert text.startswith(HEAD + "\n  unavailable")
    assert data["pipeline"] == {"available": False}
    assert data["execution"]["available"] is True
    assert data["gold"]["available"] is True and data["newest_record"]["available"] is True
    assert text.count("unavailable") == 1
    assert "Boom" not in text and "boom" not in text


def test_amp_up_but_empty_is_no_data_yet_never_failed(runs):
    data, text = run(with_amp(runs, {}))
    block = pipeline_text(text)
    assert "no data yet" in block
    assert "failed" not in block and "unavailable" not in block
    assert data["pipeline"] == {"available": True, "none": True}


def test_json_pipeline_data(runs):
    data, _ = run(with_amp(runs, healthy()))
    p = data["pipeline"]
    assert p["available"] is True and p["none"] is False
    assert p["seconds"] == 540.4 and p["events"] == 1_000_000.0
    assert p["success_share_90d"] == 0.75 and p["runs_90d"] == 8.0
    assert p["newest_finished_run"] == "exercise-1"
    assert p["started"].startswith("2026-11-02T10:00")
    assert p["finished"].startswith("2026-11-02T11:00")
    json.dumps(data, allow_nan=False)  # no NaN or Infinity anywhere


def test_a_huge_timestamp_does_not_break_the_section(runs):
    data, text = run(with_amp(runs, healthy(latest_started=[series(1e300)])))
    assert data["pipeline"]["started"] is None and "Last run started" in text


def test_the_command_asks_for_named_queries_only(runs):
    amp = fakes.FakeAmp(healthy())
    run(Sources(runs, amp_factory=lambda: amp))
    assert amp.asked == list(commands.PIPELINE_QUERIES) and len(amp.asked) == 14


def test_status_takes_no_argument_so_nothing_can_reach_query():
    for extra in ("latest_status", "up; DROP", "--query=up"):
        with pytest.raises(grammar.Refused):
            grammar.parse_argv(["status", extra])


def test_the_reader_is_only_called_with_names_from_the_fixed_tuple(runs):
    amp = fakes.FakeAmp(healthy())
    run(Sources(runs, amp_factory=lambda: amp))
    assert set(amp.asked) <= set(commands.PIPELINE_QUERIES)


# --- offline: `make status` with no AWS ------------------------------------


def test_offline_status_still_prints_the_record_section_without_a_traceback(runs):
    data, text = run(Sources(runs))  # no factories at all, as with no credentials
    assert text.count("unavailable") == 3
    assert "Newest run record" in text and "execution" in text
    assert "Traceback" not in text
    assert data["pipeline"] == {"available": False}
    assert data["newest_record"]["available"] is True


def test_the_cli_wires_the_amp_reader():
    import inspect

    from cerberus_console import __main__ as cli

    assert "amp_factory" in inspect.getsource(cli)
