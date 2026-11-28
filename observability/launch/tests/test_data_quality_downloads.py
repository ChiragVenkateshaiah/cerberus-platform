"""17.5: the downloads data-quality suite against fake boto3 clients. No AWS, no network.

Every check has a test that makes it fail (a data violation), and the fail-closed
paths (Athena failure, unreadable manifest, zero days, missing table) are tested too.
"""

import io
import json
import re

import data_quality_downloads as dq
import pytest
import sqlglot

RUN = "dl-1000-20261126t100000z"
MANIFEST = {
    "run_id": RUN,
    "events": 30,
    "per_dt": {"2026-11-18": {"events": 10}, "2026-11-19": {"events": 20}},
}
CHECKS = [
    "bronze_to_silver_count",
    "event_id_unique",
    "lifecycle_valid",
    "bytes_in_range",
    "timestamps_in_window",
    "no_license_before_release",
    "gold_sessions_match_silver",
    "cdn_logs_present",
    "cdn_logs_complete",
    "no_account_or_arn_in_outputs",
]


class FakeS3:
    def __init__(self, manifest=MANIFEST, error=None):
        self.manifest, self.error, self.keys = manifest, error, []

    def get_object(self, Bucket, Key):  # noqa: N803 -- boto3's argument names
        self.keys.append(Key)
        if self.error:
            raise self.error
        return {"Body": io.BytesIO(json.dumps(self.manifest).encode())}


class FakeAthena:
    """respond(check_name, sql) -> None (violations 0), a number, or 'FAILED'."""

    def __init__(self, respond=lambda name, sql: None):
        self.respond, self.queries, self.by_id = respond, [], {}

    def start_query_execution(self, QueryString, WorkGroup, QueryExecutionContext):  # noqa: N803
        assert WorkGroup == "cerberus_platform_dq"
        name = re.search(r"/\* check:(\w+) \*/", QueryString).group(1)
        qid = f"q{len(self.queries)}"
        self.queries.append((name, QueryString))
        self.by_id[qid] = (name, QueryString)
        return {"QueryExecutionId": qid}

    def get_query_execution(self, QueryExecutionId):  # noqa: N803
        name, sql = self.by_id[QueryExecutionId]
        failed = self.respond(name, sql) == "FAILED"
        status = {"State": "FAILED" if failed else "SUCCEEDED", "StateChangeReason": "boom"}
        return {"QueryExecution": {"Status": status, "Statistics": {"DataScannedInBytes": 5}}}

    def get_query_results(self, QueryExecutionId):  # noqa: N803
        name, sql = self.by_id[QueryExecutionId]
        value = self.respond(name, sql) or 0
        rows = [{"Data": []}, {"Data": [{"VarCharValue": str(value)}, {"VarCharValue": "d"}]}]
        return {"ResultSet": {"Rows": rows}}


class FakeSession:
    def __init__(self, athena=None, s3=None):
        self.athena, self.s3 = athena or FakeAthena(), s3 or FakeS3()

    def client(self, name):
        return {"athena": self.athena, "s3": self.s3}[name]


def run(tmp_path, session=None, records=None, outputs=None, **kw):
    records_dir = tmp_path / "runs"
    records_dir.mkdir(exist_ok=True)
    for name, body in (records or {}).items():
        target = records_dir / name  # name is "<run_id>/run.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body if isinstance(body, str) else json.dumps(body))
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "run.log").write_text(outputs if outputs is not None else "clean log\n")
    return dq.run_suite(
        session or FakeSession(),
        RUN,
        "bronze-bucket",
        records_dir=records_dir,
        scan_paths=[out],
        poll_seconds=0,
        **kw,
    )


def by_name(suite):
    return {c["name"]: c for c in suite["checks"]}


def test_all_ten_checks_pass_on_clean_data(tmp_path):
    suite = run(tmp_path)
    assert [c["name"] for c in suite["checks"]] == CHECKS
    assert suite["passed"] and suite["errors"] == 0


