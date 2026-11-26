"""Render the launch results: six SVG charts and docs/launch-day-results.md (17.7).

OFFLINE, no AWS. Reads three things the owner collected:

  observability/launch/runs/<run_id>/   run.json, results/<name>.json (k6 summaries),
                                        results/<name>.window.json (sub-run windows), probe-p.json
  observability/launch/ledger.jsonl     the cost ledger (launch/ledger.py)
  observability/launch/extracts/        the CSVs and cost.json of launch/results_pull.py
  launch/cost_baseline.json             the November baseline through 2026-11-24

and writes six charts to docs/img/launch/ plus the doc. The output is the same
bytes for the same input: no timestamps, sorted everywhere. A number that has no
input is written "not measured" and never filled in. The chart helpers (the SVG
frame and the palette) come from observability/scale/charts.py.

    python3 launch/results_render.py [--runs DIR] [--ledger FILE] [--extracts DIR]
        [--baseline FILE] [--doc FILE] [--img-dir DIR]
"""

# ruff: noqa: E501 -- SVG markup in f-strings reads better on one line each.

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import ledger as ledger_mod  # noqa: E402


def _charts():
    spec = importlib.util.spec_from_file_location(
        "scale_charts", ROOT / "observability" / "scale" / "charts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


charts = _charts()

NM = "not measured"
TARGET_GBPS = 33030  # the launch plan's total exchange peak (33.03 Tbps)
ACCOUNT_USD = Decimal("40")  # ADR 0030: the account ceiling
ATTRIB_USD = ledger_mod.STOP_USD  # ADR 0030 Decision 12: the $25 stop rule
IMAGES = {
    "release": "release-window.svg",
    "isp": "isp-heatmap.svg",
    "cache": "cache-offload.svg",
    "ttfb": "ttfb.svg",
    "cost": "cost.svg",
    "scale": "scale.svg",
}
EXTRA_STYLE = """
  .ln1 { stroke: #2a78d6; fill: none; stroke-width: 1.5; }
  .ln2 { stroke: #eb6834; fill: none; stroke-width: 1.5; }
  .t0 { stroke: #898781; stroke-dasharray: 3 3; }
  @media (prefers-color-scheme: dark) {
    .ln1 { stroke: #3987e5; }
    .ln2 { stroke: #d95926; }
  }
"""
RUN_ID = re.compile(r"^[a-z0-9-]{1,40}$")
EXTRACT_NAMES = ("release_window", "isp_minute", "cdn_run", "cdn_minute", "cdn_class", "cdn_subrun")


# ---------------------------------------------------------------- loading


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def read_window(path: Path):
    """(start_ms, end_ms) from a window file, or None when it is not two whole numbers in order."""
    item = read_json(path)
    if not isinstance(item, dict):
        return None
    start, end = item.get("start_ms"), item.get("end_ms")
    if any(type(v) is not int or v <= 0 for v in (start, end)) or end < start:
        return None
    return start, end


def load_runs(directory: Path) -> dict:
    """run_id -> {"record", "kind", "results": {name: summary}, "windows": {name: (start_ms, end_ms)}, "probe"}.

    A *.window.json file is a sub-run window, never a k6 summary. Unreadable parts are None or left out.
    """
    runs = {}
    if not directory.is_dir():
        return runs
    for sub in sorted(p for p in directory.iterdir() if p.is_dir()):
        record = read_json(sub / "run.json")
        if not isinstance(record, dict) or not RUN_ID.match(sub.name):
            continue
        results, windows = {}, {}
        for path in sorted((sub / "results").glob("*.json")):
            if path.name.endswith(".window.json"):
                window = read_window(path)
                if window:
                    windows[path.name[: -len(".window.json")]] = window
                continue
            summary = read_json(path)
            if isinstance(summary, dict) and isinstance(summary.get("metrics"), dict):
                results[path.stem] = summary
        probe = read_json(sub / "probe-p.json")
        runs[sub.name] = {
            "record": record,
            "kind": "exercise" if record.get("kind") == "exercise" else "session",
            "results": results,
            "windows": windows,
            "probe": probe
            if isinstance(probe, dict) and isinstance(probe.get("metrics"), dict)
            else None,
        }
    return runs


def load_ledger(path: Path) -> dict:
    """run_id -> {"kind", "estimate", "usd", "gb"}; the corrected value replaces the estimate."""
    entries: dict[str, dict] = {}
    if not path.exists():
        return entries
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if item["event"] == "record":
                est = Decimal(str(item["estimate_usd"]))
                entries[item["run_id"]] = {
                    "kind": item.get("kind", "session"),
                    "estimate": est,
                    "usd": est,
                    "gb": Decimal(str(item.get("gb", 0))),
                }
            elif item["event"] == "correct":
                entries[item["run_id"]]["usd"] = Decimal(str(item["usd"]))
        except (ValueError, KeyError, InvalidOperation, TypeError):
            continue
    return entries


def load_extracts(directory: Path) -> dict:
    """{"rows": {name: [dict] or None}, "manifest": dict or None, "cost": dict or None}."""
    rows = {}
    for name in EXTRACT_NAMES:
        path = directory / f"{name}.csv"
        if path.exists():
            with path.open(newline="") as handle:
                rows[name] = list(csv.DictReader(handle))
        else:
            rows[name] = None
    return {
        "rows": rows,
        "manifest": read_json(directory / "manifest.json"),
        "cost": read_json(directory / "cost.json"),
    }


def read_baseline(path: Path):
    try:
        return ledger_mod.read_baseline(path)
    except (ledger_mod.LedgerError, OSError):
        return None


# ---------------------------------------------------------------- small helpers


def num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def dec(value):
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def iso(ms) -> str:
    """Epoch milliseconds to an ISO UTC string; NM when it is not a number."""
    value = num(ms)
    if value is None or value <= 0:
        return NM
    return datetime.fromtimestamp(value / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def usd(value) -> str:
    return NM if value is None else f"${value.quantize(Decimal('0.01'))}"


def cell(value, spec="") -> str:
    return NM if value is None else format(value, spec)


def esc(text) -> str:
    return charts.esc(text)


def txt(x, y, text, cls="ink2 l", anchor=None) -> str:
    extra = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text class="{cls}" x="{x}" y="{y}"{extra}>{esc(text)}</text>'


def frame(width, height, title, subtitle, body) -> str:
    out = charts.svg(width, height, title, subtitle, body)
    return out.replace("</style>", EXTRA_STYLE + "</style>", 1)


def nm_chart(what: str, why: str) -> str:
    return frame(760, 110, f"{what}: {NM}", why, txt(20, 90, NM, "ink t"))


# ---------------------------------------------------------------- facts (shared by charts and doc)


def release_facts(rows):
    if not rows:
        return None
    by: dict[str, dict[int, int]] = {}
    early = 0
    for r in rows:
        minute, granted = num(r.get("minutes_from_release")), num(r.get("licenses_granted"))
        if minute is None or granted is None or not r.get("region"):
            continue
        series = by.setdefault(r["region"], {})
        series[int(minute)] = series.get(int(minute), 0) + int(granted)
        early += int(num(r.get("early_license_denials")) or 0)
    if not by:
        return None
    regions = {k: sorted(v.items()) for k, v in sorted(by.items())}
    return {
        "regions": regions,
        "granted": sum(v for pts in regions.values() for _, v in pts),
        "peak": max(v for pts in regions.values() for _, v in pts),
        "early_denials": early,
    }


def isp_facts(rows):
    if not rows:
        return None
    cells: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}
    for r in rows:
        gbps = num(r.get("modelled_gbps"))
        if gbps is None or not r.get("isp") or not r.get("minute_at"):
            continue
        minute = r["minute_at"][:16]
        cells.setdefault(r["isp"], {})
        cells[r["isp"]][minute] = cells[r["isp"]].get(minute, 0.0) + gbps
        totals[minute] = totals.get(minute, 0.0) + gbps
    if not cells:
        return None
    peaks = {isp: max(v.values()) for isp, v in cells.items()}
    top = max(sorted(peaks), key=lambda k: peaks[k])
    top_minute = max(sorted(cells[top]), key=lambda m: cells[top][m])
    total_minute = max(sorted(totals), key=lambda m: totals[m])
    return {
        "cells": cells,
        "peaks": peaks,
        "top": top,
        "top_peak": peaks[top],
        "top_minute": top_minute,
        "total_peak": totals[total_minute],
        "total_minute": total_minute,
    }


def hold_runs(runs) -> list[str]:
    return sorted(
        rid for rid, r in runs.items() if r["kind"] == "session" and r["record"].get("hold") is True
    )


def cache_facts(rows, runs):
    holds = hold_runs(runs)
    if not rows or not holds:
        return None
    agg: dict[tuple[str, str], list[int]] = {}
    for r in rows:
        if r.get("run_id") not in holds:
            continue
        h, rh, m = (num(r.get(k)) for k in ("hits", "refresh_hits", "origin_misses"))
        if None in (h, rh, m) or not r.get("pop") or not r.get("uri_class"):
            continue
        slot = agg.setdefault((r["pop"], r["uri_class"]), [0, 0])
        slot[0] += int(h)
        slot[1] += int(h + rh + m)
    if not agg:
        return None
    ratios = {k: (v[0] / v[1] if v[1] else None) for k, v in sorted(agg.items())}
    hits, looked = sum(v[0] for v in agg.values()), sum(v[1] for v in agg.values())
    return {
        "holds": holds,
        "ratios": ratios,
        "pops": sorted({p for p, _ in agg}),
        "overall": hits / looked if looked else None,
    }


def pick(metrics: dict, name: str, keys=("p(50)", "med")):
    entry = metrics.get(name)
    if not isinstance(entry, dict):
        return None
    for key in keys:
        value = num(entry.get(key))
        if value is not None:
            return value
    return None


def p50(metrics, name):
    return pick(metrics, name, ("p(50)", "med"))


def p99(metrics, name):
    return pick(metrics, name, ("p(99)",))


def reqs(summary) -> float:
    value = num(summary["metrics"].get("http_reqs", {}).get("count")) if summary else None
    return value or 0.0


def ttfb_facts(runs, cdn_run_rows):
    client = []
    for rid, run in sorted(runs.items()):
        if run["kind"] != "session":
            continue
        best = max(
            (run["results"][k] for k in sorted(run["results"])), key=reqs, default=None
        )  # the summary with most requests: percentiles cannot be added up
        inst = (
            (p50(best["metrics"], "http_req_waiting"), p99(best["metrics"], "http_req_waiting"))
            if best
            else (None, None)
        )
        probe = (
            (
                p50(run["probe"]["metrics"], "http_req_waiting"),
                p99(run["probe"]["metrics"], "http_req_waiting"),
            )
            if run["probe"]
            else (None, None)
        )
        if inst != (None, None) or probe != (None, None):
            client.append({"run": rid, "instance": inst, "probe": probe})
    server = None
    if cdn_run_rows:
        alls = [r for r in cdn_run_rows if r.get("pop") == "ALL" and num(r.get("requests"))]
        if alls:
            top = max(sorted(alls, key=lambda r: r["run_id"]), key=lambda r: num(r["requests"]))
            pops = [
                (r["pop"], num(r.get("server_ttfb_p50_ms")), num(r.get("server_ttfb_p99_ms")))
                for r in sorted(cdn_run_rows, key=lambda r: r.get("pop", ""))
                if r.get("run_id") == top["run_id"] and r.get("pop") != "ALL"
            ]
            pops = [p for p in pops if p[1] is not None or p[2] is not None]
            if pops:
                server = {"run": top["run_id"], "pops": pops}
    return {"client": client, "server": server}


def measured_peak(rows):
    best = None
    for r in rows or []:
        mb = num(r.get("bytes_mb"))
        if mb is None:
            continue
        gbps = mb * 1e6 * 8 / 60 / 1e9
        key = (gbps, r.get("run_id", ""), r.get("minute_at", ""))
        if best is None or key > best:
            best = key
    return None if best is None else {"gbps": best[0], "run": best[1], "minute": best[2][:16]}


# ---------------------------------------------------------------- cost


def day_of(run) -> str | None:
    record = run["record"]
    if run["kind"] == "session":
        text = iso(record.get("window_start_ms"))
        return None if text == NM else text[:10]
    stamp = str(record.get("started", ""))
    match = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", stamp)
    return "-".join(match.groups()) if match else None


def cost_read(entries: dict, cost, baseline) -> dict:
    """The cost arithmetic. entries: run_id -> {kind, estimate, usd, gb, date}.

    attributable = Cost Explorer November Usage minus the baseline, against $25.
    The account total is the November Usage total, against $40. The ledger sum is
    shown beside them and never added. A run's Cost Explorer day is given only
    when it is the only ledger run on that date."""
    total = dec(cost.get("month_total_usd")) if isinstance(cost, dict) else None
    daily = (
        cost.get("daily")
        if isinstance(cost, dict) and isinstance(cost.get("daily"), list)
        else None
    )
    per_day: dict[str, Decimal] = {}
    for item in daily or []:
        value = dec(item.get("usd")) if isinstance(item, dict) else None
        if value is not None and item.get("date"):
            per_day[item["date"]] = per_day.get(item["date"], Decimal(0)) + value
    on_day: dict[str, int] = {}
    for item in entries.values():
        if item.get("date"):
            on_day[item["date"]] = on_day.get(item["date"], 0) + 1
    per_run = []
    for rid in sorted(entries):
        item = entries[rid]
        date = item.get("date")
        if daily is None:
            ce_day, why = None, NM
        elif not date or on_day.get(date, 0) != 1:
            ce_day, why = (
                None,
                f"not separable ({on_day.get(date, 0)} runs that day)"
                if date
                else "not separable (no date)",
            )
        elif date not in per_day:
            # Zero rows are dropped and Cost Explorer lags, so no row is not $0.
            ce_day, why = None, "no Cost Explorer row yet"
        else:
            ce_day, why = per_day[date], ""
        per_run.append(
            {
                "run_id": rid,
                "kind": item["kind"],
                "date": date,
                "estimate": item["estimate"],
                "corrected": item["usd"],
                "ce_day": ce_day,
                "ce_day_note": why,
            }
        )
    attributable = total - baseline if total is not None and baseline is not None else None
    return {
        "per_run": per_run,
        "nov_total": total,
        "baseline": baseline,
        "attributable": attributable,
        "attributable_status": NM
        if attributable is None
        else (
            "within the $25 stop rule" if attributable <= ATTRIB_USD else "OVER the $25 stop rule"
        ),
        "account_total": total,
        "account_status": NM
        if total is None
        else ("within the $40 ceiling" if total <= ACCOUNT_USD else "OVER the $40 ceiling"),
        "ledger_sum": sum((i["usd"] for i in entries.values()), Decimal(0)),
    }


def subrun_facts(rows, runs):
    """HOLD-run sub-runs from the cdn_subrun extract, with the hit ratio of each; None without rows.

    Run D is a cold patch (d-0, 50 clients at T0) then a warm repeat (d-1, one client).
    """
    holds = hold_runs(runs)
    if not rows or not holds:
        return None
    items = []
    for r in rows:
        if r.get("run_id") not in holds or not r.get("sub_run"):
            continue
        h, rh, m, n = (num(r.get(k)) for k in ("hits", "refresh_hits", "origin_misses", "requests"))
        if None in (h, rh, m, n):
            continue
        looked = h + rh + m
        window = runs[r["run_id"]].get("windows", {}).get(r["sub_run"])
        items.append(
            {
                "run": r["run_id"],
                "sub_run": r["sub_run"],
                "requests": int(n),
                "hits": int(h),
                "misses": int(m),
                "ratio": h / looked if looked else None,
                "window": window,
            }
        )
    if not items:
        return None
    items.sort(key=lambda i: (i["run"], i["sub_run"]))
    by_name = {i["sub_run"]: i for i in items if i["run"] == holds[0]} or {
        i["sub_run"]: i for i in items
    }
    return {"items": items, "cold": by_name.get("d-0"), "warm": by_name.get("d-1")}


def k6_bytes_of(summary) -> float:
    return sum(
        num(summary["metrics"].get(k, {}).get("count")) or 0.0
        for k in ("bytes_build", "bytes_patch", "bytes_licence")
    )


def bytes_facts(runs):
    """Per session: planned, the nftables budget, k6 bytes (instance, probe P) and the CloudWatch sum."""
    out = []
    for rid, run in sorted(runs.items()):
        if run["kind"] != "session":
            continue
        rec = run["record"]
        planned_gb = dec(rec.get("planned_gb"))
        budget = num(rec.get("budget_bytes"))
        cw = num(rec.get("cloudwatch_bytes_downloaded"))
        instance = (
            sum(k6_bytes_of(sm) for sm in run["results"].values()) if run["results"] else None
        )
        probe = k6_bytes_of(run["probe"]) if run["probe"] else None
        out.append(
            {
                "run": rid,
                "planned": float(planned_gb * 10**9) if planned_gb is not None else None,
                "budget": budget if budget and budget > 0 else None,
                "instance": instance,
                "probe": probe,
                "cloudwatch": cw if cw is not None and cw >= 0 else None,
            }
        )
    return out


def gb(value) -> str:
    return NM if value is None else f"{value / 1e9:.3f} GB"


def cost_facts(runs, entries, cost, baseline):
    dated = {
        rid: {**item, "date": day_of(runs[rid]) if rid in runs else None}
        for rid, item in entries.items()
    }
    read = cost_read(dated, cost, baseline)
    k6_bytes = 0.0
    planned = Decimal(0)
    for run in runs.values():
        if run["kind"] != "session":
            continue
        planned += dec(run["record"].get("planned_gb")) or Decimal(0)
        parts = [*run["results"].values(), *([run["probe"]] if run["probe"] else [])]
        for summary in parts:
            k6_bytes += k6_bytes_of(summary)
    attributable = read["attributable"]
    per_gb, basis = None, NM
    if attributable is not None and k6_bytes > 0:
        per_gb, basis = (
            attributable / (Decimal(str(k6_bytes)) / Decimal(10**9)),
            "all attributable spend / k6 bytes (upper bound)",
        )
    elif attributable is not None and planned > 0:
        per_gb, basis = (
            attributable / planned,
            "all attributable spend / planned GB (fallback, not measured bytes)",
        )
    ex_usd, ex_events = Decimal(0), 0
    for rid, item in sorted(entries.items()):
        if item["kind"] == "exercise" and rid in runs:
            events = int(num(runs[rid]["record"].get("events_requested")) or 0)
            if events > 0:
                ex_usd += item["usd"]
                ex_events += events
    per_million = ex_usd / Decimal(ex_events) * 1_000_000 if ex_events else None
    return {
        "read": read,
        "k6_gb": k6_bytes / 1e9,
        "per_gb": per_gb,
        "per_gb_basis": basis,
        "per_million": per_million,
        "exercise_events": ex_events,
    }


# ---------------------------------------------------------------- charts


def chart_release(facts) -> str:
    what = "Release window"
    if not facts:
        return nm_chart(what, "The release_window extract is missing.")
    regions = facts["regions"]
    pw, ph, cols = 112, 56, 6
    minutes = [m for pts in regions.values() for m, _ in pts]
    lo, hi = min(minutes), max(minutes)
    span = max(hi - lo, 1)
    ymax = max(facts["peak"], 1)
    body = []
    rows = math.ceil(len(regions) / cols)
    for idx, (region, pts) in enumerate(regions.items()):
        px, py = 20 + (idx % cols) * (pw + 12), 74 + (idx // cols) * (ph + 36)
        match = re.match(r"region_(\d+)$", region)
        label = f"UTC{int(match.group(1)) - 12:+d}" if match else region
        body.append(txt(px, py, label, "ink2 st"))
        top = py + 8
        body.append(
            f'<line class="axis" x1="{px}" y1="{top + ph}" x2="{px + pw}" y2="{top + ph}"/>'
        )
        if lo <= 0 <= hi:
            x0 = px + (0 - lo) / span * pw
            body.append(
                f'<line class="t0" x1="{x0:.1f}" y1="{top}" x2="{x0:.1f}" y2="{top + ph}"/>'
            )
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{px + (m - lo) / span * pw:.1f},{top + ph - v / ymax * ph:.1f}"
            for i, (m, v) in enumerate(pts)
        )
        body.append(f'<path class="ln1" stroke="#2a78d6" fill="none" d="{path}"/>')
    height = 74 + rows * (ph + 36) + 20
    body.append(
        txt(
            20,
            height - 12,
            f"Dashed line = T0, the region's local midnight. Same scale in every panel (top = {ymax} licences granted per minute).",
            "muted st",
        )
    )
    title = f"{facts['granted']:,} licences granted across {len(regions)} release zones, each opening at its own midnight (T0)"
    return frame(
        760,
        height,
        title,
        "synthetic telemetry (generated clients, not real players). Licences granted per minute.",
        "\n".join(body),
    )


def chart_isp_heatmap(facts) -> str:
    what = "ISP heatmap"
    if not facts:
        return nm_chart(what, "The isp_minute extract is missing.")
    chosen = sorted(facts["peaks"], key=lambda k: (-facts["peaks"][k], k))[:20]
    minutes = sorted({m for isp in chosen for m in facts["cells"][isp]})
    step = math.ceil(len(minutes) / 150)
    bins = [minutes[i : i + step] for i in range(0, len(minutes), step)]
    vmax = max(facts["peaks"][i] for i in chosen) or 1.0
    cw, ch, x0, y0 = 560 / len(bins), 18, 170, 74
    body = []
    for r, isp in enumerate(chosen):
        y = y0 + r * (ch + 2)
        body.append(txt(x0 - 8, y + 13, isp, "ink2 st", "end"))
        for c, group in enumerate(bins):
            v = max(facts["cells"][isp].get(m, 0.0) for m in group)
            opacity = 0.06 + 0.94 * v / vmax
            body.append(
                f'<rect class="s1" fill-opacity="{opacity:.2f}" x="{x0 + c * cw:.2f}" y="{y}" width="{cw + 0.3:.2f}" height="{ch}"/>'
            )
    yb = y0 + len(chosen) * (ch + 2) + 14
    body.append(txt(x0, yb, minutes[0][11:16] + " UTC", "muted st"))
    body.append(txt(x0 + 560, yb, minutes[-1][11:16] + " UTC", "muted st", "end"))
    body.append(
        txt(x0 + 280, yb, f"darker = more Gbps (full dark = {vmax:.2f} Gbps)", "muted st", "middle")
    )
    title = f"Modelled: {facts['top']} peaks at {facts['top_peak']:.2f} Gbps at {facts['top_minute'][11:16]} UTC"
    return frame(
        760,
        yb + 24,
        title,
        "modelled, not measured: each transfer's bytes are spread evenly over its duration. Synthetic telemetry.",
        "\n".join(body),
    )


def chart_cache(facts, subrun=None) -> str:
    what = "Cache hit ratio"
    if not facts:
        return nm_chart(what, "It needs a HOLD run and the cdn_class extract.")
    classes = [("build", "s1"), ("patch", "s2"), ("other", "s3")]
    body, y = [], 78
    for pop in facts["pops"]:
        body.append(txt(20, y + 4, pop, "ink t"))
        for cls, color in classes:
            ratio = facts["ratios"].get((pop, cls))
            y += 22
            body.append(txt(60, y + 12, cls, "ink2 st"))
            if ratio is None:
                body.append(txt(120, y + 12, NM, "muted st"))
                continue
            body.append(charts.bar(120, y, max(ratio, 0) * 520, 16, color, True))
            body.append(txt(120 + ratio * 520 + 8, y + 13, f"{ratio:.1%}", "ink st"))
        y += 30
    title = (
        f"{facts['overall']:.1%} of requests were answered by the edge cache"
        if facts["overall"] is not None
        else "Cache hit ratio per POP"
    )
    sub = "Request-based offload: hits / (hits + refresh hits + misses), by URI class. Single metro, 50 virtual clients. HOLD run only."
    # Run D: cold (50 clients at T0) against warm (one-client repeat).
    body.append(txt(20, y + 4, "Run D patch: cold vs warm", "ink t"))
    for label, key, color in (("cold (d-0)", "cold", "s2"), ("warm (d-1)", "warm", "s1")):
        item = subrun and subrun.get(key)
        y += 22
        body.append(txt(60, y + 12, label, "ink2 st"))
        if not item or item["ratio"] is None:
            body.append(txt(150, y + 12, NM, "muted st"))
            continue
        body.append(charts.bar(150, y, max(item["ratio"], 0) * 490, 16, color, True))
        body.append(txt(150 + item["ratio"] * 490 + 8, y + 13, f"{item['ratio']:.1%}", "ink st"))
    y += 30
    return frame(760, y + 20, title, sub, "\n".join(body))


def chart_ttfb(facts) -> str:
    what = "Time to first byte"
    if not facts["client"] and not facts["server"]:
        return nm_chart(what, "No k6 summary and no cdn_run extract.")
    body = [txt(20, 76, "Client: k6 http_req_waiting (ms)", "ink t")]
    y = 90
    cmax = max(
        [
            v
            for c in facts["client"]
            for pair in (c["instance"], c["probe"])
            for v in pair
            if v is not None
        ]
        or [1.0]
    )
    if not facts["client"]:
        body.append(txt(20, y + 14, NM, "muted st"))
        y += 24
    for c in facts["client"]:
        for label, pair in (("instance", c["instance"]), ("probe P", c["probe"])):
            for tag, value, color in (("p50", pair[0], "s1"), ("p99", pair[1], "s2")):
                body.append(txt(20, y + 12, f"{c['run']} {label} {tag}", "ink2 st"))
                if value is None:
                    body.append(txt(250, y + 12, NM, "muted st"))
                else:
                    body.append(charts.bar(250, y, value / cmax * 380, 14, color, True))
                    body.append(txt(250 + value / cmax * 380 + 6, y + 12, f"{value:.0f}", "ink st"))
                y += 18
        y += 6
    y += 14
    body.append(
        txt(
            20, y, "Server: CloudFront time to first byte per POP (ms), from the edge logs", "ink t"
        )
    )
    y += 14
    server = facts["server"]
    if not server:
        body.append(txt(20, y + 14, NM, "muted st"))
        y += 24
    else:
        smax = max([v for _, a, b in server["pops"] for v in (a, b) if v is not None] or [1.0])
        for pop, a, b in server["pops"]:
            for tag, value, color in (("p50", a, "s1"), ("p99", b, "s2")):
                body.append(txt(20, y + 12, f"{pop} {tag}", "ink2 st"))
                if value is None:
                    body.append(txt(250, y + 12, NM, "muted st"))
                else:
                    body.append(charts.bar(250, y, value / smax * 380, 14, color, True))
                    body.append(txt(250 + value / smax * 380 + 6, y + 12, f"{value:.0f}", "ink st"))
                y += 18
            y += 6
    worst_c = max(
        [c["instance"][1] for c in facts["client"] if c["instance"][1] is not None] or [None],
        key=lambda v: -1 if v is None else v,
    )
    worst_s = (
        max(
            [b for _, _, b in server["pops"] if b is not None] or [None],
            key=lambda v: -1 if v is None else v,
        )
        if server
        else None
    )
    title = f"Client wait p99 {cell(worst_c, '.0f')} ms and edge TTFB p99 {cell(worst_s, '.0f')} ms are two clocks, never added"
    return frame(
        760,
        y + 20,
        title,
        "The client panel is what a player waits; the server panel is the edge's own clock. They are never mixed. Blue = p50, orange = p99.",
        "\n".join(body),
    )


def chart_cost(facts) -> str:
    read = facts["read"]
    body = [txt(20, 76, "Spend against the two limits", "ink t")]
    y = 90
    for label, value, limit in (
        ("Attributable", read["attributable"], ATTRIB_USD),
        ("Account total", read["account_total"], ACCOUNT_USD),
    ):
        body.append(txt(20, y + 13, label, "ink2 st"))
        if value is None:
            body.append(txt(150, y + 13, NM, "muted st"))
        else:
            width = min(float(value / limit), 1.0) * 400
            body.append(f'<rect class="grid" x="150" y="{y}" width="400" height="16" rx="3"/>')
            body.append(
                charts.bar(150, y, max(width, 0.5), 16, "s1" if value <= limit else "s2", True)
            )
            body.append(txt(560, y + 13, f"{usd(value)} of ${limit}", "ink st"))
        y += 28
    body.append(
        txt(
            20,
            y + 8,
            f"Ledger sum {usd(read['ledger_sum'])} is shown beside these, not added to them.",
            "muted st",
        )
    )
    y += 40
    body.append(txt(20, y, "Unit costs", "ink t"))
    y += 22
    body.append(
        txt(
            20,
            y,
            f"Per GB: {usd(facts['per_gb']) if facts['per_gb'] is not None else NM} ({facts['per_gb_basis']}; {facts['k6_gb']:.2f} GB in k6 counters)",
            "ink2 l",
        )
    )
    y += 20
    pm = facts["per_million"]
    body.append(
        txt(
            20,
            y,
            f"Per million events: {usd(pm) if pm is not None else NM} (exercise ledger cost / events requested)",
            "ink2 l",
        )
    )
    if read["attributable"] is not None:
        title = f"Launch spend {usd(read['attributable'])} of ${ATTRIB_USD}: {read['attributable_status']}"
    else:
        title = f"Launch spend against Cost Explorer: {NM}"
    return frame(
        760,
        y + 24,
        title,
        "Cost Explorer Usage (credits excluded) minus the baseline through 2026-11-24. Finance reads the bars; engineers read the unit costs.",
        "\n".join(body),
    )


def chart_scale(measured, modelled) -> str:
    rows = [
        ("Measured, one region (edge logs)", measured["gbps"] if measured else None, "s1"),
        ("Modelled, all ISPs (synthetic)", modelled, "s2"),
        ("Total exchange peak (plan figure)", float(TARGET_GBPS), "s4"),
    ]
    lo, hi = -2.0, math.log10(TARGET_GBPS) + 0.3
    body, y = [], 82
    for label, value, color in rows:
        body.append(txt(20, y + 13, label, "ink2 st"))
        if value is None or value <= 0:
            body.append(txt(260, y + 13, NM, "muted st"))
        else:
            width = (min(max(math.log10(value), lo), hi) - lo) / (hi - lo) * 380
            body.append(charts.bar(260, y, max(width, 0.5), 16, color, True))
            body.append(txt(260 + width + 8, y + 13, f"{value:,.2f} Gbps", "ink st"))
        y += 30
    body.append(
        txt(
            20,
            y + 6,
            "Log scale. Measured and modelled are separate numbers and are never added.",
            "muted st",
        )
    )
    if measured:
        title = f"Measured peak {measured['gbps']:.2f} Gbps is {measured['gbps'] / TARGET_GBPS:.4%} of the 33,030 Gbps exchange peak"
    else:
        title = f"Measured peak Gbps against the 33,030 Gbps exchange peak: {NM}"
    return frame(
        760,
        y + 30,
        title,
        "one region; 33.03 Tbps is a total exchange peak. This run shows the shape, not the size.",
        "\n".join(body),
    )


# ---------------------------------------------------------------- the doc


def table(header, rows) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def subrun_doc(subrun) -> list[str]:
    if not subrun:
        return [f"Run D cold against warm: {NM} [extracts/cdn_subrun.csv, results/*.window.json]."]
    rows = []
    for i in subrun["items"]:
        w = i["window"]
        rows.append(
            (
                f"`{i['run']}`",
                i["sub_run"],
                f"{iso(w[0])} to {iso(w[1])}" if w else NM,
                f"{i['requests']:,}",
                f"{i['hits']:,}",
                f"{i['misses']:,}",
                f"{i['ratio']:.1%}" if i["ratio"] is not None else NM,
            )
        )
    lines = [
        "Run D is a cold patch (`d-0`, 50 clients at T0) then a warm repeat (`d-1`, one client). Edge results inside each sub-run window:",
        "",
        table(
            ["Run", "Sub-run", "Window (UTC)", "Requests", "Hits", "Origin misses", "Hit ratio"],
            rows,
        ),
        "",
        "[extracts/cdn_subrun.csv, results/*.window.json]",
    ]
    cold, warm = subrun["cold"], subrun["warm"]
    if cold and warm and cold["ratio"] is not None and warm["ratio"] is not None:
        lines += [
            "",
            f"Cold {cold['ratio']:.1%}, warm {warm['ratio']:.1%} [extracts/cdn_subrun.csv].",
        ]
    else:
        lines += [
            "",
            f"Run D cold against warm: {NM} (`d-0` or `d-1` has no rows) [extracts/cdn_subrun.csv].",
        ]
    return lines


def bytes_doc(facts) -> list[str]:
    rows = []
    notes = []
    for f in facts:
        rows.append(
            (
                f"`{f['run']}`",
                gb(f["planned"]),
                gb(f["budget"]),
                gb(f["instance"]),
                gb(f["probe"]),
                gb(f["cloudwatch"]),
            )
        )
        if f["instance"] is None or f["budget"] is None:
            notes.append(
                f"`{f['run']}`: nftables quota comparison {NM} (no k6 summary or no budget)."
            )
        else:
            state = "within" if f["instance"] <= f["budget"] else "over"
            notes.append(
                f"`{f['run']}`: instance k6 body bytes {gb(f['instance'])} are {f['instance'] / f['budget']:.1%} of the nftables quota {gb(f['budget'])}: {state} the quota (nft also counts headers, the seed and SSM, so this reads slightly low)."
            )
    out = [
        table(
            [
                "Run",
                "Planned [run.json planned_gb]",
                "Budget = nftables quota [run.json budget_bytes]",
                "k6 bytes, instance [results/*.json]",
                "k6 bytes, probe P [probe-p.json]",
                "CloudWatch BytesDownloaded [run.json]",
            ],
            rows,
        )
        if rows
        else NM,
        "",
        "Planned GB include probe P. The budget is the planned instance bytes x 1.10 and is the quota the instance enforced (`launch/plan_bytes.py`). CloudWatch is the highest sum the layer 4 poll read; it lags, so a short run can read low or "
        + NM
        + ". It is an independent count of what the edge sent: compare it with k6 bytes of instance and probe P together.",
        "",
        *notes,
    ]
    return out


def render_doc(ctx: dict, img_rel: str) -> str:
    runs, ex = ctx["runs"], ctx["extracts"]
    out = [
        "# Launch-day results",
        "",
        "Written by `launch/results_render.py` from the run records, the cost ledger and the extracts of `launch/results_pull.py`. "
        f'A number with no input reads "{NM}". Each number carries a source tag in square brackets.',
        "",
    ]
    manifest = ex["manifest"]
    if manifest:
        out.append(
            f"Extracts: exercise run `{manifest.get('exercise_run_id', NM)}`, sessions "
            f"{', '.join('`' + s + '`' for s in manifest.get('session_run_ids', [])) or NM}, pulled {manifest.get('pull_date', NM)} [extracts/manifest.json]."
        )
    else:
        out.append(f"Extracts: {NM} [extracts/manifest.json is missing].")
    out += ["", "## The runs", ""]
    rows = []
    for rid, run in sorted(runs.items()):
        rec = run["record"]
        if run["kind"] == "session":
            rows.append(
                (
                    f"`{rid}`",
                    rec.get("scenario", NM),
                    "yes" if rec.get("hold") is True else "no",
                    iso(rec.get("window_start_ms")),
                    iso(rec.get("window_end_ms")),
                    cell(rec.get("k6_requests")),
                    cell(rec.get("curl_requests")),
                )
            )
    out.append(
        table(
            ["Run", "Scenario", "HOLD", "Start (UTC)", "End (UTC)", "k6 requests", "curl requests"],
            rows,
        )
        if rows
        else NM
    )
    out += [
        "",
        "[run.json] The session's own `curl` checks also reach the edge, so the CDN logs of a small run (Run A) read a few lines higher than the k6 request count (`launch_session.sh`, `curl_requests`).",
        "",
    ]

    rel = release_facts(ex["rows"]["release_window"])
    out += [
        f"## 1. Release window ({'synthetic telemetry'})",
        "",
        f"![Release window]({img_rel}/{IMAGES['release']})",
        "",
    ]
    out.append(
        f"For everyone: a release does not hit all players at once. Each zone opens at its own midnight, so demand arrives in waves, one per zone. "
        f"Licences granted: {cell(rel and rel['granted'], ',')}; busiest minute in one zone: {cell(rel and rel['peak'])}; "
        f"licence requests refused before release: {cell(rel and rel['early_denials'])} [extracts/release_window.csv]."
    )
    isp = isp_facts(ex["rows"]["isp_minute"])
    out += ["", "## 2. ISP load (modelled)", "", f"![ISP heatmap]({img_rel}/{IMAGES['isp']})", ""]
    out.append(
        "For network and capacity planning: which ISP would carry the most traffic, and when. This is modelled from synthetic telemetry, not measured. "
        f"Busiest ISP: {isp['top'] if isp else NM} at {cell(isp and isp['top_peak'], '.2f')} Gbps, {isp['top_minute'] + ' UTC' if isp else NM}; "
        f"all ISPs together peak at {cell(isp and isp['total_peak'], '.2f')} Gbps [extracts/isp_minute.csv]."
    )
    cache = cache_facts(ex["rows"]["cdn_class"], runs)
    subrun = subrun_facts(ex["rows"]["cdn_subrun"], runs)
    out += [
        "",
        "## 3. Cache offload (single metro, 50 virtual clients)",
        "",
        f"![Cache hit ratio]({img_rel}/{IMAGES['cache']})",
        "",
    ]
    if cache:
        crow = [
            (pop, cls, f"{r:.1%}" if r is not None else NM)
            for (pop, cls), r in cache["ratios"].items()
        ]
        out.append(
            "For finance and operations: every request the cache answers is a request the origin does not pay for. Request-based offload by POP and URI class, HOLD run(s) "
            + ", ".join(f"`{h}`" for h in cache["holds"])
            + " [extracts/cdn_class.csv, run.json]."
        )
        out += ["", table(["POP", "URI class", "Hit ratio"], crow)]
        out += ["", *subrun_doc(subrun)]
    else:
        out.append(
            f"For finance and operations: cache offload is {NM}. It needs a HOLD run and the cdn_class extract."
        )
        out += ["", *subrun_doc(subrun)]
    ttfb = ttfb_facts(runs, ex["rows"]["cdn_run"])
    out += [
        "",
        "## 4. Time to first byte",
        "",
        f"![Time to first byte]({img_rel}/{IMAGES['ttfb']})",
        "",
    ]
    out.append(
        "For product and operations: how long a player waits before data starts. The client numbers and the server numbers use different clocks and are never mixed."
    )
    out += [
        "",
        table(
            ["Run", "Instance p50 / p99 (ms)", "Probe P p50 / p99 (ms)"],
            [
                (
                    f"`{c['run']}`",
                    f"{cell(c['instance'][0], '.0f')} / {cell(c['instance'][1], '.0f')}",
                    f"{cell(c['probe'][0], '.0f')} / {cell(c['probe'][1], '.0f')}",
                )
                for c in ttfb["client"]
            ]
            or [(NM, NM, NM)],
        ),
        "",
        "[results/*.json, probe-p.json]",
    ]
    if ttfb["server"]:
        out += [
            "",
            table(
                ["POP", "Edge TTFB p50 / p99 (ms)"],
                [(p, f"{cell(a, '.0f')} / {cell(b, '.0f')}") for p, a, b in ttfb["server"]["pops"]],
            ),
            "",
            f"[extracts/cdn_run.csv, run `{ttfb['server']['run']}`]",
        ]
    else:
        out += ["", f"Edge TTFB per POP: {NM} [extracts/cdn_run.csv]."]
    cf = cost_facts(runs, ctx["ledger"], ex["cost"], ctx["baseline"])
    read = cf["read"]
    out += ["", "## 5. Cost", "", f"![Cost]({img_rel}/{IMAGES['cost']})", ""]
    out.append(
        "For finance: what the launch cost and whether it stayed inside the limits. "
        f"Attributable spend (November Usage minus the baseline) {usd(read['attributable'])} of $25: {read['attributable_status']}. "
        f"Account total {usd(read['account_total'])} of $40: {read['account_status']}. "
        f"Ledger sum {usd(read['ledger_sum'])}, shown beside these and not added [extracts/cost.json, launch/cost_baseline.json, ledger.jsonl]."
    )
    out += [
        "",
        table(
            ["Run", "Kind", "Ledger estimate", "Ledger corrected", "Cost Explorer that day"],
            [
                (
                    f"`{r['run_id']}`",
                    r["kind"],
                    usd(r["estimate"]),
                    usd(r["corrected"]),
                    usd(r["ce_day"]) if r["ce_day"] is not None else r["ce_day_note"],
                )
                for r in read["per_run"]
            ]
            or [(NM,) * 5],
        ),
        "",
        "Cost Explorer that day is the whole account for that date, background spend included, and is shown only when the run is the only ledger run that day.",
    ]
    out += [
        "",
        table(
            ["Unit cost", "Value", "Basis"],
            [
                (
                    "Per GB",
                    usd(cf["per_gb"]) if cf["per_gb"] is not None else NM,
                    cf["per_gb_basis"],
                ),
                (
                    "Per million events",
                    usd(cf["per_million"]) if cf["per_million"] is not None else NM,
                    f"exercise ledger cost / {cf['exercise_events']:,} events requested"
                    if cf["exercise_events"]
                    else NM,
                ),
            ],
        ),
        "",
        "[k6 bytes counters, ledger.jsonl, run.json]",
        "",
        "### Bytes: planned, quota, k6 and CloudWatch",
        "",
        *bytes_doc(bytes_facts(runs)),
    ]
    peak = measured_peak(ex["rows"]["cdn_minute"])
    out += ["", "## 6. Scale", "", f"![Scale]({img_rel}/{IMAGES['scale']})", ""]
    out.append(
        "For leadership: how far this test is from the real thing. One region; 33.03 Tbps is a total exchange peak, so this is the shape of a launch, not its size. "
        f"Measured peak {cell(peak and peak['gbps'], '.2f')} Gbps ({peak['run'] + ' at ' + peak['minute'] + ' UTC' if peak else NM}) [extracts/cdn_minute.csv]; "
        f"modelled peak {cell(isp and isp['total_peak'], '.2f')} Gbps, separate and synthetic [extracts/isp_minute.csv]; "
        f"target {TARGET_GBPS:,} Gbps [launch plan figure]."
    )
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main


def build_context(
    runs_dir: Path, ledger_path: Path, extracts_dir: Path, baseline_path: Path
) -> dict:
    return {
        "runs": load_runs(runs_dir),
        "ledger": load_ledger(ledger_path),
        "extracts": load_extracts(extracts_dir),
        "baseline": read_baseline(baseline_path),
    }


def render(ctx: dict, doc: Path, img_dir: Path) -> list[Path]:
    ex, runs = ctx["extracts"], ctx["runs"]
    isp = isp_facts(ex["rows"]["isp_minute"])
    images = {
        "release": chart_release(release_facts(ex["rows"]["release_window"])),
        "isp": chart_isp_heatmap(isp),
        "cache": chart_cache(
            cache_facts(ex["rows"]["cdn_class"], runs), subrun_facts(ex["rows"]["cdn_subrun"], runs)
        ),
        "ttfb": chart_ttfb(ttfb_facts(runs, ex["rows"]["cdn_run"])),
        "cost": chart_cost(cost_facts(runs, ctx["ledger"], ex["cost"], ctx["baseline"])),
        "scale": chart_scale(
            measured_peak(ex["rows"]["cdn_minute"]), isp["total_peak"] if isp else None
        ),
    }
    img_dir.mkdir(parents=True, exist_ok=True)
    doc.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for key, name in IMAGES.items():
        (img_dir / name).write_text(images[key])
        written.append(img_dir / name)
    img_rel = os.path.relpath(img_dir, doc.parent).replace(os.sep, "/")
    doc.write_text(render_doc(ctx, img_rel))
    written.append(doc)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default=str(ROOT / "observability" / "launch" / "runs"))
    ap.add_argument("--ledger", default=str(ledger_mod.LEDGER))
    ap.add_argument("--extracts", default=str(ROOT / "observability" / "launch" / "extracts"))
    ap.add_argument("--baseline", default=str(ledger_mod.BASELINE))
    ap.add_argument("--doc", default=str(ROOT / "docs" / "launch-day-results.md"))
    ap.add_argument("--img-dir", default=str(ROOT / "docs" / "img" / "launch"))
    args = ap.parse_args(argv)
    ctx = build_context(
        Path(args.runs), Path(args.ledger), Path(args.extracts), Path(args.baseline)
    )
    for path in render(ctx, Path(args.doc), Path(args.img_dir)):
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
