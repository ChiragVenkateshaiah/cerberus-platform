"""Layer 1 (plan_bytes.py) and the scenario files."""

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LAUNCH = HERE.parent
sys.path.insert(0, str(LAUNCH))

import plan_bytes  # noqa: E402
import scenario  # noqa: E402

D = Decimal


def test_session_cap_boundaries():
    plan_bytes.evaluate(D("399.9"), D(0))  # allowed
    plan_bytes.evaluate(D("400"), D(0))  # exactly the cap is allowed
    with pytest.raises(plan_bytes.Refused):
        plan_bytes.evaluate(D("400.1"), D(0))


def test_month_cap_boundaries():
    plan_bytes.evaluate(D("100"), D("800"))  # 900 exactly is allowed
    with pytest.raises(plan_bytes.Refused):
        plan_bytes.evaluate(D("100"), D("800.1"))
    with pytest.raises(plan_bytes.Refused):
        plan_bytes.evaluate(D("0.1"), D("900"))


MIB64 = 64 * 2**20  # one chunk
BUILD = 64 * MIB64  # 64 chunks: 4 GiB
PATCH = 8 * MIB64  # 8 chunks: 512 MiB


def test_exact_bytes_per_run_from_the_chunk_sizes():
    """Bytes are chunk requests x 64 MiB plus the licence response bodies (17 B, 403: 18 B)."""
    b = {n: plan_bytes.scenario_bytes(n) for n in "abcdp"}
    assert b["a"] == BUILD + PATCH + 18 + 17  # build, patch, licence 403 then 200
    assert b["b"] == 50 * BUILD  # 214.7 GB
    assert (
        b["c"] == 50 * PATCH + 20 * BUILD + 1_000_000 * 17 + 17
    )  # patch, late full builds, licence, gate
    assert b["d"] == 50 * PATCH + PATCH + 17  # cold 50, warm 1, one gate request
    assert b["p"] == 30 * MIB64  # the first 30 chunks of the build, through the edge
    assert plan_bytes.scenario_bytes("bcd") == b["b"] + b["c"] + b["d"]
    assert plan_bytes.scenario_gb("bcd") > 354 and plan_bytes.scenario_gb("bcd") < 355
    assert str(scenario.gb(plan_bytes.scenario_bytes("bcd"))) == "354.889"
    assert plan_bytes.probe_bytes("bcd") == b["p"] and plan_bytes.probe_bytes("p") == 0
    assert plan_bytes.budget_bytes("bcd") == -(
        -plan_bytes.scenario_bytes("bcd") * 11 // 10
    )  # x 1.10, rounded up to whole bytes


def test_plan_requests_by_type():
    plan = scenario.session_plan("bcd")
    assert plan.requests == {"build": 3200 + 1280, "patch": 400 + 408, "licence": 1_000_002}
    assert scenario.session_plan("p").requests == {"build": 30, "manifest": 1}
    assert scenario.session_plan("a").requests == {"build": 64, "patch": 8, "licence": 2}


def test_licence_bytes_are_the_function_bodies():
    sets = scenario.load_sets()
    assert sets["licence_bytes"] == {
        "200": len(json.dumps({"released": True}, separators=(",", ":"))),
        "403": len(json.dumps({"released": False}, separators=(",", ":"))),
    }
    fn = (LAUNCH.parent / "terraform/modules/launch_edge/function/license.js").read_text()
    assert (
        "JSON.stringify(payload)" in fn
        and "{ released: true }" in fn
        and "{ released: false }" in fn
    )


def test_unknown_scenario_is_an_error():
    assert plan_bytes.main(["zz", "--mtd-gb", "0"]) == 3


def test_cli_exit_codes(capsys):
    assert plan_bytes.main(["bcd", "--mtd-gb", "543"]) == 0  # 543 + 356.9 = 899.9
    assert plan_bytes.main(["bcd", "--mtd-gb", "543.2"]) == 2  # 543.2 + 356.902 > 900
    out = capsys.readouterr().out
    assert f"budget_bytes={plan_bytes.budget_bytes('bcd')}" in out
    assert "session_gb=354.889" in out and "probe_gb=2.013" in out and "total_gb=356.902" in out
    assert f"total_bytes={plan_bytes.scenario_bytes('bcd') + plan_bytes.scenario_bytes('p')}" in out


def test_mtd_is_the_larger_of_ledger_and_cloudwatch(env):
    # ledger 100 GB, CloudWatch 600 GB: the larger (600) plus 356 is over 900.
    env.ledger.write_text(
        json.dumps({"event": "record", "run_id": "x", "estimate_usd": "1", "gb": "100"}) + "\n"
    )
    cw = str(600 * 10**9)
    args = ["bcd", "--ledger", str(env.ledger), "--distribution-id", "DSTUB"]
    import os
    import subprocess

    def run(cw_sum, *extra):
        e = env.environ(STUB_CW_SUM=cw_sum)
        return subprocess.run(
            [sys.executable, str(LAUNCH / "plan_bytes.py"), *args, *extra],
            env=e, capture_output=True, text=True,
        )  # fmt: skip

    refused = run(cw)
    assert refused.returncode == 2
    assert "mtd_gb=600" in refused.stdout
    allowed = run(str(100 * 10**9))  # both 100: 100 + 356 is fine
    assert allowed.returncode == 0
    # A CloudWatch failure is an error, never a zero.
    failing = subprocess.run(
        [sys.executable, str(LAUNCH / "plan_bytes.py"), *args],
        env=env.environ(FAIL_AWS="cloudwatch get-metric"), capture_output=True, text=True,
    )  # fmt: skip
    assert failing.returncode == 3
    assert os.path.exists(env.log)


