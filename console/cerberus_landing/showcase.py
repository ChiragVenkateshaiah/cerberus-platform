"""The showcase snapshot builder (step 11.2a; ADR 0027 Decisions 3 and 4, ADR 0028).

Reads git files only: the run records, the named query set, the ASL template and
docs/slo.md. It writes observability/showcase/{runs,status,slo}.json, and
comparison.json only when an optional input file exists. No AWS, no network, no
clock: the same inputs give the same bytes (`generated_at` is the newest run end).

    python -m cerberus_landing.showcase --runs observability/scale/runs \\
        --out observability/showcase [--comparison-input FILE] [--check]

Redaction is fail-closed. Every string in every output must match a field
allowlist, and no value may hold `arn:`, `s3://`, `amazonaws.com`,
`cloudfront.net`, `@` or a 12-digit run. A failure raises before any file is
written, so the previous files stay as they were.

The status values come from the run records through observability/status/series.py,
the same code path as publish.py, so they equal the named-query results
(observability/status/test_e2e.py checks that against a local Prometheus).
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from datetime import UTC
from functools import cache
from pathlib import Path

from cerberus_console import config, queries, records
from cerberus_console.grammar import _TOKEN
from cerberus_landing.runs import STATES, STATUS_WORDS

REPO = Path(__file__).resolve().parents[2]
SERIES_PATH = REPO / "observability" / "status" / "series.py"
QUERIES_PATH = REPO / "observability" / "queries" / "status.json"
SLO_DOC = REPO / "docs" / "slo.md"
DEFAULT_RUNS = REPO / "observability" / "scale" / "runs"
DEFAULT_OUT = REPO / "observability" / "showcase"

SCHEMA_VERSION = 1
OUTPUTS = ("runs.json", "status.json", "slo.json")
COMPARISON = "comparison.json"
COMPARISON_INPUT = "comparison-input.json"
KINDS = ("exercise", "demo", "rehearsal")
DAY = 86400
# docs/slo.md, objective 1: at least 95% of the trailing 20 runs reach SUCCEEDED.
SLO_WINDOW_RUNS = 20
SLO_TARGET = 0.95
SLO_BUDGET = 0.05

# Redaction rules (ADR 0027 Decision 4). `@` also covers an email address.
FORBIDDEN = ("arn:", "s3://", "amazonaws.com", "cloudfront.net", "@")
_DIGITS_12 = re.compile(r"\d{12}")
_SHA = re.compile(r"[0-9a-f]{40}")

DROP_REASONS = (
    "unreadable",
    "invalid_execution",
    "execution_digit_run",
    "unknown_kind",
    "kind_mismatch",
    "unknown_status",
    "bad_timestamp",
    "bad_field",
    "duplicate_execution",
    "over_file_cap",
)


class ShowcaseError(Exception):
    pass


class RedactionError(ShowcaseError):
    pass


# ---- the redaction scan -------------------------------------------------------------


def scan_text(text: str, account_id: str | None = None) -> list[str]:
    """Names of the rules `text` breaks, in a fixed order. Never returns the text.

    The rules are the forbidden fragments, and an exact match of `account_id`
    when one is given. A plain "12 digits" rule is not here, because run records
    hold byte counts of 12 digits (ADR 0027 Decision 4); the builder applies that
    rule to JSON strings only, where numbers are not strings. The account ID is
    never part of a result or a message.
    """
    if account_id is not None and not re.fullmatch(r"\d{12}", account_id):
        raise ValueError("account_id must be exactly 12 digits")
    lowered = text.lower()
    found = [f"forbidden text {frag!r}" for frag in FORBIDDEN if frag in lowered]
    if account_id is not None and account_id in text:
        found.append("the exact account ID")
    return found


def _walk(value, path=()):
    """(path, last key, is_key, string) for every key and every string value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield path + (key,), key, True, key
            yield from _walk(item, path + (key,))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk(item, path + (i,))
    elif isinstance(value, str):
        yield path, path[-1] if path else "", False, value