def test_cdn_with_no_collected_record_says_skipped_not_passed_silently(tmp_path):
    check = by_name(run(tmp_path))["cdn_logs_present"]
    assert check["skipped"] is True
    assert check["detail"] == "skipped, telemetry only"


@pytest.mark.parametrize(
    "name",
    [
        "bronze_to_silver_count",
        "event_id_unique",
        "lifecycle_valid",
        "bytes_in_range",
        "timestamps_in_window",
        "no_license_before_release",
        "gold_sessions_match_silver",
    ],
)
def test_a_violation_fails_that_check_and_the_suite(tmp_path, name):
    athena = FakeAthena(lambda n, sql: 3 if n == name else None)
    suite = run(tmp_path, FakeSession(athena))
    assert not suite["passed"]
    assert [c["name"] for c in suite["checks"] if not c["passed"]] == [name]


@pytest.mark.parametrize("name", CHECKS[:7])
def test_an_athena_failure_fails_closed(tmp_path, name):
    athena = FakeAthena(lambda n, sql: "FAILED" if n == name else None)
    suite = run(tmp_path, FakeSession(athena))
    check = by_name(suite)[name]
    assert not suite["passed"] and not check["passed"]
    assert check["violations"] is None and "FAILED" in check["detail"]


def test_a_missing_table_fails_check_seven(tmp_path):
    athena = FakeAthena(lambda n, sql: "FAILED" if "fct_download_sessions" in sql else None)
    suite = run(tmp_path, FakeSession(athena))
    assert not by_name(suite)["gold_sessions_match_silver"]["passed"]


def test_unreadable_manifest_fails_check_one_and_runs_nothing_for_it(tmp_path):
    athena = FakeAthena()
    suite = run(tmp_path, FakeSession(athena, FakeS3(error=OSError("denied"))))
    check = by_name(suite)["bronze_to_silver_count"]
    assert not check["passed"] and "manifest unreadable" in check["detail"]
    assert "bronze_to_silver_count" not in [n for n, _ in athena.queries]
    assert not suite["passed"]


@pytest.mark.parametrize(
    "manifest",
    [
        {"run_id": RUN, "events": 0, "per_dt": {}},
        {"run_id": RUN},
        {"run_id": RUN, "per_dt": {"2026-11-19": {"events": 0}}},
        {"run_id": RUN, "per_dt": {"not-a-day": {"events": 5}}},
        {"run_id": RUN, "per_dt": {"2026-11-19": "x"}},
    ],
)
def test_zero_days_or_a_bad_manifest_entry_fails(tmp_path, manifest):
    suite = run(tmp_path, FakeSession(s3=FakeS3(manifest)))
    assert not by_name(suite)["bronze_to_silver_count"]["passed"]


def test_every_bronze_query_pins_run_id_and_dt(tmp_path):
    athena = FakeAthena()
    run(tmp_path, FakeSession(athena))
    bronze = [sql for n, sql in athena.queries if "bronze_downloads_bulk_by_run" in sql]
    assert len(bronze) == 2  # one per manifest day
    for sql in bronze:
        assert f"run_id = '{RUN}' AND dt = '" in sql
    assert any("dt = '2026-11-18'" in s for s in bronze)


def test_cdn_check_fails_when_a_record_says_collected_and_rows_are_absent(tmp_path):
    record = {"run_id": "sess-1", "cdn_logs_collected": True}
    athena = FakeAthena(lambda n, sql: 1 if n == "cdn_logs_present" else None)
    suite = run(tmp_path, FakeSession(athena), records={"sess-1/run.json": record})
    check = by_name(suite)["cdn_logs_present"]
    # Decision 13: a warning, visible, never a plain pass, and it does not fail the suite.
    assert check["status"] == "warning" and check["severity"] == "warning"
    assert not check["passed"] and "skipped" not in check
    assert suite["passed"] and suite["errors"] == 0 and suite["warnings"] >= 1
    assert "'sess-1'" in [sql for n, sql in athena.queries if n == "cdn_logs_present"][0]


def test_cdn_check_passes_when_collected_and_rows_exist(tmp_path):
    record = {"run_id": "sess-1", "cdn_logs_collected": True}
    suite = run(tmp_path, records={"sess-1/run.json": record})
    assert by_name(suite)["cdn_logs_present"]["passed"]
    assert "skipped" not in by_name(suite)["cdn_logs_present"]


