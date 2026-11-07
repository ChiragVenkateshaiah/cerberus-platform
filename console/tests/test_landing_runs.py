"""The run cards: same record as `cerberus run latest`, nothing raw from data."""

from landing_helpers import FIXTURE_RUNS, REAL_RUNS, build_site, parse, write_record

from cerberus_console import records
from cerberus_landing import build, runs


def test_latest_run_matches_the_console_for_the_real_records(tmp_path):
    _, html = build_site(tmp_path / "site", runs_dir=REAL_RUNS)
    newest = records.load(REAL_RUNS).records[0]["execution"]
    hrefs = [a["href"] for a in parse(html).named("a") if "href" in a]
    assert any(h.endswith(f"/observability/scale/runs/{newest}.json") for h in hrefs)
    latest = runs.pick(REAL_RUNS)[0]
    assert latest.execution == newest
    assert latest.events in html


def test_largest_is_the_succeeded_run_with_most_events(tmp_path):
    d = tmp_path / "runs"
    write_record(d, "exercise-20261101T100000Z", events_processed=500)
    write_record(d, "exercise-20261102T100000Z", events_processed=9000, status="FAILED")
    write_record(d, "exercise-20261103T100000Z", events_processed=700)
    latest, largest, total, ok = runs.pick(d)
    assert latest.execution == "exercise-20261103T100000Z"
    assert largest.execution == "exercise-20261103T100000Z"
    assert (total, ok) == (3, 2)
    assert largest.events == "700"


def test_hostile_record_text_never_reaches_the_page(tmp_path):
    out = tmp_path / "site"
    _, html = build_site(out, runs_dir=FIXTURE_RUNS)
    assert "hostile-20990101T000000Z" in html  # it is the newest, and a valid token
    for raw in ("\x1b", "\x07", "‮", "\u009b", "52;c", "SGVsbG8", "Svc"):
        assert raw not in html, repr(raw)
    assert build.csp_problems(html) == []
    # The only angle brackets are tags the builder wrote: no markup from data.
    assert "<script" not in html.lower()


def test_hostile_state_name_is_replaced_by_the_fixed_label(tmp_path):
    latest = runs.pick(FIXTURE_RUNS)[0]
    labels = [label for label, _ in latest.states]
    assert labels == [label for _, label in runs.STATES]
    seconds = dict(latest.states)
    # RunDbt's name carries an escape in the record, so the exact-name lookup finds nothing.
    assert seconds["Build the business tables"] == "not recorded"
    assert seconds["Answer a test query"] == "55.0"


def test_an_invalid_execution_name_links_nowhere(tmp_path):
    d = tmp_path / "runs"
    write_record(d, "ok-20261101T100000Z", execution="../x<script>alert(1)</script>")
    _, html = build_site(tmp_path / "site", runs_dir=d)
    assert "alert(1)" not in html
    assert "observability/scale/runs/" not in html
    latest = runs.pick(d)[0]
    assert latest.execution is None and latest.file_name is None


def test_unknown_status_shows_unknown(tmp_path):
    d = tmp_path / "runs"
    write_record(d, "exercise-20261101T100000Z", status="<b>PWNED</b>")
    latest = runs.pick(d)[0]
    assert latest.status == "unknown"
    _, html = build_site(tmp_path / "site", runs_dir=d)
    assert "PWNED" not in html


def test_an_empty_runs_directory_says_no_runs(tmp_path):
    (tmp_path / "runs").mkdir()
    _, html = build_site(tmp_path / "site", runs_dir=tmp_path / "runs")
    assert "No runs recorded yet." in html
    assert 'class="card"' not in html


def test_incomplete_cost_says_not_final(tmp_path):
    d = tmp_path / "runs"
    write_record(
        d,
        "exercise-20261101T100000Z",
        cost={"usd_per_million_events": 1.5, "estimated": True, "complete": False},
    )
    _, html = build_site(tmp_path / "site", runs_dir=d)
    assert "Cost not final yet" in html
    assert "$1.5000" not in html


def test_incomplete_cost_without_a_figure_says_not_final(tmp_path):
    d = tmp_path / "runs"
    write_record(
        d,
        "exercise-20261101T100000Z",
        cost={"usd_per_million_events": None, "estimated": True, "complete": False},
    )
    assert runs.pick(d)[0].cost == "cost not final yet"
    _, html = build_site(tmp_path / "site", runs_dir=d)
    assert "Cost not final yet" in html


def test_estimated_cost_is_labelled(tmp_path):
    d = tmp_path / "runs"
    write_record(d, "exercise-20261101T100000Z")
    _, html = build_site(tmp_path / "site", runs_dir=d)
    assert "$1.5000 per million events (estimated)" in html
    assert "Data checks passed" in html


def test_formatting():
    assert runs.format_int(100008511) == "100,008,511"
    assert runs.format_int(None) == "not recorded"
    assert runs.format_duration(581.2) == "9 min 41 s"
    assert runs.format_duration(42.0) == "42 s"
    assert runs.format_date("2026-10-15T15:15:18.155000+00:00") == "15 October 2026 (UTC)"
    assert runs.format_date("2026-10-15T23:30:00-05:00") == "16 October 2026 (UTC)"
    assert runs.format_date("garbage") == "date not recorded"
    assert runs.format_date(None) == "date not recorded"


def test_bulk_note_shows_only_for_generator_runs(tmp_path):
    note = "That time is not in this table."
    plain = tmp_path / "plain"
    write_record(plain, "exercise-20261101T100000Z")
    assert note not in build_site(tmp_path / "a", runs_dir=plain)[1]
    bulk = tmp_path / "bulk"
    write_record(bulk, "exercise-20261101T100000Z", generator={"write_seconds": 90.0})
    assert note in build_site(tmp_path / "b", runs_dir=bulk)[1]
