"""The review core (plan 14.2a): one run record in, one review object out.

Deterministic and model-free: same input, same bytes (no clock, no network,
no randomness). The status values come from `series.end_series`, the same
function that feeds the alerts, so the review cannot drift from them.

    review = {execution, scale_class, findings[], evidence[]}

Each finding is `{id, rule, evidence[]}`. Evidence holds allowlisted tokens and
numbers only (see evidence.py); no free text from a record passes through.
"""

import json
import math

from cerberus_console import records as rec

from cerberus_agents import baselines
from cerberus_agents.evidence import (
    STEPS,
    Evidence,
    check_name,
    execution_token,
    series,
    status_token,
    step_name,
)

RULES = (
    "run_failed",
    "dq_errors",
    "dq_missing",
    "step_slow",
    "cost_outlier",
    "athena_queue",
    "cost_missing",
    "record_invalid",
)


def _values(record):
    """end_series as {(name, step-or-None): value}."""
    out = {}
    for name, labels, value in series.end_series(record):
        out[(name, labels.get("step"))] = value
    return out


def _finite(value):
    return value is not None and not math.isnan(value)


def review(record, records=()):
    """Review `record` against `records` (the baseline; it may include `record`)."""
    try:
        vals = _values(record)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        ev = Evidence()
        e1 = ev.add("record_invalid")
        return {
            "execution": execution_token(record.get("execution"))
            if isinstance(record, dict)
            else None,
            "scale_class": baselines.UNKNOWN_CLASS,
            "findings": [{"id": "f1", "rule": "record_invalid", "evidence": [e1]}],
            "evidence": ev.items,
        }

    ev = Evidence()
    found = []  # (rule, [evidence ids])
    cls = baselines.scale_class(record)
    peer_set = baselines.peers(record, records)

    # 1. run_failed
    if vals[("cerberus_run_status", None)] != 1.0:
        status = status_token(record.get("status")) or "OTHER"
        e = ev.add("run_failed", status=status, step=step_name(series.failed_step(record)))
        found.append(("run_failed", [e]))

    # 2. dq_errors / 3. dq_missing
    dq_errors = vals[("cerberus_dq_errors", None)]
    if not _finite(dq_errors):
        found.append(("dq_missing", [ev.add("dq_missing")]))
    elif dq_errors > 0:
        n = int(dq_errors)
        failing = []
        for chk in (record["data_quality"].get("checks") or [])[:200]:
            if not isinstance(chk, dict) or chk.get("passed") is not False:
                continue
            if chk.get("severity") != "error":
                continue
            name = check_name(chk.get("name"))
            if name and name not in failing:
                failing.append(name)
        ids = [ev.add("dq_errors", check=name, errors=n) for name in sorted(failing)]
        found.append(("dq_errors", ids or [ev.add("dq_errors", check=None, errors=n)]))

    # 4. step_slow
    for step in STEPS:
        sec = vals[("cerberus_step_duration_seconds", step)]
        if not _finite(sec):
            continue
        med = baselines.peer_median(_step_seconds(p, step) for p in peer_set)
        if med and sec > baselines.STEP_SLOW_FACTOR * med:
            e = ev.add("step_slow", step=step, seconds=sec, peer_median=med, peers=len(peer_set))
            found.append(("step_slow", [e]))

    # 5. cost_outlier
    usd = baselines.number(rec.dig(record, "cost", "usd_per_million_events"))
    if usd is not None:
        med = baselines.peer_median(rec.dig(p, "cost", "usd_per_million_events") for p in peer_set)
        if med and usd > baselines.COST_OUTLIER_FACTOR * med:
            e = ev.add(
                "cost_outlier", usd_per_million_events=usd, peer_median=med, peers=len(peer_set)
            )
            found.append(("cost_outlier", [e]))

    # 6. athena_queue
    for state in record.get("states") or []:
        step = step_name(state.get("state")) if isinstance(state, dict) else None
        queue = baselines.number(rec.dig(state, "athena", "queue_seconds"))
        if step and queue is not None and queue > baselines.ATHENA_QUEUE_LIMIT_SECONDS:
            e = ev.add(
                "athena_queue",
                step=step,
                queue_seconds=queue,
                limit_seconds=baselines.ATHENA_QUEUE_LIMIT_SECONDS,
            )
            found.append(("athena_queue", [e]))

    # 7. cost_missing: no cost block, no per-million figure, or an incomplete bill.
    if usd is None or rec.dig(record, "cost", "complete") is not True:
        found.append(("cost_missing", [ev.add("cost_missing")]))

    # Rules run in the order of RULES; steps keep STEPS order. No sort needed.
    return {
        "execution": execution_token(record.get("execution")),
        "scale_class": cls,
        "findings": [
            {"id": f"f{i}", "rule": rule, "evidence": ids}
            for i, (rule, ids) in enumerate(found, start=1)
        ],
        "evidence": ev.items,
    }


def _step_seconds(record, step):
    for state in record.get("states") or []:
        if isinstance(state, dict) and state.get("state") == step:
            return state.get("seconds")
    return None


def dumps(obj):
    """The canonical bytes of a review: sorted keys, fixed indent, final newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
