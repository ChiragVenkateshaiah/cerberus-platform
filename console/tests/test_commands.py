import json
from datetime import UTC, datetime

import fakes
import pytest

from cerberus_console import commands, config, grammar, records
from cerberus_console.sources import Sources

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
GOOD = "exercise-20261013T055859Z"
BAD = "exercise-20261008T085728Z"
DEMO = "demo-7-8-take1-20261006T075445"


@pytest.fixture
def runs(tmp_path):
    return fakes.materialize_runs(tmp_path / "runs")


def run(argv, sources):
    ctx = commands.Context(sources, records.load(sources.runs_dir), NOW)
    return commands.run(grammar.parse_argv(argv), ctx)


def test_help_lists_every_command(runs):
    data, text = run(["help"], Sources(runs))
    assert len(data["commands"]) == len(grammar.COMMANDS)
    for name in grammar.COMMANDS:
        assert name in text


def test_runs_table(runs):
    data, text = run(["runs"], Sources(runs))
    assert data["total"] == 4
    assert [r["execution"] for r in data["runs"]][0] == "hostile-20990101T000000Z"
    assert GOOD in text and BAD in text and "FAILED" in text
    assert len(text) < config.TEXT_BYTES


def test_run_latest_and_by_id_use_records_and_sfn(runs):
    src = fakes.aws_sources(runs)
    data, text = run(["run", GOOD], src)
    assert data["record"]["events"] == 100008511
    assert data["sfn"]["available"] is True
    assert "RunDbt" in text


def test_run_failed_shows_state_and_error_code_only(runs):
    data, text = run(["run", BAD], fakes.aws_sources(runs))
    assert data["sfn"]["available"] is True
    assert data["sfn"]["failed_state"] == "RunDbt"
    assert "SECRET-CAUSE-TEXT" not in json.dumps(data) + text
    assert "States.TaskFailed" in text


def test_run_survives_sfn_failure(runs):
    src = Sources(runs, lambda: fakes.ExplodingSfn())
    data, text = run(["run", GOOD], src)
    assert data["record"]["execution"] == GOOD
    assert data["sfn"] == {"available": False}
    assert "unavailable" in text


def test_run_history_expired(runs):
    ctx = commands.Context(
        fakes.aws_sources(runs), records.load(runs), datetime(2027, 6, 1, tzinfo=UTC)
    )
    data, text = commands.run(grammar.parse_argv(["run", BAD]), ctx)
    assert data["sfn"]["expired"] is True
    assert "90 days" in text


def test_run_sfn_only_execution(runs):
    data, text = run(["run", "phase7-exercise-run-1-sfn-only"], fakes.aws_sources(runs))
    assert "No run record in git" in text
    assert "record" not in data


def test_run_unknown_is_not_found(runs):
    with pytest.raises(commands.NotFound):
        run(["run", "nope-1"], fakes.aws_sources(runs))


def test_status_sections(runs):
    src = fakes.aws_sources(runs)
    data, text = run(["status"], src)
    assert data["execution"]["status"] == "RUNNING"
    assert data["execution"]["current_state"] == "RunDbt"
    tables = [t["table"] for t in data["gold"]["tables"]]
    assert tables == list(config.GOLD_TABLES)
    assert data["gold"]["bytes_scanned"] == 24680
    assert data["newest_record"]["available"] is True
    assert "Gold freshness" in text


def test_status_sections_fail_independently(runs):
    src = Sources(runs, lambda: fakes.ExplodingSfn(), lambda: fakes.ExplodingFresh())
    data, text = run(["status"], src)
    assert data["execution"] == {"available": False}
    assert data["gold"] == {"available": False}
    assert data["newest_record"]["available"] is True
    assert text.count("unavailable") == 2


def test_cost_ladder_and_detail_call_no_source(runs):
    src = Sources(runs, fakes.forbidden_factory, fakes.forbidden_factory)
    data, text = run(["cost"], src)
    assert len(data["runs"]) == 4
    assert "no Cost Explorer call" in text
    data, text = run(["cost", GOOD], src)
    assert data["cost"]["day"] == "2026-10-13"
    assert len(data["cost"]["top_services"]) <= 8
    assert "rate excludes" in text


def test_cost_unknown_id(runs):
    with pytest.raises(commands.NotFound):
        run(["cost", "nope-1"], Sources(runs))


def test_dq_default_and_null(runs):
    data, text = run(["dq"], Sources(runs, fakes.forbidden_factory))
    assert data["execution"] == "hostile-20990101T000000Z"
    data, text = run(["dq", DEMO], Sources(runs))
    assert data["data_quality"] is None
    assert "the suite was added in 8.4" in text
    data, text = run(["dq", GOOD], Sources(runs))
    assert data["passed"] is True
    assert len(data["checks"]) > 10
    assert all(len(c["detail"]) <= 120 for c in data["checks"])


def only(runs, tmp_path, *names):
    return fakes.copy_records(tmp_path / "subset", *names)


def test_slo_numbers_on_a_fixture_subset(runs, tmp_path):
    d = only(runs, tmp_path, GOOD, BAD, DEMO)
    data, text = run(["slo"], Sources(d))
    s1, s3, s4 = data["slos"]
    # 2 of 3 succeeded; all 3 under 30 min; serving query seen in 2 (the failed run never got there)
    assert (s1["good"], s1["total"], s1["verdict"]) == (2, 3, "not met")
    assert (s3["good"], s3["total"]) == (3, 3)
    assert (s4["good"], s4["total"]) == (2, 2)
    # one failure that is not the known pair: the generic line, not the 8.6 claim
    assert data["slo1_context"][0].startswith("Failed runs in this window")
    assert "fixed" not in " ".join(data["slo1_context"])


def make_record(tmp_path, name, status, start):
    d = tmp_path / "synthetic"
    d.mkdir(exist_ok=True)
    rec = {"execution": name, "status": status, "start": start, "run_seconds": 100.0}
    (d / f"{name}.json").write_text(json.dumps(rec))
    return d


def test_slo1_context_line_only_for_the_two_known_failures(tmp_path):
    make_record(tmp_path, BAD, "FAILED", "2026-10-08T09:13:33+00:00")
    make_record(tmp_path, "exercise-20261009T101830Z", "FAILED", "2026-10-09T10:36:13+00:00")
    d = make_record(tmp_path, GOOD, "SUCCEEDED", "2026-10-13T06:35:02+00:00")
    data, text = run(["slo"], Sources(d))
    joined = " ".join(data["slo1_context"])
    assert "RunDbt" in joined and "raised to 10 GiB in 8.6" in joined
    assert "1 of 1 runs since the last failure succeeded" in joined
    # a third failure makes the line generic again
    d = make_record(tmp_path, "exercise-20261101T000000Z", "FAILED", "2026-11-01T00:00:00+00:00")
    data, _ = run(["slo"], Sources(d))
    assert "RunDbt" not in " ".join(data["slo1_context"])


def test_slo_without_failures_has_no_context_line(tmp_path):
    d = make_record(tmp_path, GOOD, "SUCCEEDED", "2026-10-13T06:35:02+00:00")
    data, _ = run(["slo"], Sources(d))
    assert data["slo1_context"] == []


def test_no_records_is_unavailable(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    for argv in (["runs"], ["cost"], ["dq"], ["slo"]):
        with pytest.raises(commands.Unavailable):
            run(argv, Sources(empty))