def _path_text(path) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out.lstrip(".") or "(root)"


def _scan_doc(name: str, doc) -> list[str]:
    problems = []
    for path, _last, is_key, text in _walk(doc):
        for rule in scan_text(text):
            problems.append(f"{name}: {rule} at {_path_text(path)}")
        # A git blob SHA is 40 hex characters and may hold 12 digits by chance. It is
        # exempt only at generated_from[<n>].sha, and only when the whole value is a SHA.
        is_sha = (
            not is_key
            and len(path) == 3
            and path[0] == "generated_from"
            and isinstance(path[1], int)
            and path[2] == "sha"
            and _SHA.fullmatch(text) is not None
        )
        if not is_sha and _DIGITS_12.search(text):
            problems.append(f"{name}: a 12-digit run in a string at {_path_text(path)}")
    return problems


# ---- the field allowlist (a schema for each output file) ----------------------------


def _str(pattern):
    return ("str", re.compile(pattern))


def _enum(*values):
    return ("enum", tuple(values))


_NUM = ("num",)
_INT = ("int",)
_BOOL = ("bool",)
_NULL = ("null",)


def _opt(spec):
    return ("opt", spec)


def _obj(**fields):
    return ("obj", fields)


def _list(spec):
    return ("list", spec)


def _map(key_pattern, spec):
    return ("map", re.compile(key_pattern), spec)


