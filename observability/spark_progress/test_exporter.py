"""Tests for exporter.py, driven by the 6b fixtures (fixtures/*.json).

A fake driver serves a fixture over real HTTP, so `/probe` is tested end to
end. Run: pytest observability/spark_progress
"""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import exporter
import pytest

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def parse(text):
    """Prometheus text -> {series: value}, skipping comment lines."""
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            series, value = line.rsplit(" ", 1)
            out[series] = float(value)
    return out


def run_fixture(name):
    fx = load(name)
    return exporter.compute(fx["applications"], fx["jobs"], fx["stages"])


class FakeDriver(BaseHTTPRequestHandler):
    payloads = {}  # path -> (status, body)

    def do_GET(self):  # noqa: N802
        status, body = self.payloads.get(self.path, (404, b"{}"))
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def driver_for(fx):
    app_id = fx["applications"][0]["id"]
    base = "/api/v1/applications"
    FakeDriver.payloads = {
        base: (200, json.dumps(fx["applications"]).encode()),
        f"{base}/{app_id}/jobs": (200, json.dumps(fx["jobs"]).encode()),
        f"{base}/{app_id}/stages": (200, json.dumps(fx["stages"]).encode()),
    }
    return serve(FakeDriver)


@pytest.fixture
def exporter_url():
    srv = serve(exporter.Handler)
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


# fixture -> (rows, activity). Values come from the fixtures (CAPTURE.md).
EXPECTED = {
    "generator-early-map-stage": ({"payments_created": 0}, "creating_payments"),
    "generator-map-done": ({"payments_created": 0}, "creating_payments"),
    "generator-write-mid": ({"payments_created": 3262330}, "creating_payments"),
    "generator-end-idle": ({"payments_created": 8000122}, "saving_files"),
    "generator-count-pass": ({"payments_created": 300023}, "finishing"),
    "silver-early-bronze-scan": (
        {"new_payments_read": 0, "added_to_clean_table": 0},
        "reading_new_payments",
    ),
    "silver-bronze-scan-mid": (
        {"new_payments_read": 5293805, "added_to_clean_table": 0},
        "reading_new_payments",
    ),
    "silver-anti-join-mid": (
        {"new_payments_read": 8000122, "added_to_clean_table": 0},
        "adding_to_clean_table",
    ),
    "silver-append-mid": (
        {"new_payments_read": 8000122, "added_to_clean_table": 902388},
        "adding_to_clean_table",
    ),
    "silver-end-commit": (
        {"new_payments_read": 8000122, "added_to_clean_table": 8000122},
        "finishing",
    ),
    "silver-incr-two-scans": (
        {"new_payments_read": 0, "added_to_clean_table": 0},
        "reading_new_payments",
    ),
    "silver-incr-append-mid": (
        {"new_payments_read": 300023, "added_to_clean_table": 0},
        "adding_to_clean_table",
    ),
    "silver-compaction-active": (
        {"new_payments_read": 300023, "added_to_clean_table": 300023},
        "tidying_files",
    ),
    "silver-compaction-end": (
        {"new_payments_read": 300023, "added_to_clean_table": 300023},
        "finishing",
    ),
}


def test_expected_covers_every_fixture():
    assert {p.stem for p in FIXTURES.glob("*.json")} == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_rows_and_activity(name):
    rows, activity, _ = run_fixture(name)
    assert (rows, activity) == EXPECTED[name]


def test_end_values_equal_the_logged_ones():
    # CAPTURE.md "Row definitions against the logs": generator
    # `events=8000122`, silver `appended 8000122`, round 4 `300023`.
    assert run_fixture("generator-end-idle")[0]["payments_created"] == 8_000_122
    silver = run_fixture("silver-end-commit")[0]
    assert silver["added_to_clean_table"] == 8_000_122
    assert silver["new_payments_read"] == 8_000_122
    assert run_fixture("generator-count-pass")[0]["payments_created"] == 300_023
    assert run_fixture("silver-compaction-end")[0]["added_to_clean_table"] == 300_023
    capture = (HERE / "CAPTURE.md").read_text()
    assert "8,000,122" in capture and "300,023" in capture


def test_exactly_one_activity_series_per_probe():
    for name in EXPECTED:
        fx = load(name)
        text = exporter.render(True, *run_fixture(name)[:2], 0)
        assert len(re.findall(r"^cerberus_spark_activity\{", text, re.M)) == 1, fx["capturedAt"]
    assert exporter.render(True, {}, "waiting", 0).count("cerberus_spark_activity{") == 1


