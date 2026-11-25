"""The ledger CLI (the contract with 17.5) and the $25 rule."""

import json
import subprocess
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ledger.py"


def run(env, *args, **extra):
    return subprocess.run(
        [sys.executable, str(LEDGER), *args],
        env=env.environ(**extra), capture_output=True, text=True,
    )  # fmt: skip


def guard(env, next_usd, **extra):
    return run(env, "guard", "--next-usd", str(next_usd), **extra)


def test_guard_allows_up_to_25_and_refuses_above(env):
    # CE 15.00 - baseline 10.00 = 5.00 reported, so next 20.00 makes 25.00.
    assert guard(env, "20.00", STUB_CE_USD="15.00").returncode == 0
    refused = guard(env, "20.01", STUB_CE_USD="15.00")
    assert refused.returncode == 1
    assert "REFUSED" in refused.stderr


def test_guard_counts_the_ledger(env):
    assert (
        run(env, "record", "--run-id", "r1", "--kind", "session", "--estimate-usd", "10").returncode
        == 0
    )
    # reported 5 + ledger 10 + next 10 = 25.00 allowed; 10.01 refused
    assert guard(env, "10.00", STUB_CE_USD="15.00").returncode == 0
    assert guard(env, "10.01", STUB_CE_USD="15.00").returncode == 1


def test_guard_refuses_without_a_baseline(env):
    env.baseline.unlink()
    result = guard(env, "1", STUB_CE_USD="10.00")
    assert result.returncode != 0
    assert "baseline" in result.stderr


def test_guard_refuses_on_a_bad_baseline(env):
    env.baseline.write_text("{}")
    assert guard(env, "1").returncode != 0
    env.baseline.write_text('{"through": "2026-11-23", "usage_usd": "1"}')
    assert guard(env, "1").returncode != 0


def test_guard_refuses_when_cost_explorer_errors(env):
    assert guard(env, "1", FAIL_AWS="ce get-cost-and-usage").returncode != 0


def test_guard_refuses_on_bad_input_and_bad_ledger(env):
    assert guard(env, "abc").returncode != 0
    assert guard(env, "-1").returncode != 0
    env.ledger.write_text("garbage\n")
    assert guard(env, "1").returncode != 0
    assert run(env, "guard").returncode != 0  # missing argument


def test_guard_refuses_when_reported_is_below_the_baseline(env):
    assert guard(env, "1", STUB_CE_USD="9.00").returncode != 0


def test_record_and_correct(env):
    args = (
        "record",
        "--run-id",
        "run-1",
        "--kind",
        "exercise",
        "--estimate-usd",
        "3.5",
        "--gb",
        "7",
    )
    assert run(env, *args).returncode == 0
    assert run(env, *args).returncode != 0  # twice is refused
    assert run(env, "correct", "--run-id", "run-1", "--usd", "2.25").returncode == 0
    assert run(env, "correct", "--run-id", "nope", "--usd", "1").returncode != 0
    events = [json.loads(x) for x in env.ledger.read_text().splitlines()]
    assert [e["event"] for e in events] == ["record", "correct"]
    # the corrected figure replaces the estimate in the sum
    assert guard(env, "22.76", STUB_CE_USD="10.00").returncode == 1
    assert guard(env, "22.75", STUB_CE_USD="10.00").returncode == 0


def test_record_rejects_bad_run_id_and_kind(env):
    assert (
        run(
            env, "record", "--run-id", "Bad_ID", "--kind", "session", "--estimate-usd", "1"
        ).returncode
        != 0
    )
    assert (
        run(
            env, "record", "--run-id", "x" * 41, "--kind", "session", "--estimate-usd", "1"
        ).returncode
        != 0
    )
    assert (
        run(env, "record", "--run-id", "ok", "--kind", "other", "--estimate-usd", "1").returncode
        != 0
    )
    assert not env.ledger.exists()


def test_estimate(env):
    # (90 + 30 min) / 60 x 0.40 + 1.00 allowance = 1.80; no GB over the free tier
    result = run(env, "estimate", "--minutes", "90", "--gb", "356")
    assert result.stdout.strip() == "1.80"
    over = run(env, "estimate", "--minutes", "0", "--gb", "100", "--mtd-gb", "950")
    # 50 GB over the free tier x 0.085 = 4.25, plus 0.20 for 30 min, plus 1.00
    assert over.stdout.strip() == "5.45"


def test_baseline_is_written_once_and_never_invented(env):
    env.baseline.unlink()
    assert run(env, "baseline", STUB_CE_USD="12.34").returncode == 0
    data = json.loads(env.baseline.read_text())
    assert data["through"] == "2026-11-24" and data["usage_usd"] == "12.34"
    assert run(env, "baseline", STUB_CE_USD="99").returncode != 0  # not rewritten
    assert json.loads(env.baseline.read_text())["usage_usd"] == "12.34"
    env.baseline.unlink()
    assert run(env, "baseline", FAIL_AWS="ce get-cost").returncode != 0
    assert not env.baseline.exists()
    # the query is Usage only (credits excluded)
    assert "RECORD_TYPE" in env.log.read_text()
