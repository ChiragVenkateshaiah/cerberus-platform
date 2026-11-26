"""cdn_filter.py and launch_collect.sh: the bronze contract and the privacy checks."""

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCH))

import cdn_filter  # noqa: E402

COLLECT = "orchestration/launch_collect.sh"
FIELDS = cdn_filter.allowlist()
ACCT = "1234" + "56789012"
LOGS = "cerberus-platform-launch-logs-" + ACCT
BRONZE = "cerberus-platform-bronze-" + ACCT
START, END = 1_790_000_000_000, 1_790_000_100_000  # 13-digit ms timestamps


def line(**over):
    row = {
        "timestamp(ms)": START + 5, "x-edge-request-id": "a" * 56, "x-edge-location": "BOM78-P1",
        "x-edge-result-type": "Hit", "x-edge-response-result-type": "Hit", "sc-status": 200,
        "sc-bytes": 104857600, "cs-method": "GET", "cs-uri-stem": "/build/main-1.bin",
        "time-taken": 0.5, "time-to-first-byte": 0.1, "cs-protocol": "https",
    }  # fmt: skip
    row.update(over)
    return json.dumps(row)


def test_allowlist_has_12_fields_and_no_private_ones():
    assert len(FIELDS) == 12
    assert not {
        "c-ip",
        "x-forwarded-for",
        "c-port",
        "cs(Cookie)",
        "cs(Referer)",
        "cs(User-Agent)",
    } & set(FIELDS)


def test_filter_keeps_window_lines_and_original_key_names():
    text = "\n".join(
        [line(), line(**{"timestamp(ms)": START - 1}), line(**{"timestamp(ms)": END + 1})]
    )
    kept = cdn_filter.filter_text(text, FIELDS, START, END, "f")
    assert len(kept) == 1
    assert "timestamp(ms)" in json.loads(kept[0])


def test_filter_refuses_a_field_outside_the_allowlist():
    bad = json.loads(line())
    bad["c-ip"] = "203.0.113.9"
    with pytest.raises(cdn_filter.Refused) as err:
        cdn_filter.filter_text(json.dumps(bad), FIELDS, START, END, "f")
    assert "203.0.113.9" not in str(err.value)  # a value is never in the message


def test_twelve_digit_scan_is_bounded():
    # a 13-digit timestamp and a 13-digit byte count must pass
    cdn_filter.filter_text(line(**{"sc-bytes": 1234567890123}), FIELDS, START, END, "f")
    # exactly 12 digits in a value is refused ...
    for field, value in [("sc-bytes", int(ACCT)), ("x-edge-location", "ab" + ACCT)]:
        with pytest.raises(cdn_filter.Refused):
            cdn_filter.filter_text(line(**{field: value}), FIELDS, START, END, "f")
    # ... but not in the two exempt fields (and cs-uri-stem, see the stem tests)
    cdn_filter.filter_text(line(**{"x-edge-request-id": "q" + ACCT + "q"}), FIELDS, START, END, "f")


def test_filter_refuses_bad_json_and_a_missing_timestamp():
    for bad in ("not json", "[1]", json.dumps({"sc-status": 200})):
        with pytest.raises(cdn_filter.Refused):
            cdn_filter.filter_text(bad, FIELDS, START, END, "f")