_TOKEN_SPEC = ("str", _TOKEN)
_ISO = _str(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SOURCE = _obj(
    path=_str(r"(?!.*\.\.)[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}"), sha=_str(r"[0-9a-f]{40}")
)
_LABEL = _str(r"[A-Za-z][A-Za-z0-9 ().,'-]{0,59}")


def _common(**fields):
    return _obj(
        schema_version=("const", SCHEMA_VERSION),
        generated_from=_list(_SOURCE),
        generated_at=_ISO,
        **fields,
    )


def _schemas(steps):
    step = _enum(*steps)
    run = _obj(
        execution=_TOKEN_SPEC,
        kind=_enum(*KINDS),
        status=_enum(*STATUS_WORDS),
        start=_ISO,
        end=_ISO,
        run_seconds=_opt(_NUM),
        events_processed=_opt(_NUM),
        events_per_second=_opt(_NUM),
        dq_passed=_opt(_BOOL),
        dq_errors=_opt(_NUM),
        dq_warnings=_opt(_NUM),
        cost_usd=_opt(_NUM),
        cost_usd_per_million_events=_opt(_NUM),
        cost_estimated=_opt(_BOOL),
        steps=_list(_obj(state=_enum(*(name for name, _ in STATES)), seconds=_opt(_NUM))),
    )
    entry = (
        "oneof",
        (
            _obj(label=_LABEL, value=("oneof", (_NUM, _NULL, step))),
            _obj(label=_LABEL, by_step=_map(r"[A-Za-z][A-Za-z0-9]{0,63}", _opt(_NUM))),
            _obj(label=_LABEL, execution=_opt(_TOKEN_SPEC), value=_opt(_NUM)),
            _obj(label=_LABEL, by_execution=_list(_obj(execution=_TOKEN_SPEC, value=_NUM))),
        ),
    )
    engine = _obj(
        run_seconds=_NUM,
        usd=_NUM,
        usd_per_million_events=_NUM,
        cost_source=_enum("run_record", "databricks_billing"),
        estimated=_BOOL,
    )
    comparison = dict(
        step=step,
        input=_obj(run_id=_TOKEN_SPEC, events=_INT),
        measured_on=_str(r"\d{4}-\d{2}-\d{2}"),
        trial=("const", True),
        engines=_obj(cerberus=engine, databricks=engine),
        caveats=_list(_str(r"[a-z][a-z0-9_]{2,47}")),
    )
    return {
        "runs.json": _common(
            dropped=_obj(count=_INT, reasons=_map(r"[a-z_]{1,32}", _INT)),
            runs=_list(run),
        ),
        "status.json": _common(queries=_map(r"[a-z][a-z0-9_]{2,63}", entry)),
        "slo.json": _common(
            objectives=_list(
                _obj(
                    id=_enum("pipeline_success"),
                    target_share=_NUM,
                    error_budget_share=_NUM,
                    window_runs=_INT,
                    runs_in_window=_INT,
                    succeeded=_INT,
                    share_succeeded=_opt(_NUM),
                    error_budget_used=_opt(_NUM),
                    met=_opt(_BOOL),
                )
            )
        ),
        COMPARISON: _common(**comparison),
        "comparison-input": _obj(**comparison),
    }


def _matches(value, spec, path, problems) -> None:
    kind = spec[0]
    where = _path_text(path)
    if kind == "str":
        ok = isinstance(value, str) and spec[1].fullmatch(value) is not None
    elif kind == "enum":
        ok = isinstance(value, str) and value in spec[1]
    elif kind == "int":
        ok = type(value) is int and value >= 0
    elif kind == "num":
        ok = type(value) in (int, float) and math.isfinite(value)
    elif kind == "bool":
        ok = type(value) is bool
    elif kind == "const":
        ok = type(value) is type(spec[1]) and value == spec[1]
    elif kind == "null":
        ok = value is None
    elif kind == "opt":
        if value is not None:
            _matches(value, spec[1], path, problems)
        return
    elif kind == "oneof":
        for option in spec[1]:
            trial: list[str] = []
            _matches(value, option, path, trial)
            if not trial:
                return
        problems.append(f"{where} matches no allowed shape")
        return
    elif kind == "obj":
        if not isinstance(value, dict) or list(value) != list(spec[1]):
            problems.append(f"{where} is not an object with exactly the allowed fields")
            return
        for key, sub in spec[1].items():
            _matches(value[key], sub, path + (key,), problems)
        return
    elif kind == "list":
        if not isinstance(value, list):
            problems.append(f"{where} is not a list")
            return
        for i, item in enumerate(value):
            _matches(item, spec[1], path + (i,), problems)
        return
    elif kind == "map":
        if not isinstance(value, dict):
            problems.append(f"{where} is not an object")
            return
        for key, item in value.items():
            if not isinstance(key, str) or spec[1].fullmatch(key) is None:
                problems.append(f"{where} has a key outside the allowlist")
                continue
            _matches(item, spec[2], path + (key,), problems)
        return
    else:  # a bug in this file, not in the data
        raise AssertionError(kind)
    if not ok:
        problems.append(f"{where} does not match its field allowlist")


def gate(name: str, doc, steps) -> None:
    """Fail closed: raise RedactionError unless `doc` passes every rule.

    Messages name the file, the rule and the path. They never hold the value.
    """
    problems = _scan_doc(name, doc)
    schema = _schemas(steps)[name]
    structural: list[str] = []
    _matches(doc, schema, (), structural)
    problems += [f"{name}: {p}" for p in structural]
    if problems:
        shown = "; ".join(problems[:5])
        more = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
        raise RedactionError(f"redaction gate failed: {shown}{more}")


# ---- sources ------------------------------------------------------------------------


@cache
def _series():
    """observability/status/series.py, loaded by path: the publisher's own code."""
    spec = importlib.util.spec_from_file_location("cerberus_status_series", SERIES_PATH)
    if spec is None or spec.loader is None:
        raise ShowcaseError("cannot load observability/status/series.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blob_sha(data: bytes) -> str:
    """The git blob SHA of `data`, as `git hash-object` computes it."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _source(path: Path, root: Path, data: bytes) -> dict:
    rel = Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()
    if rel.startswith(".."):
        raise ShowcaseError("a source file is outside the repository root")
    return {"path": rel, "sha": blob_sha(data)}


def _iso(value: str) -> str:
    return _series().parse_iso(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite(value) -> bool:
    return value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    )


def _field_problem(rec: dict) -> str | None:
    """Why a record cannot be read safely, or None. Names a reason, never the value."""
    status = rec.get("status")
    if not isinstance(status, str) or status not in STATUS_WORDS:
        return "unknown_status"
    for key in ("start", "end"):
        value = rec.get(key)
        if not isinstance(value, str):
            return "bad_timestamp"
        try:
            _series().parse_iso(value)
        except ValueError:
            return "bad_timestamp"
    if not all(
        _finite(rec.get(k)) for k in ("run_seconds", "events_processed", "events_per_second")
    ):
        return "bad_field"
    for key in ("data_quality", "cost"):
        if rec.get(key) is not None and not isinstance(rec[key], dict):
            return "bad_field"
    dq = rec.get("data_quality") or {}
    cost = rec.get("cost") or {}
    if dq.get("passed") not in (None, True, False):
        return "bad_field"
    if not all(_finite(dq.get(k)) for k in ("errors", "warnings")):
        return "bad_field"
    if not all(_finite(cost.get(k)) for k in ("run_usd", "usd_per_million_events")):
        return "bad_field"
    if any(cost.get(k) not in (None, True, False) for k in ("estimated", "complete")):
        return "bad_field"
    failed = rec.get("failed_state")
    if failed is not None and not isinstance(failed, str):
        return "bad_field"
    states = rec.get("states")
    if states is not None:
        if not isinstance(states, list):
            return "bad_field"
        names = []
        for st in states:
            if not isinstance(st, dict) or not isinstance(st.get("state"), str):
                return "bad_field"
            if not _finite(st.get("seconds")):
                return "bad_field"
            names.append(st["state"])
        if len(set(names)) != len(names):
            return "bad_field"
    try:
        _series().end_series(rec)
    except (KeyError, TypeError, ValueError, AttributeError):
        return "bad_field"
    return None


def _count(value):
    """An integral float becomes an int, so 6104.0 and 6104 give the same bytes."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _row(rec: dict, kind: str) -> dict:
    cost = rec.get("cost") or {}
    final = cost.get("complete") is not False  # runs.py: not final means no figure
    usd = records.number(rec, "cost", "run_usd") if final else None
    per_million = records.number(rec, "cost", "usd_per_million_events") if final else None
    has_cost = usd is not None or per_million is not None
    passed = records.dig(rec, "data_quality", "passed")
    return {
        "execution": rec["execution"],
        "kind": kind,
        "status": rec["status"],
        "start": _iso(rec["start"]),
        "end": _iso(rec["end"]),
        "run_seconds": records.number(rec, "run_seconds"),
        "events_processed": _count(records.number(rec, "events_processed")),
        "events_per_second": _count(records.number(rec, "events_per_second")),
        "dq_passed": passed if isinstance(passed, bool) else None,
        "dq_errors": _count(records.number(rec, "data_quality", "errors")),
        "dq_warnings": _count(records.number(rec, "data_quality", "warnings")),
        "cost_usd": usd,
        "cost_usd_per_million_events": per_million,
        "cost_estimated": (cost.get("estimated") is not False) if has_cost else None,
        "steps": [
            {"state": name, "seconds": records.number(records.state(rec, name) or {}, "seconds")}
            for name, _ in STATES
        ],
    }


def load_runs(runs_dir: Path, root: Path):
    """(converted [(record, row)], sources, drop counts). Newest first.

    A file that cannot be converted is dropped and counted under a fixed reason.
    Its name and its text are never read into the output.
    """
    drops = dict.fromkeys(DROP_REASONS, 0)
    kept: list[tuple[dict, dict, dict]] = []
    seen: set[str] = set()
    try:
        files = sorted(Path(runs_dir).glob("*.json"))
    except OSError as exc:
        raise ShowcaseError("cannot list the run records directory") from exc
    drops["over_file_cap"] += max(0, len(files) - config.MAX_RECORD_FILES)
    for path in files[: config.MAX_RECORD_FILES]:
        try:
            if not path.is_file() or path.stat().st_size > config.MAX_RECORD_BYTES:
                raise ValueError("unreadable")
            data = path.read_bytes()
            rec = json.loads(data.decode("utf-8"))
            if not isinstance(rec, dict):
                raise ValueError("unreadable")
        except (OSError, ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
            drops["unreadable"] += 1
            continue
        execution = rec.get("execution")
        if not isinstance(execution, str) or _TOKEN.fullmatch(execution) is None:
            drops["invalid_execution"] += 1
            continue
        if _DIGITS_12.search(execution):
            drops["execution_digit_run"] += 1
            continue
        kind = execution.split("-", 1)[0]
        if kind not in KINDS:
            drops["unknown_kind"] += 1
            continue
        if not path.name.startswith(f"{kind}-"):
            drops["kind_mismatch"] += 1
            continue
        problem = _field_problem(rec)
        if problem:
            drops[problem] += 1
            continue
        if execution in seen:
            drops["duplicate_execution"] += 1
            continue
        seen.add(execution)
        kept.append((rec, _row(rec, kind), _source(path, root, data)))
    sr = _series()
    kept.sort(key=lambda t: (sr.epoch(t[0]["start"]), t[0]["execution"]), reverse=True)
    return [(r, row) for r, row, _ in kept], [s for _, _, s in kept], drops


# ---- status.json: the named queries, from the same series code as publish.py --------

_SCALAR = {
    "latest_status": "cerberus_run_status",
    "latest_started": "cerberus_run_started_timestamp_seconds",
    "latest_finished": "cerberus_run_finished_timestamp_seconds",
    "latest_run_seconds": "cerberus_run_duration_seconds",
    "latest_events": "cerberus_run_events_processed",
    "latest_dq_passed": "cerberus_dq_passed",
    "latest_dq_errors": "cerberus_dq_errors",
    "latest_dq_warnings": "cerberus_dq_warnings",
}
_OTHER = (
    "latest_failed_step",
    "latest_step_seconds",
    "last_success",
    "newest_finished_execution",
    "newest_started_execution",
    "run_success_share_90d",
    "runs_90d",
    "runs_started_30d",
    "runs_finished_30d",
)


def _val(value):
    """NaN and infinity become null, as the named queries show an unknown value."""
    return None if value is None or not math.isfinite(value) else value


def status_values(recs: list[dict], entries: list[dict]) -> dict:
    """{query name: entry} for the newest run, from raw run records (any order).

    `entries` is the `queries` list of observability/queries/status.json. The
    windows (30 and 90 days) end at the newest run end, not at a clock, so the
    result is the same on every run. A record is expected to have passed
    load_runs; the parity test passes raw records it also pushed to Prometheus.
    """
    sr = _series()
    ordered = sorted(recs, key=lambda r: (sr.epoch(r["start"]), r["execution"]), reverse=True)
    if not ordered:
        raise ShowcaseError("no usable run records")
    known = {e["name"] for e in entries}
    wanted = set(_SCALAR) | set(_OTHER)
    if known != wanted:
        raise ShowcaseError(
            "the query set and the builder disagree: "
            f"unmapped {sorted(known - wanted)}, missing {sorted(wanted - known)}"
        )
    anchor = max(sr.epoch(r["end"]) for r in ordered)
    in30 = [r for r in ordered if sr.epoch(r["end"]) >= anchor - 30 * DAY]
    in90 = [r for r in ordered if sr.epoch(r["end"]) >= anchor - 90 * DAY]

    latest = ordered[0]
    plain: dict[str, float] = {}
    by_step: dict[str, dict[str, float | None]] = {"failed": {}, "seconds": {}}
    for name, labels, value in sr.end_series(latest):
        if not labels:
            plain[name] = _val(value)
        elif "step" in labels and name == "cerberus_run_step_failed":
            by_step["failed"][labels["step"]] = value
        elif "step" in labels and name == "cerberus_step_duration_seconds":
            by_step["seconds"][labels["step"]] = _val(value)

    def execution_entry(rows, key):
        if not rows:
            return {"execution": None, "value": None}
        best = max(rows, key=lambda r: (sr.epoch(r[key]), r["execution"]))
        return {"execution": best["execution"], "value": sr.epoch(best[key])}

    def by_execution(key):
        rows = sorted(in30, key=lambda r: (sr.epoch(r[key]), r["execution"]), reverse=True)
        return [{"execution": r["execution"], "value": sr.epoch(r[key])} for r in rows]

    ok = [r for r in in30 if r["status"] == "SUCCEEDED"]
    failed = [step for step, v in by_step["failed"].items() if v == 1.0]
    values: dict[str, dict] = {}
    for entry in entries:
        name = entry["name"]
        if name in _SCALAR:
            body = {"value": plain.get(_SCALAR[name])}
        elif name == "latest_failed_step":
            body = {"value": failed[0] if failed else None}
        elif name == "latest_step_seconds":
            body = {"by_step": by_step["seconds"]}
        elif name == "last_success":
            body = {"value": sr.epoch(ok[0]["end"]) if ok else None}
        elif name == "newest_finished_execution":
            body = execution_entry(in30, "end")
        elif name == "newest_started_execution":
            body = execution_entry(in30, "start")
        elif name == "run_success_share_90d":
            share = sum(r["status"] == "SUCCEEDED" for r in in90) / len(in90)
            body = {"value": share}
        elif name == "runs_90d":
            body = {"value": len(in90)}
        elif name == "runs_started_30d":
            body = {"by_execution": by_execution("start")}
        else:  # runs_finished_30d
            body = {"by_execution": by_execution("end")}
        values[name] = {"label": entry["label"], **body}
    return values


# ---- slo.json -----------------------------------------------------------------------


def slo_objectives(rows: list[dict]) -> list[dict]:
    """Objective 1 of docs/slo.md over the newest 20 terminal runs of runs.json."""
    terminal = [r for r in rows if r["status"] != "RUNNING"]  # newest first
    window = terminal[:SLO_WINDOW_RUNS]
    n = len(window)
    done = sum(r["status"] == "SUCCEEDED" for r in window)
    share = done / n if n else None
    # A multiple of the budget, not clamped: 1.0 is exactly used, above 1.0 is overspent.
    used = None if share is None else round((1 - share) / SLO_BUDGET, 4) + 0.0
    return [
        {
            "id": "pipeline_success",
            "target_share": SLO_TARGET,
            "error_budget_share": SLO_BUDGET,
            "window_runs": SLO_WINDOW_RUNS,
            "runs_in_window": n,
            "succeeded": done,
            "share_succeeded": None if share is None else round(share, 4),
            "error_budget_used": used,
            "met": None if share is None else share >= SLO_TARGET,
        }
    ]


# ---- comparison.json (optional until 11.5) ------------------------------------------


def _comparison(path: Path, root: Path, steps) -> tuple[dict, dict]:
    """(fields, source) from the optional input. The input has the output fields."""
    try:
        data = path.read_bytes()
        doc = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ShowcaseError("the comparison input cannot be read as JSON") from exc
    fields = list(_schemas(steps)["comparison-input"][1])
    if not isinstance(doc, dict) or set(doc) != set(fields):
        raise ShowcaseError(f"the comparison input must have exactly the fields {fields}")
    ordered = {key: doc[key] for key in fields}
    # Scan and check the input itself, so a bad value is named before it is copied.
    gate("comparison-input", ordered, steps)
    return ordered, _source(path, root, data)


# ---- the build ----------------------------------------------------------------------


def _dump(doc: dict) -> bytes:
    text = json.dumps(doc, indent=2, ensure_ascii=True, allow_nan=False)
    return (text + "\n").encode("ascii")


def build_files(
    runs_dir: Path = DEFAULT_RUNS,
    *,
    root: Path = REPO,
    comparison_input: Path | None = None,
) -> dict[str, bytes]:
    """{file name: bytes}. Pure: it writes nothing. Raises ShowcaseError."""
    sr = _series()
    steps = list(sr.STEPS)
    converted, sources, drops = load_runs(runs_dir, root)
    if not converted:
        raise ShowcaseError("no run record could be converted")
    qdoc = queries.load(QUERIES_PATH)
    problems = queries.lint(qdoc)
    if problems:
        raise ShowcaseError(f"observability/queries/status.json fails its lint: {problems[0]}")
    entries = queries.queries(qdoc)
    rows = [row for _, row in converted]
    generated_at = max(row["end"] for row in rows)

    def fixed(path: Path) -> dict:
        return _source(path, REPO, path.read_bytes())

    runs_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_from": sources,
        "generated_at": generated_at,
        "dropped": {
            "count": sum(drops.values()),
            "reasons": {k: v for k, v in sorted(drops.items()) if v},
        },
        "runs": rows,
    }
    runs_bytes = _dump(runs_doc)
    status_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_from": [*sources, fixed(QUERIES_PATH), fixed(sr.ASL)],
        "generated_at": generated_at,
        "queries": status_values([r for r, _ in converted], entries),
    }
    slo_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_from": [
            {"path": "observability/showcase/runs.json", "sha": blob_sha(runs_bytes)},
            fixed(SLO_DOC),
        ],
        "generated_at": generated_at,
        "objectives": slo_objectives(rows),
    }
    docs = {"runs.json": runs_doc, "status.json": status_doc, "slo.json": slo_doc}
    if comparison_input is not None and Path(comparison_input).is_file():
        fields, source = _comparison(Path(comparison_input), root, steps)
        docs[COMPARISON] = {
            "schema_version": SCHEMA_VERSION,
            "generated_from": [source],
            "generated_at": generated_at,
            **fields,
        }
    for name, doc in docs.items():  # every file is checked before any is written
        gate(name, doc, steps)
    out = {name: _dump(doc) for name, doc in docs.items()}
    out["runs.json"] = runs_bytes
    return out


