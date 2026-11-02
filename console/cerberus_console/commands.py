"""One function per command -> (data, text). Read-only; no command takes free text.

The run-record commands (runs, run, cost, dq, slo) read git. Only `status` and
the detail part of `run <id>` call AWS, and a failed AWS read shows as
"unavailable" in its own section while the rest of the answer stands. No
command calls Cost Explorer: cost figures are the collector's, already in the
records.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cerberus_console import config, records, render
from cerberus_console.grammar import COMMANDS, Command
from cerberus_console.sources import Sources, Unavailable

log = logging.getLogger(__name__)

UNAVAILABLE = "unavailable"


class NotFound(Exception):
    pass


@dataclass
class Context:
    sources: Sources
    records: records.RecordSet
    now: datetime


SUMMARIES = {
    "help": ("help [command]", "list the commands"),
    "status": ("status", "latest execution, gold freshness, newest run record"),
    "runs": ("runs", "the newest run records"),
    "run": ("run <id|latest>", "one run: record, plus Step Functions detail"),
    "cost": ("cost [id]", "cost per run, from the records"),
    "dq": ("dq [id]", "data-quality result of a run"),
    "slo": ("slo", "service level objectives, from the records"),
}


# ---- small helpers ---------------------------------------------------------


def _when(iso) -> str:
    """'2026-10-13T06:35:02.004000+00:00' -> '2026-10-13 06:35 UTC'."""
    return f"{iso[:10]} {iso[11:16]} UTC" if isinstance(iso, str) and len(iso) >= 16 else "-"


def _parse(ts) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        d = datetime.fromisoformat(ts.replace(" UTC", "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _age(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "-"
    secs = max(0, int((now - then).total_seconds()))
    if secs >= 86400:
        return f"{secs // 86400} d {secs % 86400 // 3600} h"
    if secs >= 3600:
        return f"{secs // 3600} h {secs % 3600 // 60} min"
    return f"{secs // 60} min"


def _pass_word(v) -> str:
    return "-" if v is None else ("yes" if v else "no")


def _newest(ctx: Context) -> dict:
    if not ctx.records.records:
        raise Unavailable
    return ctx.records.records[0]


def _section(label: str, fn):
    """Run one source read. Any failure becomes a fixed 'unavailable' section."""
    try:
        return fn()
    except Exception as exc:  # the visitor never sees the message
        log.warning("%s failed: %s", label, type(exc).__name__)
        return None


# ---- commands --------------------------------------------------------------


def cmd_help(ctx: Context, args: tuple) -> tuple[dict, str]:
    names = [args[0]] if args else list(COMMANDS)
    rows = [[SUMMARIES[n][0], SUMMARIES[n][1]] for n in names]
    data = {"commands": [{"usage": r[0], "summary": r[1]} for r in rows]}
    text = "Commands (read-only; no shell, no write):\n" + render.table(
        ["command", "what it shows"], rows
    )
    return data, text


def cmd_status(ctx: Context, args: tuple) -> tuple[dict, str]:
    data: dict = {}
    lines: list[str] = []

    def latest_execution():
        sfn = ctx.sources.sfn()
        executions = sfn.list_executions()
        if not executions:
            return {"none": True}
        newest = executions[0]
        out = {k: newest[k] for k in ("name", "status", "start", "stop")}
        if newest["status"] == "RUNNING" and newest.get("arn"):
            out["current_state"] = sfn.current_state(newest["arn"])
        start, stop = _parse(newest["start"]), _parse(newest["stop"])
        out["seconds"] = round((stop - start).total_seconds(), 1) if start and stop else None
        return out

    ex = _section("latest execution", latest_execution)
    lines.append("Latest execution")
    if ex is None:
        data["execution"] = {"available": False}
        lines.append("  " + UNAVAILABLE)
    elif ex.get("none"):
        data["execution"] = {"available": True, "none": True}
        lines.append("  none yet")
    else:
        data["execution"] = {"available": True, **ex}
        pairs = [("name", ex["name"]), ("status", ex["status"]), ("start", _when(ex["start"]))]
        if ex.get("seconds") is not None:
            pairs.append(("duration", f"{ex['seconds']:.0f} s"))
        if ex.get("current_state"):
            pairs.append(("current state", ex["current_state"]))
        # A failed run's record lists the states up to the one that stopped it.
        rec = ctx.records.get(ex["name"]) if ex["status"] == "FAILED" else None
        stages = (
            [s.get("state") for s in rec.get("states", []) if isinstance(s, dict)] if rec else []
        )
        if stages:
            pairs.append(("failed state", stages[-1]))
        lines.append(render.kv([(f"  {k}", v) for k, v in pairs]))

    gold = _section("gold freshness", lambda: ctx.sources.freshness().gold_freshness())
    lines.append("")
    lines.append("Gold freshness (last commit per table)")
    if gold is None:
        data["gold"] = {"available": False}
        lines.append("  " + UNAVAILABLE)
    else:
        rows = []
        for t in gold.get("tables", []):
            rows.append(
                [t.get("table"), t.get("last_commit"), _age(_parse(t.get("last_commit")), ctx.now)]
            )
        data["gold"] = {
            "available": True,
            "tables": [{"table": r[0], "last_commit": r[1], "age": r[2]} for r in rows],
            "bytes_scanned": gold.get("bytes_scanned"),
        }
        lines.append(render.table(["table", "last commit", "age"], rows))
        if gold.get("bytes_scanned") is not None:
            lines.append(f"Athena scanned {render.num(gold['bytes_scanned'])} bytes")

    lines.append("")
    lines.append("Newest run record")
    if not ctx.records.records:
        data["newest_record"] = {"available": False}
        lines.append("  " + UNAVAILABLE)
    else:
        rec = ctx.records.records[0]
        summary = _record_summary(rec)
        data["newest_record"] = {"available": True, **summary}
        lines.append(render.kv([(f"  {k}", v) for k, v in _summary_pairs(summary)]))
    return data, "\n".join(lines)


def _record_summary(rec: dict) -> dict:
    return {
        "execution": rec["execution"],
        "status": records.text(rec, "status"),
        "start": records.text(rec, "start"),
        "events": records.number(rec, "events_processed"),
        "seconds": records.number(rec, "run_seconds"),
        "run_usd": records.number(rec, "cost", "run_usd"),
        "dq_passed": records.dig(rec, "data_quality", "passed"),
    }


def _summary_pairs(s: dict) -> list[tuple[str, object]]:
    return [
        ("execution", s["execution"]),
        ("status", s["status"]),
        ("start", _when(s["start"])),
        ("events", render.num(s["events"])),
        ("seconds", render.num(s["seconds"], 1)),
        ("run cost", render.money(s["run_usd"])),
        ("data quality passed", _pass_word(s["dq_passed"])),
    ]


def cmd_runs(ctx: Context, args: tuple) -> tuple[dict, str]:
    recs = ctx.records.records[: config.TABLE_ROWS]
    if not recs:
        raise Unavailable
    items = [_record_summary(r) for r in recs]
    rows = [
        [
            s["execution"],
            s["status"],
            _when(s["start"]),
            render.num(s["events"]),
            render.num(s["seconds"], 1),
            render.money(s["run_usd"]),
            _pass_word(s["dq_passed"]),
        ]
        for s in items
    ]
    headers = ["execution", "status", "start", "events", "seconds", "run usd", "dq pass"]
    text = render.table(headers, rows)
    if ctx.records.skipped:
        text += f"\n({ctx.records.skipped} record file(s) skipped)"
    return {"runs": items, "total": len(ctx.records.records), "skipped": ctx.records.skipped}, text


def _find_record(ctx: Context, ident: str) -> dict:
    rec = ctx.records.get(ident)
    if rec is None:
        raise NotFound
    return rec


def cmd_run(ctx: Context, args: tuple) -> tuple[dict, str]:
    ident = args[0]
    rec = _newest(ctx) if ident == "latest" else ctx.records.get(ident)
    # A known id is in the records or in the (cached) execution list. Lookup is
    # exact membership; the ARN used below is the one AWS returned.
    entry = _sfn_entry_for(ctx, rec["execution"] if rec else ident)
    if rec is None and not entry:
        raise Unavailable if entry is False else NotFound
    sfn_entry = entry or None

    data: dict = {}
    lines: list[str] = []
    if rec is not None:
        summary = _record_summary(rec)
        data["record"] = summary
        lines.append(render.kv(_summary_pairs(summary)))
        eps = records.number(rec, "events_per_second")
        extra = [
            ("events per second", render.num(eps)),
            ("silver events", render.num(records.number(rec, "silver", "events"))),
            ("silver transactions", render.num(records.number(rec, "silver", "transactions"))),
            (
                "peak active series",
                render.num(records.number(rec, "prometheus", "peak_active_series")),
            ),
        ]
        lines.append(render.kv(extra))
        data["record"].update(
            events_per_second=eps,
            silver=records.dig(rec, "silver"),
            peak_active_series=records.number(rec, "prometheus", "peak_active_series"),
        )
        state_rows = []
        for st in rec.get("states", []) if isinstance(rec.get("states"), list) else []:
            if isinstance(st, dict):
                state_rows.append(
                    [
                        st.get("state"),
                        render.num(records.number(st, "seconds"), 1),
                        render.money(records.number(st, "athena", "usd")),
                    ]
                )
        data["record"]["states"] = [
            {"state": r[0], "seconds": r[1], "athena_usd": r[2]} for r in state_rows
        ]
        lines.append("")
        lines.append(render.table(["state", "seconds", "athena usd"], state_rows))
        cost = records.dig(rec, "cost", default={})
        cost_pairs = [
            ("day", records.text(cost, "day")),
            ("day cost", render.money(records.number(cost, "usd"))),
            ("run cost", render.money(records.number(cost, "run_usd"))),
            ("per million events", render.money(records.number(cost, "usd_per_million_events"))),
            ("estimated", _pass_word(records.dig(cost, "estimated"))),
        ]
        lines.append("")
        lines.append("Cost (the collector's reading)")
        lines.append(render.kv(cost_pairs))
        dq = records.dig(rec, "data_quality")
        lines.append("")
        lines.append("Data quality")
        if isinstance(dq, dict):
            lines.append(
                render.kv(
                    [
                        ("passed", _pass_word(dq.get("passed"))),
                        ("errors", dq.get("errors")),
                        ("warnings", dq.get("warnings")),
                    ]
                )
            )
        else:
            lines.append(_NO_DQ)
    else:
        lines.append("No run record in git for this execution.")

    lines.append("")
    lines.append("Step Functions detail")
    detail = None
    if sfn_entry is not None and _within_history(sfn_entry, ctx.now):
        detail = _section(
            "execution detail", lambda: ctx.sources.sfn().execution_detail(sfn_entry["arn"])
        )
        if detail is None:
            data["sfn"] = {"available": False}
            lines.append("  " + UNAVAILABLE)
        else:
            data["sfn"] = {"available": True, **detail}
            rows = [[s.get("state"), render.num(s.get("seconds"), 1)] for s in detail["states"]]
            if rows:
                lines.append(render.table(["state", "seconds"], rows))
            if detail.get("failed_state") or detail.get("error"):
                lines.append(
                    f"failed state: {detail.get('failed_state')}; error: {detail.get('error')}"
                )
            lines.append(
                f"(history is kept {config.SFN_HISTORY_DAYS} days after an execution closes)"
            )
    elif sfn_entry is not None:
        data["sfn"] = {"available": False, "expired": True}
        lines.append(
            f"  expired: history is kept {config.SFN_HISTORY_DAYS} days after close; "
            "the record above remains"
        )
    elif entry is False:
        data["sfn"] = {"available": False}
        lines.append("  " + UNAVAILABLE)
    else:
        data["sfn"] = {"available": False}
        lines.append("  no execution found (or older than the history retention)")
    return data, "\n".join(lines)


def _sfn_entry_for(ctx: Context, name: str):
    """The list entry for an execution, None if absent, False if the list failed."""
    try:
        for ex in ctx.sources.sfn().list_executions():
            if ex.get("name") == name:
                return ex
    except Exception as exc:
        log.warning("execution list failed: %s", type(exc).__name__)
        return False
    return None


def _within_history(entry: dict, now: datetime) -> bool:
    closed = _parse(entry.get("stop")) or _parse(entry.get("start"))
    return closed is None or now - closed <= timedelta(days=config.SFN_HISTORY_DAYS)


def cmd_cost(ctx: Context, args: tuple) -> tuple[dict, str]:
    footnote = (
        "From the collector's Cost Explorer reading; this command makes no Cost Explorer call."
    )
    if args:
        rec = _find_record(ctx, args[0])
        cost = records.dig(rec, "cost")
        if not isinstance(cost, dict):
            return {
                "execution": rec["execution"],
                "cost": None,
            }, "No cost reading for this run.\n" + footnote
        by_service = records.dig(cost, "by_service", default={})
        items = sorted(
            (
                (k, v)
                for k, v in by_service.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ),
            key=lambda kv: kv[1],
            reverse=True,
        )[:8]
        pairs = [
            ("execution", rec["execution"]),
            ("day", records.text(cost, "day")),
            ("day cost", render.money(records.number(cost, "usd"))),
            ("run cost", render.money(records.number(cost, "run_usd"))),
            ("per million events", render.money(records.number(cost, "usd_per_million_events"))),
            ("estimated", _pass_word(records.dig(cost, "estimated"))),
            ("complete", _pass_word(records.dig(cost, "complete"))),
        ]
        text = render.kv(pairs) + "\n\nTop services that day\n"
        text += render.table(["service", "usd"], [[k, render.money(v)] for k, v in items])
        excl = records.text(cost, "rate_excludes")
        if excl:
            text += f"\nThe per-hour rate excludes: {excl}"
        data = {
            "execution": rec["execution"],
            "cost": {
                "day": records.text(cost, "day"),
                "usd": records.number(cost, "usd"),
                "run_usd": records.number(cost, "run_usd"),
                "usd_per_million_events": records.number(cost, "usd_per_million_events"),
                "estimated": records.dig(cost, "estimated"),
                "complete": records.dig(cost, "complete"),
                "rate_excludes": excl,
                "top_services": [{"service": k, "usd": v} for k, v in items],
            },
        }
        return data, text + "\n" + footnote
    recs = ctx.records.records[: config.TABLE_ROWS]
    if not recs:
        raise Unavailable
    rows, items = [], []
    for rec in recs:
        cost = records.dig(rec, "cost", default={})
        item = {
            "execution": rec["execution"],
            "events": records.number(rec, "events_processed"),
            "run_usd": records.number(cost, "run_usd"),
            "usd_per_million_events": records.number(cost, "usd_per_million_events"),
            "day_usd": records.number(cost, "usd"),
            "estimated": records.dig(cost, "estimated"),
            "complete": records.dig(cost, "complete"),
        }
        items.append(item)
        flags = ("estimated" if item["estimated"] else "") + (
            " complete" if item["complete"] else ""
        )
        rows.append(
            [
                item["execution"],
                render.num(item["events"]),
                render.money(item["run_usd"]),
                render.money(item["usd_per_million_events"]),
                render.money(item["day_usd"]),
                flags.strip() or "-",
            ]
        )
    headers = ["execution", "events", "run usd", "usd per M events", "day usd", "flags"]
    return {"runs": items}, render.table(headers, rows) + "\n" + footnote


_NO_DQ = "No data-quality record for this run (the suite was added in 8.4)."


def cmd_dq(ctx: Context, args: tuple) -> tuple[dict, str]:
    if args:
        rec = _find_record(ctx, args[0])
    else:
        with_dq = [r for r in ctx.records.records if isinstance(r.get("data_quality"), dict)]
        if not with_dq:
            raise Unavailable
        rec = with_dq[0]
    dq = rec.get("data_quality")
    if not isinstance(dq, dict):
        return {"execution": rec["execution"], "data_quality": None}, _NO_DQ
    checks = (
        [c for c in dq.get("checks", []) if isinstance(c, dict)]
        if isinstance(dq.get("checks"), list)
        else []
    )
    rows = [
        [
            c.get("name"),
            c.get("severity"),
            _pass_word(c.get("passed")),
            c.get("violations"),
            str(c.get("detail", ""))[:120],
        ]
        for c in checks
    ]
    head = render.kv(
        [
            ("execution", rec["execution"]),
            ("passed", _pass_word(dq.get("passed"))),
            ("errors", dq.get("errors")),
            ("warnings", dq.get("warnings")),
        ]
    )
    data = {
        "execution": rec["execution"],
        "passed": dq.get("passed"),
        "errors": dq.get("errors"),
        "warnings": dq.get("warnings"),
        "checks": [
            {
                "name": r[0],
                "severity": r[1],
                "passed": c.get("passed"),
                "violations": c.get("violations"),
                "detail": r[4],
            }
            for r, c in zip(rows, checks, strict=True)
        ],
    }
    return data, head + "\n\n" + render.table(
        ["check", "severity", "pass", "violations", "detail"], rows
    )


# The two failed runs in the records. Evidence for the SLO 1 context line below
# (checked 2026-11-02): both stopped in RunDbt (records' `states`). Neither was
# a plain "scale-up" failure, so the line says what each was.
#  - exercise-20261008T085728Z (1.05M events): the dbt task role could not read
#    the new Iceberg silver path (docs/adr/0017-iceberg-incremental-processing.md,
#    "Every role that reads silver needed the new path", found 2026-10-08). Fixed
#    in the 8.5 Iceberg work, not in 8.6.
#  - exercise-20261009T101830Z (9.0M events): Athena's 1 GiB per-query scan cutoff
#    stopped dbt's incremental fct_transactions merge (docs/scale-metrics.md,
#    "What 10M broke outside Spark"). Fixed in 8.6: the cutoff went to 10 GiB
#    (#83, commit 53218eb, 2026-10-10).
# Every run after the second failure succeeded, including 9M, 1M and 100M runs.
KNOWN_FAILURES = frozenset({"exercise-20261008T085728Z", "exercise-20261009T101830Z"})


def _slo1_context(window: list[dict]) -> list[str]:
    failed = [r for r in window if records.text(r, "status") != "SUCCEEDED"]
    if not failed:
        return []
    ids = {r["execution"] for r in failed}
    if ids != KNOWN_FAILURES:
        return [
            "Failed runs in this window: "
            + ", ".join(sorted(ids))
            + ". Type run <id> for the stage."
        ]
    last = max(str(records.text(r, "start") or "") for r in failed)
    after = [r for r in window if str(records.text(r, "start") or "") > last]
    ok = sum(1 for r in after if records.text(r, "status") == "SUCCEEDED")
    return [
        "Both failures stopped in RunDbt, and both causes were fixed: a missing dbt-role grant",
        "on the new Iceberg silver path (found 2026-10-08), and Athena's 1 GiB scan cutoff at 10M",
        "events (raised to 10 GiB in 8.6, 2026-10-10).",
        f"{ok} of {len(after)} runs since the last failure succeeded.",
        "(docs/scale-metrics.md, ADR 0017)",
    ]


def cmd_slo(ctx: Context, args: tuple) -> tuple[dict, str]:
    window = ctx.records.records[: config.SLO_WINDOW]
    if not window:
        raise Unavailable
    total = len(window)
    ok = sum(1 for r in window if records.text(r, "status") == "SUCCEEDED")
    lat = [records.number(r, "run_seconds") for r in window]
    lat = [v for v in lat if v is not None]
    fast = sum(1 for v in lat if v < config.SLO3_LIMIT_SECONDS)
    serving = []
    for r in window:
        v = records.number(records.state(r, "RunServingQuery") or {}, "athena", "engine_seconds")
        if v is not None:
            serving.append(v)
    quick = sum(1 for v in serving if v < config.SLO4_LIMIT_SECONDS)

    def slo(number, name, good, count, target):
        if count == 0:
            verdict = "n/a"
        else:
            verdict = "met" if 100.0 * good / count >= target else "not met"
        return {
            "slo": number,
            "name": name,
            "good": good,
            "total": count,
            "target_pct": target,
            "verdict": verdict,
        }

    slos = [
        slo(1, "Pipeline success", ok, total, config.SLO1_TARGET_PCT),
        slo(3, "Run latency under 30 min", fast, len(lat), config.SLO3_TARGET_PCT),
        slo(
            4, "Serving query under 30 s (engine time)", quick, len(serving), config.SLO4_TARGET_PCT
        ),
    ]
    context = _slo1_context(window)
    lines = [f"Trailing {total} run records, newest first (docs/slo.md targets)."]
    lines.append("")
    for s in slos:
        pct = 100.0 * s["good"] / s["total"] if s["total"] else 0.0
        lines.append(
            f"SLO {s['slo']} {s['name']}: {s['good']}/{s['total']} = {pct:.1f}% "
            f"(target {s['target_pct']:g}%), {s['verdict']}"
        )
        if s["slo"] == 1:
            lines.extend("  " + c for c in context)
    lines.append("SLO 5 Data quality: a dbt test failure fails the run; see SLO 1.")
    lines.append("SLO 2 and 6: measured from CloudWatch FreshnessSeconds; not available here.")
    return {"window": total, "slos": slos, "slo1_context": context}, "\n".join(lines)


HANDLERS = {
    "help": cmd_help,
    "status": cmd_status,
    "runs": cmd_runs,
    "run": cmd_run,
    "cost": cmd_cost,
    "dq": cmd_dq,
    "slo": cmd_slo,
}


def run(cmd: Command, ctx: Context) -> tuple[dict, str]:
    return HANDLERS[cmd.name](ctx, cmd.args)
