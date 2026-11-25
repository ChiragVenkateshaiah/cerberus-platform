"""The k6 scripts against the REAL k6 binary and a local HTTP stub of the edge.

Skipped when k6 is absent (set K6_BIN, or put k6 on PATH). `k6 inspect` is run
on every scenario file. The shrunk runs use the same scenario schema with small
counts and 1 KiB chunks, and the real seed.py: they prove the exact request
counts, the bytes, the licence gating and that a 403 causes no extra request.
EDGE_SCHEME=http reaches only 127.0.0.1 (the script refuses anything else).
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LAUNCH = HERE.parent
sys.path.insert(0, str(LAUNCH))

import k6_counts  # noqa: E402
import scenario  # noqa: E402
import seed  # noqa: E402

K6 = os.environ.get("K6_BIN") or shutil.which("k6")
pytestmark = pytest.mark.skipif(not K6, reason="k6 is not installed (set K6_BIN)")
SCRIPT = LAUNCH / "k6" / "download.js"
COOKIE = "CloudFront-Policy=p; CloudFront-Signature=s; CloudFront-Key-Pair-Id=k"
CHUNK = 1024


class Edge:
    """A local stand-in for the edge: signed cookie needed, /license gated by time."""

    def __init__(self, root: Path, release_at: float):
        self.root = root
        self.release_at = release_at
        self.log: list[tuple[float, str, int]] = []
        self.forbid: set[str] = set()
        self.lock = threading.Lock()
        edge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                path = self.path
                if "CloudFront-Policy=" not in (self.headers.get("Cookie") or ""):
                    status, body = 403, b"no cookie"
                elif path == "/license":
                    ok = time.time() >= edge.release_at
                    status = 200 if ok else 403
                    body = b'{"released":true}' if ok else b'{"released":false}'
                elif path in edge.forbid:
                    status, body = 403, b"forbidden"
                elif (edge.root / path.lstrip("/")).is_file():
                    status, body = 200, (edge.root / path.lstrip("/")).read_bytes()
                else:
                    status, body = 404, b"missing"
                with edge.lock:
                    edge.log.append((time.time(), path, status))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.domain = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def count(self, path: str, status: int | None = None) -> int:
        return sum(1 for _, p, s in self.log if p == path and (status is None or s == status))


@pytest.fixture
def world(tmp_path):
    """Shrunk sets: build 4, patch 2, patch2 2 chunks of 1 KiB, seeded for real."""
    sets = scenario.load_sets()
    sets["chunk_bytes"] = CHUNK
    for name, n in (("build", 4), ("patch", 2), ("patch2", 2)):
        sets["sets"][name]["chunks"] = n
    sets_file = tmp_path / "sets.json"
    sets_file.write_text(json.dumps(sets))
    root = tmp_path / "edge"
    manifests = tmp_path / "manifests"
    for name in sets["sets"]:
        seed.seed(sets_file, name, root / ".out" / name, None)  # chunks and manifest
        out = root / ".out" / name
        for path in out.rglob("*"):
            if path.is_file() and path.name != f"{name}.json" and not path.name.startswith("."):
                dest = root / path.relative_to(out)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(path, dest)
        manifests.mkdir(exist_ok=True)
        shutil.copy(out / f"{name}.json", manifests / f"{name}.json")
    cookie = tmp_path / "cookie.txt"
    cookie.write_text(COOKIE)
    w = type("World", (), {})()
    w.tmp, w.sets, w.sets_file, w.root, w.manifests, w.cookie = (
        tmp_path,
        sets,
        sets_file,
        root,
        manifests,
        cookie,
    )
    w.edges = []

    def edge(release_in: float) -> Edge:
        e = Edge(root, time.time() + release_in)
        w.edges.append(e)
        return e

    w.edge = edge
    yield w
    for e in w.edges:
        e.close()


def write_scenario(world, name: str, runs: list[dict]) -> Path:
    path = world.tmp / f"{name}.json"
    path.write_text(json.dumps({"name": name, "runs": runs}))
    return path


def k6_env(world, scn: Path, domain: str, index: int = 0, **extra) -> list[str]:
    env = {
        "SCENARIO_FILE": str(scn),
        "SETS_FILE": str(world.sets_file),
        "COOKIE_FILE": str(world.cookie),
        "EDGE_DOMAIN": domain,
        "EDGE_SCHEME": "http",
        "MINUTES": "1",
        "RUN_INDEX": str(index),
        "MANIFEST_DIR": str(world.manifests),
    }
    env.update(extra)
    return [a for k, v in env.items() for a in ("-e", f"{k}={v}")]


def k6_run(world, scn: Path, edge: Edge, index: int = 0, **extra) -> dict:
    out = world.tmp / f"summary-{scn.stem}-{index}.json"
    env = k6_env(world, scn, edge.domain, index, **extra)
    proc = subprocess.run(
        [K6, "run", "--quiet", "--summary-export", str(out), *env, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=world.tmp,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(out.read_text())["metrics"]


def n(metrics: dict, name: str) -> int:
    return int(metrics.get(name, {}).get("count", 0))


def planned(world, run: dict) -> scenario.Plan:
    return scenario.run_plan(world.sets, run)


def check_counts(world, metrics: dict, edge: Edge, run: dict) -> None:
    """k6's own counters, the server's log and the plan agree, per type and in bytes."""
    plan = planned(world, run)
    assert n(metrics, "http_reqs") == len(edge.log) == plan.total_requests
    for kind in ("build", "patch", "licence", "manifest"):
        assert n(metrics, f"req_{kind}") == plan.requests.get(kind, 0), kind
    for kind in ("build", "patch", "licence"):
        assert n(metrics, f"bytes_{kind}") == plan.nbytes.get(kind, 0), kind
    assert n(metrics, "chunk_errors") == 0
    # the p(50) and p(99) of the TTFB are in the summary
    assert "p(50)" in metrics["http_req_waiting"] and "p(99)" in metrics["http_req_waiting"]


def chunk_hits(world, edge: Edge, set_name: str) -> list[int]:
    m = json.loads((world.manifests / f"{set_name}.json").read_text())
    return [edge.count("/" + c["key"]) for c in m["chunks"]]


# --- k6 inspect on the real scenario files -----------------------------------


def inspect(tmp_path: Path, name: str, index: int = 0, **extra) -> subprocess.CompletedProcess:
    """`k6 inspect` of the real scenario file with full-size manifests of made-up names."""
    sets = scenario.load_sets()
    sets_file = tmp_path / "sets.json"
    sets_file.write_text(json.dumps(sets))
    mdir = tmp_path / "m"
    mdir.mkdir(exist_ok=True)
    for s, spec in sets["sets"].items():
        chunks = [
            {"key": f"{spec['prefix']}/{i:064x}.bin", "bytes": sets["chunk_bytes"]}
            for i in range(spec["chunks"])
        ]
        (mdir / f"{s}.json").write_text(json.dumps({"set": s, "chunks": chunks}))
    cookie = tmp_path / "c.txt"
    cookie.write_text(COOKIE)
    env = {
        "SCENARIO_FILE": str(LAUNCH / "scenarios" / f"{name}.json"),
        "SETS_FILE": str(sets_file),
        "COOKIE_FILE": str(cookie),
        "EDGE_DOMAIN": "example.test",
        "MINUTES": "120",
        "RUN_INDEX": str(index),
        "MANIFEST_DIR": str(mdir),
        "RELEASE_AT": str(int(time.time()) + 3600),
    }
    env.update(extra)
    args = [K6, "inspect", *[a for k, v in env.items() for a in ("-e", f"{k}={v}")], str(SCRIPT)]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def options(tmp_path: Path, name: str, index: int = 0) -> dict:
    proc = inspect(tmp_path, name, index)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def seconds(duration: str) -> int:
    """A Go duration as k6 prints it (1h2m3s, 6m0s, 36s) in whole seconds."""
    total = 0
    for value, unit in re.findall(r"(\d+)([hms])", duration):
        total += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


@pytest.mark.parametrize("name", ["a", "b", "c", "d", "p"])
def test_inspect_every_real_scenario(tmp_path, name):
    sets = scenario.load_sets()
    for index, run in enumerate(scenario.load_scenario(name)["runs"]):
        opts = options(tmp_path, name, index)
        scens = opts["scenarios"]
        # fixed iterations only
        assert {s["executor"] for s in scens.values()} <= {"per-vu-iterations", "shared-iterations"}
        assert "p(50)" in opts["summaryTrendStats"] and "p(99)" in opts["summaryTrendStats"]
        plan = scenario.run_plan(sets, run)
        fetch = sum(s["vus"] * s["iterations"] for s in scens.values() if s["exec"] == "fetchSet")
        licence = sum(s["iterations"] for s in scens.values() if s["exec"] == "licenceFlood")
        if name == "a":  # one client does every step in one iteration
            assert [s["exec"] for s in scens.values()] == ["sequence"]
            continue
        # the iterations k6 will run equal the plan
        assert fetch == plan.requests.get("build", 0) + plan.requests.get("patch", 0)
        assert licence + (1 if run.get("gate") else 0) == plan.requests.get("licence", 0)
        if run.get("gate"):
            assert opts["setupTimeout"]  # the setup sleeps until T0


def test_inspect_numbers_of_the_four_runs(tmp_path):
    """The headline numbers of the approved design, read back from k6's own options."""
    b = options(tmp_path, "b")["scenarios"]
    assert len(b) == 50
    assert {s["iterations"] for s in b.values()} == {64} and {s["vus"] for s in b.values()} == {1}
    starts = sorted(seconds(s["startTime"]) for s in b.values())
    assert starts[0] == 0 and starts[-1] == 1764  # 49 x 36 s: a 30 minute ramp
    c = options(tmp_path, "c")["scenarios"]
    assert (c["patch"]["vus"], c["patch"]["iterations"]) == (50, 8)
    assert (c["late"]["vus"], c["late"]["iterations"]) == (20, 64)
    assert c["licence"]["executor"] == "shared-iterations"
    assert c["licence"]["iterations"] == 1_000_000
    assert c["licence"]["vus"] == 250  # paced at 250 / 0.15 s: the rate cap is 1667 per second
    d0, d1 = options(tmp_path, "d", 0)["scenarios"], options(tmp_path, "d", 1)["scenarios"]
    assert (d0["cold"]["vus"], d0["cold"]["iterations"]) == (50, 8)
    assert (d1["warm"]["vus"], d1["warm"]["iterations"]) == (1, 8)
    p = options(tmp_path, "p")["scenarios"]["probe"]
    assert (p["vus"], p["iterations"]) == (1, 30)


