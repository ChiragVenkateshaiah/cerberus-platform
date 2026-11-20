"""Run record -> status series (ADR 0021 amendment 2026-11-20, plan 5.1).

Pure functions, stdlib only. A series is a tuple `(name, labels, value)`:
`labels` is a dict, `value` is a float. NaN marks a value as unknown, so that
`last_over_time` does not keep showing an earlier run's value. It is an
ordinary NaN, not the Prometheus stale marker.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

NAN = float("nan")

ASL = Path(__file__).resolve().parents[2] / "orchestration" / "state_machine.asl.json.tftpl"


def parse_steps(text):
    """Task state names, in order, from the ASL template text.

    The file is a Terraform template, so it is not valid JSON as it stands.
    Quoted `${x}` becomes a plain string and a bare `${x}` becomes null; only
    then does `json.loads` read it. Only `"Type": "Task"` states count.
    """
    text = re.sub(r'"\$\{[^}]*\}"', '"x"', text)
    text = re.sub(r"\$\{[^}]*\}", "null", text)
    states = json.loads(text)["States"]
    return [name for name, state in states.items() if state.get("Type") == "Task"]


STEPS = parse_steps(ASL.read_text())


def parse_iso(value):
    """ISO 8601 string -> aware datetime. A string with no zone means UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def epoch(value):
    return parse_iso(value).timestamp()


def _num(value):
    return NAN if value is None else float(value)


def start_series(execution, started):
    """The two series written at run start. `started` is an ISO string."""
    ts = epoch(started)
    return [
        ("cerberus_run_started_timestamp_seconds", {}, ts),
        ("cerberus_execution_started_timestamp_seconds", {"execution": execution}, ts),
    ]


def failed_step(record):
    """Name of the failed state, or None.

    None when the run succeeded or when no state can be named. Order: the
    record's `failed_state`, else the last `states[]` entry.
    """
    if record.get("status") == "SUCCEEDED":
        return None
    if record.get("failed_state"):
        return record["failed_state"]
    # The states[] fallback holds only for FAILED: a Catch makes the failed
    # step exit. After ABORTED or TIMED_OUT the last entry is a step that ended.
    if record.get("status") != "FAILED":
        return None
    states = record.get("states") or []
    return states[-1]["state"] if states else None


def end_series(record):
    """All series written at run end, from one run record."""
    execution = record["execution"]
    succeeded = record["status"] == "SUCCEEDED"
    finished = epoch(record["end"])
    failed = failed_step(record)
    seconds = {s["state"]: s.get("seconds") for s in record.get("states") or []}
    dq = record.get("data_quality")

    out = [
        ("cerberus_run_status", {}, 1.0 if succeeded else 0.0),
        ("cerberus_run_finished_timestamp_seconds", {}, finished),
        ("cerberus_execution_finished_timestamp_seconds", {"execution": execution}, finished),
        ("cerberus_run_duration_seconds", {}, _num(record.get("run_seconds"))),
        ("cerberus_run_events_processed", {}, _num(record.get("events_processed"))),
        ("cerberus_run_info", {"execution": execution}, 1.0),
    ]
    if succeeded:
        out.append(("cerberus_last_success_timestamp_seconds", {}, finished))
    out += start_series(execution, record["start"])
    if dq is None:
        out += [(f"cerberus_dq_{k}", {}, NAN) for k in ("passed", "errors", "warnings")]
    else:
        out += [
            (
                "cerberus_dq_passed",
                {},
                NAN if dq.get("passed") is None else float(bool(dq["passed"])),
            ),
            ("cerberus_dq_errors", {}, _num(dq.get("errors"))),
            ("cerberus_dq_warnings", {}, _num(dq.get("warnings"))),
        ]
    for step in STEPS:
        out.append(("cerberus_run_step_failed", {"step": step}, 1.0 if step == failed else 0.0))
        out.append(("cerberus_step_duration_seconds", {"step": step}, _num(seconds.get(step))))
    return out
