"""launch_session.sh against stubs: refusals, the happy path and every failure path."""

import base64
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plan_bytes  # noqa: E402
import scenario  # noqa: E402

SESSION = "orchestration/launch_session.sh"
BUDGET = str(plan_bytes.budget_bytes("bcd"))  # bcd: exact planned bytes x 1.10
PROBE = int(
    plan_bytes.scenario_bytes("p") * 11 // 10
)  # probe P: 30 chunks x 1.10, on the same distribution
LIMIT = int(BUDGET) + PROBE  # the layer 4 stop limit
A_BUDGET = plan_bytes.budget_bytes("a")  # scenario a: build + patch + 2 licence bodies, x 1.10
A_LIMIT = A_BUDGET + PROBE


def stage1_apply(env, start=0):
    """Index of an apply that has no public key and create_load_gen=false (stage 1)."""
    for i, line in enumerate(env.calls()[start:], start):
        if (
            line.startswith("terraform")
            and " apply " in line
            and "create_load_gen=false" in line
            and "public_key_pem" not in line
        ):
            return i
    return -1


def everything(proc, env):
    return proc.stdout + proc.stderr + (env.log.read_text() if env.log.exists() else "")


def assert_clean_exit_state(env):
    assert env.key_dirs() == [], "the key directory must be gone"


def test_dry_run_calls_nothing(env):
    proc = env.run(SESSION, "--dry-run")
    assert proc.returncode == 0
    assert env.calls() == []  # no aws, terraform, openssl, k6 or curl call
    assert f"budget_bytes: {BUDGET}" in proc.stdout
    assert "ledger estimate" in proc.stdout
    assert env.key_dirs() == []
    assert env.ledger.read_text() == ""  # nothing recorded


def test_dry_run_prewarm_and_refusal(env):
    assert env.run(SESSION, "--dry-run", PREWARM="1").returncode == 0
    assert env.calls() == []
    # a refused plan stops the dry run too: ledger holds 600 GB, bcd adds 356
    env.ledger.write_text(
        json.dumps({"event": "record", "run_id": "x", "estimate_usd": "1", "gb": "600"}) + "\n"
    )
    proc = env.run(SESSION, "--dry-run")
    assert proc.returncode != 0
    assert env.calls() == []


@pytest.mark.parametrize(
    "extra",
    [
        {"SCENARIO": "zz"},
        {"MINUTES": "0"},
        {"MINUTES": "121"},
        {"MINUTES": "abc"},
        {"LAUNCH_RUN_ID": "BAD_ID"},
    ],
)
def test_bad_input_is_refused_before_any_call(env, extra):
    proc = env.run(SESSION, "--yes", **extra)
    assert proc.returncode != 0
    assert env.calls() == []


def test_refuses_over_the_month_cap(env):
    env.ledger.write_text(
        json.dumps({"event": "record", "run_id": "x", "estimate_usd": "1", "gb": "544.1"}) + "\n"
    )  # 544.1 + 356 > 900
    proc = env.run(SESSION, "--yes")
    assert proc.returncode != 0
    assert "plan_bytes refused" in proc.stdout
    assert env.find("apply") == -1 and env.find("openssl") == -1
    assert env.key_dirs() == []
    assert env.ledger_events() == ["record"]  # no new entry


def test_refuses_over_25_dollars(env):
    proc = env.run(SESSION, "--yes", STUB_CE_USD="40.00")  # reported 30 over the baseline
    assert proc.returncode != 0
    assert "cost rule refused" in proc.stdout
    assert env.find("apply") == -1 and env.find("openssl") == -1
    assert env.ledger_events() == []


def test_refuses_with_no_baseline_or_when_cost_explorer_fails(env):
    env.baseline.unlink()
    assert env.run(SESSION, "--yes").returncode != 0
    assert env.find("apply") == -1
    env.write_baseline("10.00")
    assert env.run(SESSION, "--yes", FAIL_AWS="ce get-cost-and-usage").returncode != 0
    assert env.find("apply") == -1


def test_refuses_without_tmpfs_for_the_key(env, tmp_path):
    disk = Path(__file__).resolve().parent / "not-tmpfs"
    disk.mkdir(exist_ok=True)
    try:
        import subprocess

        fs = subprocess.run(["stat", "-f", "-c", "%T", str(disk)], capture_output=True, text=True)
        if fs.stdout.strip() == "tmpfs":
            pytest.skip("the repo is on tmpfs here")
        proc = env.run(SESSION, "--yes", XDG_RUNTIME_DIR=str(disk))
        assert proc.returncode != 0
        assert "not tmpfs" in proc.stdout
        assert env.find("openssl") == -1 and env.find("apply") == -1
        assert list(disk.iterdir()) == []
    finally:
        disk.rmdir()