def test_a_non_local_http_edge_is_refused(tmp_path):
    proc = inspect(tmp_path, "p", EDGE_SCHEME="http", MINUTES="1")
    assert proc.returncode != 0 and "EDGE_SCHEME must be https" in proc.stderr


# --- real shrunk runs against the stub edge ----------------------------------


def test_run_a_licence_403_then_200_and_exact_counts(world):
    edge = world.edge(release_in=4)
    scn = scenario.load_scenario("a")
    path = write_scenario(world, "a", scn["runs"])
    t0 = time.time()
    metrics = k6_run(world, path, edge, RELEASE_AT=math.ceil(edge.release_at))
    run = scn["runs"][0]
    check_counts(world, metrics, edge, run)  # 4 build + 2 patch chunks, 2 licence requests
    assert (
        edge.count("/license") == 2
        and edge.count("/license", 403) == 1
        and edge.count("/license", 200) == 1
    )
    assert n(metrics, "licence_retry") == 0 and n(metrics, "licence_unexpected") == 0
    assert (
        chunk_hits(world, edge, "build") == [1] * 4 and chunk_hits(world, edge, "patch") == [1] * 2
    )
    # the 403 came first and the 200 only after the release; the wait sent no request
    lic = [(t, s) for t, p, s in edge.log if p == "/license"]
    assert lic[0][1] == 403 and lic[1][1] == 200 and lic[1][0] >= edge.release_at
    assert time.time() - t0 >= 3  # it waited for the release


