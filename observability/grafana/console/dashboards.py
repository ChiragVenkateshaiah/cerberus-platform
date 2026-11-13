"""Console copies of the repo dashboards, and the "Recorded runs" home (step 10).

Stdlib only and Python 3.9 compatible. The console Grafana mounts only the AMP
data source (a Viewer can send any query through /api/ds/query), so every
CloudWatch panel needs a console form (plan 2026-11-12, option 4.3 A). The
transform reads the shared dashboards in observability/grafana/dashboards/ and
returns copies. It never writes to them.

Panels are found by id and checked by title. If the repo dashboards change and
a panel moves, the transform raises DashboardError instead of guessing.
"""

import copy
import html
import re
import unicodedata
from datetime import timedelta

from annotations import clean, generator_window, parse_time, status_of, to_ms

STORY, LIVE, SPARK = "cerberus-run-story", "cerberus-run-live", "cerberus-spark-on-eks"
HOME_UID = "cerberus-runs"
HOME_TITLE = "0 · Recorded runs"
MARGIN = timedelta(minutes=10)

# (dashboard uid, panel id) -> the title the panel must still have.
EXPECTED_TITLES = {
    (STORY, 4): "Pipeline journey",
    (STORY, 9): "Cost so far (estimate)",
    (LIVE, 7): "Step Functions executions",
    (SPARK, 2): "Step Functions executions",
}

NO_CLOUDWATCH = (
    "This panel reads AWS CloudWatch. The console session does not have "
    "CloudWatch: a visitor can send any query to a data source, so the console "
    "mounts the Amazon Managed Prometheus data source only.\n\n"
    "What this panel shows on the recording host is in the run record. "
    "Open **0 · Recorded runs** and pick a run."
)


class DashboardError(ValueError):
    """A repo dashboard no longer has the shape the transform expects."""


def iter_panels(dash):
    """Every panel, including those nested inside collapsed rows."""
    for panel in dash.get("panels", []):
        yield panel
        yield from iter_panels(panel)


def find_panel(dash, panel_id):
    uid = dash.get("uid")
    matches = [p for p in iter_panels(dash) if p.get("id") == panel_id]
    if len(matches) != 1:
        raise DashboardError(f"{uid}: expected one panel with id {panel_id}, found {len(matches)}")
    panel = matches[0]
    want = EXPECTED_TITLES[(uid, panel_id)]
    if panel.get("title") != want:
        raise DashboardError(
            f"{uid}: panel {panel_id} is {panel.get('title')!r}, expected {want!r}"
        )
    return panel


def datasource_uid(obj):
    ds = obj.get("datasource")
    return ds.get("uid") if isinstance(ds, dict) else None


def has_cloudwatch(node):
    """True if any data source reference below this node points at CloudWatch."""
    if isinstance(node, dict):
        if node.get("uid") == "cloudwatch" or node.get("type") == "cloudwatch":
            return True
        return any(has_cloudwatch(v) for v in node.values())
    if isinstance(node, list):
        return any(has_cloudwatch(v) for v in node)
    return False


def text_panel(old, content):
    """A markdown text panel in the place of a CloudWatch panel."""
    return {
        "id": old["id"],
        "type": "text",
        "title": old["title"],
        "gridPos": old["gridPos"],
        "options": {"mode": "markdown", "content": content},
    }


def replace_panel(dash, panel_id, new):
    """Swap one panel in place, wherever it sits (top level or in a row)."""

    def swap(panels):
        for i, panel in enumerate(panels):
            if panel.get("id") == panel_id:
                panels[i] = new
                return True
            if swap(panel.get("panels", [])):
                return True
        return False

    if not swap(dash["panels"]):
        raise DashboardError(f"{dash.get('uid')}: panel {panel_id} vanished")


def transform_story(dash):
    # Panel 4: keep the AMP rows, drop CloudWatch. The step rows come back as
    # annotation regions, so add an annotation layer for that panel only.
    journey = find_panel(dash, 4)
    kept = [t for t in journey["targets"] if datasource_uid(t) == "amp"]
    dropped = {t["refId"] for t in journey["targets"] if t not in kept}
    if not kept or not dropped:
        raise DashboardError(f"{STORY}: panel 4 has no AMP or no CloudWatch targets")
    journey["targets"] = kept
    for tr in journey.get("transformations", []):
        if tr.get("id") == "filterByRefId":
            tr["options"]["include"] = "|".join(t["refId"] for t in kept)
    journey["description"] = (
        "One row per Kubernetes step: Start servers, Create test payments and Saving files "
        "(15 s resolution). The later steps (ingestion, transform, dbt, the serving query) "
        "come from the run record and show as step regions on this panel and in the Run log "
        "on 2 · Run Health. "
        "Needs the dashboard range to start at the run start."
    )
    dash["annotations"]["list"].append(
        {
            "name": "Pipeline steps",
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True,
            "iconColor": "blue",
            "filter": {"exclude": False, "ids": [4]},
            "target": {
                "type": "tags",
                "tags": ["cerberus", "step"],
                "limit": 100,
                "matchAny": False,
            },
        }
    )

    # Panel 9: no Athena bytes without CloudWatch, so the cost is the compute part.
    cost = find_panel(dash, 9)
    by_ref = {t["refId"]: t for t in cost["targets"]}
    if set(by_ref) != {"S", "P0", "P", "COST"}:
        raise DashboardError(f"{STORY}: panel 9 targets are {sorted(by_ref)}")
    cost["targets"] = [by_ref["S"], by_ref["COST"]]
    by_ref["COST"]["expression"] = "$S"
    cost["title"] = "Compute cost so far (estimate)"
    cost["description"] = (
        "Compute estimate only: servers = hours from the dashboard start to the cluster's last "
        "metrics plus teardown_s (780 s), times $1.15 an hour (2026-10-13 run record: $1.207592 "
        "non-Athena over 1.048 h of observed cluster time). Athena query cost is left out on "
        "this host, because it needs CloudWatch. On a recorded run the dashboard starts "
        "10 minutes before the first step, "
        "not when the servers started; the run record has the real cost. "
        "The real bill comes a day later."
    )
    for override in cost["fieldConfig"]["overrides"]:
        for prop in override["properties"]:
            if prop.get("id") == "displayName":
                prop["value"] = "servers (compute estimate)"