def test_run_writes_nothing_when_one_file_is_bad(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "0123456789abcdef").write_text(line() + "\n")
    (tmp_path / "in" / "fedcba9876543210").write_text(
        line(**{"x-edge-location": "ab" + ACCT}) + "\n"
    )
    with pytest.raises(cdn_filter.Refused):
        cdn_filter.run("run-1", START, END, tmp_path / "in", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_run_manifest_and_gzip_input(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "0123456789abcdef").write_bytes(
        gzip.compress((line() + "\n" + line() + "\n").encode())
    )
    m = cdn_filter.run("run-1", START, END, tmp_path / "in", tmp_path / "out")
    assert m["files"] == 1 and m["lines"] == 2 and m["fields"] == FIELDS
    assert set(m) == {
        "run_id",
        "files",
        "lines",
        "fields",
        "window_start",
        "window_end",
        "collected_at",
    }
    part = (tmp_path / "out" / "part-0123456789abcdef.json").read_text().splitlines()
    assert len(part) == 2 and all(json.loads(x) for x in part)
    assert "run_id" not in json.loads(part[0])  # the run id is in the path only


def test_run_id_regex(tmp_path):
    (tmp_path / "in").mkdir()
    for bad in ("Bad", "", "x" * 41, "a_b"):
        with pytest.raises(cdn_filter.Refused):
            cdn_filter.run(bad, START, END, tmp_path / "in", tmp_path / "out")


# --- launch_collect.sh -------------------------------------------------------


def prepare(env, files: dict[str, str], run_id="c-run"):
    rd = env.runs / run_id
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(
        json.dumps({"window_start_ms": START, "window_end_ms": END, "cdn_logs_collected": False})
    )
    for key, body in files.items():
        env.set_marker(key, bucket=LOGS)
        (env.state / "s3" / LOGS / key).write_text(body)


def bronze_keys(env):
    root = env.state / "s3" / BRONZE
    return (
        sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
        if root.exists()
        else []
    )


def collect(env, run_id="c-run", **extra):
    return env.run(COLLECT, run_id, **extra)


def test_collect_copies_parts_then_the_manifest_and_repeats_safely(env):
    prepare(
        env,
        {
            "cdn/EDIST/2026/11/26/05/a.json": line() + "\n",
            "cdn/EDIST/2026/11/26/06/b.json": line() + "\n",
        },
    )
    proc = collect(env)
    assert proc.returncode == 0, proc.stdout
    keys = bronze_keys(env)
    assert len(keys) == 3 and keys[0].startswith("downloads_cdn/run_id=c-run/_manifest.json")
    assert all(k.startswith("downloads_cdn/run_id=c-run/") for k in keys)
    # the manifest is copied last
    cps = [c for c in env.calls() if "s3 cp" in c and BRONZE in c]
    assert cps[-1].endswith("_manifest.json --only-show-errors")
    # a repeat copies nothing new
    env.log.write_text("")
    again = collect(env)
    assert again.returncode == 0 and "0 part(s) copied, 2 already there" in again.stdout
    assert not [c for c in env.calls() if "s3 cp" in c and BRONZE in c]
    # a later log file is added on the next repeat, and the manifest is refreshed
    env.set_marker("cdn/EDIST/2026/11/26/07/c.json", bucket=LOGS)
    (env.state / "s3" / LOGS / "cdn/EDIST/2026/11/26/07/c.json").write_text(line() + "\n")
    third = collect(env)
    assert "1 part(s) copied, 2 already there" in third.stdout
    assert json.loads((env.state / "s3" / BRONZE / keys[0]).read_text())["files"] == 3


def test_collect_copies_nothing_for_a_field_outside_the_allowlist(env):
    bad = json.loads(line())
    bad["cs(User-Agent)"] = "agent"
    prepare(env, {"cdn/E/a.json": line() + "\n", "cdn/E/b.json": json.dumps(bad) + "\n"})
    proc = collect(env)
    assert proc.returncode != 0
    assert "Nothing was copied" in proc.stdout
    assert bronze_keys(env) == []
    assert "agent" not in proc.stdout + proc.stderr


def test_collect_copies_nothing_for_a_twelve_digit_path_or_value(env):
    prepare(env, {"cdn/E/" + ACCT + "/a.json": line() + "\n"})
    proc = collect(env)
    assert proc.returncode != 0 and bronze_keys(env) == []
    assert ACCT not in proc.stdout + proc.stderr
    env2_key = "cdn/E/ok.json"
    for p in (env.state / "s3" / LOGS).rglob("*.json"):
        p.unlink()
    prepare_extra = {env2_key: line(**{"x-edge-location": "ab" + ACCT}) + "\n"}
    for key, body in prepare_extra.items():
        env.set_marker(key, bucket=LOGS)
        (env.state / "s3" / LOGS / key).write_text(body)
    proc = collect(env)
    assert proc.returncode != 0 and bronze_keys(env) == []
    assert ACCT not in proc.stdout + proc.stderr


def test_collect_accepts_a_thirteen_digit_timestamp(env):
    prepare(env, {"cdn/E/a.json": line() + "\n"})
    assert collect(env).returncode == 0


def test_collect_without_a_log_bucket_exits_zero_and_says_why(env):
    rd = env.runs / "c-run"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(json.dumps({"window_start_ms": START, "window_end_ms": END}))
    proc = collect(env)
    assert proc.returncode == 0 and "only for a HOLD run" in proc.stdout


@pytest.mark.parametrize(
    "fail",
    ["s3api head-bucket", "s3api list-objects-v2", "sts get-caller-identity", "s3 cp s3://" + LOGS],
)
def test_collect_aws_failure_is_non_zero(env, fail):
    prepare(env, {"cdn/E/a.json": line() + "\n"})
    proc = collect(env, FAIL_AWS=fail)
    assert proc.returncode != 0 and bronze_keys(env) == []


def test_collect_input_errors(env):
    assert collect(env, "BAD_ID").returncode == 2
    assert collect(env, "no-record").returncode != 0
    assert env.calls() == [] or "get-caller-identity" not in "\n".join(env.calls())


def test_collect_upload_failure_never_writes_the_manifest(env):
    prepare(env, {"cdn/E/a.json": line() + "\n"})
    proc = collect(env, FAIL_AWS="s3 cp /")
    assert proc.returncode != 0
    assert not any(k.endswith("_manifest.json") for k in bronze_keys(env))


def test_cdn_filter_cli_exit_codes(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "0123456789abcdef").write_text(line() + "\n")
    ok = subprocess.run(
        [
            sys.executable, str(LAUNCH / "cdn_filter.py"), "--run-id", "r",
            "--start-ms", str(START), "--end-ms", str(END),
            "--in-dir", str(tmp_path / "in"), "--out-dir", str(tmp_path / "out"),
        ],
        capture_output=True, text=True,
    )  # fmt: skip
    assert ok.returncode == 0 and "lines=1" in ok.stdout


def record(env, run_id="c-run"):
    return json.loads((env.runs / run_id / "run.json").read_text())


def test_collect_sets_cdn_logs_collected_after_the_manifest(env):
    prepare(env, {"cdn/E/a.json": line() + "\n"})
    assert record(env)["cdn_logs_collected"] is False
    proc = collect(env)
    assert proc.returncode == 0, proc.stdout
    after = record(env)
    assert after["cdn_logs_collected"] is True
    assert after["window_start_ms"] == START  # the other fields stay
    assert list((env.runs / "c-run").iterdir()) == [env.runs / "c-run" / "run.json"]  # no temp left
    # a repeat keeps it true
    assert collect(env).returncode == 0 and record(env)["cdn_logs_collected"] is True


@pytest.mark.parametrize("fail", ["s3 cp /", "s3api list-objects-v2"])
def test_collect_failure_leaves_the_flag_false(env, fail):
    prepare(env, {"cdn/E/a.json": line() + "\n"})
    assert collect(env, FAIL_AWS=fail).returncode != 0
    assert record(env)["cdn_logs_collected"] is False


def test_collect_refusal_leaves_the_flag_false(env):
    prepare(env, {"cdn/E/a.json": line(**{"x-edge-location": "ab" + ACCT}) + "\n"})
    assert collect(env).returncode != 0 and record(env)["cdn_logs_collected"] is False


def test_collect_with_no_log_bucket_leaves_the_flag_false(env):
    rd = env.runs / "n-run"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(
        json.dumps({"window_start_ms": START, "window_end_ms": END, "cdn_logs_collected": False})
    )
    assert collect(env, "n-run").returncode == 0
    assert record(env, "n-run")["cdn_logs_collected"] is False


def test_collect_without_a_run_record_is_an_error(env):
    assert collect(env, "missing-run").returncode != 0
    assert not (env.runs / "missing-run").exists()


# --- cs-uri-stem is normalised, the window comes before the 12-digit scan ----

SHA = "0123456789" + ACCT[:2] + "a" * 52  # 64 hex characters
SHA12 = "a" * 20 + ACCT + "b" * 32  # a sha256 with a 12-digit run inside
assert len(SHA) == 64 and len(SHA12) == 64


def stem_of(stem):
    kept = cdn_filter.filter_text(line(**{"cs-uri-stem": stem}), FIELDS, START, END, "f")
    return json.loads(kept[0])["cs-uri-stem"]


def test_a_known_stem_with_a_twelve_digit_sha_passes_unchanged():
    for stem in (f"/build/{SHA12}.bin", f"/patch/{SHA12}.bin", f"/build/{SHA}.bin"):
        assert stem_of(stem) == stem
    for stem in (
        "/build/manifest.json",
        "/patch/manifest.json",
        "/patch/manifest-2.json",
        "/license",
    ):
        assert stem_of(stem) == stem


def test_any_other_stem_becomes_other_and_no_attack_path_is_kept():
    attack = [
        "/x/" + ACCT + "/y",
        "/" + ACCT,
        f"/build/{SHA12}.bin/" + ACCT,
        f"/build/{SHA12}.bin?x=" + ACCT,
        f"/build/{SHA12}.binx",
        f"/other/{SHA12}.bin",
        "/license/" + ACCT,
        "/build/main-1.bin",
        "",
    ]
    for stem in attack:
        assert stem_of(stem) == "/other", stem
    kept = cdn_filter.filter_text(line(**{"cs-uri-stem": "/x/" + ACCT}), FIELDS, START, END, "f")
    assert ACCT not in kept[0]


def test_an_out_of_window_bad_line_is_dropped_not_refused():
    text = "\n".join(
        [
            line(**{"timestamp(ms)": START - 1, "x-edge-location": "ab" + ACCT}),
            line(**{"timestamp(ms)": END + 1, "sc-bytes": int(ACCT)}),
            line(),
        ]
    )
    assert len(cdn_filter.filter_text(text, FIELDS, START, END, "f")) == 1


def test_out_of_window_lines_still_need_json_fields_and_a_timestamp():
    bad = json.loads(line(**{"timestamp(ms)": START - 1}))
    bad["c-ip"] = "203.0.113.9"
    for text in ("not json", json.dumps(bad), json.dumps({"sc-status": 200}),
                 line(**{"timestamp(ms)": "soon"})):  # fmt: skip
        with pytest.raises(cdn_filter.Refused):
            cdn_filter.filter_text(text, FIELDS, START, END, "f")


def test_twelve_digits_in_another_field_in_the_window_is_still_refused():
    for field in ("x-edge-location", "x-edge-result-type", "cs-method", "cs-protocol"):
        with pytest.raises(cdn_filter.Refused):
            cdn_filter.filter_text(line(**{field: "a" + ACCT + "b"}), FIELDS, START, END, "f")