def test_refuses_without_xdg_runtime_dir(env):
    proc = env.run(SESSION, "--yes", XDG_RUNTIME_DIR="")
    assert proc.returncode != 0
    assert env.find("openssl") == -1 and env.find("apply") == -1


def test_refuses_with_a_leftover_instance(env):
    proc = env.run(SESSION, "--yes", STUB_NONZERO="describe-instances")
    assert proc.returncode != 0
    assert env.find("apply") == -1


def test_happy_path(env):
    env.clear_marker("results/done")  # appears at the first CloudWatch poll
    proc = env.run(SESSION, "--yes", STUB_DONE_AFTER_CW="2")
    assert proc.returncode == 0, proc.stdout
    calls = env.calls()
    first = env.find("terraform", " apply ", "public_key_pem=", "create_load_gen=false")
    rel = env.find("terraform", " apply ", "release_at_epoch=")
    curl = env.find("curl")
    delete1 = env.find("aws", "ssm delete-parameter")
    put = env.find("aws", "ssm put-parameter")
    gen = env.find("terraform", " apply ", "create_load_gen=true", f"budget_bytes={BUDGET}")
    probe = env.find("k6", "p.json")
    s1 = stage1_apply(env, gen)
    delete2 = env.find("aws", "ssm delete-parameter", start=s1)
    destroy = env.find("terraform", " destroy ")
    check = env.find("aws", "cloudfront list-distributions")
    order = [first, delete1, put, curl, gen, probe, s1, delete2, destroy, check]
    assert -1 not in order, order
    assert order == sorted(order), order
    # T0 is fixed after Deployed: the first apply has the PEM only (default release_at), the
    # second the same PEM and the explicit release_at, with the instance
    assert rel == gen and "release_at_epoch=" not in calls[first]
    pem = lambda i: calls[i].split("public_key_pem=")[1].split(" -var")[0]  # noqa: E731
    assert pem(first) == pem(gen)  # the key is constant between the applies
    assert env.find("cloudfront wait distribution-deployed") < env.find(
        "terraform", " apply ", "release_at_epoch="
    )
    # the parameter: delete first (--tags conflicts with --overwrite), SecureString, Standard
    put_line = calls[put]
    for want in (
        "--type SecureString",
        "--tier Standard",
        "--tags Key=Project,Value=cerberus-platform",
    ):
        assert want in put_line
    assert "--value file://" in put_line
    assert "--overwrite" not in put_line and "--key-id" not in put_line
    # CloudFront wait before cookies, scenario upload before the instance
    assert env.find("cloudfront wait distribution-deployed") < put
    assert env.find("s3 cp", "scenarios/order") < gen
    for uploaded in (
        "scenarios/sets.json",
        "scenarios/seed.py",
        "scenarios/download.js",
        "scenarios/seed -",
    ):
        assert env.find("s3 cp", uploaded) != -1 and env.find("s3 cp", uploaded) < gen, uploaded
    assert (
        env.find("s3 cp", "scenarios/b.json") != -1 and env.find("s3 cp", "scenarios/d.json") != -1
    )
    assert env.find("aws", "cloudwatch get-metric-statistics") != -1
    assert_clean_exit_state(env)
    assert env.ledger_events() == ["record", "correct"]
    assert "STAGE 2" in proc.stdout and "launch_check ok" in proc.stdout
    # run record and results are copied out before stage 2
    assert (env.runs / "t-run" / "run.json").exists()
    copy_out = env.find("s3 cp s3://stub-build/results/")
    assert copy_out != -1 and copy_out < destroy


