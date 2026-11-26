"""results_render.py against the synthetic fixtures: no AWS, no network."""

# ruff: noqa: E501 -- long expected strings read better on one line.

import re
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LAUNCH = HERE.parent
FIXTURES = HERE / "fixtures" / "synthetic"
sys.path.insert(0, str(LAUNCH))

import results_render as rr  # noqa: E402

RUN12 = re.compile(r"(?<!\d)\d{12}(?!\d)")
EXPECTED = {
    "release-window.svg",
    "isp-heatmap.svg",
    "cache-offload.svg",
    "ttfb.svg",
    "cost.svg",
    "scale.svg",
    "launch-day-results.md",
}


@pytest.fixture
def fx(tmp_path):
    root = tmp_path / "fx"
    shutil.copytree(FIXTURES, root)
    return root


def render(fx: Path, out: Path):
    ctx = rr.build_context(fx / "runs", fx / "ledger.jsonl", fx / "extracts", fx / "baseline.json")
    paths = rr.render(ctx, out / "doc" / "launch-day-results.md", out / "img")
    return {p.name: p for p in paths}


def test_exact_output_file_set(fx, tmp_path):
    out = render(fx, tmp_path / "o")
    assert set(out) == EXPECTED
    written = {p.name for p in (tmp_path / "o").rglob("*") if p.is_file()}
    assert written == EXPECTED


def test_stable_bytes(fx, tmp_path):
    a = render(fx, tmp_path / "a")
    b = render(fx, tmp_path / "b")
    for name in EXPECTED:
        assert a[name].read_bytes() == b[name].read_bytes(), name


def test_titles_are_takeaways_and_synthetic_is_labelled(fx, tmp_path):
    out = render(fx, tmp_path)
    title = lambda name: re.search(r"<title>([^<]*)", out[name].read_text()).group(1)  # noqa: E731
    assert title("release-window.svg").startswith("804 licences granted across 3 release zones")
    assert "Modelled:" in title("isp-heatmap.svg")
    assert "87.1%" in title("cache-offload.svg")
    assert "two clocks" in title("ttfb.svg")
    assert "within the $25 stop rule" in title("cost.svg")
    assert "of the 33,030 Gbps" in title("scale.svg")
    assert "synthetic telemetry" in out["release-window.svg"].read_text()
    assert "modelled" in out["isp-heatmap.svg"].read_text()
    assert "single metro, 50 virtual clients" in out["cache-offload.svg"].read_text().lower()
    assert "one region; 33.03 Tbps is a total exchange peak" in out["scale.svg"].read_text()
    assert "T0" in out["release-window.svg"].read_text()


def test_cache_ratio_is_request_based_and_hold_only(fx):
    rows = rr.load_extracts(fx / "extracts")["rows"]["cdn_class"]
    runs = rr.load_runs(fx / "runs")
    facts = rr.cache_facts(rows, runs)
    assert facts["holds"] == ["synthetic-bcd"]  # Run A is not a HOLD run: left out
    # SEA build: 1100 hits of 1100 + 20 + 80
    assert facts["ratios"][("SEA", "build")] == pytest.approx(1100 / 1200)
    hits = 1100 + 450 + 250 + 650 + 180 + 70
    looked = sum(1200 + 500 + 300 + 800 + 200 + 100 for _ in [0])
    assert facts["overall"] == pytest.approx(hits / looked)


def test_missing_cdn_extracts_read_not_measured(fx, tmp_path):
    for name in ("cdn_run", "cdn_minute", "cdn_class"):
        (fx / "extracts" / f"{name}.csv").unlink()
    out = render(fx, tmp_path)
    assert "Cache hit ratio: not measured" in out["cache-offload.svg"].read_text()
    assert (
        "Measured peak Gbps against the 33,030 Gbps exchange peak: not measured"
        in out["scale.svg"].read_text()
    )
    doc = out["launch-day-results.md"].read_text()
    assert "cache offload is not measured" in doc
    assert "Edge TTFB per POP: not measured" in doc
    assert "synthetic-bcd" in doc  # the rest still renders


