"""The nine agent tools (plan 14.2b): the 9.3 commands, `review`, and the named queries.

Offline by default. The run-record tools read the committed records through
`records.load` and the console command handlers, with no AWS source: `status`
and `run` show their Step Functions and gold-freshness sections as "unavailable",
and `run` for an id that is not in the records answers the fixed "unavailable"
text. Nothing here imports boto3 or opens a connection.

A run record is untrusted text. Before a console handler sees it, `_scrub`
rebuilds it from allowlisted fields: free text (a check `detail`, `rate_excludes`)
is dropped and every kept string must match a strict pattern. The sanitiser then
runs again over every output (registry.py). `query` takes a NAME from the entry
set, never free text, and runs only through an injected reader.
"""

import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cerberus_console import commands, config, grammar, queries, records
from cerberus_console.sources import Sources, Unavailable

from cerberus_agents import review as review_core
from cerberus_agents.evidence import (
    UNKNOWN_CHECK,
    check_name,
    execution_token,
    status_token,
    step_name,
)
from cerberus_agents.registry import Registry, Tool

_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?", re.ASCII
)
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# Fits all 21 service keys in the committed records (longest 47 chars) with headroom.
# A key must also start with Amazon or AWS, or be a listed Cost Explorer name that
# does not (a new such name must be added to _OTHER_SERVICES).
_SERVICE = re.compile(r"[A-Za-z][A-Za-z0-9 ()&,.-]{0,63}", re.ASCII)
_OTHER_SERVICES = frozenset({"EC2 - Other", "CloudWatch Events", "Tax"})
_LONG_DIGITS = re.compile(r"\d{12,}")
_SEVERITIES = ("error", "warn", "warning", "info")
_MAX_CHECKS = 200

_ID = {
    "type": "string",
    "pattern": grammar._TOKEN.pattern,
    "maxLength": config.MAX_TOKEN_CHARS,
}
_NO_AWS = " Offline: the AWS sections read as unavailable."


class QueryReader(Protocol):
    def run_query(self, name: str) -> dict:
        """The JSON-shaped result of the named entry. Raise Unavailable if it cannot answer."""


class UnavailableReader:
    """The default: no AMP reader exists yet (it belongs to the IAM step)."""

    def run_query(self, name: str) -> dict:
        raise Unavailable


# ---- scrubbing a record ----------------------------------------------------


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return v


def _int(v):
    return v if type(v) is int else None


def _bool(v):
    return v if type(v) is bool else None


def _pattern(v, rx):
    return v if type(v) is str and rx.fullmatch(v) else None


def _service(k):
    ok = _pattern(k, _SERVICE) and not _LONG_DIGITS.search(k)
    return ok and (k.startswith(("Amazon", "AWS")) or k in _OTHER_SERVICES)


def _put(out: dict, key, value):
    if value is not None:
        out[key] = value


def _scrub(rec: dict) -> dict | None:
    """A copy of one record with allowlisted fields only; None if it has no safe name."""
    name = execution_token(rec.get("execution"))
    if name is None:
        return None
    out = {"execution": name}
    _put(out, "status", status_token(rec.get("status")))
    _put(out, "start", _pattern(rec.get("start"), _TIMESTAMP))
    _put(out, "end", _pattern(rec.get("end"), _TIMESTAMP))
    for key in ("run_seconds", "events_processed", "events_per_second"):
        _put(out, key, _num(rec.get(key)))
    silver = records.dig(rec, "silver")
    if isinstance(silver, dict):
        out["silver"] = {
            k: _num(silver.get(k))
            for k in ("events", "transactions")
            if _num(silver.get(k)) is not None
        }
    peak = records.number(rec, "prometheus", "peak_active_series")
    if peak is not None:
        out["prometheus"] = {"peak_active_series": peak}
    if isinstance(rec.get("states"), list):
        states = []
        for st in rec["states"]:
            step = step_name(st.get("state")) if isinstance(st, dict) else None
            if step is None:
                continue
            item = {"state": step}
            _put(item, "seconds", _num(st.get("seconds")))
            athena = {}
            for k in ("usd", "engine_seconds", "queue_seconds"):
                _put(athena, k, _num(records.dig(st, "athena", k)))
            if athena:
                item["athena"] = athena
            states.append(item)
        out["states"] = states
    cost = records.dig(rec, "cost")
    if isinstance(cost, dict):
        c = {}
        _put(c, "day", _pattern(cost.get("day"), _DAY))
        for key in ("usd", "run_usd", "usd_per_million_events"):
            _put(c, key, _num(cost.get(key)))
        _put(c, "estimated", _bool(cost.get("estimated")))
        _put(c, "complete", _bool(cost.get("complete")))
        by_service = cost.get("by_service")
        if isinstance(by_service, dict):
            kept = {
                k: _num(v) for k, v in by_service.items() if _service(k) and _num(v) is not None
            }
            c["by_service"] = kept
            if len(kept) < len(by_service):  # never drop silently: show a count
                c["dropped_services"] = len(by_service) - len(kept)
        out["cost"] = c
    dq = records.dig(rec, "data_quality")
    if isinstance(dq, dict):
        d = {}
        _put(d, "passed", _bool(dq.get("passed")))
        _put(d, "errors", _int(dq.get("errors")))
        _put(d, "warnings", _int(dq.get("warnings")))
        if isinstance(dq.get("checks"), list):
            checks = []
            for chk in dq["checks"][:_MAX_CHECKS]:
                if not isinstance(chk, dict) or type(chk.get("name")) is not str:
                    continue
                nm = check_name(chk["name"]) or UNKNOWN_CHECK
                item = {"name": nm}
                sev = chk.get("severity")
                _put(item, "severity", sev if sev in _SEVERITIES else None)
                _put(item, "passed", _bool(chk.get("passed")))
                _put(item, "violations", _int(chk.get("violations")))
                checks.append(item)  # `detail` is free text: never copied
            d["checks"] = checks
        out["data_quality"] = d
    return out