def test_cookies_and_key_material_are_never_printed(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", STUB_DONE_AFTER_CW="2")
    assert proc.returncode == 0
    text = everything(proc, env)
    sig = base64.b64encode(b"stub-signature-bytes").decode()
    sig_cf = sig.replace("+", "-").replace("=", "_").replace("/", "~")
    for secret in ("stub-signature-bytes", sig, sig_cf, "CloudFront-Signature", "CloudFront-Policy",
                   "stub-key-material", "Cookie:"):  # fmt: skip
        assert secret not in text, f"{secret} leaked"
    # the pipeline sets no trace output
    code = Path("orchestration/launch_session.sh").read_text().splitlines()
    assert not [x for x in code if x.lstrip().startswith(("set -x", "set -o xtrace"))]


def test_hold_keeps_the_edge_and_prints_a_deadline(env):
    proc = env.run(SESSION, "--yes", HOLD="1")
    assert proc.returncode == 0
    assert env.find("terraform", " destroy ") == -1
    assert "make launch-destroy" in proc.stdout and "THE EDGE IS STILL UP" in proc.stdout
    assert stage1_apply(env) != -1  # stage 1 still ran
    assert env.find("aws", "ssm delete-parameter", start=stage1_apply(env)) != -1
    assert_clean_exit_state(env)


def test_prewarm_has_no_key_no_instance_and_no_stage_two(env):
    proc = env.run(SESSION, "--yes", PREWARM="1")
    assert proc.returncode == 0
    assert env.find("openssl") == -1 and env.find("k6") == -1
    assert env.find("create_load_gen=true") == -1
    assert env.find("public_key_pem=") == -1  # the default key stays
    assert env.find("terraform", " destroy ") == -1
    assert "make launch-destroy" in proc.stdout
    assert env.ledger_events() == ["record", "correct"]


def test_failed_prewarm_apply_runs_both_stages(env):
    proc = env.run(SESSION, "--yes", PREWARM="1", FAIL_TF=" apply ")
    assert proc.returncode != 0
    assert env.find("terraform", " destroy ") != -1
    assert env.find("aws", "ssm delete-parameter") != -1
    assert env.ledger_events() == ["record", "correct"]


def test_failed_first_apply_runs_stage_one_and_two(env):
    proc = env.run(SESSION, "--yes", FAIL_TF="public_key_pem=")
    assert proc.returncode != 0
    assert env.find("aws", "ssm delete-parameter") != -1
    assert env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)
    assert env.ledger_events() == ["record", "correct"]


def test_failed_instance_apply_runs_stage_one_and_two(env):
    proc = env.run(SESSION, "--yes", FAIL_TF="create_load_gen=true")
    assert proc.returncode != 0
    assert stage1_apply(env) != -1
    assert env.find("aws", "ssm delete-parameter", start=stage1_apply(env)) != -1
    assert env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)


def test_failed_openssl_and_failed_curl_probe(env):
    proc = env.run(SESSION, "--yes", FAIL_OPENSSL="1")
    assert proc.returncode != 0
    assert env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)
    proc = env.run(SESSION, "--yes", STUB_LICENSE_CODE="200", LAUNCH_RUN_ID="t-run2")
    assert proc.returncode != 0
    assert "expected 403" in proc.stdout
    assert env.find("create_load_gen=true") == -1  # no instance when the probe fails
    assert_clean_exit_state(env)


# --- stage 1 steps are independent -------------------------------------------


def test_stage1_apply_failure_still_deletes_parameter_removes_key_and_terminates(env):
    proc = env.run(SESSION, "--yes", FAIL_TF="create_load_gen=false", FAIL_TF_NOT="public_key_pem")
    assert proc.returncode != 0
    assert "STAGE 1 APPLY FAILED" in proc.stdout
    s1 = stage1_apply(env)
    assert s1 != -1
    assert env.find(
        "aws", "ec2 terminate-instances", start=s1
    ) != -1 or "ec2 describe-instances" in "\n".join(env.calls()[s1:])
    assert env.find("aws", "ssm delete-parameter", start=s1) != -1
    assert_clean_exit_state(env)
    assert env.find("terraform", " destroy ") != -1  # stage 2 still ran
    assert "SESSION NOT CLEANLY ENDED" in proc.stdout


def test_stage1_apply_failure_terminates_the_instance_directly(env):
    proc = env.run(
        SESSION, "--yes", FAIL_TF="create_load_gen=false", FAIL_TF_NOT="public_key_pem",
        STUB_INSTANCE_IDS="i-0stub",
    )  # fmt: skip
    assert proc.returncode != 0
    assert env.find("aws", "ec2 terminate-instances", "i-0stub") != -1


def test_parameter_delete_failure_still_terminates_removes_key_and_destroys(env):
    # the 2nd delete-parameter call is the one in stage 1
    proc = env.run(SESSION, "--yes", FAIL_AWS="ssm delete-parameter=2")
    assert proc.returncode != 0
    assert "COOKIE PARAMETER DELETE FAILED" in proc.stdout
    assert stage1_apply(env) != -1
    assert_clean_exit_state(env)
    assert env.find("terraform", " destroy ") != -1
    assert "SESSION NOT CLEANLY ENDED" in proc.stdout


def test_key_shred_failure_is_loud_but_the_key_is_still_removed(env):
    proc = env.run(SESSION, "--yes", FAIL_SHRED="1")
    assert proc.returncode != 0
    assert "SHRED FAILED" in proc.stdout
    assert_clean_exit_state(env)
    assert env.find("aws", "ssm delete-parameter", start=stage1_apply(env)) != -1
    assert env.find("terraform", " destroy ") != -1