def test_a_403_causes_no_extra_request(world):
    edge = world.edge(release_in=3)
    m = json.loads((world.manifests / "build.json").read_text())
    bad = "/" + m["chunks"][1]["key"]
    edge.forbid.add(bad)
    scn = scenario.load_scenario("a")
    metrics = k6_run(
        world, write_scenario(world, "a", scn["runs"]), edge, RELEASE_AT=math.ceil(edge.release_at)
    )
    assert edge.count(bad) == 1 and edge.count(bad, 403) == 1  # asked once, no retry
    assert n(metrics, "http_reqs") == len(edge.log) == planned(world, scn["runs"][0]).total_requests
    assert n(metrics, "chunk_errors") == 1
    assert n(metrics, "bytes_build") == 3 * CHUNK  # the 403 chunk adds no bytes


def test_run_b_clients_ramp_and_never_wait_for_the_release(world):
    edge = world.edge(release_in=3600)  # the release never comes: B must not care
    run = {
        "id": "b",
        "workloads": [
            {"kind": "fetch", "name": "preload", "set": "build", "clients": 3, "ramp_minutes": 0.05}
        ],
    }
    metrics = k6_run(world, write_scenario(world, "b", [run]), edge)  # no RELEASE_AT
    check_counts(world, metrics, edge, run)
    assert chunk_hits(world, edge, "build") == [3] * 4  # every client downloads every chunk
    assert edge.count("/license") == 0
    first_chunk = "/" + json.loads((world.manifests / "build.json").read_text())["chunks"][0]["key"]
    starts = sorted(t for t, p, _ in edge.log if p == first_chunk)
    assert starts[2] - starts[0] >= 1.8  # three clients start about 1 s apart (0.05 min / 3)


