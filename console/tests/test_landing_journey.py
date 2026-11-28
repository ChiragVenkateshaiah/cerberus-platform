"""The journey data (9.4b): each value equals its record field; nothing raw gets out."""

import dataclasses
import json
import re

import hostile
import pytest
from landing_helpers import FIXTURE_RUNS, REAL_RUNS

from cerberus_console import config
from cerberus_landing import journey, runs
from cerberus_landing.showcase import scan_text

ONE_M = "exercise-20261015T145812Z"
TEN_M = "exercise-20261009T074853Z"
HUNDRED_M = "exercise-20261013T055859Z"
NAMES = (ONE_M, TEN_M, HUNDRED_M)
STATES = ("InvokeIngestion", "RunTransform", "RunDbt", "RunServingQuery")
HOSTILE_FILE = FIXTURE_RUNS / "hostile-20990101T000000Z.json"
ARRIVE, CLEAN, MODEL, ANSWER = STATES
# Written out here on purpose: a change of station or words must change both.
CHECK_TABLE = {
    "bronze_ledger": (ARRIVE, "The raw file list and the generator manifests could be read"),
    "bulk_ledger_integrity": (
        ARRIVE,
        "Pre-written generator data: file counts and byte totals match the manifests",
    ),
    "bulk_runs_without_manifest": (
        ARRIVE,
        "No pre-written generator batch is missing its manifest",
    ),
    "bulk_duplicate_keys": (
        ARRIVE,
        "Pre-written generator data: no payment has the same event type twice",
    ),
    "bulk_run_counts": (
        ARRIVE,
        "Pre-written generator data: this batch's per-day counts match the generator's report",
    ),
    "bronze_to_silver_count": (
        CLEAN,
        "The raw data and the clean table hold the same number of events",
    ),
    "bronze_to_silver_keys": (CLEAN, "Every raw event is in the clean table, and no others"),
    "silver_caught_up": (CLEAN, "No raw file is newer than the cleaning job's last read mark"),
    "lambda_keys_in_silver": (CLEAN, "Every small-batch event is in the clean table"),
    "new_run": (
        CLEAN,
        "Each day of the new generator batch matches its manifest count, "
        "has no repeats and is in the clean table",
    ),
    "silver_duplicate_keys": (CLEAN, "No payment has the same event type twice"),
    "lifecycle_created_authorized": (
        CLEAN,
        "Every payment has exactly one created and one authorized event",
    ),
    "lifecycle_one_terminal": (CLEAN, "Every payment settled or failed, exactly one of the two"),
    "lifecycle_refunds": (CLEAN, "Only settled payments have a refund, and at most one each"),
    "lifecycle_order": (CLEAN, "No payment step is dated earlier than the step before it"),
    "silver_key_nulls": (CLEAN, "No required field is missing"),
    "amount_range_and_stability": (
        CLEAN,
        "Amounts are in range; amount, currency, merchant, customer and token "
        "stay the same within a payment",
    ),
    "roster": (CLEAN, "Merchant and customer counts are within limits, and no ID has two names"),
    "masking": (CLEAN, "Emails are test addresses; cards show a brand and last four digits only"),
    "token_format": (CLEAN, "Payment tokens have the expected format"),
    "token_digit_runs": (CLEAN, "No payment token holds a run of 13 or more digits"),
    "silver_to_gold_transactions": (
        MODEL,
        "The business table and the clean table hold the same payments",
    ),
    "gold_status_matches_lifecycle": (
        MODEL,
        "Each payment status matches that payment's recorded events",
    ),
}
WARNING_TABLE = {
    "token_digit_runs": (
        "Some payment tokens hold a run of 13 or more digits, which a data-leak "
        "scanner could read as card numbers. The check only warns, because older "
        "tokens with this pattern are accepted."
    ),
}
LEAKS = (
    "arn:aws:states:us-east-1:123456789012:execution:x",
    "s3://some-bucket/key",
    "name@example.org",
    "host.cloudfront.net",
    "x.amazonaws.com",
    "123456789012",
    "PWNED",
)