def transform_live(dash):
    replace_panel(dash, 7, text_panel(find_panel(dash, 7), NO_CLOUDWATCH))


def transform_spark(dash):
    replace_panel(dash, 2, text_panel(find_panel(dash, 2), NO_CLOUDWATCH))


TRANSFORMS = {STORY: transform_story, LIVE: transform_live, SPARK: transform_spark}


def run_window(record):
    """(from, to) datetimes that show a whole run, generator included."""
    start = parse_time(record["start"])
    first = start
    gen = generator_window(record)
    if gen is not None:
        first = min(first, gen[0])
    return first - MARGIN, parse_time(record["end"]) + MARGIN


def console_dashboards(repo_dashboards, newest_record):
    """Transformed copies keyed by uid. `repo_dashboards` is a list of dicts.

    Raises DashboardError if a needed dashboard is missing, or if any
    CloudWatch reference is left in any copy.
    """
    by_uid = {d.get("uid"): d for d in repo_dashboards}
    missing = [uid for uid in TRANSFORMS if uid not in by_uid]
    if missing:
        raise DashboardError(f"missing dashboards: {', '.join(missing)}")
    start, end = run_window(newest_record)
    out = {}
    for uid, dash in by_uid.items():
        dash = copy.deepcopy(dash)
        if uid in TRANSFORMS:
            TRANSFORMS[uid](dash)
        dash["refresh"] = ""
        dash["time"] = {"from": iso_ms(start), "to": iso_ms(end)}
        if has_cloudwatch(dash):
            raise DashboardError(f"{uid}: a CloudWatch reference is left after the transform")
        out[uid] = dash
    return out


def iso_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- the home dashboard -------------------------------------------------------

_MD_SPECIAL = re.compile(r"([\\`*_\[\]()#|!~])")
# Unicode categories that draw nothing or reorder text: controls (C0, DEL, C1),
# format characters (bidi overrides, zero-width), surrogates, private use,
# unassigned, and the line and paragraph separators.
_MD_INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


def md_escape(value, limit=80):
    """Make a record field harmless inside a markdown line.

    Order matters: first turn &, < and > into entities, then backslash-escape
    the markdown characters. Whitespace (newlines too) collapses to one space.
    A control, bidi or zero-width character becomes "?" (9.6 hardening).
    """
    text = " ".join(str(value).split())[:limit]
    text = "".join("?" if unicodedata.category(ch) in _MD_INVISIBLE else ch for ch in text)
    return _MD_SPECIAL.sub(r"\\\1", html.escape(text, quote=False))


def run_link(record):
    start, end = run_window(record)
    return f"/d/{STORY}?from={to_ms(start)}&to={to_ms(end)}"


def duration_text(seconds):
    total = int(round(seconds))
    return f"{total // 60}m {total % 60:02d}s"


def home_line(record):
    """One markdown list item: a link to the run, plus its result."""
    start = parse_time(record["start"])
    status = status_of(record)
    label = f"{start:%Y-%m-%d %H:%M} UTC · {clean(record['execution'], 80)}"
    dq = record.get("data_quality")
    failed = status != "SUCCEEDED" or (isinstance(dq, dict) and dq.get("passed") is False)
    mark = f"**{md_escape(status)}**" if failed else md_escape(status)
    note = f" — {mark}, {duration_text(record['run_seconds'])}"
    if isinstance(dq, dict) and dq.get("passed") is False:
        note += ", quality checks failed"
    return f"- [{md_escape(label)}]({run_link(record)}){note}"


def home_dashboard(records):
    """The home dashboard: one link per run record, newest first."""
    ordered = sorted(records, key=lambda r: parse_time(r["start"]), reverse=True)
    lines = [
        "Pick a recorded run. Each link opens the Run Overview on that run's time window.",
        "Failed runs are marked in bold.",
        "",
    ] + [home_line(r) for r in ordered]
    newest = ordered[0] if ordered else None
    start, end = run_window(newest) if newest else (None, None)
    return {
        "uid": HOME_UID,
        "title": HOME_TITLE,
        "tags": ["cerberus", "console"],
        "editable": False,
        "graphTooltip": 0,
        "schemaVersion": 41,
        "timezone": "utc",
        "time": {"from": iso_ms(start), "to": iso_ms(end)}
        if newest
        else {"from": "now-6h", "to": "now"},
        "links": [],
        "annotations": {"list": []},
        "templating": {"list": []},
        "panels": [
            {
                "id": 1,
                "type": "text",
                "title": "Recorded runs (newest first)",
                "gridPos": {"x": 0, "y": 0, "w": 24, "h": 24},
                "options": {"mode": "markdown", "content": "\n".join(lines)},
            }
        ],
    }
