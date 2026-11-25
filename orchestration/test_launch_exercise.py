"""17.5: orchestration/launch_exercise.sh against stubs. Nothing reaches AWS.

aws, kubectl, terraform, uv, sleep, exercise.sh, the ledger and submit_job.sh are
stubs in a throwaway copy of the repo layout, so the script runs end to end. Each
stub appends one line to a call log, and the tests read the order of the lines.
The fake account number below is the scan's allowed test value.
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FAKE_ACCOUNT = "123456789012"

AWS = """#!/usr/bin/env bash
echo "aws $*" >>"$STUB_LOG"
case "$*" in
  *"sts get-caller-identity"*) echo "$FAKE_ACCOUNT" ;;
  *"eks list-clusters"*) echo "${STUB_EKS_LEFT:-0}" ;;
  *"describe-nat-gateways"*|*"describe-addresses"*|*"describe-instances"*) echo 0 ;;
  *"list-objects-v2"*) echo "${STUB_CDN_KEYS:-0}" ;;
esac
exit 0
"""
TERRAFORM = """#!/usr/bin/env bash
echo "terraform $*" >>"$STUB_LOG"
case "$*" in
  *" apply "*)
    echo "terraform apply running" >>"$STUB_LOG"
    [[ -n "${STUB_APPLY_SLEEP:-}" ]] && /bin/sleep "$STUB_APPLY_SLEEP"
    [[ -z "${STUB_APPLY_FAIL:-}" ]] || exit 1 ;;
  *" destroy "*) [[ -z "${STUB_DESTROY_FAIL:-}" ]] || exit 1 ;;
esac
exit 0
"""
KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >>"$STUB_LOG"
case "$1" in
  get) echo COMPLETED ;;
  logs) echo "[generate] done"; echo "[spark-transform] appended 5 new events (silver now 5)" ;;
  apply) [[ -z "${STUB_KUBECTL_APPLY_FAIL:-}" ]] || exit 1 ;;
esac
exit 0
"""
SLEEP = "#!/usr/bin/env bash\nexit 0\n"
UV = """#!/usr/bin/env bash
echo "uv $*" >>"$STUB_LOG"
case "$*" in
  *dbt*) exit "${STUB_DBT_RC:-0}" ;;
  *data_quality_downloads*) exit "${STUB_DQ_RC:-0}" ;;
esac
exit 0
"""
EXERCISE_CHECK = (
    '#!/usr/bin/env bash\necho "exercise.sh $*" >>"$STUB_LOG"\nexit "${STUB_CHECK_RC:-0}"\n'
)
SUBMIT = '#!/usr/bin/env bash\necho "submit_job APP=$APP_NAME SCRIPT=$SCRIPT_NAME" >>"$STUB_LOG"\n'
LEDGER = """import os, sys
with open(os.environ["STUB_LOG"], "a") as log:
    log.write("ledger " + " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "guard":
    sys.exit(int(os.environ.get("LEDGER_GUARD_RC", "0")))
if sys.argv[1] == "record":
    sys.exit(int(os.environ.get("LEDGER_RECORD_RC", "0")))
if sys.argv[1] == "correct":
    sys.exit(int(os.environ.get("LEDGER_CORRECT_RC", "0")))
"""


def write(path, body, mode=0o755):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(mode)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "repo"
    write(
        root / "orchestration" / "launch_exercise.sh",
        (REPO / "orchestration" / "launch_exercise.sh").read_text(),
    )
    write(root / "orchestration" / "exercise.sh", EXERCISE_CHECK)
    write(root / "launch" / "ledger.py", LEDGER, 0o644)
    (root / "terraform" / "envs" / "dev-compute").mkdir(parents=True)
    spark = root / "transform" / "spark"
    write(spark / "submit_job.sh", SUBMIT)
    write(spark / "generate_bulk_downloads.py", "# stub\n", 0o644)
    shutil.copy(REPO / "transform/spark/spark-application-generate-downloads.yaml", spark)
    write(root / "transform" / "dbt" / "requirements.txt", "", 0o644)
    write(root / "observability/launch/data_quality_downloads.py", "# stub\n", 0o644)
    bin_dir = tmp_path / "bin"
    for name, body in (
        ("aws", AWS), ("terraform", TERRAFORM), ("kubectl", KUBECTL), ("sleep", SLEEP), ("uv", UV),
    ):  # fmt: skip
        write(bin_dir / name, body)
    return root, bin_dir, tmp_path / "calls.log"


