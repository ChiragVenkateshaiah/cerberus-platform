"""Render check of the pipeline-status dashboard against a real Grafana (plan 10.3b).

Skipped unless CERBERUS_GRAFANA_URL and CERBERUS_PROM_URL are set. `run.sh`
(`make status-render`) starts a throwaway Prometheus and a throwaway Grafana
13.2.3, sets both variables and removes both containers. The Prometheus must be
fresh: the samples are written at now-60 s, now-45 s and now-30 s, in order.

What it proves: Grafana provisions the dashboard JSON unchanged (the panel
datasource type differs from the test datasource, and Grafana resolves it by
uid), and every panel target runs through POST /api/ds/query with no error and
the expected values. It uses the standard library only. No AWS.

What it cannot prove: the transformations (x1000 to milliseconds, rename and
sort of the steps, the runs-table join) and the value mappings run in the
browser, not in /api/ds/query. `screenshot.py` covers them by eye; it is local
only and is not part of CI.
"""

import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

import pytest

GRAFANA = os.environ.get("CERBERUS_GRAFANA_URL", "").rstrip("/")
PROM = os.environ.get("CERBERUS_PROM_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(
    not (GRAFANA and PROM), reason="CERBERUS_GRAFANA_URL and CERBERUS_PROM_URL are not both set"
)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "observability" / "status"))
import publish  # noqa: E402  (stdlib only; needs the path above)

RUNS = ROOT / "observability" / "scale" / "runs"
DASHBOARD = ROOT / "observability" / "grafana" / "dashboards" / "cerberus-pipeline-status.json"
UID = "cerberus-pipeline-status"
FAILED = "exercise-20261008T085728Z"
SUCCEEDED = "exercise-20261015T145812Z"
NEXT = "render-next-run"
DS = {"uid": "amp", "type": "prometheus"}


def panels(node):
    for p in node.get("panels", []):
        yield p
        yield from panels(p)


def targets(dash):
    """(panel title, target) for every target that has a query."""
    return [(p["title"], t) for p in panels(dash) for t in p.get("targets", []) if "expr" in t]


def record_path(execution):
    for path in sorted(RUNS.glob(f"{execution}*.json")):
        if json.loads(path.read_text())["execution"] == execution:
            return path
    raise AssertionError(f"no run record for {execution}")


def iso(offset_seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_seconds))


def push(*argv):
    assert publish.main([*argv, "--url", f"{PROM}/api/v1/write"]) == 0


def get(path):
    with urllib.request.urlopen(f"{GRAFANA}{path}", timeout=15) as resp:
        return json.load(resp)


