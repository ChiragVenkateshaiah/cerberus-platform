"""The console transform and the home dashboard, against the real repo files."""

import copy
import json
import re
import unicodedata

import annotations as ann
import dashboards as db
import pytest


def newest_of(records):
    return max((r for _, r in records), key=lambda r: ann.parse_time(r["start"]))


def make(repo_dashboards, records):
    return db.console_dashboards(repo_dashboards, newest_of(records))


def refs_of(panel):
    return {t["refId"] for t in panel.get("targets", [])}


def test_no_cloudwatch_left(repo_dashboards, records):
    for uid, dash in make(repo_dashboards, records).items():
        assert not db.has_cloudwatch(dash), uid
        assert '"cloudwatch"' not in json.dumps(dash), uid


def test_no_expression_references_a_dropped_ref(repo_dashboards, records):
    # The only expression targets are in story panel 9; each reference must be a
    # refId the panel still has.
    seen = 0
    for uid, dash in make(repo_dashboards, records).items():
        for p in db.iter_panels(dash):
            for t in p.get("targets", []):
                if db.datasource_uid(t) != "__expr__":
                    continue
                seen += 1
                named = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", t["expression"]))
                if t.get("type") != "math":
                    named.add(t["expression"])
                assert named <= refs_of(p), (uid, p["id"], named - refs_of(p))
    assert seen == 1  # COST = $S


def test_every_amp_panel_and_row_survives(repo_dashboards, records):
    out = make(repo_dashboards, records)
    for dash in repo_dashboards:
        before = {p["id"] for p in db.iter_panels(dash) if db.datasource_uid(p) == "amp"}
        after = {p["id"] for p in db.iter_panels(out[dash["uid"]]) if db.datasource_uid(p) == "amp"}
        assert before <= after, dash["uid"]

    def amp_rows(dash):
        return {
            (p["id"], t["refId"])
            for p in db.iter_panels(dash)
            for t in p.get("targets", [])
            if db.datasource_uid(t) == "amp"
        }

    for dash in repo_dashboards:
        assert amp_rows(dash) == amp_rows(out[dash["uid"]]), dash["uid"]


def test_story_panel_4_and_9(repo_dashboards, records):
    story = make(repo_dashboards, records)[db.STORY]
    journey = db.find_panel(story, 4)
    assert [t["refId"] for t in journey["targets"]] == ["A", "B", "C"]
    assert journey["transformations"][0]["options"]["include"] == "A|B|C"
    layer = story["annotations"]["list"][-1]
    assert layer["target"]["tags"] == ["cerberus", "step"] and layer["enable"] is True
    cost = next(p for p in db.iter_panels(story) if p["id"] == 9)
    assert [t["refId"] for t in cost["targets"]] == ["S", "COST"]
    assert cost["targets"][1]["expression"] == "$S"
    assert "Compute" in cost["title"] and "estimate" in cost["title"]


def test_text_panels_keep_id_and_place(repo_dashboards, records):
    out = make(repo_dashboards, records)
    for uid, pid in ((db.LIVE, 7), (db.SPARK, 2)):
        before = next(d for d in repo_dashboards if d["uid"] == uid)
        old = next(p for p in db.iter_panels(before) if p["id"] == pid)
        new = next(p for p in db.iter_panels(out[uid]) if p["id"] == pid)
        assert new["type"] == "text" and new["gridPos"] == old["gridPos"]
        assert "CloudWatch" in new["options"]["content"]


def test_shared_dashboards_are_not_modified(repo_dashboards, records):
    before = copy.deepcopy(repo_dashboards)
    make(repo_dashboards, records)
    assert repo_dashboards == before


def test_default_time_is_newest_run_window(repo_dashboards, records):
    newest = newest_of(records)
    assert newest["execution"].startswith("demo-100m-")
    start, end = db.run_window(newest)
    for dash in make(repo_dashboards, records).values():
        assert dash["refresh"] == ""
        assert dash["time"] == {"from": db.iso_ms(start), "to": db.iso_ms(end)}


def test_panel_not_found_fails_loudly(repo_dashboards, records):
    broken = copy.deepcopy(repo_dashboards)
    story = next(d for d in broken if d["uid"] == db.STORY)
    story["panels"] = [p for p in story["panels"] if p["id"] != 4]
    with pytest.raises(db.DashboardError):
        make(broken, records)
    renamed = copy.deepcopy(repo_dashboards)
    live = next(d for d in renamed if d["uid"] == db.LIVE)
    next(p for p in live["panels"] if p["id"] == 7)["title"] = "Something else"
    with pytest.raises(db.DashboardError):
        make(renamed, records)