def _note_hidden(data, text, clean, ident):
    """Add the count of hidden service lines to a one-run cost answer, never silently."""
    rec = clean.records[0] if ident == "latest" and clean.records else clean.get(ident)
    n = records.dig(rec, "cost", "dropped_services") if rec else None
    if type(n) is int and n > 0 and isinstance(data.get("cost"), dict):
        data["cost"]["dropped_services"] = n
        text += f"\n({n} service lines hidden)"
    return data, text


def _load(runs_dir: Path):
    """(raw RecordSet, scrubbed RecordSet). Read on each call, so a new record shows."""
    raw = records.load(runs_dir)
    clean = records.RecordSet(skipped=raw.skipped)
    for rec in raw.records:
        s = _scrub(rec)
        if s is None:
            clean.skipped += 1
        else:
            clean.records.append(s)
    return raw, clean


# ---- the tools -------------------------------------------------------------


def build_registry(
    runs_dir: Path = config.RUNS_DIR,
    queries_file: Path = config.QUERIES_FILE,
    reader: QueryReader | None = None,
    now=None,
    budget: int | None = None,
) -> Registry:
    """The registry with the nine tools, in their fixed order."""
    reader = reader or UnavailableReader()
    doc = queries.load(queries_file)
    if queries.lint(doc):
        raise ValueError("the named query set does not lint")
    entries = [
        q
        for q in queries.queries(doc)
        if all(type(q.get(k)) is str for k in ("name", "label", "meaning"))
    ]
    names = tuple(q["name"] for q in entries)
    sources = Sources(runs_dir=Path(runs_dir))  # no AWS factories: offline

    def console(name: str):
        def handler(arguments: dict):
            argv = [name] + ([arguments["id"]] if "id" in arguments else [])
            cmd = grammar.parse_argv(argv)
            _, clean = _load(sources.runs_dir)
            ctx = commands.Context(sources, clean, now or datetime.now(UTC))
            data, text = commands.run(cmd, ctx)
            if name == "cost" and "id" in arguments:
                data, text = _note_hidden(data, text, clean, arguments["id"])
            return data, text

        return handler

    def review_handler(arguments: dict):
        ident = arguments["id"]
        grammar.parse_argv(["run", ident])  # the console grammar checks the id
        raw, _ = _load(sources.runs_dir)
        if ident == "latest":
            if not raw.records:
                raise Unavailable
            rec = raw.records[0]
        else:
            rec = raw.get(ident)
            if rec is None:
                raise commands.NotFound
        result = review_core.review(rec, raw.records)
        return result, review_core.dumps(result)

    def queries_list_handler(arguments: dict):
        items = [{"name": q["name"], "label": q["label"], "meaning": q["meaning"]} for q in entries]
        lines = [f"{i['name']}: {i['label']} - {i['meaning']}" for i in items]
        return {"queries": items}, "\n".join(lines)

    def query_handler(arguments: dict):
        name = arguments["name"]
        if name not in names:  # exact membership; never parsed, never forwarded
            raise grammar.Refused
        return {"name": name, "result": reader.run_query(name)}, f"Result of query {name}"

    reg = Registry() if budget is None else Registry(budget)
    one = {"id": _ID}
    for name, desc, props, required in (
        ("status", "Latest execution, gold freshness and newest run record." + _NO_AWS, {}, ()),
        ("runs", "The newest run records, from git.", {}, ()),
        ("run", "One run by id or `latest`: its record." + _NO_AWS, one, ("id",)),
        ("cost", "Cost per run, or one run by id, from the records.", one, ()),
        ("dq", "Data-quality result of the newest run or one run by id.", one, ()),
        ("slo", "Service level objectives over the newest records.", {}, ()),
    ):
        reg.register(Tool(name, desc, props, required, console(name)))
    reg.register(
        Tool(
            "review",
            "Deterministic review of one run (id or `latest`): findings with evidence ids.",
            one,
            ("id",),
            review_handler,
        )
    )
    reg.register(
        Tool(
            "queries_list",
            "The named queries: name, label and meaning.",
            {},
            (),
            queries_list_handler,
        )
    )
    reg.register(
        Tool(
            "query",
            "Run one named query by NAME from `queries_list`. Never free text. "
            "Unavailable until a reader is injected.",
            {"name": {"type": "string", "enum": list(names)}},
            ("name",),
            query_handler,
        )
    )
    return reg