def test_phase_rows_only():
    assert set(run_fixture("generator-write-mid")[0]) == {"payments_created"}
    assert set(run_fixture("silver-end-commit")[0]) == {
        "new_payments_read",
        "added_to_clean_table",
    }


def test_skipped_stages_are_ignored():
    fx = load("silver-end-commit")
    assert any(s["status"] == "SKIPPED" for s in fx["stages"])
    for s in fx["stages"]:
        if s["status"] == "SKIPPED":
            s.update(numCompleteTasks=999, inputRecords=999, outputRecords=999)
    rows, _, tasks = exporter.compute(fx["applications"], fx["jobs"], fx["stages"])
    assert rows == {"new_payments_read": 8000122, "added_to_clean_table": 8000122}
    assert tasks == sum(s["numCompleteTasks"] for s in fx["stages"] if s["status"] != "SKIPPED")


def test_compaction_stages_are_not_counted_as_added():
    fx = load("silver-compaction-end")
    compaction = [s for s in fx["stages"] if s["name"].startswith(exporter.COMPACTION_PREFIX)]
    assert compaction and all(s["outputRecords"] > 0 for s in compaction)
    rows, _, _ = exporter.compute(fx["applications"], fx["jobs"], fx["stages"])
    assert rows["added_to_clean_table"] == 300023


def test_new_payments_read_ignores_the_silver_key_scan():
    # Round 4 has two scans: bronze at stage 1 (300,023), silver keys at
    # stage 2 (8,900,216). The lowest stageId wins.
    fx = load("silver-incr-append-mid")
    assert any(s["inputRecords"] == 8900216 for s in fx["stages"])
    rows, _, _ = exporter.compute(fx["applications"], fx["jobs"], fx["stages"])
    assert rows["new_payments_read"] == 300023


def test_tasks_completed():
    assert run_fixture("generator-end-idle")[2] == 36  # 32 write + 4 map
    assert run_fixture("generator-early-map-stage")[2] == 0


def test_unknown_app_waits():
    rows, activity, _ = exporter.compute([{"id": "x", "name": "other"}], [], [])
    assert (rows, activity) == ({}, "waiting")


@pytest.mark.parametrize(
    "payload", [b"", b"not json", b"null", b'{"a": 1}', b'["x"]', b"[1, 2]", b"[{}]"]
)
def test_garbage_gives_probe_success_0(payload):
    FakeDriver.payloads = {"/api/v1/applications": (200, payload)}
    srv = serve(FakeDriver)
    try:
        text = exporter.probe(f"127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert parse(text) == {"cerberus_spark_probe_success": 0.0}


def test_garbage_stages_give_probe_success_0():
    fx = load("silver-end-commit")
    srv = driver_for(fx)
    app_id = fx["applications"][0]["id"]
    FakeDriver.payloads[f"/api/v1/applications/{app_id}/stages"] = (200, b'{"x": 1}')
    try:
        text = exporter.probe(f"127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert parse(text) == {"cerberus_spark_probe_success": 0.0}


def test_unreachable_driver_gives_probe_success_0():
    text = exporter.probe("127.0.0.1:1")
    assert parse(text) == {"cerberus_spark_probe_success": 0.0}


def test_no_application_yet_waits():
    FakeDriver.payloads = {"/api/v1/applications": (200, b"[]")}
    srv = serve(FakeDriver)
    try:
        parsed = parse(exporter.probe(f"127.0.0.1:{srv.server_port}"))
    finally:
        srv.shutdown()
    assert parsed == {
        "cerberus_spark_probe_success": 1.0,
        'cerberus_spark_activity{activity="waiting"}': 1.0,
        "cerberus_spark_tasks_completed": 0.0,
    }


def test_probe_end_to_end_over_http(exporter_url):
    driver = driver_for(load("generator-write-mid"))
    try:
        url = f"{exporter_url}/probe?target=127.0.0.1:{driver.server_port}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            text = resp.read().decode()
    finally:
        driver.shutdown()
    assert parse(text) == {
        "cerberus_spark_probe_success": 1.0,
        'cerberus_spark_rows{row="payments_created"}': 3262330.0,
        'cerberus_spark_activity{activity="creating_payments"}': 1.0,
        "cerberus_spark_tasks_completed": 15.0,  # 4 map + 11 write
    }


def test_healthz_and_bad_target(exporter_url):
    with urllib.request.urlopen(f"{exporter_url}/healthz", timeout=5) as resp:
        assert resp.status == 200
    for path in (
        "/probe",
        "/probe?target=",
        "/probe?target=a/b:1",
        "/probe?target=example.com:4040",
    ):
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{exporter_url}{path}", timeout=5)
        assert err.value.code == 400