def start(tree, args, **env):
    root, bin_dir, calls = tree
    full = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(root),
        "STUB_LOG": str(calls),
        "FAKE_ACCOUNT": FAKE_ACCOUNT,
        **{k: str(v) for k, v in env.items()},
    }
    return subprocess.Popen(
        ["bash", str(root / "orchestration" / "launch_exercise.sh"), *args],
        env=full, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )  # fmt: skip


def run(tree, args=("--generate", "1000", "--yes"), **env):
    proc = start(tree, list(args), **env)
    out, _ = proc.communicate(timeout=60)
    calls = tree[2].read_text().splitlines() if tree[2].exists() else []
    return proc.returncode, out, calls


def index(calls, prefix):
    return next(i for i, c in enumerate(calls) if c.startswith(prefix))


def has(calls, prefix):
    return any(c.startswith(prefix) for c in calls)


def test_a_guard_refusal_makes_no_aws_write(tree):
    rc, out, calls = run(tree, LEDGER_GUARD_RC=1)
    assert rc != 0
    assert "REFUSED" in out
    assert [c for c in calls if c.startswith("aws")] == [
        "aws --profile cerberus-admin --region us-east-1 sts get-caller-identity "
        "--query Account --output text"
    ] * 2  # the account lookups: both read-only
    for forbidden in ("terraform", "kubectl", "uv", "submit_job"):
        assert not has(calls, forbidden)
    assert not has(calls, "ledger record")
    assert not has(calls, "ledger correct")
    assert has(calls, "ledger guard --next-usd 1.00")


def test_a_missing_ledger_fails_closed_with_no_call_at_all(tree):
    (tree[0] / "launch" / "ledger.py").unlink()
    rc, out, calls = run(tree)
    assert rc == 2 and "REFUSED" in out
    assert calls == []


def test_a_failed_exercise_preflight_stops_before_the_guard(tree):
    rc, _, calls = run(tree, STUB_CHECK_RC=1)
    assert rc != 0
    assert not has(calls, "ledger") and not has(calls, "terraform")


def test_happy_path_order_and_destroy_before_dbt(tree):
    rc, out, calls = run(tree)
    assert rc == 0, out
    order = [
        index(calls, "ledger guard"),
        index(calls, "ledger record --run-id"),
        index(calls, "terraform -chdir"),
        index(calls, "kubectl apply"),
        index(calls, "submit_job APP=cerberus-promote-downloads SCRIPT=promote_downloads_spark.py"),
    ]
    assert order == sorted(order)
    destroy = next(i for i, c in enumerate(calls) if " destroy " in c)
    dbt = index(calls, "uv run --no-project --python 3.12")
    dq = next(i for i, c in enumerate(calls) if "data_quality_downloads" in c)
    assert order[-1] < destroy < dbt < dq
    assert has(calls, "ledger record --run-id dl-1000-") and "--kind exercise" in " ".join(calls)
    assert has(calls, "ledger correct --run-id dl-1000-")
    assert not [c for c in calls if c.startswith("ledger guard")][1:]  # the teardown never guards
    assert (
        "--vars {enable_downloads: true, enable_downloads_cdn: false, k6_requests_by_run: {}}"
        in " ".join(calls)
    )


def test_cdn_models_turn_on_only_when_bronze_has_log_files(tree):
    rc, _, calls = run(tree, STUB_CDN_KEYS=1)
    assert rc == 0
    assert "enable_downloads_cdn: true" in " ".join(calls)


def test_no_account_number_in_the_log_or_the_record(tree):
    rc, out, _ = run(tree)
    assert rc == 0
    assert FAKE_ACCOUNT not in out
    for path in (tree[0] / "observability" / "launch").rglob("*"):
        if path.is_file():
            assert FAKE_ACCOUNT not in path.read_text()
    record = next((tree[0] / "observability/launch/runs").glob("*/run.json")).read_text()
    assert '"cdn_logs_collected": false' in record