def test_unknown_dashboard_with_cloudwatch_fails(repo_dashboards, records):
    extra = {"uid": "other", "panels": [{"id": 1, "datasource": {"uid": "cloudwatch"}}]}
    with pytest.raises(db.DashboardError):
        make(repo_dashboards + [extra], records)


# --- home dashboard -----------------------------------------------------------


def home_text(records, extra=()):
    home = db.home_dashboard([r for _, r in records] + list(extra))
    return home, home["panels"][0]["options"]["content"]


def test_home_identity(records):
    home, _ = home_text(records)
    assert home["uid"] == "cerberus-runs" and home["title"] == "0 · Recorded runs"


def test_one_link_per_record_newest_first_failed_marked(records):
    _, text = home_text(records)
    links = re.findall(r"^- \[(.+?)\]\((\S+?)\) — (.*)$", text, re.M)
    assert len(links) == len(records) == 17
    starts = [int(re.search(r"from=(\d+)", u).group(1)) for _, u, _ in links]
    assert starts == sorted(starts, reverse=True)
    failed = [n for _, _, n in links if "**FAILED**" in n]
    assert len(failed) == sum(1 for _, r in records if r["status"] != "SUCCEEDED") == 2


def test_link_windows(records):
    _, text = home_text(records)
    margin = 600_000
    for _, rec in records:
        start = ann.to_ms(ann.parse_time(rec["start"]))
        end = ann.to_ms(ann.parse_time(rec["end"]))
        url = db.run_link(rec)
        m = re.fullmatch(r"/d/cerberus-run-story\?from=(\d+)&to=(\d+)", url)
        frm, to = int(m.group(1)), int(m.group(2))
        assert to == end + margin
        gen = ann.generator_window(rec)
        if gen:
            assert frm == min(start, ann.to_ms(gen[0])) - margin
            assert frm <= ann.to_ms(gen[0]) and ann.to_ms(gen[1]) < to
        else:
            assert frm == start - margin
        assert url in text


def test_hostile_record_is_escaped(records):
    hostile = dict(records[0][1])
    hostile.update(
        execution="<script>alert(1)</script>[x](javascript:alert(1))\n- [evil](http://evil.example/)",
        status="<img src=x onerror=alert(1)>",
    )
    _, text = home_text(records, [hostile])
    assert "<script" not in text and "<img" not in text and "evil.example" not in text
    for target in re.findall(r"\]\(([^)]*)\)", text):
        assert re.fullmatch(r"/d/cerberus-run-story\?from=\d+&to=\d+", target), target
    # The newline in the name did not start a new list item.
    assert len(re.findall(r"^- ", text, re.M)) == 18


def test_md_escape_directly():
    out = db.md_escape("<b>[a](b)</b> & *x* `y` _z_")
    assert "<" not in out and ">" not in out
    assert "\\[" in out and "\\(" in out and "&amp;" in out and "\\*" in out


# --- invisible characters (9.6) ---------------------------------------------

# C0 controls that str.split() does not treat as whitespace, DEL, C1, bidi,
# zero-width, BOM, a lone surrogate and a private-use character.
HIDDEN = (
    [chr(c) for c in range(0x20) if chr(c) not in "\t\n\v\f\r\x1c\x1d\x1e\x1f"]
    + ["\x7f", "\x80", "\x9b", "\x9f"]
    + ["\u200b", "\u200d", "\u202a", "\u202e", "\u2066", "\u2069", "\ufeff", "\ud800", "\ue000"]
)
INVISIBLE_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


def test_md_escape_replaces_invisible_characters():
    for ch in HIDDEN:
        assert db.md_escape(f"a{ch}b") == "a?b", repr(ch)
    assert db.md_escape("\x1b[31m\u202e") == "?\\[31m?"
    # Whitespace still collapses to one space.
    assert db.md_escape("a\x1c\x85\u2028b\r\n\tc") == "a b c"


def test_md_escape_keeps_visible_text():
    # The home label has a middle dot (U+00B7) between the time and the run name.
    label = "2026-10-13 05:58 UTC \xb7 exercise-1"
    assert db.md_escape(label) == label


def test_hostile_status_leaves_no_invisible_character_in_the_home_text(records):
    hostile = dict(records[0][1])
    hostile.update(status="OK\u2066\x1b[31m\u200b\x00\u202e")
    _, text = home_text(records, [hostile])
    assert "?" in text
    assert not [c for c in text if c != "\n" and unicodedata.category(c) in INVISIBLE_CATEGORIES]
