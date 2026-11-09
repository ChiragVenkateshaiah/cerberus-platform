"""Turns run records into the plain strings the page shows.

No record text reaches the HTML. The state names are a fixed list, the status
comes from an allowlist, the execution name is shown only if it matches the
console grammar's token pattern, and every number is formatted here. Anything
else in a record is never read into the page. The page builder still passes
every string through cerberus_console.sanitize and html.escape.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cerberus_console import records
from cerberus_console.grammar import _TOKEN

# (state name in the record, plain label). The only state names the page prints.
STATES = (
    ("InvokeIngestion", "Add the day's new events (small batch)"),
    ("RunTransform", "Clean it with Spark"),
    ("RunDbt", "Build the business tables"),
    ("RunServingQuery", "Answer a test query"),
)
STATUS_WORDS = {
    "SUCCEEDED": "Succeeded",
    "FAILED": "Failed",
    "TIMED_OUT": "Timed out",
    "ABORTED": "Aborted",
    "RUNNING": "Running",
}
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True)
class RunView:
    execution: str | None  # None when it fails the token pattern: the card links nowhere
    status: str
    date: str
    events: str  # "1,005,920" or "not recorded"
    duration: str
    cost: str  # "$0.2928 per million events (estimated)", "cost not final yet", ...
    checks: str
    states: tuple[tuple[str, str], ...]  # (plain label, seconds text)
    file_name: str | None  # record file under observability/scale/runs/
    bulk: bool  # a Spark generator wrote the events beforehand (ADR 0018)


def format_int(n) -> str:
    return "not recorded" if n is None else f"{round(n):,}"


def format_duration(seconds) -> str:
    if seconds is None:
        return "not recorded"
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    return f"{total // 60} min {total % 60} s"


def format_date(iso) -> str:
    if not isinstance(iso, str):
        return "date not recorded"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return "date not recorded"
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year} (UTC)"


def _cost(rec: dict) -> str:
    if records.dig(rec, "cost", "complete") is False:
        return "cost not final yet"
    per_million = records.number(rec, "cost", "usd_per_million_events")
    if per_million is None:
        return "cost not recorded"
    label = f"${per_million:,.4f} per million events"
    return label if records.dig(rec, "cost", "estimated") is False else f"{label} (estimated)"


def _checks(rec: dict) -> str:
    passed = records.dig(rec, "data_quality", "passed")
    if passed is True:
        return "Data checks passed"
    if passed is False:
        return "Data checks failed"
    return "Data checks not run"


def view(rec: dict) -> RunView:
    execution = rec.get("execution")
    ok = isinstance(execution, str) and _TOKEN.fullmatch(execution) is not None
    raw_status = records.text(rec, "status")
    status = STATUS_WORDS.get(raw_status, "unknown")
    rows = []
    for name, label in STATES:
        seconds = records.number(records.state(rec, name) or {}, "seconds")
        rows.append((label, "not recorded" if seconds is None else f"{seconds:.1f}"))
    return RunView(
        execution=execution if ok else None,
        status=status,
        date=format_date(records.text(rec, "start")),
        events=format_int(records.number(rec, "events_processed")),
        duration=format_duration(records.number(rec, "run_seconds")),
        cost=_cost(rec),
        checks=_checks(rec),
        states=tuple(rows),
        file_name=f"{execution}.json" if ok else None,
        bulk=isinstance(rec.get("generator"), dict),
    )


def pick(runs_dir: Path) -> tuple[RunView | None, RunView | None, int, int]:
    """(latest, largest succeeded, record count, succeeded count)."""
    rs = records.load(runs_dir)
    if not rs.records:
        return None, None, 0, 0
    ok = [r for r in rs.records if r.get("status") == "SUCCEEDED"]
    largest = None
    best = -1
    for rec in ok:  # newest first, so a tie keeps the newest
        events = records.number(rec, "events_processed")
        if events is not None and events > best:
            best, largest = events, rec
    return (
        view(rs.records[0]),
        view(largest) if largest is not None else None,
        len(rs.records),
        len(ok),
    )
