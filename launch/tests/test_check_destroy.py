"""launch_check.sh and launch_destroy.sh against stubs."""

import pytest

CHECK = "orchestration/launch_check.sh"
DESTROY = "orchestration/launch_destroy.sh"

# One count query per stub pattern: raising it to 1 must fail the check.
COUNTS = [
    "list-functions", "list-key-value-stores", "list-public-keys", "list-key-groups",
    "list-cache-policies", "list-origin-access-controls", "describe-delivery-sources",
    "describe-delivery-destinations", "describe-deliveries", "describe-volumes",
    "describe-spot-instance-requests", "describe-security-groups", "describe-parameters",
    "resourcegroupstaggingapi", "describe-instances",
]  # fmt: skip


def test_check_is_clean_when_everything_is_gone(env):
    proc = env.run(CHECK)
    assert proc.returncode == 0, proc.stdout
    assert "launch_check ok" in proc.stdout
    for key in ("distributions_beyond_standing", "key_groups", "cache_policies", "iam_role",
                "cookie_parameter", "build_bucket", "log_bucket", "dev_launch_state"):  # fmt: skip
        assert f"{key} 0" in proc.stdout


@pytest.mark.parametrize("pattern", COUNTS)
def test_check_fails_on_a_leftover(env, pattern):
    proc = env.run(CHECK, STUB_NONZERO=pattern)
    assert proc.returncode == 1
    assert "launch_check FAILED" in proc.stdout


def test_check_counts_distributions_beyond_the_standing_edge(env):
    proc = env.run(CHECK, STUB_NONZERO="list-distributions")  # answers 1: only the standing edge
    assert proc.returncode == 0


def test_check_fails_on_a_leftover_role_profile_and_buckets(env):
    assert env.run(CHECK, STUB_ROLE="1").returncode == 1
    env.set_marker("x", bucket="cerberus-platform-launch-build-" + "1234" + "56789012")
    proc = env.run(CHECK)
    assert proc.returncode == 1 and "build_bucket 1" in proc.stdout


def test_check_fails_on_leftover_state(env):
    proc = env.run(CHECK, STUB_STATE_LIST="aws_s3_bucket.build\n")
    assert proc.returncode == 1 and "dev_launch_state 1" in proc.stdout


@pytest.mark.parametrize(
    "fail",
    [
        "cloudfront list-distributions", "cloudfront list-functions", "cloudfront list-key-groups",
        "logs describe-deliveries", "ec2 describe-volumes", "ec2 describe-instances",
        "ssm describe-parameters", "s3api head-bucket", "iam get-role",
        "iam get-instance-profile", "sts get-caller-identity", "resourcegroupstaggingapi",
    ],
)  # fmt: skip
def test_check_prints_error_and_fails_on_any_aws_failure(env, fail):
    proc = env.run(CHECK, FAIL_AWS=fail)
    assert proc.returncode == 1
    assert "error" in proc.stdout


def test_check_state_error_is_an_error_not_a_zero(env):
    proc = env.run(CHECK, FAIL_TF="state list")
    assert proc.returncode == 1 and "dev_launch_state error" in proc.stdout
    proc = env.run(CHECK, FAIL_TF="init")
    assert proc.returncode == 1 and "dev_launch_state error" in proc.stdout


def test_check_prints_no_account_id_bucket_or_domain(env):
    proc = env.run(CHECK)
    assert "cerberus-platform-launch" not in proc.stdout + proc.stderr
    assert ("1234" + "56789012") not in proc.stdout + proc.stderr


# --- destroy -----------------------------------------------------------------


def test_destroy_full_run(env):
    proc = env.run(DESTROY)
    assert proc.returncode == 0, proc.stdout
    s1 = env.find("aws", "ssm delete-parameter")
    destroy = env.find("terraform", " destroy ")
    check = env.find("aws", "cloudfront list-distributions")
    assert -1 < s1 < destroy < check


def test_destroy_stage2_only_skips_the_parameter(env):
    assert env.run(DESTROY, "--stage2").returncode == 0
    assert env.find("aws", "ssm delete-parameter") == -1


def test_destroy_failure_is_non_zero_and_loud(env):
    proc = env.run(DESTROY, FAIL_TF="destroy")
    assert proc.returncode != 0
    assert "DESTROY FAILED TWICE" in proc.stdout and "NOT CLEANLY DESTROYED" in proc.stdout
    destroys = [c for c in env.calls() if " destroy " in c]
    assert len(destroys) == 2 and "-refresh=false" in destroys[1]
    assert env.find("aws", "cloudfront list-distributions") != -1  # the check still ran