def test_parameter_delete_and_key_removal_run_even_if_stage_one_apply_fails(env):
    proc = env.run(
        SESSION, "--yes", FAIL_TF="create_load_gen=false", FAIL_TF_NOT="public_key_pem",
        FAIL_SHRED="1",
    )  # fmt: skip
    assert proc.returncode != 0
    s1 = stage1_apply(env)
    assert env.find("aws", "ssm delete-parameter", start=s1) != -1
    assert env.find("shred") != -1
    assert_clean_exit_state(env)


# --- stage 2 -----------------------------------------------------------------


def test_destroy_failure_exits_non_zero_and_is_loud(env):
    proc = env.run(SESSION, "--yes", FAIL_TF="destroy")
    assert proc.returncode != 0
    assert "DESTROY FAILED TWICE" in proc.stdout
    assert "STAGE 2 FAILED" in proc.stdout
    assert "SESSION NOT CLEANLY ENDED" in proc.stdout
    assert "\a" in proc.stdout  # the bell
    destroys = [c for c in env.calls() if " destroy " in c]
    assert len(destroys) == 2 and "-refresh=false" in destroys[1]
    assert_clean_exit_state(env)
    assert env.ledger_events() == ["record", "correct"]


def test_destroy_retry_without_refresh_succeeds(env):
    proc = env.run(SESSION, "--yes", FAIL_TF_ONCE=" destroy ")
    assert proc.returncode == 0
    assert "retrying with -refresh=false" in proc.stdout
    destroys = [c for c in env.calls() if " destroy " in c]
    assert len(destroys) == 2 and "-refresh=false" in destroys[1]


def test_a_dirty_final_check_fails_the_session(env):
    proc = env.run(SESSION, "--yes", STUB_NONZERO="list-functions")
    assert proc.returncode != 0
    assert "launch_check FAILED" in proc.stdout
    assert "SESSION NOT CLEANLY ENDED" in proc.stdout


# --- signals -----------------------------------------------------------------


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("hang", ["first", "second"])
def test_signal_during_apply_stops_everything(env, sig, hang):
    proc = env.start(SESSION, "--yes", TF_HANG=hang)
    hanging = env.state / "hanging"
    deadline = time.time() + 30
    while not hanging.exists():
        assert time.time() < deadline, "the stub apply never started"
        assert proc.poll() is None
        time.sleep(0.05)
    proc.send_signal(sig)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == {signal.SIGTERM: 143, signal.SIGINT: 130}[sig]
    assert any("interrupted, state saved" in c for c in env.calls()) or "interrupted" in "\n".join(
        env.calls()
    )
    # the running apply got one INT first; then stage 1, stage 2 and the ledger
    intr = env.find("terraform: interrupted")
    s1 = stage1_apply(env)
    assert intr != -1 and s1 > intr
    assert env.find("aws", "ssm delete-parameter", start=s1) != -1
    assert env.find("terraform", " destroy ", start=s1) != -1
    assert_clean_exit_state(env)
    assert env.ledger_events() == ["record", "correct"]
    assert "SESSION NOT CLEANLY ENDED" not in out


def test_sighup_also_cleans_up(env):
    proc = env.start(SESSION, "--yes", TF_HANG="first")
    deadline = time.time() + 30
    while not (env.state / "hanging").exists():
        assert time.time() < deadline
        time.sleep(0.05)
    proc.send_signal(signal.SIGHUP)
    proc.communicate(timeout=60)
    assert proc.returncode == 129
    assert_clean_exit_state(env)
    assert env.find("terraform", " destroy ") != -1


# --- layer 4: the CloudWatch poll --------------------------------------------


def test_layer4_stops_above_the_budget_plus_the_probe(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", STUB_CW_SUM=str(LIMIT + 1))
    assert proc.returncode == 3
    assert "BYTE BUDGET EXCEEDED" in proc.stdout
    assert stage1_apply(env) != -1
    assert env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)


def test_layer4_does_not_stop_at_the_limit(env):
    env.clear_marker("results/done")
    # the budget alone would be over; budget + probe bytes is the limit. The
    # instance "finishes" at the 3rd CloudWatch call (1st is preflight).
    proc = env.run(SESSION, "--yes", STUB_CW_SUM=str(LIMIT), STUB_DONE_AFTER_CW="3")
    assert proc.returncode == 0, proc.stdout
    assert "BYTE BUDGET EXCEEDED" not in proc.stdout
    assert len([c for c in env.calls() if "cloudwatch get-metric" in c]) >= 2


