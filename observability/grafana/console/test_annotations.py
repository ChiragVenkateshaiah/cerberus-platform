"""Run records to annotations, against the real records in observability/scale/runs."""

import annotations as ann


def by_tag(items, tag):
    return [a for a in items if tag in a["tags"]]


def test_count_per_record(records):
    for name, rec in records:
        items = ann.annotations_for(rec, name)
        extra = 1 if ann.generator_window(rec) else 0
        # started + N states + end + dq + now + teardown (+ generator)
        assert len(items) == len(rec["states"]) + 5 + extra, name


def test_state_sum_matches_run_seconds(records):
    # The record rounds each state to 0.1 s, so the sum is within a few tenths.
    for name, rec in records:
        total = sum(s["seconds"] for s in rec["states"])
        assert abs(total - rec["run_seconds"]) <= 0.5, name


def test_regions_are_contiguous_and_end_at_run_end(records):
    for name, rec in records:
        items = ann.annotations_for(rec, name)
        start = ann.to_ms(ann.parse_time(rec["start"]))
        end = ann.to_ms(ann.parse_time(rec["end"]))
        names = {s["state"] for s in rec["states"]}
        regions = [a for a in items if a["text"] in names]
        assert len(regions) == len(rec["states"])
        assert regions[0]["time"] == start
        for a, b in zip(regions, regions[1:]):
            assert a["timeEnd"] == b["time"], name
        assert abs(regions[-1]["timeEnd"] - end) <= 1000, name


def test_tags_follow_annotate_sh(records):
    name, rec = records[-1]
    items = ann.annotations_for(rec, name)
    run_tag = "run:" + rec["execution"]
    for a in items:
        assert "console" in a["tags"] and run_tag in a["tags"]
    started = next(a for a in items if a["text"] == "Pipeline run started")
    assert started["tags"] == ["cerberus", run_tag, "step", "console"]
    dq = by_tag(items, "cerberus-dq")
    assert len(dq) == 1 and {"cerberus", "dq"} <= set(dq[0]["tags"])
    # Like annotate_placeholders, the Now and Clean-up tiles carry no `cerberus` tag.
    for tag in ("cerberus-now", "cerberus-teardown"):
        (one,) = by_tag(items, tag)
        assert "cerberus" not in one["tags"]
    assert by_tag(items, "cerberus-teardown")[0]["text"] == ann.TEARDOWN_TEXT


def test_dq_wording_matches_annotate_dq_verdict(records):
    by_name = dict(records)
    ok = by_name["exercise-20261013T055859Z.json"]
    assert ann.dq_text(ok) == "Quality checks: PASSED (26 checks, 0 errors, 1 warning)"
    bad = by_name["exercise-20261008T085728Z.json"]
    assert ann.dq_text(bad) == "Quality checks: FAILED (2 errors) — see run record"
    none = by_name["demo-7-8-take1-20261006T075445.json"]
    assert "not recorded" in ann.dq_text(none)


def test_failed_run_says_failed(records):
    rec = dict(records)["exercise-20261008T085728Z.json"]
    items = ann.annotations_for(rec)
    assert "Pipeline run FAILED" in [a["text"] for a in items]
    (now,) = by_tag(items, "cerberus-now")
    assert "FAILED" in now["text"]


def test_generator_region_is_approx_and_before_start(records):
    rec = dict(records)["exercise-20261013T055859Z.json"]
    (gen,) = [a for a in ann.annotations_for(rec) if "approx." in a["text"]]
    assert gen["timeEnd"] - gen["time"] == round(rec["generator"]["write_seconds"] * 1000)
    assert gen["time"] < ann.to_ms(ann.parse_time(rec["start"]))
    nogen = dict(records)["exercise-20261008T095905Z.json"]
    assert not [a for a in ann.annotations_for(nogen) if "approx." in a["text"]]


def test_hostile_fields_are_cleaned():
    rec = {
        "execution": "<script>alert(1)</script>",
        "status": "<img src=x onerror=alert(1)>",
        "start": "2026-10-13T06:35:02+00:00",
        "end": "2026-10-13T06:36:02+00:00",
        "run_seconds": 60.0,
        "states": [{"state": "<b>x</b>", "seconds": 60.0}],
    }
    for a in ann.annotations_for(rec):
        blob = a["text"] + " ".join(a["tags"])
        assert "<" not in blob and ">" not in blob and "=" not in blob


def test_hostile_data_quality_is_not_echoed():
    rec = {
        "execution": "x",
        "status": "FAILED",
        "start": "2026-10-13T06:35:02+00:00",
        "end": "2026-10-13T06:36:02+00:00",
        "run_seconds": 60.0,
        "states": [],
        "data_quality": {"passed": True, "errors": "<b>x</b>", "warnings": True, "checks": "<i>"},
    }
    assert ann.dq_text(rec) == "Quality checks: PASSED (? checks, ? errors, ? warnings)"
    rec["data_quality"]["passed"] = False
    assert "<" not in ann.dq_text(rec)


def test_missing_field_fails_loudly():
    try:
        ann.annotations_for({"execution": "x"}, "x.json")
    except ann.RunRecordError as exc:
        assert "x.json" in str(exc)
    else:
        raise AssertionError("expected RunRecordError")
