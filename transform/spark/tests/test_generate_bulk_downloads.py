"""Tests for the 17.2 downloads generator core. No Spark: the core is pure Python."""

import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

import generate_bulk_downloads as g
import pytest

SPARK_DIR = Path(g.__file__).resolve().parent
SAMPLE = SPARK_DIR.parents[1] / "data" / "samples" / "downloads" / "sample_10k.jsonl.gz"
NOW = "2026-11-22T06:00:00Z"
SAMPLE_ARGS = ["--run-id", "sample-v1", "--events", "10000", "--now", NOW]


def generate(run_id="t1", clients=300, mode="two-pass"):
    cong = g.local_congestion(run_id, clients, mode)
    return list(g.local_events(run_id, NOW, clients, cong))


def by_client(events):
    streams = {}
    for e in events:
        streams.setdefault(e["payload"]["client_id"], []).append(e)
    return streams


@pytest.fixture(scope="module")
def events():
    return generate()


def test_deterministic_and_run_id_changes_ids():
    a, b, c = generate("d1", 60), generate("d1", 60), generate("d2", 60)
    assert a == b
    assert len(a) == len(c)
    assert {e["event_id"] for e in a}.isdisjoint({e["event_id"] for e in c})


def test_uuidv7_layout(events):
    ids = set()
    for e in events:
        eid = e["event_id"]
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", eid)
        assert eid[14] == "7"
        assert eid[19] in "89ab"
        assert int(eid.replace("-", "")[:12], 16) == g.parse_ms(e["occurred_at"])
        ids.add(eid)
    assert len(ids) == len(events)


def test_lifecycle_valid_on_all_clients(events):
    for stream in by_client(events).values():
        assert g.validate_lifecycle(stream) == []


def _stream_with_install():
    for stream in by_client(generate("v1", 200)).values():
        if stream[-1]["event_type"] == "install_completed":
            return [json.loads(json.dumps(e)) for e in stream]
    raise AssertionError("no completed client in the fixture")


def _errors(stream):
    return " ".join(g.validate_lifecycle(stream))


def test_validator_rejects_each_bad_stream():
    good = _stream_with_install()
    assert g.validate_lifecycle(good) == []

    no_grant = [e for e in good if e["event_type"] != "license_granted"]
    assert "without license_granted" in _errors(no_grant)

    early = [json.loads(json.dumps(e)) for e in good]
    for e in early:
        if e["event_type"] == "license_granted":
            e["occurred_at"] = "2026-11-18T00:00:00.000Z"
    assert "before local release" in _errors(early)

    big = [json.loads(json.dumps(e)) for e in good]
    big[1]["payload"]["bytes"] = g.TITLE_BYTES + 1
    assert "bytes out of range" in _errors(big)

    short = [e for e in good if e["event_type"] != "chunk_completed"]
    assert "chunk bytes differ" in _errors(short)

    no_patch = [e for e in good if e["event_type"] != "patch_completed"]
    assert "before the patch" in _errors(no_patch)

    after = [json.loads(json.dumps(e)) for e in good]
    last = json.loads(json.dumps(after[-1]))
    last["event_type"] = "abandoned"
    last["occurred_at"] = g.iso(g.parse_ms(after[-1]["occurred_at"]) + 1)
    extra = json.loads(json.dumps(last))
    extra["event_type"] = "install_completed"
    extra["occurred_at"] = g.iso(g.parse_ms(last["occurred_at"]) + 1)
    assert "after abandoned" in _errors([*after, last, extra])

    outside = [json.loads(json.dumps(e)) for e in good]
    outside[0]["occurred_at"] = "2026-11-09T23:59:59.000Z"
    assert "outside the window" in _errors(outside)


def test_no_licence_before_local_release_in_any_region():
    events = generate("rel", 1500)
    regions = set()
    for e in events:
        if e["event_type"] == "license_granted":
            n = int(e["payload"]["region"].split("_")[1])
            regions.add(n)
            assert g.parse_ms(e["occurred_at"]) >= g.release_ms(n)
    assert regions == set(range(1, 25))


def _plans(n=20000, run_id="shape"):
    return [g.plan_client(run_id, g.client_id_of(run_id, i)) for i in range(n)]


def test_preload_share():
    plans = _plans()
    share = sum(p.preloads for p in plans) / len(plans)
    assert abs(share - 0.46) < 0.03