def test_no_hold_run_means_cache_not_measured(fx, tmp_path):
    path = fx / "runs" / "synthetic-bcd" / "run.json"
    path.write_text(path.read_text().replace('"hold": true', '"hold": false'))
    out = render(fx, tmp_path)
    assert "Cache hit ratio: not measured" in out["cache-offload.svg"].read_text()


def test_null_k6_requests_is_not_measured(fx, tmp_path):
    path = fx / "runs" / "synthetic-a" / "run.json"
    path.write_text(path.read_text().replace('"k6_requests": 12', '"k6_requests": null'))
    doc = render(fx, tmp_path)["launch-day-results.md"].read_text()
    row = next(
        line
        for line in doc.splitlines()
        if line.startswith("| `synthetic-a`") and "2026-11-27T10:00" in line
    )
    assert "| not measured | 4 |" in row


def test_no_cost_json_is_not_measured(fx, tmp_path):
    (fx / "extracts" / "cost.json").unlink()
    out = render(fx, tmp_path)
    assert "Launch spend against Cost Explorer: not measured" in out["cost.svg"].read_text()
    doc = out["launch-day-results.md"].read_text()
    assert "Attributable spend (November Usage minus the baseline) not measured of $25" in doc
    assert "Account total not measured of $40: not measured" in doc


def test_epoch_ms_converted_to_iso_utc(fx, tmp_path):
    doc = render(fx, tmp_path)["launch-day-results.md"].read_text()
    assert "2026-11-27T10:00:00Z" in doc and "2026-11-28T11:00:00Z" in doc
    assert not re.search(r"\b\d{13}\b", doc)
    assert rr.iso(0) == rr.NM and rr.iso("x") == rr.NM


def test_doc_notes_curl_requests_and_source_tags(fx, tmp_path):
    doc = render(fx, tmp_path)["launch-day-results.md"].read_text()
    assert "curl" in doc and "Run A" in doc and "a few lines higher" in doc
    assert "[extracts/release_window.csv]" in doc and "[extracts/cdn_class.csv" in doc


def test_ttfb_panels_use_p50_then_med(fx):
    runs = rr.load_runs(fx / "runs")
    metrics = runs["synthetic-a"]["results"]["a-0"]["metrics"]
    assert rr.p50(metrics, "http_req_waiting") == 42
    assert rr.p50({"w": {"med": 7}}, "w") == 7
    assert rr.p99({"w": {"med": 7}}, "w") is None
    facts = rr.ttfb_facts(runs, rr.load_extracts(fx / "extracts")["rows"]["cdn_run"])
    assert facts["server"]["run"] == "synthetic-bcd"
    assert [c["probe"] for c in facts["client"]] == [(None, None), (95, 340)]


def test_scale_peak_is_gbps_of_busiest_minute(fx):
    peak = rr.measured_peak(rr.load_extracts(fx / "extracts")["rows"]["cdn_minute"])
    assert peak["gbps"] == pytest.approx(1260 * 8 / 60 / 1000)
    assert peak["run"] == "synthetic-bcd" and peak["minute"] == "2026-11-28 10:09"


def test_empty_inputs_render_without_error(tmp_path):
    ctx = rr.build_context(tmp_path / "r", tmp_path / "l", tmp_path / "e", tmp_path / "b")
    out = rr.render(ctx, tmp_path / "doc" / "d.md", tmp_path / "img")
    assert {p.name for p in out} == (EXPECTED - {"launch-day-results.md"}) | {"d.md"}
    assert "not measured" in (tmp_path / "doc" / "d.md").read_text()


def test_no_12_digit_runs_in_outputs_or_fixtures(fx, tmp_path):
    render(fx, tmp_path / "o")
    files = [p for p in (tmp_path / "o").rglob("*") if p.is_file()]
    files += [p for p in FIXTURES.rglob("*") if p.is_file()]
    assert files
    for path in files:
        assert not RUN12.search(path.read_text()), path.name
