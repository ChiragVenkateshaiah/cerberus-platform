"""The data behind "follow the batch" (9.4b): 3 fixed runs, station by station.

Numbers and fixed strings only: no record text reaches the output. Check names
come from an allowlist that maps each one to plain words; any other name is
counted, never kept.

None means "not recorded" (or the station has no such figure). A record that is
missing or unreadable, did not succeed, has no state list or holds a failed data
check raises JourneyError, because the page cannot tell the story with it. A
missing field inside a record, or a number outside 0 to MAX_NUMBER, is None, as
the run cards in runs.py show "not recorded".

The data-quality suite runs after the run, not inside a state, and most of its
checks scan whole tables (earlier batches too), not only this run's batch. A
check sits at the station whose data it looks at.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from cerberus_console import config, records
from cerberus_landing import runs

# (execution, size label). The fixed runs of the scale ladder (docs/scale-metrics.md).
RUNS = (
    ("exercise-20261015T145812Z", "1M"),
    ("exercise-20261009T074853Z", "10M"),
    ("exercise-20261013T055859Z", "100M"),
)
FEATURED = "exercise-20261013T055859Z"
MAX_NUMBER = 1e15

# One station per runs.STATES entry, in the same order.
STATION_NAMES = ("Arrive", "Clean", "Model", "Answer")
ARRIVE, CLEAN, MODEL, ANSWER = (state for state, _ in runs.STATES)

SPARK_APP = "cerberus-promote-payments"
SPARK_BYTES = "Spark input"
ATHENA_BYTES = "Athena scanned"

# station -> (label, record path). A None path: no record field holds the figure.
# silver.* and the gold bytes are table totals at collection time, not per run.
TOTALS = {
    ARRIVE: (("Bronze events", None),),
    CLEAN: (
        ("Silver events", ("silver", "events")),
        ("Silver transactions", ("silver", "transactions")),
    ),
    MODEL: (
        ("Gold rows", None),
        ("Gold stored bytes", ("storage_snapshot", "gold", "bytes")),
    ),
    ANSWER: (),
}

# check name (without a [dt=...] suffix) -> (station, plain words). The words
# say no more than the check's SQL tests: observability/scale/data_quality.py.
# bulk_run_counts is not in the current data_quality.py (removed in 6addc36);
# older records hold it. bronze_ledger appears only when the suite cannot read
# the ledger, so as a failure.
# The Arrive checks look at generator data written before the run. The Arrive
# step neither writes that data nor runs these checks.
CHECKS = {
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
# check name -> the plain words for its warning. The words in CHECKS say that a
# check held, so the page prints those only for a check that passed. A warned
# check with no words here is only counted. The words say no more than the
# check's SQL and description in observability/scale/data_quality.py.
WARNINGS = {
    "token_digit_runs": (
        "Some payment tokens hold a run of 13 or more digits, which a data-leak "
        "scanner could read as card numbers. The check only warns, because older "
        "tokens with this pattern are accepted."
    ),
}
_WARNING_FOR = {CHECKS[name][1]: words for name, words in WARNINGS.items()}
_DT_SUFFIX = re.compile(r"\[dt=[^\]]*\]\Z")


class JourneyError(Exception):
    pass


@dataclass(frozen=True)
class Total:
    label: str
    value: int | None  # the table total after this run


@dataclass(frozen=True)
class Station:
    name: str  # "Arrive", "Clean", "Model" or "Answer"
    state: str  # the state name from runs.STATES
    label: str  # the plain label from runs.STATES
    seconds: int | float | None
    share: float | None  # seconds / run_seconds, 0 to 1
    bytes_read: int | None
    bytes_source: str | None  # what counted the bytes; None when bytes_read is None
    totals: tuple[Total, ...]
    # None: the record holds no check list. A failed check stops the load, so a
    # check here either passed or ended in a warning.
    checks_passed: tuple[str, ...] | None
    checks_warned: int | None  # known checks here that ended in a warning
    warnings: tuple[str, ...] | None  # words from WARNINGS for the warned checks that have them
    # Athena only. Both are sums over the state's queries
    # (observability/scale/collect_run_metrics.py), not wall time.
    queue_seconds: int | float | None
    engine_seconds: int | float | None


@dataclass(frozen=True)
class Run:
    execution: str
    size: str
    featured: bool
    date: str  # "13 October 2026 (UTC)" or "date not recorded"
    events: int | None
    bulk: bool  # a Spark generator wrote the events beforehand (ADR 0018)
    run_seconds: int | float | None
    cost_usd: int | float | None
    cost_usd_per_million_events: int | float | None
    cost_estimated: bool  # False only when the record says so, as in runs.py
    cost_complete: bool | None
    unknown_checks: int | None  # check entries whose name is not in CHECKS
    # Prometheus: the most series with a sample at any 15 s step of the run, read
    # at collection (docs/scale-metrics.md, "Peak active series").
    peak_series: int | None
    file_name: str  # record file under observability/scale/runs/
    stations: tuple[Station, ...]


def _number(obj, *path):
    """A number from 0 to MAX_NUMBER at the path, or None. Booleans are not numbers."""
    v = records.dig(obj, *path)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if 0 <= v <= MAX_NUMBER else None  # NaN fails both comparisons


def _count(obj, *path):
    """As _number, for counts and bytes: integers only."""
    v = _number(obj, *path)
    return v if isinstance(v, int) else None


def _date(iso) -> str:
    try:
        return runs.format_date(iso)
    except OverflowError:  # the conversion to UTC leaves the years datetime can hold
        return runs.format_date(None)


def _checks(rec: dict, execution: str):
    """({station: {plain words: all entries passed}}, unknown count), or (None, None).

    An entry that did not pass is a warning only if its severity is exactly
    "warn". Any other one, whatever its name, raises JourneyError.
    """
    entries = records.dig(rec, "data_quality", "checks")
    if not isinstance(entries, list):
        return None, None
    found: dict[str, dict[str, bool]] = {state: {} for state, _ in runs.STATES}
    unknown = 0
    for entry in entries:
        passed = records.dig(entry, "passed") is True
        if not passed and records.text(entry, "severity") != "warn":
            raise JourneyError(f"journey run {execution}: a data check failed")
        name = records.text(entry, "name")
        known = None if name is None else CHECKS.get(_DT_SUFFIX.sub("", name))
        if known is None:
            unknown += 1
            continue
        station, words = known
        found[station][words] = found[station].get(words, True) and passed
    return found, unknown


def _station(rec: dict, name: str, state: str, label: str, run_seconds, checks) -> Station:
    st = records.state(rec, state) or {}
    seconds = _number(st, "seconds")
    share = None
    if seconds is not None and run_seconds and seconds <= run_seconds:
        share = seconds / run_seconds
    # A state with no Athena query records zeros. They are not figures.
    athena = {} if _number(st, "athena", "queries") == 0 else st.get("athena")
    if state == CLEAN:
        read = _count(rec, "prometheus", "spark", SPARK_APP, "spark_input_bytes")
        source = SPARK_BYTES
    else:
        read = _count(athena, "bytes_scanned")
        source = ATHENA_BYTES
    here = None if checks is None else checks[state]
    return Station(
        name=name,
        state=state,
        label=label,
        seconds=seconds,
        share=share,
        bytes_read=read,
        bytes_source=None if read is None else source,
        totals=tuple(
            Total(title, None if path is None else _count(rec, *path))
            for title, path in TOTALS[state]
        ),
        checks_passed=None if here is None else tuple(w for w, ok in here.items() if ok),
        checks_warned=None if here is None else sum(not ok for ok in here.values()),
        warnings=(
            None
            if here is None
            else tuple(_WARNING_FOR[w] for w, ok in here.items() if not ok and w in _WARNING_FOR)
        ),
        queue_seconds=_number(athena, "queue_seconds"),
        engine_seconds=_number(athena, "engine_seconds"),
    )


def _run(rec: dict, execution: str, size: str) -> Run:
    run_seconds = _number(rec, "run_seconds")
    # As in runs.py: a cost that is not final shows no figure.
    complete = records.dig(rec, "cost", "complete")
    final = complete is not False
    checks, unknown = _checks(rec, execution)
    return Run(
        execution=execution,
        size=size,
        featured=execution == FEATURED,
        date=_date(records.text(rec, "start")),
        events=_count(rec, "events_processed"),
        bulk=isinstance(rec.get("generator"), dict),
        run_seconds=run_seconds,
        cost_usd=_number(rec, "cost", "run_usd") if final else None,
        cost_usd_per_million_events=(
            _number(rec, "cost", "usd_per_million_events") if final else None
        ),
        cost_estimated=records.dig(rec, "cost", "estimated") is not False,
        cost_complete=complete if isinstance(complete, bool) else None,
        unknown_checks=unknown,
        peak_series=_count(rec, "prometheus", "peak_active_series"),
        file_name=f"{execution}.json",
        stations=tuple(
            _station(rec, name, state, label, run_seconds, checks)
            for name, (state, label) in zip(STATION_NAMES, runs.STATES, strict=True)
        ),
    )


def _read(runs_dir: Path, execution: str) -> dict:
    """<execution>.json itself, so no other file can supply the run's numbers.

    The size and type limits are those of records.load. The page links to the
    record by this file name.
    """
    path = Path(runs_dir) / f"{execution}.json"
    try:
        if path.stat().st_size > config.MAX_RECORD_BYTES:
            raise ValueError("too large")
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        rec = None
    if not isinstance(rec, dict) or rec.get("execution") != execution:
        raise JourneyError(f"journey run {execution}: record missing or unreadable")
    return rec


def load(runs_dir: Path) -> tuple[Run, ...]:
    """The fixed runs, in RUNS order. Raises JourneyError if one cannot be shown."""
    out = []
    for execution, size in RUNS:
        rec = _read(runs_dir, execution)
        if rec.get("status") != "SUCCEEDED":
            raise JourneyError(f"journey run {execution}: run did not succeed")
        if not isinstance(rec.get("states"), list):
            raise JourneyError(f"journey run {execution}: record has no state list")
        out.append(_run(rec, execution, size))
    return tuple(out)