def test_layer4_scenario_a_probe_bytes_do_not_false_stop(env):
    # Run A: instance 5.3e9 + probe 2.2e9. 7e9 is over the instance budget alone.
    env.clear_marker("results/done")
    ok = env.run(SESSION, "--yes", SCENARIO="a", STUB_CW_SUM="7000000000", STUB_DONE_AFTER_CW="3")
    assert ok.returncode == 0, ok.stdout
    assert "BYTE BUDGET EXCEEDED" not in ok.stdout
    assert str(A_LIMIT) in ok.stdout  # the limit is printed
    env.clear_marker("results/done")
    over = env.run(
        SESSION, "--yes", SCENARIO="a", STUB_CW_SUM=str(A_LIMIT + 1), LAUNCH_RUN_ID="t-run2"
    )
    assert over.returncode == 3 and "BYTE BUDGET EXCEEDED" in over.stdout


def test_five_unreadable_layer4_minutes_stop_the_session(env):
    env.clear_marker("results/done")
    # call 1 is preflight's plan_bytes; the poll fails from the 2nd call on
    proc = env.run(SESSION, "--yes", FAIL_AWS="cloudwatch get-metric-statistics=2")
    assert proc.returncode == 4, proc.stdout
    assert "5 of 5 in a row" in proc.stdout and "layer 4 is blind" in proc.stdout
    assert len([c for c in env.calls() if "cloudwatch get-metric" in c]) == 6
    assert stage1_apply(env) != -1
    assert env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)


def test_layer4_cloudwatch_failure_is_reported_not_silent(env):
    # preflight's CloudWatch read (plan_bytes) fails first: a refusal, never a zero
    proc = env.run(SESSION, "--yes", FAIL_AWS="cloudwatch get-metric")
    assert proc.returncode != 0
    assert env.find("apply") == -1


# --- timeline: MINUTES against the planned release and run -------------------

SCHED = {n: scenario.schedule(n) for n in ("a", "b", "c", "d", "bcd", "p")}
MIN_MINUTES = {n: v["min_minutes"] for n, v in SCHED.items()}  # derived from the scenario data


def test_the_minimums_are_derived_not_fixed():
    # a gated run waits for T0 after the runs before it: bcd = B (30 min ramp) then C
    assert SCHED["bcd"]["release_offset_minutes"] > SCHED["b"]["end_minutes"] - 5  # after B ends
    assert SCHED["bcd"]["release_offset_minutes"] - SCHED["c"]["release_offset_minutes"] >= 30
    assert SCHED["bcd"]["min_minutes"] > SCHED["bcd"]["release_offset_minutes"]
    assert SCHED["bcd"]["min_minutes"] <= SCHED["bcd"]["max_minutes"]
    assert SCHED["a"]["seed_sets"] == ["build", "patch"]
    assert SCHED["d"]["seed_sets"] == ["build", "patch2"]  # the build too: probe P reads it
    assert SCHED["bcd"]["run_files"] == ["b-0", "c-0", "d-0", "d-1"]


@pytest.mark.parametrize("scn", sorted(MIN_MINUTES))
def test_default_minutes_satisfy_the_scenario_timeline(env, scn):
    proc = env.run(SESSION, "--dry-run", SCENARIO=scn, MINUTES="")
    assert proc.returncode == 0, proc.stdout
    assert f"minimum MINUTES {MIN_MINUTES[scn]}" in proc.stdout
    assert f"{MIN_MINUTES[scn]} minutes" in proc.stdout  # the default is the minimum
    assert f"release at +{SCHED[scn]['release_offset_minutes']} min" in proc.stdout


@pytest.mark.parametrize("scn", sorted(MIN_MINUTES))
def test_too_few_minutes_is_refused_before_any_call(env, scn):
    proc = env.run(SESSION, "--yes", SCENARIO=scn, MINUTES=str(MIN_MINUTES[scn] - 1))
    assert proc.returncode != 0
    assert "below the planned timeline" in proc.stdout
    assert env.calls() == []
    ok = env.run(SESSION, "--dry-run", SCENARIO=scn, MINUTES=str(MIN_MINUTES[scn]))
    assert ok.returncode == 0


def test_the_maximum_minutes_is_derived_too(env):
    top = SCHED["bcd"]["max_minutes"]
    assert env.run(SESSION, "--dry-run", SCENARIO="bcd", MINUTES=str(top)).returncode == 0
    over = env.run(SESSION, "--yes", SCENARIO="bcd", MINUTES=str(top + 1))
    assert over.returncode != 0 and f"from 1 to {top}" in over.stdout
    assert env.calls() == []


