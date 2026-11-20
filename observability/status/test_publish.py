"""Tests for publish.py (dry run) and the no-network rule.

No AWS and no network. Run: pytest observability/status
"""

import json
import math
import re
from pathlib import Path

import publish
import pytest

HERE = Path(__file__).parent
FAILED_RUN = "exercise-20261008T085728Z"
AT = "2026-11-20T12:00:00Z"
AT_MS = 1795176000000


def run(capsys, *argv):
    code = publish.main(list(argv))
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err


def parse(lines):
    """Text exposition -> {series text: (value, ts)}."""
    out = {}
    for line in lines:
        head, value, ts = line.rsplit(" ", 2)
        out[head] = (float(value), int(ts))
    return out


def test_end_dry_run_output(capsys):
    code, lines, err = run(capsys, "end", "--execution", FAILED_RUN, "--at", AT)
    assert code == 0
    assert lines == sorted(lines)
    got = parse(lines)
    assert {ts for _, ts in got.values()} == {AT_MS}
    assert got["cerberus_run_status"][0] == 0
    assert got['cerberus_run_step_failed{step="RunDbt"}'][0] == 1
    assert got['cerberus_run_step_failed{step="RunTransform"}'][0] == 0
    assert math.isnan(got['cerberus_step_duration_seconds{step="RunServingQuery"}'][0])
    assert "cerberus_last_success_timestamp_seconds" not in got
    assert "not sent" in err


def test_nan_is_printed_as_nan(capsys):
    _, lines, _ = run(capsys, "end", "--execution", FAILED_RUN, "--at", AT)
    assert f'cerberus_step_duration_seconds{{step="RunServingQuery"}} NaN {AT_MS}' in lines
    assert f"cerberus_dq_errors 2 {AT_MS}" in lines


def test_start_dry_run(capsys):
    started = "2026-11-20T11:59:00Z"
    code, lines, _ = run(capsys, "start", "--execution", "e1", "--started", started, "--at", AT)
    assert code == 0
    assert lines == [
        f'cerberus_execution_started_timestamp_seconds{{execution="e1"}} 1795175940 {AT_MS}',
        f"cerberus_run_started_timestamp_seconds 1795175940 {AT_MS}",
    ]


def test_start_defaults_started_to_publish_time(capsys):
    _, lines, _ = run(capsys, "start", "--execution", "e1", "--at", AT)
    assert f"cerberus_run_started_timestamp_seconds 1795176000 {AT_MS}" in lines


def test_record_override(capsys, tmp_path):
    record = json.loads(
        (HERE.parents[1] / "observability/scale/runs" / f"{FAILED_RUN}.json").read_text()
    )
    record["execution"] = "copy"
    path = tmp_path / "r.json"
    path.write_text(json.dumps(record))
    code, lines, _ = run(capsys, "end", "--execution", "copy", "--record", str(path), "--at", AT)
    assert code == 0
    assert any('execution="copy"' in line for line in lines)


def test_missing_record_exits_2(capsys, tmp_path):
    code, lines, err = run(capsys, "end", "--execution", "nope", "--record", str(tmp_path / "x"))
    assert code == 2 and lines == [] and "cannot read" in err


def test_unknown_command_is_refused():
    with pytest.raises(SystemExit):
        publish.main(["send", "--execution", "x"])


def test_no_boto3_or_network_imports():
    banned = re.compile(r"^\s*(import|from)\s+(boto3|botocore|urllib|http|socket|requests)\b", re.M)
    for path in HERE.glob("*.py"):
        text = path.read_text()
        assert not banned.search(text), path.name
        if not path.name.startswith("test_"):  # test files only name the modules
            assert "boto3" not in text, path.name


def test_record_for_another_execution_exits_2(capsys, tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"execution": "other"}))
    code, lines, err = run(capsys, "end", "--execution", "wanted", "--record", str(path))
    assert code == 2 and lines == [] and "'other'" in err and "'wanted'" in err