def test_cdn_check_fails_on_an_unreadable_record(tmp_path):
    suite = run(tmp_path, records={"bad/run.json": "{not json"})
    for name in ("cdn_logs_present", "cdn_logs_complete"):
        assert by_name(suite)[name]["status"] == "fail"
    assert not suite["passed"]
    assert dq.print_suite(suite) is None


# The shape of 17.4's real record (launch_session.sh collect_results), with the key
# launch_collect.sh adds after its manifest upload.
RECORD_17_4 = {
    "run_id": "sess-1",
    "scenario": "ramp",
    "minutes": 30,
    "hold": False,
    "window_start_ms": 1_764_151_200_000,
    "window_end_ms": 1_764_153_000_000,
    "planned_gb": "12.5",
    "budget_bytes": 1000000000,
    "release_at_epoch": 1764151,
}


def test_17_4_record_without_the_key_is_not_collected(tmp_path):
    check = by_name(run(tmp_path, records={"sess-1/run.json": RECORD_17_4}))["cdn_logs_present"]
    assert check["skipped"] is True and check["passed"]


def test_17_4_record_with_the_key_true_is_checked_and_fails_with_zero_rows(tmp_path):
    record = {**RECORD_17_4, "cdn_logs_collected": True}
    athena = FakeAthena(lambda n, sql: 1 if n == "cdn_logs_present" else None)
    suite = run(tmp_path, FakeSession(athena), records={"sess-1/run.json": record})
    assert by_name(suite)["cdn_logs_present"]["status"] == "warning"
    assert suite["passed"]


def test_17_4_record_with_the_key_false_is_skipped(tmp_path):
    record = {**RECORD_17_4, "cdn_logs_collected": False}
    check = by_name(run(tmp_path, records={"sess-1/run.json": record}))["cdn_logs_present"]
    assert check["skipped"] is True


@pytest.mark.parametrize("value", ["true", 1, None, "yes", [], {}])
def test_a_non_boolean_cdn_logs_collected_fails_closed(tmp_path, value):
    record = {**RECORD_17_4, "cdn_logs_collected": value}
    check = by_name(run(tmp_path, records={"sess-1/run.json": record}))["cdn_logs_present"]
    assert not check["passed"] and "not a boolean" in check["detail"]


def test_a_flat_record_outside_a_run_directory_is_not_read(tmp_path):
    # Records live at runs/<run_id>/run.json; a stray runs/x.json is not one.
    check = by_name(run(tmp_path, records={"x.json": {"run_id": "a", "cdn_logs_collected": True}}))[
        "cdn_logs_present"
    ]
    assert check["skipped"] is True


def test_cdn_models_missing_fails_the_check(tmp_path):
    # Athena says fct_cdn_requests does not exist: a FAILED query is a FAIL.
    record = {**RECORD_17_4, "cdn_logs_collected": True}
    athena = FakeAthena(lambda n, sql: "FAILED" if n == "cdn_logs_present" else None)
    suite = run(tmp_path, FakeSession(athena), records={"sess-1/run.json": record})
    assert not by_name(suite)["cdn_logs_present"]["passed"]


def test_cdn_check_fails_on_a_collected_record_without_run_id(tmp_path):
    suite = run(tmp_path, records={"x/run.json": {"cdn_logs_collected": True}})
    assert not by_name(suite)["cdn_logs_present"]["passed"]


@pytest.mark.parametrize(
    "text", ["bucket 123456789012 here", "arn:aws:iam::x:role/y", "account=123456789012"]
)
def test_an_account_number_or_arn_in_an_output_fails_check_nine(tmp_path, text):
    suite = run(tmp_path, outputs=text)
    assert not by_name(suite)["no_account_or_arn_in_outputs"]["passed"]
    assert not suite["passed"]


def test_a_13_digit_epoch_is_not_an_account_number(tmp_path):
    suite = run(tmp_path, outputs="ts " + "1764" + "151200" + "000\n")
    assert by_name(suite)["no_account_or_arn_in_outputs"]["passed"]