def test_a_later_release_offset_raises_the_minimum(env):
    later = SCHED["a"]["release_offset_minutes"] + 10
    proc = env.run(
        SESSION,
        "--yes",
        SCENARIO="a",
        MINUTES=str(MIN_MINUTES["a"]),
        RELEASE_OFFSET_MINUTES=str(later),
    )
    assert proc.returncode != 0 and "below the planned timeline" in proc.stdout
    assert env.calls() == []
    ok = env.run(SESSION, "--dry-run", SCENARIO="a", MINUTES="", RELEASE_OFFSET_MINUTES=str(later))
    assert ok.returncode == 0 and f"minimum MINUTES {MIN_MINUTES['a'] + 10}" in ok.stdout


def test_a_release_offset_before_the_runs_end_is_refused(env):
    # T0 earlier than the end of B (plus margin) would put the release inside run B
    early = SCHED["bcd"]["release_offset_minutes"] - 1
    proc = env.run(SESSION, "--yes", SCENARIO="bcd", RELEASE_OFFSET_MINUTES=str(early))
    assert proc.returncode != 0 and "below the derived" in proc.stdout
    assert env.calls() == []


def test_the_release_offset_per_scenario_reaches_terraform(env):
    for scn in ("a", "bcd"):
        offset = SCHED[scn]["release_offset_minutes"]
        env.log.write_text("")
        before = int(time.time())
        proc = env.run(SESSION, "--yes", SCENARIO=scn, LAUNCH_RUN_ID=f"t-{scn}", MINUTES="")
        assert proc.returncode == 0, proc.stdout
        line = env.calls()[env.find("terraform", " apply ", "release_at_epoch=")]
        release = int(line.split("release_at_epoch=")[1].split()[0])
        assert before + offset * 60 <= release <= int(time.time()) + offset * 60
        assert "create_load_gen=true" in line  # T0 is set by the second apply, with the instance
        # the cookies and the instance deadline follow MINUTES, which is the derived minimum here
        assert f"minutes={MIN_MINUTES[scn]}" in line


def test_the_deadline_counts_from_the_cookie_mint():
    text = Path("orchestration/launch_session.sh").read_text()
    assert "deadline=$((MINT_SECONDS + MINUTES * 60))" in text
    assert text.index("MINT_SECONDS=$SECONDS\nEXPIRES") > 0


def test_release_wait_arithmetic():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    code = (
        "import { secondsUntil, setupTimeoutSeconds, startSeconds, chunkCount }"
        " from './launch/k6/wait.js';"
        "console.log(JSON.stringify([secondsUntil(10000, 10000*1000 - 45*60*1000),"
        " secondsUntil(10000, 10000*1000 + 700*1000), secondsUntil(10000, 9999500),"
        " setupTimeoutSeconds(2700, 30, 2), startSeconds(49, 50, 30), startSeconds(0, 50, 30),"
        " chunkCount(64, null), chunkCount(64, 30), chunkCount(8, 30)]));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", code], capture_output=True, text=True, check=True
    ).stdout
    until, past, partial, timeout, last, first, full, limited, small = json.loads(out)
    assert until == 45 * 60  # a sleep until T0, no polling
    assert past == 0  # already past: no wait
    assert partial == 1  # whole seconds, rounded up
    assert timeout == 2700 + 60 + 60  # the sleep, the gate tries and a minute
    assert (first, last) == (0, 1764)  # 50 clients over 30 minutes: 36 s apart
    assert (full, limited, small) == (64, 30, 8)


# --- edge checks after seeding -----------------------------------------------


def test_edge_checks_run_after_seeding_and_before_the_probe(env):
    proc = env.run(SESSION, "--yes", SCENARIO="a", MINUTES="")
    assert proc.returncode == 0, proc.stdout
    assert "does not prove the signature" in proc.stdout
    calls = env.calls()
    license_ = env.find("curl", "/license")
    nocookie = next(
        i
        for i, c in enumerate(calls)
        if c.startswith("curl") and "/build/manifest.json" in c and " -H " not in c
    )
    signed = next(
        i
        for i, c in enumerate(calls)
        if c.startswith("curl") and "/build/manifest.json" in c and " -H " in c
    )
    probe = env.find("k6", "p.json")
    assert license_ < nocookie < signed < probe


@pytest.mark.parametrize("extra", [{"STUB_NOCOOKIE_CODE": "200"}, {"STUB_BUILD_CODE": "403"}])
def test_a_failed_edge_check_stops_the_session(env, extra):
    proc = env.run(SESSION, "--yes", SCENARIO="a", MINUTES="", **extra)
    assert proc.returncode != 0
    assert env.find("k6 run") == -1
    assert stage1_apply(env) != -1 and env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)