def raw(execution: str) -> dict:
    return json.loads((REAL_RUNS / f"{execution}.json").read_text(encoding="utf-8"))


def write(directory, execution: str, rec) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = rec if isinstance(rec, str) else json.dumps(rec)
    (directory / f"{execution}.json").write_text(text, encoding="utf-8")


def runs_dir_with(tmp_path, change=None, target=HUNDRED_M):
    """The 3 real records in a temp directory, one of them changed in place."""
    d = tmp_path / "runs"
    for name in NAMES:
        rec = raw(name)
        if change is not None and name == target:
            change(rec)
        write(d, name, rec)
    return d


def by_name(result) -> dict:
    return {r.execution: r for r in result}


def stations(run) -> dict:
    return {s.name: s for s in run.stations}


def strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def fixed_strings() -> set[str]:
    out = set(journey.STATION_NAMES) | {journey.SPARK_BYTES, journey.ATHENA_BYTES}
    out |= {text for pair in runs.STATES for text in pair}
    out |= {label for totals in journey.TOTALS.values() for label, _ in totals}
    out |= {words for _, words in CHECK_TABLE.values()}
    out |= set(WARNING_TABLE.values())
    out |= {text for pair in journey.RUNS for text in pair}
    out |= {f"{name}.json" for name, _ in journey.RUNS}
    return out


def assert_clean(result) -> None:
    docs = [dataclasses.asdict(r) for r in result]
    text = json.dumps(docs, ensure_ascii=False)
    assert scan_text(text) == []
    for leak in LEAKS:
        assert leak not in text
    allowed = fixed_strings()
    date = re.compile(r"\d{1,2} [A-Z][a-z]+ \d{4} \(UTC\)|date not recorded")
    for s in strings(docs):
        assert s in allowed or date.fullmatch(s), repr(s)


def test_the_three_fixed_runs_in_order_with_one_featured():
    result = journey.load(REAL_RUNS)
    assert [r.execution for r in result] == list(NAMES)
    assert [r.size for r in result] == ["1M", "10M", "100M"]
    assert [r.execution for r in result if r.featured] == [HUNDRED_M]
    for r in result:
        assert [s.name for s in r.stations] == ["Arrive", "Clean", "Model", "Answer"]
        assert [s.state for s in r.stations] == list(STATES)
        assert [(s.state, s.label) for s in r.stations] == list(runs.STATES)


@pytest.mark.parametrize("execution", NAMES)
def test_run_values_equal_the_record(execution):
    rec = raw(execution)
    run = by_name(journey.load(REAL_RUNS))[execution]
    assert run.events == rec["events_processed"]
    assert run.run_seconds == rec["run_seconds"]
    assert run.cost_usd == rec["cost"]["run_usd"]
    assert run.cost_usd_per_million_events == rec["cost"]["usd_per_million_events"]
    assert run.cost_estimated is rec["cost"]["estimated"]
    assert run.cost_complete is rec["cost"]["complete"]
    assert run.date == runs.format_date(rec["start"])
    assert run.file_name == f"{execution}.json"
    assert (REAL_RUNS / run.file_name).is_file()
    assert run.unknown_checks == 0
    assert run.peak_series == rec["prometheus"]["peak_active_series"]


