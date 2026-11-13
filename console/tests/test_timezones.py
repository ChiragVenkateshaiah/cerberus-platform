"""Times labelled UTC are really UTC, whatever the machine's local zone is."""

import time
from datetime import UTC, datetime, timedelta, timezone

import fakes
import pytest

from cerberus_console import aws, commands, grammar, records
from cerberus_console.sources import Sources

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def ist_machine(monkeypatch):
    """A machine in Asia/Kolkata: naive local times and boto3 datetimes are IST."""
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def runs_dir(tmp_path):
    return fakes.materialize_runs(tmp_path / "runs")


def run(argv, sources):
    ctx = commands.Context(sources, records.load(sources.runs_dir), NOW)
    return commands.run(grammar.parse_argv(argv), ctx)


def test_when_converts_offsets_to_utc():
    assert commands._when("2026-10-13T11:05:02+05:30") == "2026-10-13 05:35 UTC"
    assert commands._when("2026-10-13T06:35:02.004000+00:00") == "2026-10-13 06:35 UTC"
    assert commands._when("2026-10-13T06:35:02Z") == "2026-10-13 06:35 UTC"
    # The date changes when the UTC time crosses midnight.
    assert commands._when("2026-10-13T01:00:00+05:30") == "2026-10-12 19:30 UTC"


def test_when_treats_naive_as_utc_under_a_local_zone(ist_machine):
    assert commands._when("2026-10-13T06:35:02") == "2026-10-13 06:35 UTC"
    assert commands._when(None) == "-"
    assert commands._when("garbage") == "-"


def test_aws_dt_and_iso_are_utc_under_a_local_zone(ist_machine):
    local = datetime(2026, 11, 2, 19, 56, tzinfo=IST)
    assert aws._iso(local) == "2026-11-02T14:26:00+00:00"
    assert aws._iso(datetime(2026, 11, 2, 14, 26)) == "2026-11-02T14:26:00+00:00"
    assert aws._iso("2026-11-02T19:56:00+05:30") == "2026-11-02T14:26:00+00:00"
    assert aws._dt(local).utcoffset() == timedelta(0)


class IstSfn(fakes.ExplodingSfn):
    def list_executions(self):
        start = datetime(2026, 11, 2, 19, 56, tzinfo=IST)
        return [
            {
                "name": "exercise-20261102T142600Z",
                "status": "SUCCEEDED",
                "arn": "arn:x",
                "start": aws._iso(start),
                "stop": aws._iso(start + timedelta(minutes=30)),
            }
        ]


def test_status_start_is_utc_under_a_local_zone(runs_dir, ist_machine):
    src = Sources(runs_dir, lambda: IstSfn(), fakes.forbidden_factory)
    data, text = run(["status"], src)
    assert "2026-11-02 14:26 UTC" in text
    assert "19:56" not in text
    assert data["execution"]["seconds"] == 1800.0


def test_record_commands_render_utc_under_a_local_zone(runs_dir, ist_machine):
    src = Sources(runs_dir, fakes.forbidden_factory, fakes.forbidden_factory)
    # Fixture start 06:35:02+00:00 must print as 06:35 UTC on an IST machine.
    _, text = run(["runs"], src)
    assert "2026-10-13 06:35 UTC" in text
    _, text = run(["run", "exercise-20261013T055859Z"], Sources(runs_dir, lambda: IstSfn()))
    assert "2026-10-13 06:35 UTC" in text
    # cost, dq and slo print dates and numbers only, never a local clock time.
    for argv in (["cost"], ["dq"], ["slo"]):
        _, text = run(argv, src)
        assert "IST" not in text