def test_nothing_to_scan_and_a_missing_explicit_path_both_fail(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert dq.scan_check([str(empty)], set(), "")["result"]["violations"] is None
    result = dq.scan_check([str(tmp_path / "gone")], {str(tmp_path / "gone")}, "")["result"]
    assert result["violations"] is None


def test_a_suite_result_with_an_account_number_in_a_detail_fails_check_nine(tmp_path):
    class Leaky(FakeAthena):
        def get_query_results(self, QueryExecutionId):  # noqa: N803
            rows = [
                {"Data": []},
                {"Data": [{"VarCharValue": "0"}, {"VarCharValue": "x 123456789012"}]},
            ]
            return {"ResultSet": {"Rows": rows}}

    suite = run(tmp_path, FakeSession(Leaky()))
    assert not by_name(suite)["no_account_or_arn_in_outputs"]["passed"]


def test_a_bad_run_id_is_refused_before_any_query():
    with pytest.raises(ValueError):
        dq.run_suite(FakeSession(), "x'; drop", "b")


def test_main_exit_codes_and_json_out(tmp_path, capsys):
    out_file = tmp_path / "result.json"
    base = ["--run-id", RUN, "--bronze-bucket", "b", "--records-dir", str(tmp_path / "runs"),
            "--scan", str(tmp_path / "scan"), "--json-out", str(out_file)]  # fmt: skip
    (tmp_path / "scan").mkdir()
    (tmp_path / "scan" / "a.log").write_text("ok\n")
    assert dq.main(base, session=FakeSession()) == 0
    assert json.loads(out_file.read_text())["passed"] is True
    bad = FakeSession(FakeAthena(lambda n, sql: 2 if n == "event_id_unique" else None))
    assert dq.main(base, session=bad) == 3


def test_main_fails_closed_when_the_suite_cannot_run(tmp_path):
    class Broken:
        def client(self, name):
            raise RuntimeError("no credentials")

    argv = ["--run-id", RUN, "--bronze-bucket", "b"]
    assert dq.main(argv, session=Broken()) == 3


def test_every_query_parses_as_trino(tmp_path):
    athena = FakeAthena()
    record = {"run_id": "sess-1", "cdn_logs_collected": True, "k6_requests": 10}
    run(tmp_path, FakeSession(athena), records={"s/run.json": record})
    assert {n for n, _ in athena.queries} == set(CHECKS[:9])
    for name, sql in athena.queries:
        assert sqlglot.parse_one(sql, read="trino"), name


def test_constants_match_the_generator():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(dq.__file__).resolve().parents[2] / "transform" / "spark"))
    import calendar
    import time

    import generate_bulk_downloads as g

    def ms(text):
        return calendar.timegm(time.strptime(text, "%Y-%m-%d %H:%M:%S")) * 1000

    assert ms(dq.WINDOW_START) == g.WINDOW_START_MS
    assert ms(dq.WINDOW_END) == g.WINDOW_END_MS
    assert ms(dq.RELEASE_UTC) == g.RELEASE_UTC_MS
    assert dq.TITLE_BYTES == g.TITLE_BYTES
    assert dq.EVENT_TYPES == g.TYPES


# cdn_logs_complete (ADR 0030 Decision 13): log lines versus the k6 count, 99% line.
def complete_run(tmp_path, lines, k6="absent", collected=True):
    record = {**RECORD_17_4, "cdn_logs_collected": collected}
    if k6 != "absent":
        record["k6_requests"] = k6

    def respond(name, sql):
        if name != "cdn_logs_complete":
            return None
        wanted = int(re.search(r"< 99 \* (\d+)", sql).group(1))
        return 1 if lines * 100 < 99 * wanted else 0

    athena = FakeAthena(respond)
    suite = run(tmp_path, FakeSession(athena), records={"sess-1/run.json": record})
    return suite, by_name(suite)["cdn_logs_complete"], athena