# --- probe P in the background -----------------------------------------------


def test_probe_runs_in_the_background_and_is_waited_for_before_stage_one(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", STUB_K6_SLEEP="1", STUB_DONE_AFTER_CW="8")
    assert proc.returncode == 0, proc.stdout
    start = env.find("k6", "p.json")
    end = env.find("k6 finished")
    s1 = stage1_apply(env, start)
    polls = [
        i for i, c in enumerate(env.calls()) if "cloudwatch get-metric" in c and start < i < end
    ]
    assert polls, "the byte poll must go on while the probe runs"
    assert start < end < s1


def test_a_failed_probe_fails_the_session_after_stage_two(env):
    proc = env.run(SESSION, "--yes", FAIL_K6="1")
    assert proc.returncode != 0 and "probe P failed" in proc.stdout
    assert env.find("terraform", " destroy ") != -1


def test_the_probe_is_ended_on_a_budget_stop(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", STUB_K6_SLEEP="30", STUB_CW_SUM=str(LIMIT + 1))
    assert proc.returncode == 3
    assert env.find("k6 finished") == -1  # killed, not waited for 30 s


# --- results copy-out is bounded ---------------------------------------------


def test_a_hung_copy_out_never_delays_stage_two(env):
    t0 = time.time()
    proc = env.run(
        SESSION, "--yes", STUB_HANG="s3 cp s3://stub-build/results/", LAUNCH_COLLECT_TIMEOUT="1",
        timeout=40,
    )  # fmt: skip
    assert time.time() - t0 < 30
    assert proc.returncode == 0, proc.stdout
    assert "collection failed" in proc.stdout
    assert env.find("terraform", " destroy ") != -1


def test_the_run_record_starts_with_cdn_logs_collected_false(env):
    assert env.run(SESSION, "--yes").returncode == 0
    record = json.loads((env.runs / "t-run" / "run.json").read_text())
    assert record["cdn_logs_collected"] is False


def test_the_run_record_has_the_k6_request_counts_before_stage_two(env):
    """run.json: k6_requests (an integer) from the k6 summaries copied out of the bucket."""
    summaries = {
        "results/b-0.json": 3200,
        "results/c-0.json": 1_000_000,
        "results/d-0.json": 400,
        "results/d-1.json": 8,
    }
    for key, n in summaries.items():
        counters = {"http_reqs": {"count": n, "rate": 1.0}, "req_build": {"count": n, "rate": 1.0}}
        env.write_s3(key, json.dumps({"metrics": counters}))
    probe = env.runs / "t-run"
    probe.mkdir(parents=True)
    (probe / "probe-p.json").write_text(json.dumps({"metrics": {"http_reqs": {"count": 31}}}))
    assert env.run(SESSION, "--yes").returncode == 0
    record = json.loads((env.runs / "t-run" / "run.json").read_text())
    assert record["k6_requests"] == sum(summaries.values()) + 31
    assert isinstance(record["k6_requests"], int) and record["k6_complete"] is True
    assert record["cdn_logs_collected"] is False  # launch_collect keeps its own key
    assert isinstance(record["curl_requests"], int) and record["curl_requests"] >= 3
    assert env.find("s3 cp s3://stub-build/results/") < env.find("terraform", " destroy ")


def test_a_missing_summary_makes_the_k6_count_incomplete(env):
    assert env.run(SESSION, "--yes").returncode == 0
    record = json.loads((env.runs / "t-run" / "run.json").read_text())
    assert record["k6_complete"] is False and record["k6_requests"] is None


# --- review fixes (Opus security review of the launch tooling) ---------------


def test_a_changed_signing_key_stops_the_session_before_the_second_licence_check(env):
    proc = env.run(SESSION, "--yes", STUB_KEY_CHANGE="1")
    assert proc.returncode != 0
    assert "the signing key changed after the cookies were minted" in proc.stdout
    gen = env.find("terraform", " apply ", "create_load_gen=true")
    assert gen != -1
    assert env.find("curl", start=gen) == -1  # no /license check after the second apply
    assert stage1_apply(env) != -1 and env.find("terraform", " destroy ") != -1
    assert_clean_exit_state(env)


def test_old_results_are_cleared_before_the_instance_apply(env):
    assert env.run(SESSION, "--yes").returncode == 0
    rm = env.find("s3 rm s3://stub-build/results/", "--recursive")
    assert rm != -1 and rm < env.find("terraform", " apply ", "create_load_gen=true")
    proc = env.run(SESSION, "--yes", FAIL_AWS="s3 rm", LAUNCH_RUN_ID="t-run2")
    assert proc.returncode != 0 and "could not clear old results" in proc.stdout
    assert_clean_exit_state(env)


def test_stage_one_always_terminates_directly_and_removes_the_key_first(env):
    assert env.run(SESSION, "--yes", STUB_INSTANCE_IDS="i-0stub").returncode == 0
    gen = env.find("terraform", " apply ", "create_load_gen=true")
    term = env.find("ec2 terminate-instances", "i-0stub", start=gen)
    s1 = stage1_apply(env, gen)
    assert gen < term < s1  # direct termination, even with a good apply, before stage 1 apply


def test_stage_one_apply_is_retried_once(env):
    # the first stage 1 apply fails, the second works: no failure, no forced stage 2 under HOLD
    proc = env.run(
        SESSION, "--yes", HOLD="1", FAIL_TF_ONCE="create_load_gen=false -var minutes=120"
    )
    # FAIL_TF_ONCE matches only the stage 1 argument order (apply 1 has minutes first)
    s1 = [
        i
        for i, c in enumerate(env.calls())
        if c.startswith("terraform")
        and " apply " in c
        and "public_key_pem" not in c
        and "create_load_gen=false" in c
    ]
    assert len(s1) == 2, env.calls()
    assert proc.returncode == 0, proc.stdout
    assert env.find("terraform", " destroy ") == -1  # HOLD kept the edge


def test_stage_one_apply_failing_twice_runs_stage_two_despite_hold(env):
    proc = env.run(SESSION, "--yes", HOLD="1", FAIL_TF="create_load_gen=false",
                   FAIL_TF_NOT="public_key_pem")  # fmt: skip
    assert proc.returncode != 0
    s1 = [
        i
        for i, c in enumerate(env.calls())
        if c.startswith("terraform")
        and " apply " in c
        and "public_key_pem" not in c
        and "create_load_gen=false" in c
    ]
    assert len(s1) == 2
    assert env.find("terraform", " destroy ") != -1
    assert "HOLD is ignored" in proc.stdout


def test_a_budget_stop_runs_stage_two_despite_hold(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", HOLD="1", STUB_CW_SUM=str(LIMIT + 1))
    assert proc.returncode == 3
    assert env.find("terraform", " destroy ") != -1


def test_a_state_lock_error_prints_the_force_unlock_hint_and_never_runs_it(env):
    proc = env.run(SESSION, "--yes", FAIL_TF="create_load_gen=false", FAIL_TF_NOT="public_key_pem",
                   FAIL_TF_LOCK="1")  # fmt: skip
    assert "force-unlock <LOCK_ID>" in proc.stdout
    assert env.find("force-unlock") == -1


def test_the_cloudwatch_sum_is_logged_each_poll(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", STUB_CW_SUM="12345", STUB_DONE_AFTER_CW="4")
    assert proc.returncode == 0, proc.stdout
    assert proc.stdout.count("BytesDownloaded since the start: 12345") >= 2


def test_the_run_record_keeps_the_cloudwatch_bytes_read_by_the_poll(env):
    env.clear_marker("results/done")
    proc = env.run(SESSION, "--yes", STUB_CW_SUM="12345", STUB_DONE_AFTER_CW="4")
    assert proc.returncode == 0, proc.stdout
    record = json.loads((env.runs / "t-run" / "run.json").read_text())
    assert record["cloudwatch_bytes_downloaded"] == 12345
    assert record["cloudwatch_bytes_last"] == 12345


def test_the_cloudwatch_bytes_are_null_when_the_poll_never_read_them(env):
    assert env.run(SESSION, "--yes").returncode == 0  # results/done is there at once: no poll
    record = json.loads((env.runs / "t-run" / "run.json").read_text())
    assert record["cloudwatch_bytes_downloaded"] is None
    assert record["cloudwatch_bytes_last"] is None


@pytest.mark.parametrize("bad", ["0", "9", "121", "abc", "1.5"])
def test_the_poll_interval_is_checked_without_the_test_override(env, bad):
    proc = env.run(SESSION, "--yes", LAUNCH_ALLOW_FAST_POLL="0", LAUNCH_POLL_SECONDS=bad)
    assert proc.returncode != 0 and "LAUNCH_POLL_SECONDS" in proc.stdout
    assert env.calls() == []


def test_a_good_poll_interval_passes_the_check(env):
    proc = env.run(SESSION, "--dry-run", LAUNCH_ALLOW_FAST_POLL="0", LAUNCH_POLL_SECONDS="60")
    assert proc.returncode == 0