@pytest.mark.parametrize("execution", NAMES)
def test_station_values_equal_the_record(execution):
    rec = raw(execution)
    states = {s["state"]: s for s in rec["states"]}
    got = stations(by_name(journey.load(REAL_RUNS))[execution])
    for station, state in zip(("Arrive", "Clean", "Model", "Answer"), STATES, strict=True):
        assert got[station].seconds == states[state]["seconds"]
        assert got[station].share == states[state]["seconds"] / rec["run_seconds"]

    # No Athena query ran in these two states, so their zeros are not figures.
    for station, state in (("Arrive", STATES[0]), ("Clean", STATES[1])):
        assert states[state]["athena"]["queries"] == 0
        assert got[station].queue_seconds is None
        assert got[station].engine_seconds is None
    assert (got["Arrive"].bytes_read, got["Arrive"].bytes_source) == (None, None)
    spark = rec["prometheus"]["spark"]["cerberus-promote-payments"]
    assert got["Clean"].bytes_read == spark["spark_input_bytes"]
    assert got["Clean"].bytes_source == "Spark input"
    for station, state in (("Model", STATES[2]), ("Answer", STATES[3])):
        athena = states[state]["athena"]
        assert got[station].bytes_read == athena["bytes_scanned"]
        assert got[station].bytes_source == "Athena scanned"
        assert got[station].queue_seconds == athena["queue_seconds"]
        assert got[station].engine_seconds == athena["engine_seconds"]

    totals = {name: [(t.label, t.value) for t in s.totals] for name, s in got.items()}
    assert totals == {
        "Arrive": [("Bronze events", None)],
        "Clean": [
            ("Silver events", rec["silver"]["events"]),
            ("Silver transactions", rec["silver"]["transactions"]),
        ],
        "Model": [
            ("Gold rows", None),
            ("Gold stored bytes", rec["storage_snapshot"]["gold"]["bytes"]),
        ],
        "Answer": [],
    }


def test_the_check_table():
    assert journey.CHECKS == CHECK_TABLE
    assert journey.WARNINGS == WARNING_TABLE
    # A warned check is one the suite sets to "warn"; its words differ from the pass words.
    assert set(WARNING_TABLE) <= set(CHECK_TABLE)
    for name, words in WARNING_TABLE.items():
        assert CHECK_TABLE[name][1] not in words


@pytest.mark.parametrize("execution", NAMES)
def test_checks_follow_the_record(execution):
    entries = raw(execution)["data_quality"]["checks"]
    results: dict[str, list[bool]] = {}
    for c in entries:
        results.setdefault(c["name"].split("[")[0], []).append(c["passed"])
    run = by_name(journey.load(REAL_RUNS))[execution]
    for s in run.stations:
        here = {n: all(v) for n, v in results.items() if CHECK_TABLE[n][0] == s.state}
        assert sorted(s.checks_passed) == sorted(CHECK_TABLE[n][1] for n, ok in here.items() if ok)
        assert s.checks_warned == sum(not ok for ok in here.values())
    got = stations(run)
    # The accepted token warning is the one check that did not pass in these runs.
    assert [s.checks_warned for s in run.stations] == [0, 1, 0, 0]
    assert CHECK_TABLE["token_digit_runs"][1] not in got["Clean"].checks_passed
    assert [s.warnings for s in run.stations] == [
        (),
        (WARNING_TABLE["token_digit_runs"],),
        (),
        (),
    ]
    assert got["Answer"].checks_passed == ()


def test_the_1m_queue_time_is_kept_apart_from_its_duration():
    model = stations(by_name(journey.load(REAL_RUNS))[ONE_M])["Model"]
    assert (model.seconds, model.queue_seconds) == (286.7, 230.5)


def test_check_words_are_unique_and_clean():
    words = [w for _, w in CHECK_TABLE.values()]
    assert len(set(words)) == len(words)
    assert scan_text("\n".join(words)) == []


def test_the_result_is_deterministic():
    assert journey.load(REAL_RUNS) == journey.load(REAL_RUNS)
    assert_clean(journey.load(REAL_RUNS))


def test_an_unknown_check_name_is_counted_not_kept(tmp_path):
    def change(rec):
        rec["data_quality"]["checks"] += [
            {"name": "PWNED_check", "passed": True},
            {"name": "PWNED[dt=2026-10-01]", "severity": "warn", "passed": False},
            {"name": ["PWNED"], "passed": True},
            {"passed": True},
        ]

    result = journey.load(runs_dir_with(tmp_path, change))
    run = by_name(result)[HUNDRED_M]
    assert run.unknown_checks == 4
    real = by_name(journey.load(REAL_RUNS))[HUNDRED_M]
    assert run.stations == real.stations
    assert_clean(result)


def assert_a_check_failed(tmp_path, change):
    with pytest.raises(journey.JourneyError, match="a data check failed") as err:
        journey.load(runs_dir_with(tmp_path, change))
    assert HUNDRED_M in str(err.value)
    assert "PWNED" not in str(err.value)