def test_logs_complete_when_all_lines_are_there(tmp_path):
    suite, check, _ = complete_run(tmp_path, lines=1000, k6=1000)
    assert check["status"] == "complete" and check["passed"]
    assert suite["passed"]


def test_logs_at_98_9_percent_are_partial_and_a_warning_only(tmp_path):
    suite, check, _ = complete_run(tmp_path, lines=989, k6=1000)
    assert check["status"] == "partial" and check["severity"] == "warning"
    assert not check["passed"]
    assert suite["passed"] and suite["errors"] == 0 and suite["warnings"] == 1


def test_logs_at_exactly_99_percent_are_complete(tmp_path):
    _, check, _ = complete_run(tmp_path, lines=990, k6=1000)
    assert check["status"] == "complete"


def test_a_missing_k6_count_is_unknown_never_complete(tmp_path):
    suite, check, athena = complete_run(tmp_path, lines=1000)
    assert check["status"] == "unknown" and not check["passed"]
    assert "sess-1" in check["detail"]
    assert not [n for n, _ in athena.queries if n == "cdn_logs_complete"]
    assert suite["passed"]  # a warning, not a failure


@pytest.mark.parametrize("k6", ["1000", 0, -5, 12.5, True, None])
def test_a_bad_k6_count_is_unknown(tmp_path, k6):
    _, check, _ = complete_run(tmp_path, lines=1000, k6=k6)
    assert check["status"] == "unknown"


def test_complete_is_skipped_with_no_collected_record(tmp_path):
    check = by_name(run(tmp_path))["cdn_logs_complete"]
    assert check["status"] == "skipped"


def test_a_failed_complete_query_fails_closed(tmp_path):
    record = {**RECORD_17_4, "cdn_logs_collected": True, "k6_requests": 10}
    athena = FakeAthena(lambda n, sql: "FAILED" if n == "cdn_logs_complete" else None)
    suite = run(tmp_path, FakeSession(athena), records={"sess-1/run.json": record})
    assert by_name(suite)["cdn_logs_complete"]["status"] == "fail"
    assert not suite["passed"]


def test_warnings_do_not_change_the_exit_code(tmp_path, capsys):
    records = tmp_path / "runs" / "sess-1"
    records.mkdir(parents=True)
    (records / "run.json").write_text(json.dumps({**RECORD_17_4, "cdn_logs_collected": True}))
    out = tmp_path / "out"
    out.mkdir()
    (out / "run.log").write_text("clean\n")
    session = FakeSession(FakeAthena(lambda n, sql: 1 if n == "cdn_logs_present" else None))
    argv = ["--run-id", RUN, "--bronze-bucket", "b", "--records-dir", str(tmp_path / "runs")]
    argv += ["--scan", str(out)]
    assert dq.main(argv, session=session) == 0
    assert "WARN" in capsys.readouterr().out


def test_scan_ignores_decimal_fractions_and_masked_arns():
    # k6 timings and masked exercise-log ARNs hold no account (Run A, 2026-11-27).
    assert dq.scan_text('"p(99)": 132.123456789012, "avg": 0.123456789012') == 0
    assert dq.scan_text("identity: arn:aws:iam::<ACCOUNT_ID>:user/cerberus-admin") == 0
    assert dq.scan_text("arn:aws:s3:::cerberus-platform-launch-x/k") == 0
    assert dq.scan_text("arn:aws:iam::aws:policy/AmazonEKSClusterPolicy") == 0
    assert dq.scan_text('"window_start_ms": 1795775501234') == 0


def test_scan_still_counts_real_accounts_and_arns():
    assert dq.scan_text("account 123456789012 here") == 1
    assert dq.scan_text("arn:aws:iam::123456789012:user/x") == 1
    assert dq.scan_text("arn:aws:logs:us-east-1:123456789012:log-group:x") == 1
    assert dq.scan_text("1.5 then 123456789012") == 1
    assert dq.scan_text("arn:aws:iam::x:role/y") == 1
    after_a_dot = ["x.123456789012", "role.123456789012", "host.123456789012.example", ".123456789012"]
    for text in after_a_dot:
        assert dq.scan_text(text) == 1, text