def test_ledger_with_a_bad_line_is_an_error(env):
    env.ledger.write_text("not json\n")
    assert plan_bytes.main(["a", "--ledger", str(env.ledger), "--offline"]) == 3


def test_a_missing_ledger_fails_closed_except_offline(env):
    env.ledger.unlink()
    assert plan_bytes.main(["a", "--ledger", str(env.ledger)]) == 3
    assert plan_bytes.main(["a", "--ledger", str(env.ledger), "--mtd-gb", "0"]) == 0
    assert plan_bytes.main(["a", "--ledger", str(env.ledger), "--offline"]) == 0  # dry run
    env.ledger.write_text("")  # an empty ledger is zero entries
    assert plan_bytes.main(["a", "--ledger", str(env.ledger)]) == 0


def test_runs_match_the_approved_design():
    sets = scenario.load_sets()
    assert sets["chunk_bytes"] == 64 * 2**20
    assert {k: (v["prefix"], v["chunks"]) for k, v in sets["sets"].items()} == {
        "build": ("build", 64), "patch": ("patch", 8), "patch2": ("patch", 8),
    }  # fmt: skip
    assert len({v["manifest"] for v in sets["sets"].values()}) == 3  # one manifest per set
    for v in sets["sets"].values():
        assert v["manifest"].startswith(v["prefix"] + "/")  # the granted prefixes only
    a, b, c, d, p = (scenario.load_scenario(n) for n in "abcdp")
    # A: one client, full build + patch, licence 403 then 200 with a wait between
    (wa,) = a["runs"][0]["workloads"]
    assert wa["steps"] == [
        "fetch:build",
        "licence:403",
        "wait:release",
        "licence:200",
        "fetch:patch",
    ]
    # B: 50 clients, full build, about 30 minutes, never gated
    (wb,) = b["runs"][0]["workloads"]
    assert (wb["clients"], wb["set"], wb["ramp_minutes"]) == (50, "build", 30)
    assert "gate" not in b["runs"][0]
    # C: gated at T0: patch for 50, 1,000,000 licence requests, 20 late full builds
    assert c["runs"][0]["gate"] == "release"
    ws = {w["name"]: w for w in c["runs"][0]["workloads"]}
    assert (ws["patch"]["clients"], ws["patch"]["set"]) == (50, "patch")
    assert (
        ws["licence"]["total"] == 1_000_000
        and ws["licence"]["total"] / ws["licence"]["rate_cap_per_s"] / 60 < 11
    )
    assert (ws["late"]["clients"], ws["late"]["set"]) == (20, "build")
    # D: a second patch set, cold for 50 at T0, then a warm repeat by 1
    cold, warm = d["runs"]
    assert cold["gate"] == "release" and cold["workloads"][0]["set"] == "patch2"
    assert cold["workloads"][0]["clients"] == 50 and warm["workloads"][0]["clients"] == 1
    assert warm["workloads"][0]["set"] == "patch2" and "gate" not in warm
    assert sets["sets"]["patch2"]["manifest"] != sets["sets"]["patch"]["manifest"]
    # P: one client, the manifest read through the edge
    assert p["runs"][0]["workloads"][0]["manifest_from_edge"] is True


def test_k6_scripts_use_fixed_iterations_only():
    scripts = list((LAUNCH / "k6").glob("*.js"))
    assert scripts
    for path in scripts:
        text = path.read_text()
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
        if path.name == "download.js":
            assert "shared-iterations" in code and "per-vu-iterations" in code
            assert (
                "iterationInScenario" in code
            )  # the chunk index follows the client's own iteration
        assert not re.search(r"\bduration\b", code)
        assert not re.search(r"stages|ramping|constant-vus|constant-arrival", code)
        # The only time setting allowed is k6's stop cap on the same executor.
        assert set(re.findall(r"\w*[dD]uration\w*", code)) <= {"maxDuration"}
        assert "console.log" not in code  # nothing may log the cookie


def test_cdn_allowlist_equals_the_terraform_fields():
    allow = json.loads((LAUNCH / "cdn_fields.json").read_text())["fields"]
    main = (LAUNCH.parent / "terraform/modules/launch_edge/main.tf").read_text()
    block = re.search(r"log_fields = \[([\s\S]*?)\n  \]", main)
    tf_fields = re.findall(r'"([^"]+)"', block.group(1))
    assert allow == tf_fields
    assert len(allow) == 12
    for bad in ("c-ip", "x-forwarded-for", "c-port", "cs(Cookie)", "cs(Referer)", "cs(User-Agent)"):
        assert bad not in allow