def test_run_c_waits_for_t0_then_patch_licence_and_late_clients(world):
    edge = world.edge(release_in=4)
    run = {
        "id": "c", "gate": "release",
        "workloads": [
            {"kind": "fetch", "name": "patch", "set": "patch", "clients": 5},
            {"kind": "licence", "name": "licence", "total": 60, "vus": 4, "rate_cap_per_s": 100},
            {"kind": "fetch", "name": "late", "set": "build", "clients": 2},
        ],
    }  # fmt: skip
    metrics = k6_run(
        world, write_scenario(world, "c", [run]), edge, RELEASE_AT=math.ceil(edge.release_at)
    )
    check_counts(world, metrics, edge, run)
    assert (
        edge.count("/license") == 61 and edge.count("/license", 403) == 0
    )  # 60 + the gate, all 200
    assert (
        chunk_hits(world, edge, "patch") == [5] * 2 and chunk_hits(world, edge, "build") == [2] * 4
    )
    assert min(t for t, _, _ in edge.log) >= edge.release_at  # nothing before T0
    assert n(metrics, "licence_denied") == 0


def test_run_c_gate_retries_are_counted_when_the_edge_is_late(world):
    edge = world.edge(release_in=3)
    edge.release_at += 3  # the edge clock is 3 s behind the k6 host
    run = {
        "id": "g",
        "gate": "release",
        "workloads": [{"kind": "fetch", "name": "x", "set": "patch", "clients": 1}],
    }
    metrics = k6_run(
        world, write_scenario(world, "g", [run]), edge, RELEASE_AT=int(time.time()) + 2
    )
    assert n(metrics, "licence_retry") >= 1  # extra requests are counted, never silent
    assert n(metrics, "req_licence") == edge.count("/license") >= 2
    assert n(metrics, "http_reqs") == len(edge.log)


def test_run_d_cold_for_many_then_a_warm_repeat_by_one(world):
    edge = world.edge(release_in=3)
    spec = scenario.load_scenario("d")
    path = write_scenario(world, "d", spec["runs"])
    cold = k6_run(world, path, edge, 0, RELEASE_AT=math.ceil(edge.release_at))
    plan0 = planned(world, spec["runs"][0])
    assert n(cold, "http_reqs") == len(edge.log) == plan0.total_requests
    assert chunk_hits(world, edge, "patch2") == [50] * 2
    before = len(edge.log)
    warm = k6_run(world, path, edge, 1, RELEASE_AT=math.ceil(edge.release_at))
    assert (
        n(warm, "http_reqs")
        == len(edge.log) - before
        == planned(world, spec["runs"][1]).total_requests
    )
    assert chunk_hits(world, edge, "patch2") == [51] * 2  # one more request per chunk
    assert n(warm, "req_licence") == 0  # the warm run has no gate


def test_probe_p_reads_the_manifest_through_the_edge(world):
    edge = world.edge(release_in=3600)
    run = {
        "id": "p",
        "workloads": [
            {
                "kind": "fetch", "name": "probe", "set": "build", "clients": 1, "chunks": 3,
                "manifest_from_edge": True,
            }
        ],
    }  # fmt: skip
    metrics = k6_run(world, write_scenario(world, "p", [run]), edge, MANIFEST_DIR="/nonexistent")
    check_counts(world, metrics, edge, run)
    assert edge.count("/build/manifest.json", 200) == 1
    assert chunk_hits(world, edge, "build") == [1, 1, 1, 0]  # the first 3 chunks only
    assert n(metrics, "req_manifest") == 1


def test_k6_counts_reads_real_summaries(world):
    edge = world.edge(release_in=3600)
    run = {
        "id": "b",
        "workloads": [{"kind": "fetch", "name": "preload", "set": "build", "clients": 2}],
    }
    k6_run(world, write_scenario(world, "b", [run]), edge)
    shutil.copy(world.tmp / "summary-b-0.json", world.tmp / "b-0.json")
    out = k6_counts.collect(world.tmp, ["b-0"], None)
    assert out == {
        "k6_requests": 8,
        "by_type": {"build": 8, "patch": 0, "licence": 0, "manifest": 0},
        "complete": True,
        "missing": [],
    }
    partial = k6_counts.collect(world.tmp, ["b-0", "c-0"], world.tmp / "nope.json")
    assert (
        partial["k6_requests"] == 8
        and partial["complete"] is False
        and partial["missing"] == ["c-0", "probe-p"]
    )
