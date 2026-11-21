"""The pipeline-status dashboard (plan 10.3a), checked as a file.

No Grafana, no AWS, no Docker. The render check against a real Grafana is 10.3b.
Row panels (type "row") are exempt from the description rule: Grafana has no
description field on a row. Every other panel needs one.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from cerberus_console import config, queries

DASHBOARD = (
    Path(__file__).resolve().parents[2]
    / "observability"
    / "grafana"
    / "dashboards"
    / "cerberus-pipeline-status.json"
)
ALLOWED_DATASOURCES = {"amp", "-- Grafana --"}
ROW1 = (
    "Last run",
    "What broke",
    "Data checks",
    "Last good data",
    "Runs that passed (90 days)",
    "How to read this page",
)


@pytest.fixture(scope="module")
def doc() -> dict:
    return queries.load(config.QUERIES_FILE)


@pytest.fixture(scope="module")
def dash() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def panels(node):
    for p in node.get("panels", []):
        yield p
        yield from panels(p)


def by_title(dash):
    out = {p["title"]: p for p in panels(dash)}
    assert len(out) == len(list(panels(dash))), "panel titles are not unique"
    return out


def refs(node):
    """Every datasource reference below a node."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "datasource" and isinstance(v, dict):
                yield v
            yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


def row1_end(dash):
    rows = [p for p in dash["panels"] if p["type"] == "row"]
    return rows[1]["gridPos"]["y"]


def test_check_dashboard_is_clean(dash, doc):
    assert queries.check_dashboard(dash, doc) == []


def test_identity(dash):
    assert dash["uid"] == "cerberus-pipeline-status"
    assert dash["title"] == "4 · Pipeline Status: did the last run pass?"
    assert dash["time"] == {"from": "now-30d", "to": "now"}
    assert dash["refresh"] == ""


def test_every_panel_has_a_description(dash):
    for p in panels(dash):
        if p["type"] == "row":
            continue
        desc = p.get("description", "")
        assert isinstance(desc, str) and desc.strip(), p["title"]
        assert len(desc) <= 200, p["title"]
        assert not re.search(r"cerberus_|PromQL|[{}]", desc), p["title"]


def test_rows_in_order(dash):
    rows = [p["title"] for p in dash["panels"] if p["type"] == "row"]
    assert rows == [
        "Right now, in plain words",
        "The last run, step by step",
        "History",
        "Runs, and how to look closer",
        "AI review (Phase 14)",
    ]


def test_only_amp_and_grafana_datasources(dash):
    seen = {r.get("uid") for r in refs(dash)}
    assert seen == ALLOWED_DATASOURCES
    for r in refs(dash):
        assert r["uid"] in ALLOWED_DATASOURCES
        assert r["type"] in {"grafana-amazonprometheus-datasource", "grafana"}
    assert "cloudwatch" not in DASHBOARD.read_text(encoding="utf-8").lower()


def test_every_expr_equals_an_entry_and_uses_its_label(dash, doc):
    entries = {queries.normalise(q["expr"]): q for q in doc["queries"]}
    used = 0
    for p in panels(dash):
        for t in p.get("targets", []):
            expr = t.get("expr")
            if expr is None:
                continue
            entry = entries.get(queries.normalise(expr))
            assert entry is not None, (p["title"], expr)
            assert entry.get("label"), (p["title"], entry["name"])
            used += 1
    assert used == 17


def test_titles_use_the_entry_labels(dash, doc):
    label = {q["name"]: q["label"] for q in doc["queries"]}
    titles = {p["title"] for p in panels(dash)}
    for name in (
        "latest_status",
        "latest_failed_step",
        "latest_dq_passed",
        "last_success",
        "run_success_share_90d",
        "latest_step_seconds",
        "latest_run_seconds",
        "latest_events",
        "latest_dq_errors",
        "latest_dq_warnings",
        "latest_started",
        "latest_finished",
    ):
        assert label[name] in titles, name


def test_row1_is_plain_words(dash):
    tiles = by_title(dash)
    row1 = [p for p in panels(dash) if p["gridPos"]["y"] < row1_end(dash)]
    assert {p["title"] for p in row1 if p["type"] != "row"} == set(ROW1)
    for title in ROW1:
        p = tiles[title]
        assert "cerberus_" not in p["title"] + p["description"], title
        assert "{{" not in p["title"], title
    guide = tiles["How to read this page"]["options"]["content"]
    lines = [ln for ln in guide.splitlines() if ln.strip()]
    assert len(lines) == 5
    assert not re.search(r"\d", guide), "the guide has no numbers"
    assert "cerberus_" not in guide


def _mapped(p):
    out = {}
    for m in p["fieldConfig"]["defaults"]["mappings"]:
        if m["type"] == "value":
            out.update({k: v["text"] for k, v in m["options"].items()})
        elif m["type"] == "special":
            out[m["options"]["match"]] = m["options"]["result"]["text"]
    return out


