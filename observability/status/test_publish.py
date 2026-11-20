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
    # PR C: urllib is allowed in publish.py (--url) and test_e2e.py (queries the
    # local Prometheus) only. boto3, botocore, socket and requests stay banned.
    always = re.compile(r"^\s*(import|from)\s+(boto3|botocore|socket|requests)\b", re.M)
    banned = re.compile(r"^\s*(import|from)\s+(boto3|botocore|urllib|http|socket|requests)\b", re.M)
    for path in HERE.glob("*.py"):
        text = path.read_text()
        if path.name in ("publish.py", "test_e2e.py"):
            assert not always.search(text), path.name
        else:
            assert not banned.search(text), path.name
        if not path.name.startswith("test_"):  # test files only name the modules
            assert "boto3" not in text, path.name


def test_record_for_another_execution_exits_2(capsys, tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"execution": "other"}))
    code, lines, err = run(capsys, "end", "--execution", "wanted", "--record", str(path))
    assert code == 2 and lines == [] and "'other'" in err and "'wanted'" in err


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/api/v1/write",
        "http://10.0.0.5:9090/api/v1/write",
        "https://127.0.0.1:9090/api/v1/write",
        "http://127.0.0.1.evil.test/api/v1/write",
        "ftp://localhost/x",
        "127.0.0.1:9090",
    ],
)
def test_url_not_loopback_http_exits_2(capsys, monkeypatch, url):
    monkeypatch.setattr(publish, "send", lambda *a: pytest.fail("must not send"))
    code, lines, err = run(capsys, "start", "--execution", "e1", "--url", url)
    assert code == 2 and lines == [] and "--url must be http" in err


@pytest.mark.parametrize("host", ["127.0.0.1:9099", "[::1]:9099", "localhost:9099"])
def test_url_loopback_sends_the_body(capsys, monkeypatch, host):
    seen = []
    monkeypatch.setattr(publish, "send", lambda url, body: seen.append((url, body)) or (204, ""))
    code, lines, err = run(
        capsys, "start", "--execution", "e1", "--at", AT, "--url", f"http://{host}/w"
    )
    assert code == 0 and len(lines) == 2 and "HTTP 204" in err
    assert seen[0][0] == f"http://{host}/w" and seen[0][1]


def test_url_non_2xx_exits_1_with_the_reply(capsys, monkeypatch):
    monkeypatch.setattr(publish, "send", lambda url, body: (400, "bad " * 100))
    code, _, err = run(capsys, "start", "--execution", "e1", "--url", "http://127.0.0.1:1/w")
    assert code == 1 and "HTTP 400" in err and "bad bad" in err


def test_url_connection_refused_exits_1(capsys):
    code, _, err = run(capsys, "start", "--execution", "e1", "--url", "http://127.0.0.1:1/w")
    assert code == 1 and "send failed" in err