def run_query(target):
    """One panel target through /api/ds/query. Returns the frames; fails on an error."""
    query = {
        "refId": target["refId"],
        "datasource": DS,
        "expr": target["expr"],
        "instant": target["instant"],
        "range": target["range"],
        "legendFormat": target.get("legendFormat", "__auto"),
        "intervalMs": 3600000,
        "maxDataPoints": 700,
    }
    if "format" in target:
        query["format"] = target["format"]
    body = json.dumps({"queries": [query], "from": "now-30d", "to": "now"}).encode()
    req = urllib.request.Request(
        f"{GRAFANA}/api/ds/query", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.load(resp)["results"][target["refId"]]
    assert "error" not in result, result
    assert result.get("status", 200) == 200, result
    return result.get("frames", [])


def rows(frames):
    """One dict per frame row: field name -> value, plus the labels of the value field."""
    out = []
    for frame in frames:
        fields = frame["schema"]["fields"]
        columns = frame["data"]["values"]
        for i in range(len(columns[0]) if columns else 0):
            row = {f["name"]: columns[j][i] for j, f in enumerate(fields)}
            for f in fields:
                row.update(f.get("labels") or {})
            row["__value__"] = columns[-1][i]
            out.append(row)
    return out


def values(dash, title, ref="A"):
    """Run one panel target by panel title and refId, return its rows."""
    for panel_title, target in targets(dash):
        if panel_title == title and target["refId"] == ref:
            return rows(run_query(target))
    raise AssertionError(f"no target {title!r}/{ref}")


def one(found):
    assert len(found) == 1, found
    return found[0]["__value__"]


def is_nan(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


@pytest.fixture(scope="module")
def dash():
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def test_grafana_provisioned_the_dashboard_unchanged(dash):
    got = get(f"/api/dashboards/uid/{UID}")
    assert got["meta"]["provisioned"] is True
    served = got["dashboard"]
    assert served["title"] == dash["title"]
    assert len(list(panels(served))) == len(list(panels(dash)))
    assert [p["title"] for p in served["panels"] if p["type"] == "row"] == [
        p["title"] for p in dash["panels"] if p["type"] == "row"
    ]
    assert len([p for p in served["panels"] if p["type"] == "row"]) == 5
    # Every panel query expression reaches Grafana as it is in the file.
    assert [t["expr"] for _, t in targets(served)] == [t["expr"] for _, t in targets(dash)]


def test_every_target_runs_before_any_data(dash):
    """A fresh Prometheus: every target answers with an empty result, not an error.

    This test must run first (pytest keeps file order): the next one pushes data.
    """
    for _, target in targets(dash):
        run_query(target)
    with urllib.request.urlopen(f"{PROM}/-/ready", timeout=10) as resp:
        assert resp.status == 200


def test_failed_then_next_start_then_success(dash):
    assert json.loads(record_path(FAILED).read_text())["status"] == "FAILED"
    assert json.loads(record_path(SUCCEEDED).read_text())["status"] == "SUCCEEDED"

    # 1. The failed run, published 60 s ago.
    push("end", "--execution", FAILED, "--record", str(record_path(FAILED)), "--at", iso(-60))
    assert one(values(dash, "Last run")) == 0
    broke = values(dash, "What broke")
    assert [r["step"] for r in broke] == ["RunDbt"]
    assert one(values(dash, "Data check errors")) == 2
    steps = {r["step"]: r["__value__"] for r in values(dash, "Time per step")}
    assert is_nan(steps["RunServingQuery"])
    assert steps["RunDbt"] > 0
    assert values(dash, "Last good data") == []  # a failure writes no last_success
    assert one(values(dash, "Runs that passed (90 days)", "B")) == 1
    assert one(values(dash, "Runs that passed (90 days)")) == 0
    for _, target in targets(dash):
        run_query(target)  # all targets, no error

    # 2. The start of the next run, 45 s ago: it adds only the two start series.
    push("start", "--execution", NEXT, "--started", iso(-45), "--at", iso(-45))
    assert one(values(dash, "Last run")) == 0  # no end series yet

    # 3. The successful run, published 30 s ago.
    push("end", "--execution", SUCCEEDED, "--record", str(record_path(SUCCEEDED)), "--at", iso(-30))
    assert one(values(dash, "Last run")) == 1
    assert values(dash, "What broke") == []
    assert one(values(dash, "Data check errors")) == 0
    assert one(values(dash, "Last good data")) > 0
    assert one(values(dash, "Runs that passed (90 days)", "B")) == 2
    assert one(values(dash, "Runs that passed (90 days)")) == pytest.approx(0.5)
    steps = {r["step"]: r["__value__"] for r in values(dash, "Time per step")}
    assert not any(is_nan(v) for v in steps.values())
    assert set(steps) == {"InvokeIngestion", "RunTransform", "RunDbt", "RunServingQuery"}

    # The runs table: one row per run in each of its two series.
    started = {r["execution"] for r in values(dash, "Recent runs", "A")}
    finished = {r["execution"] for r in values(dash, "Recent runs", "B")}
    assert started == {FAILED, NEXT, SUCCEEDED}
    assert finished == {FAILED, SUCCEEDED}
    assert len(values(dash, "Recent runs", "A")) == 3
    assert len(values(dash, "Recent runs", "B")) == 2

    # The history queries (range) run without error and carry the two statuses.
    history = values(dash, "Run result over time")
    assert {r["__value__"] for r in history} <= {0, 1}
    for _, target in targets(dash):
        run_query(target)
