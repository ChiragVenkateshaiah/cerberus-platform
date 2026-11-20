"""End-to-end test against a throwaway local Prometheus (plan 10.2, PR C).

Skipped unless CERBERUS_PROM_URL is set, for example http://127.0.0.1:9099.
`make status-e2e` starts the container, sets the variable and removes the
container. The receiver must run with --web.enable-remote-write-receiver.

It proves, against a real receiver: the protobuf field numbers, snappy
decoding, NaN samples, and that every entry in observability/queries/status.json
parses. No AWS. It needs a fresh Prometheus: the samples are written at now-60 s,
now-45 s and now-30 s, in that order, so they are in order for the TSDB.
"""

import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import publish
import pytest

BASE = os.environ.get("CERBERUS_PROM_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="CERBERUS_PROM_URL is not set")

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "observability" / "scale" / "runs"
QUERIES = json.loads((ROOT / "observability" / "queries" / "status.json").read_text())["queries"]
FAILED = "exercise-20261008T085728Z"
SUCCEEDED = "exercise-20261015T145812Z"  # checked to be SUCCEEDED in the test
NEXT = "e2e-next-run"


def record_path(execution):
    """The committed record for `execution`; the file names carry a suffix."""
    for path in sorted(RUNS.glob(f"{execution}*.json")):
        if json.loads(path.read_text()).get("execution") == execution:
            return path
    raise AssertionError(f"no run record for {execution}")


def iso(offset_seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_seconds))


def push(*argv):
    # An unreachable receiver or a non-2xx reply makes publish.main return 1.
    assert publish.main([*argv, "--url", f"{BASE}/api/v1/write"]) == 0


def evaluate():
    """{entry name: result vector}. Every entry must parse and evaluate."""
    out = {}
    for entry in QUERIES:
        params = urllib.parse.urlencode({"query": entry["expr"], "time": f"{time.time():.3f}"})
        with urllib.request.urlopen(f"{BASE}/api/v1/query?{params}", timeout=10) as resp:
            body = json.load(resp)
        assert body["status"] == "success", entry["name"]
        assert body["data"]["resultType"] == "vector", entry["name"]
        out[entry["name"]] = body["data"]["result"]
    return out


def scalar(result):
    """The sample value of a one-element vector."""
    assert len(result) == 1, result
    return float(result[0]["value"][1])


def test_failed_run_then_next_start_then_success():
    with urllib.request.urlopen(f"{BASE}/-/ready", timeout=10) as resp:
        assert resp.status == 200
    assert json.loads(record_path(FAILED).read_text())["status"] == "FAILED"
    success_record = json.loads(record_path(SUCCEEDED).read_text())
    assert success_record["status"] == "SUCCEEDED"

    # 1. The failed run, published 60 s ago.
    push("end", "--execution", FAILED, "--record", str(record_path(FAILED)), "--at", iso(-60))
    got = evaluate()
    assert scalar(got["latest_status"]) == 0
    # Prometheus v3.15.0 keeps __name__ on `last_over_time(...) == 1`; __name__ is
    # optional for consumers (AMP may differ), so only the step label is checked.
    assert [
        {k: v for k, v in r["metric"].items() if k != "__name__"} for r in got["latest_failed_step"]
    ] == [{"step": "RunDbt"}]
    assert scalar(got["latest_dq_errors"]) == 2
    by_step = {r["metric"]["step"]: float(r["value"][1]) for r in got["latest_step_seconds"]}
    assert math.isnan(by_step["RunServingQuery"])
    assert by_step["RunDbt"] > 0  # a real value next to the NaN
    assert got["last_success"] == []  # a failure writes no last_success
    assert [r["metric"]["execution"] for r in got["newest_finished_execution"]] == [FAILED]

    # 2. The start of the next run, 45 s ago. It adds only the two start series.
    push("start", "--execution", NEXT, "--started", iso(-45), "--at", iso(-45))
    got = evaluate()
    assert scalar(got["latest_status"]) == 0  # no end series yet
    assert [r["metric"]["execution"] for r in got["newest_started_execution"]] == [NEXT]
    assert [r["metric"]["execution"] for r in got["newest_finished_execution"]] == [FAILED]

    # 3. The successful run, published 30 s ago.
    push("end", "--execution", SUCCEEDED, "--record", str(record_path(SUCCEEDED)), "--at", iso(-30))
    got = evaluate()
    assert scalar(got["latest_status"]) == 1
    assert got["latest_failed_step"] == []
    assert scalar(got["last_success"]) == pytest.approx(publish.series.epoch(success_record["end"]))
    assert [r["metric"]["execution"] for r in got["newest_finished_execution"]] == [SUCCEEDED]
    assert scalar(got["latest_dq_errors"]) == 0