def test_opening_spike_and_final_evening_peak():
    starts = [(p.pre_start, p.region) for p in _plans() if p.preloads]
    hours = {}
    for ms, _region in starts:
        h = (ms - g.WINDOW_START_MS) // 3_600_000
        hours[h] = hours.get(h, 0) + 1
    first6 = sum(hours.get(h, 0) for h in range(6)) / 6
    average = len(starts) / max(hours)
    assert first6 > 1.5 * average

    # Local evenings (18-23) by local day, per hour: day 8 is 2026-11-18.
    evening = {}
    for ms, region in starts:
        local = (ms - g.WINDOW_START_MS) // 3_600_000 + g.offset_hours(region)
        if 18 <= local % 24 <= 23:
            evening[local // 24] = evening.get(local // 24, 0) + 1
    normal = sum(evening.get(d, 0) for d in range(2, 8)) / 6
    assert evening[g.LAST_EVENING_DAY] > 1.5 * normal


def test_congestion_throttles_the_weak_isp_at_release():
    run_id = "weak"
    ids, i = [], 0
    while len(ids) < 3000:
        cid = g.client_id_of(run_id, i)
        if g.plan_client(run_id, cid).isp == g.WEAK_INDEX:
            ids.append(cid)
        i += 1
    plans = [g.plan_client(run_id, cid) for cid in ids]
    diffs = g.new_diffs()
    for p in plans:
        g.add_client(diffs, run_id, p)
    cong = g.congestion_from_diffs(diffs)
    chunks = []
    for p in plans:
        chunks += [
            (g.parse_ms(e["occurred_at"]), e["payload"]["throughput_mbps"])
            for e in g.client_events(run_id, NOW, p, cong)
            if e["event_type"] == "chunk_completed"
        ]
    release = g.release_ms(17)
    window = [t for ms, t in chunks if release <= ms < release + 6 * 3_600_000]
    off_peak = [t for ms, t in chunks if ms < release - 24 * 3_600_000]
    assert window and off_peak
    assert sum(window) / len(window) < sum(off_peak) / len(off_peak)
    assert any(t == g.TM_CAP_MBPS for t in window)
    assert cong.tm_start[g.WEAK_INDEX] >= 0


def test_curve_mode_runs():
    events = generate("curve", 120, mode="curve")
    assert events
    assert all(g.validate_lifecycle(s) == [] for s in by_client(events).values())


def test_window_and_now_guard():
    events = generate("win", 300)
    assert all(g.WINDOW_START_MS <= g.parse_ms(e["occurred_at"]) < g.WINDOW_END_MS for e in events)
    assert all(e["occurred_at"] <= e["ingested_at"] for e in events)
    argv = [
        "x",
        "--run-id",
        "r",
        "--events",
        "100",
        "--now",
        "2026-11-21T00:00:00Z",
        "--local",
        "o",
    ]
    old = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(SystemExit):
            g.parse_args()
    finally:
        sys.argv = old


def test_events_per_client_mean(events):
    mean = len(events) / 300
    assert 48 <= mean <= 54


def test_names_are_synthetic_and_no_account_id(events):
    source = Path(g.__file__).read_text()
    assert not re.findall(r"(?<![\w-])\d{12}(?![\w-])", source)
    for e in events:
        rest = json.dumps({k: v for k, v in e.items() if k != "event_id"})
        assert set(re.findall(r"(?<![\w-])\d{12}(?![\w-])", rest)) <= {str(g.TITLE_BYTES)}
        p = e["payload"]
        assert p["platform"] in ("console_a", "console_b")
        assert re.fullmatch(r"region_\d\d", p["region"])
        assert re.fullmatch(r"isp_\d\d_[ab]", p["isp"])
        assert re.fullmatch(r"cl_[0-9a-f]{12}", p["client_id"])


def test_sample_is_small_and_matches_the_generator(tmp_path):
    assert SAMPLE.stat().st_size < 1_500_000
    out = tmp_path / "again.jsonl.gz"
    cmd = [sys.executable, str(SPARK_DIR / "generate_bulk_downloads.py"), *SAMPLE_ARGS]
    subprocess.run([*cmd, "--local", str(out)], check=True, capture_output=True)
    with gzip.open(SAMPLE) as a, gzip.open(out) as b:
        golden = a.read()
        assert golden == b.read()
    lines = golden.decode().splitlines()
    assert 48 <= len(lines) / 200 <= 54
    ids = [json.loads(line)["event_id"] for line in lines]
    assert len(ids) == len(set(ids))
    for stream in by_client([json.loads(line) for line in lines]).values():
        assert g.validate_lifecycle(stream) == []


def _parse(*extra, run_id="r", events="100"):
    argv = ["x", "--run-id", run_id, "--events", events, "--now", NOW, *extra]
    old = sys.argv
    sys.argv = argv
    try:
        return g.parse_args()
    finally:
        sys.argv = old


GOOD_OUT = "s3a://b/downloads_bulk/"


def test_run_id_accepts_sample_and_rejects_unsafe():
    assert _parse("--local", "o", run_id="sample-v1").run_id == "sample-v1"
    assert _parse("--output", GOOD_OUT, run_id="launch_1-A").run_id == "launch_1-A"
    for bad in ["..", ".", "a/b", "a.b", "a|b", "|", "", "-a", "a" * 65]:
        with pytest.raises(SystemExit):
            _parse("--local", "o", run_id=bad)


def test_output_must_end_in_bulk_prefix_in_spark_mode():
    assert _parse("--output", "s3a://b/downloads_bulk").output.endswith("downloads_bulk")
    assert _parse("--output", GOOD_OUT).output == GOOD_OUT
    for bad in [
        "s3a://b/",
        "s3a://b/downloads",
        "s3a://b/x_downloads_bulk",
        "s3a://b/downloads_bulk/x",
    ]:
        with pytest.raises(SystemExit):
            _parse("--output", bad)


def test_run_dir_of_builds_only_the_run_dir():
    assert g.run_dir_of(GOOD_OUT, "r1") == "s3a://b/downloads_bulk/run_id=r1"
    assert g.run_dir_of("s3a://b/downloads_bulk", "r1") == "s3a://b/downloads_bulk/run_id=r1"
    for output, run_id in [(GOOD_OUT, ".."), (GOOD_OUT, "a/b"), ("s3a://b/", "r1")]:
        with pytest.raises(ValueError):
            g.run_dir_of(output, run_id)


def test_events_and_clients_must_be_positive():
    for flag, value in [("--clients", "0"), ("--clients", "-1")]:
        with pytest.raises(SystemExit):
            _parse("--local", "o", flag, value)
    for events in ["0", "-5"]:
        with pytest.raises(SystemExit):
            _parse("--local", "o", events=events)


def test_row_layout_constants_match_the_events(events):
    e = events[0]
    assert list(e) == g.ENVELOPE_FIELDS
    assert list(e["payload"]) == [k for k, _ in g.PAYLOAD_FIELDS]