def write_atomic(out_dir: Path, files: dict[str, bytes]) -> None:
    """Write each file to a temp name, then rename. Remove a stale comparison.json.

    Atomic per file, not per set: a crash between two renames leaves a mixed set.
    `--check` and test_committed_snapshot_is_up_to_date catch a mixed set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    temps: list[tuple[str, str]] = []
    try:
        for name, data in files.items():
            fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{name}.", suffix=".tmp")
            temps.append((tmp, name))
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(tmp, 0o644)
        for tmp, name in temps:
            os.replace(tmp, out_dir / name)
        if COMPARISON not in files:
            (out_dir / COMPARISON).unlink(missing_ok=True)
    finally:
        for tmp, _ in temps:
            Path(tmp).unlink(missing_ok=True)


def stale_files(out_dir: Path, files: dict[str, bytes]) -> list[str]:
    """Names whose committed bytes differ from `files`, or that should not exist."""
    stale = []
    for name, data in files.items():
        path = out_dir / name
        if not path.is_file() or path.read_bytes() != data:
            stale.append(name)
    if COMPARISON not in files and (out_dir / COMPARISON).exists():
        stale.append(COMPARISON)
    return stale


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_landing.showcase")
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--comparison-input", type=Path, default=None)
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed files are stale"
    )
    args = parser.parse_args(argv)
    given = args.comparison_input or (args.out / COMPARISON_INPUT)
    try:
        files = build_files(args.runs, comparison_input=given)
    except ShowcaseError as exc:
        print(f"showcase build failed: {exc}", file=sys.stderr)
        return 1
    if args.check:
        stale = stale_files(args.out, files)
        if stale:
            print(
                f"showcase files are stale: {', '.join(stale)}; run `make showcase-snapshot`",
                file=sys.stderr,
            )
            return 1
        print(f"showcase files are up to date ({len(files)} files)")
        return 0
    try:
        write_atomic(args.out, files)
    except OSError as exc:
        print(f"showcase write failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {len(files)} files to {args.out}: {', '.join(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
