"""Run records to Grafana annotations for the console session (step 10).

Stdlib only and Python 3.9 compatible: it runs on the console host with the
system python3. The console host has no Step Functions history, so the
annotations come from the run records in observability/scale/runs/ instead of
`orchestration/annotate.sh --replay`. Tags and texts follow annotate.sh, plus
the tag `console`.

Per record this makes N + 5 annotations (N = steps in the record), or N + 6
when the record has a generator run:

    Pipeline run started        point  at start         cerberus run step console
    <state name>                region per state        cerberus run step console
    Generate (approx.)          region before start     cerberus run step console
    Pipeline run <status>       point  at end           cerberus run step console
    Quality checks: ...         point  at end           cerberus run dq cerberus-dq console
    Finished: ...               point  at end           cerberus-now run console
    Clean-up: not recorded ...  point  at end           cerberus-teardown run console
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONSOLE_TAG = "console"
TEARDOWN_TEXT = "Clean-up: not recorded in the run record"

REQUIRED_KEYS = ("execution", "status", "start", "end", "run_seconds", "states")
_RUN_ID_TIME = re.compile(r"-(\d{8}T\d{6}Z)$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_ .:+-]")


class RunRecordError(ValueError):
    """A run record is missing a field the console needs."""


def clean(value, limit=60):
    """Make a record field safe to show: ASCII word characters only, shortened.

    Grafana renders annotation text in tooltips, so a record must not be able
    to carry markup into it. Anything outside the safe set is dropped.
    """
    return _UNSAFE.sub("", str(value))[:limit]


def parse_time(text):
    """ISO 8601 text to an aware datetime. Python 3.9 cannot read a bare "Z"."""
    dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_ms(dt):
    return round(dt.timestamp() * 1000)


def generator_start(record):
    """Start of the generator run, read from the time in `generator.run_id`.

    The run id ends in the UTC time the generator job started, for example
    e100000000-20261013T061245Z. Returns None when the record has no
    generator or the id has no time.
    """
    gen = record.get("generator")
    if not isinstance(gen, dict):
        return None
    match = _RUN_ID_TIME.search(str(gen.get("run_id", "")))
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def generator_window(record):
    """(start, end) datetimes of the generator, or None. Approximate (F16)."""
    start = generator_start(record)
    seconds = record["generator"].get("write_seconds") if start else None
    if start is None or not isinstance(seconds, (int, float)) or seconds <= 0:
        return None
    return start, start + timedelta(seconds=seconds)


def validate(record, source="record"):
    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        raise RunRecordError(f"{source}: missing {', '.join(missing)}")
    if not isinstance(record["states"], list):
        raise RunRecordError(f"{source}: states is not a list")
    for state in record["states"]:
        if not isinstance(state, dict) or not isinstance(state.get("seconds"), (int, float)):
            raise RunRecordError(f"{source}: a state has no numeric seconds")
    parse_time(record["start"])
    parse_time(record["end"])


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def count_text(n, word):
    """ "3 errors", or "? errors" when the record holds anything but an integer."""
    if isinstance(n, bool) or not isinstance(n, int):
        return f"? {word}s"
    return plural(n, word)


def dq_text(record):
    """Same wording as annotate_dq_verdict; NOT RECORDED if the record has none."""
    dq = record.get("data_quality")
    if not isinstance(dq, dict):
        return "Quality checks: not recorded in the run record"
    errors = count_text(dq.get("errors", 0), "error")
    if dq.get("passed") is True:
        warnings = count_text(dq.get("warnings", 0), "warning")
        checks = dq.get("checks", [])
        checks = count_text(len(checks) if isinstance(checks, list) else None, "check")
        return f"Quality checks: PASSED ({checks}, {errors}, {warnings})"
    return f"Quality checks: FAILED ({errors}) — see run record"


def status_of(record):
    status = clean(record["status"], 20).strip()
    return status or "UNKNOWN"


def annotations_for(record, source="record"):
    """All annotations for one run record, as dicts for POST /api/annotations."""
    validate(record, source)
    run_tag = "run:" + clean(record["execution"], 80)
    status = status_of(record)
    start = parse_time(record["start"])
    end = parse_time(record["end"])
    start_ms, end_ms = to_ms(start), to_ms(end)
    step_tags = ["cerberus", run_tag, "step", CONSOLE_TAG]
    out = []

    def add(text, time_ms, tags, time_end=None):
        item = {"text": text, "time": time_ms, "tags": list(tags)}
        if time_end is not None:
            item["timeEnd"] = time_end
        out.append(item)

    add("Pipeline run started", start_ms, step_tags)

    # Cumulative offsets: each state starts where the one before it ended.
    offset = 0.0
    for state in record["states"]:
        begin = start_ms + round(offset * 1000)
        offset += state["seconds"]
        add(
            clean(state.get("state", "step")) or "step",
            begin,
            step_tags,
            start_ms + round(offset * 1000),
        )

    window = generator_window(record)
    if window is not None:
        add("Generate (approx.)", to_ms(window[0]), step_tags, to_ms(window[1]))

    add(f"Pipeline run {status}", end_ms, step_tags)
    add(dq_text(record), end_ms, ["cerberus", run_tag, "dq", "cerberus-dq", CONSOLE_TAG])
    add(
        f"Finished: pipeline run {status} (recorded run)",
        end_ms,
        ["cerberus-now", run_tag, CONSOLE_TAG],
    )
    add(TEARDOWN_TEXT, end_ms, ["cerberus-teardown", run_tag, CONSOLE_TAG])
    return out


def load_records(runs_dir):
    """Every *.json run record in a directory, oldest first, as (name, record)."""
    records = []
    for path in sorted(Path(runs_dir).glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        validate(record, path.name)
        records.append((path.name, record))
    records.sort(key=lambda item: parse_time(item[1]["start"]))
    return records


def all_annotations(records):
    out = []
    for name, record in records:
        out.extend(annotations_for(record, name))
    return out
