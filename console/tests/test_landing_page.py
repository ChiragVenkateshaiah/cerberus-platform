"""What the page claims (9.4c): the achievements strip, "follow the batch", the
latest run and the recorded figure. Each figure follows its record; the truth
rules of docs/plans/2026-11-28-landing-showcase.md section 5 hold.
"""

import html as htmllib
import json
import re

import pytest
from landing_helpers import (
    REAL_RUNS,
    build_site,
    journey_records,
    parse,
    write_charts,
    write_record,
)

from cerberus_landing import build, journey, page
from cerberus_landing.showcase import scan_text

ONE_M = "exercise-20261015T145812Z"
TEN_M = "exercise-20261009T074853Z"
HUNDRED_M = journey.FEATURED
DEMO = "demo-100m-20261108T135119Z"
PASS_TOKEN = journey.CHECKS["token_digit_runs"][1]
WARN_TOKEN = journey.WARNINGS["token_digit_runs"]


def words(markup: str) -> str:
    """The text a reader gets: tags removed, white space collapsed."""
    text = re.sub(r"<[^>]+>", " ", markup)
    return " ".join(htmllib.unescape(text).split())


def element(markup: str, tag: str, ident: str) -> str:
    """The whole element with this id, nested elements of the same name included."""
    start = markup.rindex(f"<{tag}", 0, markup.index(f'id="{ident}"'))
    depth = 0
    for m in re.finditer(rf"<(/?){tag}\b", markup[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return markup[start : start + m.start()]
    raise AssertionError(f"{ident} is not closed")


def panel(markup: str, size: str, station: str) -> str:
    return element(markup, "article", f"s-{size}-{station}")


def strip(markup: str) -> str:
    return markup[: markup.index("<nav")]


def built(tmp_path, change=None, target=HUNDRED_M) -> str:
    if change is None:
        return build_site(tmp_path / "site")[1]
    d = journey_records(tmp_path / "runs")
    path = d / f"{target}.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    change(rec)
    path.write_text(json.dumps(rec), encoding="utf-8")
    return build_site(tmp_path / "site", runs_dir=d)[1]


def token_check(rec) -> dict:
    return next(c for c in rec["data_quality"]["checks"] if c["name"] == "token_digit_runs")


def test_the_page_order(tmp_path):
    html = built(tmp_path)
    marks = ["<h1>", 'class="stats"', "<nav", 'id="journey"', 'id="latest"', 'id="scale"']
    marks += ['id="live"', 'id="terminal"', 'id="recorded"', 'id="architecture"', 'id="progress"']
    positions = [html.index(m) for m in marks]
    assert positions == sorted(positions)


def test_the_achievements_come_from_the_featured_record_and_all_records(tmp_path):
    text = words(strip(built(tmp_path)))
    rec = json.loads((REAL_RUNS / f"{HUNDRED_M}.json").read_text(encoding="utf-8"))
    all_runs = [json.loads(p.read_text(encoding="utf-8")) for p in REAL_RUNS.glob("*.json")]
    ok = sum(r["status"] == "SUCCEEDED" for r in all_runs)
    for claim in (
        f"synthetic payment events in one run {rec['events_processed']:,}",
        f"run time, start to finish {rec['run_seconds']} s",
        f"per million events, estimated ${rec['cost']['usd_per_million_events']:.4f}",
        f"recorded runs succeeded {ok} of {len(all_runs)}",
        "13 October 2026 (UTC)",
        "Its bulk events were written beforehand by a data generator.",
        "The cost estimate excludes setup, the data generator, the data checks and teardown.",
    ):
        assert claim in text, claim
    assert "runs passed" not in text
    assert f"/observability/scale/runs/{HUNDRED_M}.json" in strip(built(tmp_path))


def test_the_run_count_is_computed(tmp_path):
    d = journey_records(tmp_path / "runs")
    write_record(d, "exercise-20261001T100000Z", status="FAILED")
    write_record(d, "exercise-20261002T100000Z")
    html = build_site(tmp_path / "site", runs_dir=d)[1]
    assert "recorded runs succeeded 4 of 5" in words(strip(html))


def test_a_cost_that_is_not_estimated_drops_the_label(tmp_path):
    html = built(tmp_path, lambda r: r["cost"].update(estimated=False))
    text = words(strip(html))
    assert "per million events" in text and "estimate" not in text


def test_a_figure_the_record_lacks_is_not_recorded(tmp_path):
    def change(rec):
        for key in ("events_processed", "silver", "storage_snapshot", "prometheus", "cost"):
            del rec[key]

    html = built(tmp_path, change)
    assert words(strip(html)).count("not recorded") == 2  # events and cost
    assert "estimate" not in words(strip(html))
    clean = words(panel(html, "100m", "clean"))
    assert "Data read not recorded" in clean
    assert "Silver events not recorded Silver transactions not recorded" in clean
    assert "Gold stored bytes not recorded" in words(panel(html, "100m", "model"))
    assert "not recorded" in words(element(html, "div", "recorded"))


def test_the_bulk_note_follows_the_generator_entry(tmp_path):
    html = built(tmp_path, lambda r: r.pop("generator"))
    assert "written beforehand" not in words(element(html, "div", "run-100m"))
    assert "written beforehand" not in words(strip(html))
    assert "written beforehand by the generator" in words(panel(html, "10m", "arrive"))


@pytest.mark.parametrize("size", ["1m", "10m", "100m"])
def test_arrive_time_is_only_the_small_batch(tmp_path, size):
    text = words(panel(built(tmp_path), size, "arrive"))
    assert "This time covers only adding the small batch of new events." in text
    assert "Bronze events not recorded" in text


@pytest.mark.parametrize(("size", "name"), [("1m", ONE_M), ("10m", TEN_M), ("100m", HUNDRED_M)])
def test_each_panel_shows_its_record(tmp_path, size, name):
    html = built(tmp_path)
    rec = json.loads((REAL_RUNS / f"{name}.json").read_text(encoding="utf-8"))
    states = {s["state"]: s for s in rec["states"]}
    for station, state in zip(
        ("arrive", "clean", "model", "answer"),
        ("InvokeIngestion", "RunTransform", "RunDbt", "RunServingQuery"),
        strict=True,
    ):
        seconds = states[state]["seconds"]
        share = 100 * seconds / rec["run_seconds"]
        body = panel(html, size, station)
        assert f"{seconds} s {share:.1f}% of the {rec['run_seconds']} s run" in words(body)
        assert f'class="bar-mark" width="{share:.2f}%"' in body
    clean = words(panel(html, size, "clean"))
    assert f"Silver events {rec['silver']['events']:,}" in clean
    assert f"Silver transactions {rec['silver']['transactions']:,}" in clean
    assert "Gold rows not recorded" in words(panel(html, size, "model"))
    run = words(element(html, "div", f"run-{size}"))
    assert f"Events {rec['events_processed']:,}" in run
    assert f"/observability/scale/runs/{name}.json" in element(html, "div", f"run-{size}")


def test_table_totals_are_labelled_as_whole_tables_after_the_run(tmp_path):
    html = built(tmp_path)
    label = "Whole table totals, read after the run (not only this batch)"
    for size in ("1m", "10m", "100m"):
        for station in ("arrive", "clean", "model"):
            assert label in words(panel(html, size, station))
        assert label not in words(panel(html, size, "answer"))


def test_the_two_byte_measures_are_named_and_never_mixed(tmp_path):
    html = built(tmp_path)
    for size in ("1m", "10m", "100m"):
        clean = words(panel(html, size, "clean"))
        assert "Data read (Spark input)" in clean and "Athena" not in clean
        for station in ("model", "answer"):
            text = words(panel(html, size, station))
            assert "Data read (Athena scanned)" in text and "Spark input" not in text
    assert "Do not compare or add them." in words(html)
    assert "52.6 GB" in words(panel(html, "100m", "clean"))


def test_the_queue_time_comes_from_the_record(tmp_path):
    assert "230.5 s" in words(panel(built(tmp_path), "1m", "model"))

    def change(rec):
        next(s for s in rec["states"] if s["state"] == "RunDbt")["athena"]["queue_seconds"] = 111.5

    html = built(tmp_path / "changed", change, ONE_M)
    model = words(panel(html, "1m", "model"))
    assert (
        "Athena queue time (waiting, not working), summed over this step's queries, "
        "which can overlap: 111.5 s."
    ) in model
    assert "230.5" not in html.replace("img/", "")
    # No Athena query ran in Arrive and Clean, so they show no queue time.
    for station in ("arrive", "clean"):
        assert "queue" not in words(panel(html, "1m", station))


@pytest.mark.parametrize("size", ["1m", "10m", "100m"])
def test_a_warned_check_is_a_warning_and_never_the_pass_words(tmp_path, size):
    html = built(tmp_path)
    clean = words(panel(html, size, "clean"))
    assert f"Warning: {WARN_TOKEN}" in clean
    assert PASS_TOKEN not in words(html)


def test_a_check_that_passed_shows_its_words_and_no_warning(tmp_path):
    html = built(tmp_path, lambda r: token_check(r).update(passed=True))
    clean = words(panel(html, "100m", "clean"))
    assert PASS_TOKEN in clean and "Warning:" not in clean
    assert "15 checks passed" in clean


def test_a_warned_check_without_words_is_counted_not_claimed(tmp_path):
    def change(rec):
        check = next(c for c in rec["data_quality"]["checks"] if c["name"] == "masking")
        check.update(passed=False, severity="warn")

    clean = words(panel(built(tmp_path, change), "100m", "clean"))
    assert "Warning: 1 more check ended in a warning." in clean
    assert journey.CHECKS["masking"][1] not in clean


def test_checks_are_grouped_by_layer_and_run_after_the_run(tmp_path):
    html = built(tmp_path)
    for station, layer in (("arrive", "bronze"), ("clean", "silver"), ("model", "gold")):
        for size in ("1m", "10m", "100m"):
            body = panel(html, size, station)
            assert "Data checks after the run" in words(body) and f"({layer})" in words(body)
    assert "No data check is listed for this station." in words(panel(html, "1m", "answer"))
    assert "Data checks ran after each run, not inside a step." in words(html)


def test_a_record_without_checks_says_not_recorded(tmp_path):
    html = built(tmp_path, lambda r: r.pop("data_quality"))
    clean = words(panel(html, "100m", "clean"))
    assert "clean tables (silver) not recorded" in clean
    assert "checks passed" not in clean


def test_unlisted_check_results_are_counted(tmp_path):
    def change(rec):
        rec["data_quality"]["checks"].append({"name": "PWNED_check", "passed": True})

    html = built(tmp_path, change)
    assert "Check results in this record that are not listed here: 1." in words(html)
    assert "PWNED" not in html


def test_one_databricks_sentence_at_the_model_station(tmp_path):
    html = built(tmp_path)
    journey_html = element(html, "section", "journey")
    sentence = (
        "Databricks, a partner engine, is planned (Phase 11) to read these same open "
        "tables through the catalog."
    )
    assert journey_html.count("Databricks") == 3  # once in each run's Model panel
    for size in ("1m", "10m", "100m"):
        assert sentence in words(panel(html, size, "model"))


def test_no_clean_scaling_claim(tmp_path):
    text = words(built(tmp_path))
    assert "They are not a straight scaling test." in text
    assert "linear" not in text.lower()


def test_the_latest_run_is_the_newest_record_with_its_estimate_note(tmp_path):
    # A fixed set of records: a newer real record must not change this test.
    d = journey_records(tmp_path / "runs")
    (d / f"{DEMO}.json").write_bytes((REAL_RUNS / f"{DEMO}.json").read_bytes())
    html = build_site(tmp_path / "site", runs_dir=d)[1]
    text = words(element(html, "section", "latest"))
    for claim in (
        "8 November 2026 (UTC)",
        "Succeeded",
        "100,001,897",
        "14 min 19 s",
        "$0.0052 per million events (estimated)",
        "Data checks passed, with a warning",
        "They exclude setup, the data generator, the data checks and teardown.",
        "written beforehand by a data generator",
    ):
        assert claim in text, claim


def test_each_chart_has_its_caption_in_a_focusable_scroll_box(tmp_path):
    charts = write_charts(tmp_path / "charts")
    html = build_site(tmp_path / "site", charts_dir=charts)[1]
    section = element(html, "section", "scale")
    assert (
        "Chart costs are estimates that exclude setup, the data generator, the data checks "
        "and teardown."
    ) in words(section)
    figures = re.findall(r"<figure.*?</figure>", section, flags=re.DOTALL)
    assert len(figures) == 3
    captions = {
        "cost-per-million-events": "What it costs to process one million payment events, run "
        "by run. Runs were on different days with different table sizes; this is not a "
        "straight scaling test.",
        "run-time-per-state": "How long each step of a run takes.",
        "transform-throughput": "Spark read speed against the number of executors. Input "
        "sizes differ between runs.",
    }
    for figure, (stem, caption) in zip(figures, captions.items(), strict=True):
        assert f'src="img/{stem}.' in figure
        assert words(figure) == caption
        box = parse(figure).named("div")[0]
        assert (box["class"], box["role"], box["tabindex"]) == ("scroll", "group", "0")
        assert box["aria-label"].endswith(f"Chart {stem}")


def test_the_intro_asks_for_a_pick_only_where_the_picker_shows(tmp_path):
    journey_html = element(built(tmp_path), "section", "journey")
    assert "Three real runs, each followed through four stations." in words(journey_html)
    start = journey_html.index("data-picker")
    end = journey_html.index("</div>", start)
    assert "Pick a batch size" in journey_html[start:end]
    outside = journey_html[:start] + journey_html[end:]
    assert not re.search(r"\bpick\b", words(outside), flags=re.IGNORECASE)


def test_the_recorded_metric_says_recorded_not_live(tmp_path):
    text = words(element(built(tmp_path), "div", "recorded"))
    assert "10,370 metric series at once, at the peak of the run of 13 October 2026" in text
    assert "recorded at collection. It is not live." in text


def test_architecture_and_progress_are_closed_folds(tmp_path):
    p = parse(built(tmp_path))
    folds = {a["id"]: a for a in p.named("details") if a.get("class") == "fold"}
    assert set(folds) == {"architecture", "progress"}
    assert not any("open" in a for a in p.named("details"))


def failed_check(rec):
    token_check(rec)["severity"] = "error"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (failed_check, "a data check failed"),
        (lambda r: r.update(status="FAILED"), "did not succeed"),
        (lambda r: r.pop("states"), "no state list"),
    ],
)
def test_a_run_the_page_cannot_tell_fails_the_build(tmp_path, change, message):
    with pytest.raises(build.BuildError, match=message):
        built(tmp_path, change)
    assert not (tmp_path / "site" / "index.html").exists()


def test_hostile_text_in_a_featured_record_never_reaches_the_page(tmp_path):
    bad = "<script>PWNED</script> arn:x name@example.org"

    def change(rec):
        rec["start"] = rec["events_processed"] = rec["run_seconds"] = bad
        rec["silver"] = {"events": bad, "transactions": bad}
        rec["prometheus"] = {"peak_active_series": bad}
        rec["cost"] = {"usd_per_million_events": bad}
        rec["generator"] = {"run_id": bad}
        rec["data_quality"]["checks"].append(
            {"name": bad, "severity": "warn", "passed": False, "about": bad, "detail": bad}
        )
        for st in rec["states"]:
            st.update(seconds=bad, athena={"bytes_scanned": bad, "queue_seconds": bad})

    html = built(tmp_path, change)
    assert "PWNED" not in html
    assert scan_text(html) == []


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (None, None),
        (0, "0 bytes"),
        (999, "999 bytes"),
        (1_000, "1.0 kB"),
        (143_047_001, "143.0 MB"),
        (52_624_362_642, "52.6 GB"),
        (10**12, "1.0 TB"),
        (10**15, "1.0 PB"),
    ],
)
def test_bytes_are_decimal_units(n, text):
    assert page.format_bytes(n) == text