def test_teardown_runs_from_the_exit_trap_after_a_failed_step(tree):
    rc, _, calls = run(tree, STUB_KUBECTL_APPLY_FAIL=1)
    assert rc != 0
    assert any(" destroy " in c for c in calls)
    assert has(calls, "ledger correct")
    assert not has(calls, "uv")  # dbt and DQ never ran


def test_teardown_runs_after_a_failed_apply(tree):
    rc, _, calls = run(tree, STUB_APPLY_FAIL=1)
    assert rc != 0
    assert any(" destroy " in c for c in calls)
    assert not has(calls, "kubectl")


def test_teardown_runs_on_sigterm(tree):
    proc = start(tree, ["--generate", "1000", "--yes"], STUB_APPLY_SLEEP=3)
    calls = tree[2]
    deadline = time.time() + 20
    while time.time() < deadline:
        if calls.exists() and "terraform apply running" in calls.read_text():
            break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("the apply never started")
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=60)
    lines = calls.read_text().splitlines()
    assert proc.returncode == 143
    assert any(" destroy " in c for c in lines)
    assert has(lines, "ledger correct")
    assert not has(lines, "kubectl apply")


def test_a_failed_destroy_exits_non_zero_and_skips_dbt(tree):
    rc, out, calls = run(tree, STUB_DESTROY_FAIL=1)
    assert rc != 0
    assert "DESTROY FAILED" in out
    assert not has(calls, "uv")


def test_a_failed_destroy_in_the_exit_trap_exits_non_zero(tree):
    rc, out, _ = run(tree, STUB_KUBECTL_APPLY_FAIL=1, STUB_DESTROY_FAIL=1)
    assert rc == 1
    assert "DESTROY FAILED" in out


def test_a_billable_resource_left_after_destroy_exits_non_zero(tree):
    rc, out, _ = run(tree, STUB_EKS_LEFT=1)
    assert rc != 0
    assert "something billable is still up" in out


def test_a_failed_ledger_record_stops_before_the_apply(tree):
    rc, _, calls = run(tree, LEDGER_RECORD_RC=1)
    assert rc != 0
    assert not has(calls, "terraform")


def test_a_failed_ledger_correction_is_not_silent(tree):
    rc, out, _ = run(tree, LEDGER_CORRECT_RC=1)
    assert rc != 0
    assert "LEDGER CORRECTION FAILED" in out


def test_data_quality_failure_exits_3_and_dbt_failure_exits_1(tree):
    assert run(tree, STUB_DQ_RC=3)[0] == 3
    assert run(tree, STUB_DBT_RC=1)[0] == 1


def test_there_is_no_keep_flag(tree):
    rc, _, calls = run(tree, ("--generate", "1000", "--yes", "--keep"))
    assert rc == 2
    assert not has(calls, "terraform")


def test_the_record_is_runs_run_id_run_json(tree):
    rc, _, _ = run(tree)
    assert rc == 0
    records = list((tree[0] / "observability/launch/runs").glob("*/run.json"))
    assert len(records) == 1 and records[0].parent.name.startswith("dl-")
    assert not list((tree[0] / "observability/launch/runs").glob("*.json"))


def test_check_mode_applies_nothing_and_records_nothing(tree):
    rc, _, calls = run(tree, ("--check",))
    assert rc == 0
    assert has(calls, "ledger guard")
    for forbidden in ("terraform", "kubectl", "ledger record", "ledger correct"):
        assert not has(calls, forbidden)


@pytest.mark.parametrize(
    "args",
    [[], ["--generate", "abc", "--yes"], ["--generate", "10", "--run-id", "Bad_ID", "--yes"],
     ["--generate", "10", "--congestion", "x", "--yes"], ["--nope"]],
)  # fmt: skip
def test_bad_arguments_exit_2_before_any_call(tree, args):
    rc, _, calls = run(tree, args)
    assert rc == 2
    assert calls == []
