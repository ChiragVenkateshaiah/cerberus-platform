"""Every committed run record loads, and every command renders within the caps.

Guards against drift when a new record lands (the 8.10 run). No AWS: sources are fakes.
"""

import fakes
import pytest

from cerberus_console import config, records
from cerberus_console.api import dispatch
from cerberus_console.sources import Sources


def test_every_real_record_loads():
    files = sorted(config.RUNS_DIR.glob("*.json"))
    assert files, "no run records found"
    rs = records.load(config.RUNS_DIR)
    assert rs.skipped == 0
    assert len(rs.records) == len(files)


@pytest.mark.parametrize("argv", [["help"], ["status"], ["runs"], ["cost"], ["dq"], ["slo"]])
def test_every_command_renders_on_real_records(tmp_path, argv):
    src = fakes.aws_sources(config.RUNS_DIR)
    resp = dispatch(argv, src)
    assert resp.status == 200, resp.body
    assert len(resp.body["text"]) <= config.TEXT_BYTES
    assert len(resp.to_json()) <= config.RESPONSE_BYTES


def test_per_record_commands_on_real_records():
    rs = records.load(config.RUNS_DIR)
    src = Sources(config.RUNS_DIR, lambda: fakes.ExplodingSfn())
    for rec in rs.records:
        for argv in (
            ["run", rec["execution"]],
            ["cost", rec["execution"]],
            ["dq", rec["execution"]],
        ):
            resp = dispatch(argv, src)
            assert resp.status == 200, (argv, resp.body)
            assert len(resp.to_json()) <= config.RESPONSE_BYTES


def test_slo_on_real_records_matches_the_documented_numbers():
    rs = records.load(config.RUNS_DIR)
    resp = dispatch(["slo"], Sources(config.RUNS_DIR))
    s1, s3, s4 = resp.body["data"]["slos"]
    total = len(rs.records)
    ok = sum(1 for r in rs.records if r.get("status") == "SUCCEEDED")
    assert (s1["good"], s1["total"]) == (ok, total)
    assert s3["total"] == total