def test_row1_value_mappings(dash):
    tiles = by_title(dash)
    assert _mapped(tiles["Last run"]) == {"1": "Passed", "0": "Failed", "null+nan": "No run yet"}
    assert _mapped(tiles["Data checks"]) == {"1": "Passed", "0": "Failed", "null+nan": "Not run"}
    assert tiles["Last run"]["fieldConfig"]["defaults"]["noValue"] == "No run yet"
    broke = tiles["What broke"]
    assert broke["fieldConfig"]["defaults"]["noValue"] == "Nothing, the last run passed"
    assert broke["targets"][0]["legendFormat"] == "{{step}}"
    good = tiles["Last good data"]
    assert good["fieldConfig"]["defaults"]["unit"] == "dateTimeFromNow"
    share = tiles["Runs that passed (90 days)"]
    assert share["fieldConfig"]["defaults"]["unit"] == "percentunit"
    steps = share["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert steps[-1] == {"color": "green", "value": 0.95}
    assert len(share["targets"]) == 2


def test_row2_not_run_mappings(dash):
    tiles = by_title(dash)
    for title in (
        "Last run duration",
        "Events handled",
        "Data check errors",
        "Data check warnings",
    ):
        assert _mapped(tiles[title]) == {"null+nan": "Not run"}, title
    assert tiles["Time per step"]["targets"][0]["legendFormat"] == "{{step}}"


def test_history_panels(dash):
    tiles = by_title(dash)
    tl = tiles["Run result over time"]
    assert tl["type"] == "state-timeline"
    assert _mapped(tl) == {"1": "Passed", "0": "Failed"}
    ts = tiles["Share of runs that passed, over time"]
    assert ts["type"] == "timeseries"
    assert ts["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] == {"mode": "line"}
    assert ts["fieldConfig"]["defaults"]["thresholds"]["steps"][-1] == {
        "color": "green",
        "value": 0.95,
    }


def test_runs_table_and_link(dash):
    table = by_title(dash)["Recent runs"]
    ids = [t["id"] for t in table["transformations"]]
    assert ids[0] == "joinByField"
    assert table["transformations"][0]["options"]["byField"] == "execution"
    assert ids.count("calculateField") == 2
    links = table["fieldConfig"]["defaults"]["links"]
    assert len(links) == 1
    url = links[0]["url"]
    assert url == (
        "/d/cerberus-run-story"
        "?from=${__data.fields.Started.numeric}&to=${__data.fields.Finished.numeric}"
    )
    assert not re.search(r"https?://|amazonaws|cloudfront|\d{12}", url)
    assert (
        "`cerberus run <execution>`" in by_title(dash)["How to look closer"]["options"]["content"]
    )


def test_ai_review_annolist(dash):
    ai = [p for p in panels(dash) if p["type"] == "annolist"]
    assert len(ai) == 1
    assert ai[0]["options"]["tags"] == ["cerberus-ai"]
    assert ai[0]["options"]["onlyFromThisDashboard"] is False
    assert "No AI review yet (Phase 14)" in ai[0]["description"]


def test_no_account_id_or_domain(dash):
    text = DASHBOARD.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", text)
    assert not re.search(r"amazonaws|cloudfront|amazoncognito|https?://", text)


def _steps() -> list[str]:
    """The task states of the state machine, as the publisher reads them."""
    path = DASHBOARD.parents[2] / "status" / "series.py"
    spec = importlib.util.spec_from_file_location("status_series", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.STEPS)


def _rename_map(panel) -> dict[str, str]:
    out = {}
    for t in panel.get("transformations", []):
        if t["id"] == "renameByRegex":
            out[t["options"]["regex"]] = t["options"]["renamePattern"]
    return out


def test_every_step_has_a_numbered_plain_name(dash):
    tiles = by_title(dash)
    steps = _steps()
    assert steps, "no steps found"
    for title in ("Time per step", "What broke"):
        renames = _rename_map(tiles[title])
        assert set(renames) == {f"^{s}$" for s in steps}, title
        names = [renames[f"^{s}$"] for s in steps]
        assert [n.split(" ")[0] for n in names] == [str(i + 1) for i in range(len(steps))]
        assert not any(re.search(r"cerberus_|[A-Z][a-z]+[A-Z]", n) for n in names), names


def test_bar_gauge_is_sorted_into_step_order(dash):
    gauge = by_title(dash)["Time per step"]
    ids = [t["id"] for t in gauge["transformations"]]
    assert ids[-2:] == ["reduce", "sortBy"]
    assert gauge["transformations"][-1]["options"]["sort"] == [{"field": "Field"}]
    assert _mapped(gauge) == {"null+nan": "Not run"}