def first_check(rec, prefix: str) -> dict:
    return next(c for c in rec["data_quality"]["checks"] if c["name"].startswith(prefix))


NOT_PASSED = ({}, {"passed": False}, {"passed": "true"}, {"passed": 1}, {"passed": None})


@pytest.mark.parametrize("passed", NOT_PASSED)
@pytest.mark.parametrize("prefix", ["masking", "new_run["])
def test_an_error_check_that_did_not_pass_fails_the_load(tmp_path, prefix, passed):
    def change(rec):
        check = first_check(rec, prefix)
        del check["passed"]
        check.update(passed)

    assert_a_check_failed(tmp_path, change)


@pytest.mark.parametrize("severity", [{}, {"severity": "WARN"}, {"severity": "warning"}])
def test_only_the_exact_severity_warn_is_a_warning(tmp_path, severity):
    def change(rec):
        check = first_check(rec, "masking")
        del check["severity"]
        check.update(severity, passed=False)

    assert_a_check_failed(tmp_path, change)


@pytest.mark.parametrize(
    "entry",
    [
        # As data_quality.py writes it when it cannot read the ledger.
        {"name": "bronze_ledger", "severity": "error", "violations": None, "passed": False},
        {"name": "PWNED_check", "severity": "error", "passed": False},
        {"name": "PWNED_check", "passed": False},
        {"severity": "error", "passed": False},
        "PWNED",
    ],
)
def test_a_failed_entry_of_any_name_fails_the_load(tmp_path, entry):
    def change(rec):
        rec["data_quality"]["checks"].append(entry)

    assert_a_check_failed(tmp_path, change)


def test_the_ledger_check_is_a_known_name(tmp_path):
    def change(rec):
        rec["data_quality"]["checks"].append(
            {"name": "bronze_ledger", "severity": "error", "passed": True}
        )

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    assert run.unknown_checks == 0
    assert CHECK_TABLE["bronze_ledger"][1] in stations(run)["Arrive"].checks_passed


@pytest.mark.parametrize("passed", NOT_PASSED)
def test_one_warned_day_means_the_grouped_check_is_a_warning(tmp_path, passed):
    def change(rec):
        check = first_check(rec, "new_run[")
        del check["passed"]
        check.update(passed, severity="warn")

    clean = stations(by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M])["Clean"]
    assert CHECK_TABLE["new_run"][1] not in clean.checks_passed
    assert clean.checks_warned == 2
    # The new-batch check has no warning words, so it is counted and not described.
    assert clean.warnings == (WARNING_TABLE["token_digit_runs"],)


@pytest.mark.parametrize("status", [None, "FAILED", "RUNNING", "succeeded", ["PWNED"]])
def test_a_run_that_did_not_succeed_fails(tmp_path, status):
    def change(rec):
        rec["status"] = status

    with pytest.raises(journey.JourneyError, match="did not succeed") as err:
        journey.load(runs_dir_with(tmp_path, change))
    assert "PWNED" not in str(err.value)


def test_bulk_follows_the_generator_entry(tmp_path):
    assert [r.bulk for r in journey.load(REAL_RUNS)] == [True, True, True]
    for i, generator in enumerate((None, "PWNED", [])):

        def change(rec, value=generator):
            rec["generator"] = value

        d = runs_dir_with(tmp_path / str(i), change)
        assert by_name(journey.load(d))[HUNDRED_M].bulk is False


def test_the_hostile_fixture_leaks_nothing(tmp_path):
    d = tmp_path / "runs"
    for name in NAMES:
        rec = json.loads(HOSTILE_FILE.read_text(encoding="utf-8"))
        rec["execution"] = name
        write(d, name, rec)
    assert_clean(journey.load(d))