def test_destroy_retry_succeeds_with_refresh_false(env):
    proc = env.run(DESTROY, FAIL_TF_ONCE=" destroy ")
    assert proc.returncode == 0
    assert "-refresh=false" in [c for c in env.calls() if " destroy " in c][1]


def test_destroy_init_failure_is_non_zero_and_skips_the_destroy(env):
    proc = env.run(DESTROY, FAIL_TF=" init ")
    assert proc.returncode != 0
    assert env.find("terraform", " destroy ") == -1
    assert "init failed" in proc.stdout


def test_destroy_parameter_failure_still_destroys(env):
    proc = env.run(DESTROY, FAIL_AWS="ssm delete-parameter")
    assert proc.returncode != 0
    assert "COOKIE PARAMETER DELETE FAILED" in proc.stdout
    assert env.find("terraform", " destroy ") != -1


def test_destroy_parameter_not_found_is_fine(env):
    assert env.run(DESTROY, PARAM_NOT_FOUND="1").returncode == 0


def test_destroy_dirty_check_fails(env):
    proc = env.run(DESTROY, STUB_NONZERO="list-key-groups")
    assert proc.returncode != 0
    assert "launch_check FAILED" in proc.stdout


def test_destroy_rejects_an_unknown_argument(env):
    assert env.run(DESTROY, "--nope").returncode == 2
    assert env.calls() == []


# --- F8 cleanup: Spot requests without the tag, and a leftover key directory --


def test_spot_check_also_looks_by_group_name_and_instance_id(env):
    proc = env.run(CHECK, STUB_INSTANCE_IDS="i-aaa\ti-bbb")
    assert proc.returncode == 0, proc.stdout
    assert env.find("describe-spot-instance-requests", "launch.group-name") != -1
    assert env.find("describe-spot-instance-requests", "instance-id,Values=i-aaa,i-bbb") != -1


def test_spot_check_counts_a_request_found_only_by_group_name(env):
    proc = env.run(CHECK, STUB_NONZERO="launch.group-name")
    assert proc.returncode == 1 and "launch_spot_requests 1" in proc.stdout


def test_spot_check_counts_a_request_found_only_by_instance_id(env):
    proc = env.run(CHECK, STUB_INSTANCE_IDS="i-aaa", STUB_NONZERO="instance-id,Values")
    assert proc.returncode == 1 and "launch_spot_requests 1" in proc.stdout


@pytest.mark.parametrize("fail", ["launch.group-name", "describe-spot-instance-requests"])
def test_spot_check_unreadable_is_error_not_zero(env, fail):
    proc = env.run(CHECK, FAIL_AWS=fail)
    assert proc.returncode == 1 and "launch_spot_requests error" in proc.stdout


def test_spot_check_instance_id_query_failure_is_error(env):
    proc = env.run(CHECK, FAIL_AWS="InstanceId")
    assert proc.returncode == 1 and "launch_spot_requests error" in proc.stdout


def test_destroy_removes_a_leftover_key_directory(env):
    import os

    stale = os.path.join(env.xdg, "launch-Ab3xYz")
    os.mkdir(stale)
    open(os.path.join(stale, "key.pem"), "w").write("secret")
    other = os.path.join(env.xdg, "launch-keepme-not-matching")
    os.mkdir(other)
    proc = env.run(DESTROY)
    assert proc.returncode == 0, proc.stdout
    assert "LEFTOVER KEY DIRECTORY" in proc.stdout
    assert not os.path.exists(stale)
    assert os.path.exists(other)  # not the exact template: left alone


def test_destroy_never_follows_a_symlink_named_like_a_key_directory(env, tmp_path):
    import os

    target = tmp_path / "precious"
    target.mkdir()
    (target / "f").write_text("keep")
    link = os.path.join(env.xdg, "launch-Lnk123")
    os.symlink(target, link)
    proc = env.run(DESTROY)
    assert proc.returncode == 0, proc.stdout
    assert (target / "f").read_text() == "keep"
    assert os.path.islink(link)


def test_destroy_with_no_leftover_key_directory_is_quiet(env):
    proc = env.run(DESTROY)
    assert proc.returncode == 0 and "LEFTOVER KEY DIRECTORY" not in proc.stdout


def test_destroy_stage2_leaves_a_key_directory_alone(env):
    import os

    stale = os.path.join(env.xdg, "launch-Ab3xYz")
    os.mkdir(stale)
    assert env.run(DESTROY, "--stage2").returncode == 0
    assert os.path.exists(stale)