def test_hostile_text_in_every_field_leaks_nothing(tmp_path):
    # Cut long strings: a record over config.MAX_RECORD_BYTES is refused outright.
    bad = [*(s[:300] for s in hostile.DATA_STRINGS if s), *LEAKS]

    def poison(value, text):
        if isinstance(value, dict):
            return {k: poison(v, text) for k, v in value.items()}
        if isinstance(value, list):
            return [poison(v, text) for v in value]
        return text

    for i, text in enumerate(bad):
        d = tmp_path / str(i)
        for name in NAMES:
            rec = raw(name)
            states = [
                {key: (v if key == "state" else poison(v, text)) for key, v in st.items()}
                for st in rec["states"]
            ]
            rec = {k: (v if k == "execution" else poison(v, text)) for k, v in rec.items()}
            rec["states"] = states
            rec[text] = text
            rec["status"] = "SUCCEEDED"  # any other value stops the load
            rec["data_quality"] = {
                "checks": [
                    {
                        "name": text,
                        "severity": "warn",
                        "passed": text,
                        "about": text,
                        "detail": text,
                    },
                    {"name": f"masking[dt={text}]", "passed": True, "detail": text},
                ]
            }
            write(d, name, rec)
        result = journey.load(d)
        assert_clean(result)
        for run in result:
            assert run.events is None and run.run_seconds is None
            assert all(s.seconds is None and s.bytes_read is None for s in run.stations)


def test_missing_values_are_none(tmp_path):
    def change(rec):
        for key in (
            "events_processed",
            "run_seconds",
            "start",
            "silver",
            "storage_snapshot",
            "prometheus",
            "cost",
            "data_quality",
            "generator",
        ):
            del rec[key]
        rec["states"] = [s for s in rec["states"] if s["state"] != "RunDbt"]
        del rec["states"][-1]["athena"]

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    assert run.events is None and run.run_seconds is None
    assert run.cost_usd is None and run.cost_usd_per_million_events is None
    assert run.cost_complete is None and run.cost_estimated is True
    assert run.date == "date not recorded"
    assert run.unknown_checks is None
    assert run.peak_series is None
    assert run.bulk is False
    for s in run.stations:
        assert s.share is None
        assert s.bytes_read is None and s.bytes_source is None
        assert s.queue_seconds is None and s.engine_seconds is None
        assert s.checks_passed is None and s.checks_warned is None
        assert s.warnings is None
        assert all(t.value is None for t in s.totals)
    assert stations(run)["Model"].seconds is None
    assert stations(run)["Clean"].seconds == 511.6


def set_every_number(rec, value) -> None:
    for key in ("events_processed", "run_seconds"):
        rec[key] = value
    rec["silver"] = {"events": value, "transactions": value}
    rec["storage_snapshot"]["gold"]["bytes"] = value
    rec["prometheus"]["spark"][journey.SPARK_APP]["spark_input_bytes"] = value
    rec["prometheus"]["peak_active_series"] = value
    rec["cost"]["run_usd"] = rec["cost"]["usd_per_million_events"] = value
    for st in rec["states"]:
        st["seconds"] = value
        st["athena"].update(
            queries=1, bytes_scanned=value, queue_seconds=value, engine_seconds=value
        )


def counts_of(run):
    out = [run.events, run.peak_series]
    for s in run.stations:
        out += [s.bytes_read, *(t.value for t in s.totals)]
    return out


def measures_of(run):
    out = [run.run_seconds, run.cost_usd, run.cost_usd_per_million_events]
    for s in run.stations:
        out += [s.seconds, s.queue_seconds, s.engine_seconds]
    return out


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "12",
        True,
        float("nan"),
        float("inf"),
        float("-inf"),
        -1,
        -0.5,
        10**15 + 1,
        1e300,
        10**400,
    ],
)
def test_a_value_that_is_not_a_usable_number_is_none(tmp_path, bad):
    d = runs_dir_with(tmp_path, lambda rec: set_every_number(rec, bad))
    run = by_name(journey.load(d))[HUNDRED_M]
    assert all(v is None for v in counts_of(run) + measures_of(run))
    assert all(s.share is None and s.bytes_source is None for s in run.stations)


@pytest.mark.parametrize("value", [1.5, 2.0])
def test_a_count_or_byte_figure_must_be_an_integer(tmp_path, value):
    d = runs_dir_with(tmp_path, lambda rec: set_every_number(rec, value))
    run = by_name(journey.load(d))[HUNDRED_M]
    assert all(v is None for v in counts_of(run))
    assert all(v == value for v in measures_of(run))


@pytest.mark.parametrize("value", [0, 10**15])
def test_the_limits_themselves_are_figures(tmp_path, value):
    d = runs_dir_with(tmp_path, lambda rec: set_every_number(rec, value))
    run = by_name(journey.load(d))[HUNDRED_M]
    assert run.events == value and run.run_seconds == value
    assert stations(run)["Model"].bytes_read == value


def test_a_state_longer_than_the_run_has_no_share(tmp_path):
    def change(rec):
        rec["run_seconds"] = 100

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    got = stations(run)
    assert got["Clean"].seconds == 511.6 and got["Clean"].share is None
    assert got["Arrive"].share == 4.2 / 100


@pytest.mark.parametrize("start", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
def test_a_start_outside_the_utc_calendar_is_not_recorded(tmp_path, start):
    def change(rec):
        rec["start"] = start

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    assert run.date == "date not recorded"


@pytest.mark.parametrize("estimated", [False, True, "false", 0, None])
def test_only_a_false_estimated_flag_drops_the_label(tmp_path, estimated):
    def change(rec):
        rec["cost"]["estimated"] = estimated

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    assert run.cost_estimated is (estimated is not False)


def test_zero_run_seconds_gives_no_share(tmp_path):
    def change(rec):
        rec["run_seconds"] = 0

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    assert all(s.share is None for s in run.stations)


def test_a_cost_that_is_not_final_shows_no_figure(tmp_path):
    def change(rec):
        rec["cost"]["complete"] = False

    run = by_name(journey.load(runs_dir_with(tmp_path, change)))[HUNDRED_M]
    assert run.cost_complete is False
    assert run.cost_usd is None and run.cost_usd_per_million_events is None


@pytest.mark.parametrize("execution", NAMES)
def test_a_missing_record_fails(tmp_path, execution):
    d = runs_dir_with(tmp_path)
    (d / f"{execution}.json").unlink()
    with pytest.raises(journey.JourneyError, match=execution):
        journey.load(d)


@pytest.mark.parametrize("text", ["{nope", "[]", "{}", '{"execution": 5}'])
def test_an_unreadable_record_fails(tmp_path, text):
    d = runs_dir_with(tmp_path)
    write(d, HUNDRED_M, text)
    with pytest.raises(journey.JourneyError, match="missing or unreadable"):
        journey.load(d)


def test_a_record_under_another_file_name_fails(tmp_path):
    d = runs_dir_with(tmp_path)
    (d / f"{HUNDRED_M}.json").rename(d / "other.json")
    with pytest.raises(journey.JourneyError, match="missing or unreadable"):
        journey.load(d)


def test_a_second_file_cannot_supply_a_runs_numbers(tmp_path):
    d = runs_dir_with(tmp_path)
    other = raw(HUNDRED_M)
    other["events_processed"] = 7
    write(d, "aaa", other)  # sorts before the real file
    assert journey.load(d) == journey.load(REAL_RUNS)


@pytest.mark.parametrize(
    "data",
    [
        b"{nope",
        b"\xff\xfe",
        b" " * (config.MAX_RECORD_BYTES + 1),
        b"[" * 100_000,
        b'{"execution": "other"}',
    ],
    ids=["not-json", "not-utf8", "too-large", "too-deep", "another-execution"],
)
def test_a_corrupt_record_fails_even_with_a_good_copy_beside_it(tmp_path, data):
    d = runs_dir_with(tmp_path)
    write(d, "aaa", raw(HUNDRED_M))
    (d / f"{HUNDRED_M}.json").write_bytes(data)
    with pytest.raises(journey.JourneyError, match="missing or unreadable"):
        journey.load(d)


@pytest.mark.parametrize("states", [None, "PWNED", {"state": "RunDbt"}])
def test_a_record_without_a_state_list_fails_without_echoing_it(tmp_path, states):
    def change(rec):
        rec["states"] = states

    with pytest.raises(journey.JourneyError, match="no state list") as err:
        journey.load(runs_dir_with(tmp_path, change))
    assert "PWNED" not in str(err.value)
