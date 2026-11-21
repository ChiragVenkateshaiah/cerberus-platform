"""The showcase snapshot builder (11.2a): determinism, drops, redaction, freshness.

No AWS, no network. The parity test against the named queries is in
observability/status/test_e2e.py (it needs a local Prometheus).
"""

import copy
import json

import pytest

from cerberus_console import queries
from cerberus_landing import showcase

REAL_RUNS = showcase.DEFAULT_RUNS
COMMITTED = showcase.DEFAULT_OUT
ACCOUNT = "123456789012"  # a made-up ID, never a real one


def make(directory, execution, *, name=None, **over):
    rec = {
        "execution": execution,
        "status": "SUCCEEDED",
        "start": "2026-11-01T10:00:00+00:00",
        "end": "2026-11-01T10:10:00+00:00",
        "run_seconds": 600.0,
        "events_processed": 5000,
        "events_per_second": 8,
        "states": [{"state": "RunDbt", "seconds": 12.5}],
        "cost": {
            "run_usd": 0.1,
            "usd_per_million_events": 1.5,
            "estimated": True,
            "complete": True,
        },
        "data_quality": {"passed": True, "errors": 0, "warnings": 1},
    }
    rec.update(over)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name or execution}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


def build(runs, tmp_path, **kw):
    return showcase.build_files(runs, root=tmp_path, **kw)


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def test_two_builds_give_the_same_bytes():
    assert showcase.build_files(REAL_RUNS) == showcase.build_files(REAL_RUNS)


def test_every_committed_record_converts_or_is_dropped_with_a_reason():
    files = sorted(REAL_RUNS.glob("*.json"))
    converted, sources, drops = showcase.load_runs(REAL_RUNS, showcase.REPO)
    assert set(drops) == set(showcase.DROP_REASONS)
    assert len(converted) + sum(drops.values()) == len(files)
    assert len(sources) == len(converted)
    assert sum(drops.values()) == 0  # a committed record is never dropped silently


def test_committed_snapshot_is_up_to_date():
    assert showcase.stale_files(COMMITTED, showcase.build_files(REAL_RUNS)) == []


def test_runs_are_newest_first_and_generated_at_is_the_newest_end():
    runs = json.loads(showcase.build_files(REAL_RUNS)["runs.json"])
    starts = [r["start"] for r in runs["runs"]]
    assert starts == sorted(starts, reverse=True)
    assert runs["generated_at"] == max(r["end"] for r in runs["runs"])


def test_status_labels_come_from_the_named_query_set():
    doc = json.loads(showcase.build_files(REAL_RUNS)["status.json"])
    entries = queries.queries(queries.load(showcase.QUERIES_PATH))
    assert len(entries) == 17
    assert list(doc["queries"]) == [e["name"] for e in entries]
    for entry in entries:
        assert doc["queries"][entry["name"]]["label"] == entry["label"]


def test_every_source_sha_is_the_git_blob_sha():
    # `git hash-object` of "hello\n" is a known value.
    assert showcase.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    runs = json.loads(showcase.build_files(REAL_RUNS)["runs.json"])
    first = runs["generated_from"][0]
    assert showcase.blob_sha((showcase.REPO / first["path"]).read_bytes()) == first["sha"]


def test_slo_one_over_the_trailing_runs():
    files = showcase.build_files(REAL_RUNS)
    slo = json.loads(files["slo.json"])["objectives"][0]
    rows = json.loads(files["runs.json"])["runs"]
    window = rows[:20]
    assert slo["runs_in_window"] == min(len(rows), 20)
    assert slo["succeeded"] == sum(r["status"] == "SUCCEEDED" for r in window)
    assert slo["share_succeeded"] == round(slo["succeeded"] / len(window), 4)
    assert slo["met"] is (slo["share_succeeded"] >= 0.95)


def test_slo_window_is_the_newest_twenty_and_budget_is_not_clamped():
    rows = [{"status": "SUCCEEDED"}] * 19 + [{"status": "FAILED"}] + [{"status": "FAILED"}] * 5
    one = showcase.slo_objectives(rows)[0]
    assert (one["runs_in_window"], one["succeeded"]) == (20, 19)
    assert one["share_succeeded"] == 0.95 and one["met"] is True
    assert one["error_budget_used"] == 1.0  # the one allowed failure is used
    clean = showcase.slo_objectives([{"status": "SUCCEEDED"}] * 20)[0]
    assert clean["error_budget_used"] == 0.0
    over = showcase.slo_objectives([{"status": "SUCCEEDED"}] * 15 + [{"status": "FAILED"}] * 2)[0]
    assert over["error_budget_used"] == 2.3529  # overspent: not clamped
    assert showcase.slo_objectives([])[0]["met"] is None


def test_hostile_records_never_reach_the_output(tmp_path):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    hostile_names = [
        f"arn:aws:states:us-east-1:{ACCOUNT}:execution:x",
        "exercise-a@b.example",
        "../../etc/passwd",
        "exercise-" + "x" * 80,
        "s3:--bucket",
    ]
    for i, bad in enumerate(hostile_names):
        make(runs, bad, name=f"exercise-bad{i}")
    make(runs, f"exercise-{ACCOUNT}", name="exercise-digits")
    make(runs, "other-20261102T100000Z", name="other-20261102T100000Z")  # unknown kind
    make(runs, "demo-20261102T100000Z", name="exercise-mismatch")  # file/execution kind differ
    make(runs, "exercise-20261103T100000Z", status=f"arn:aws:iam::{ACCOUNT}:role/x")
    make(runs, "exercise-20261104T100000Z", start="s3://bucket/key")
    make(runs, "exercise-20261105T100000Z", run_seconds="1e999")
    make(runs, "exercise-20261106T100000Z", states=[{"state": "RunDbt", "seconds": "x@y.z"}])
    make(runs, "exercise-20261107T100000Z", data_quality="https://x.amazonaws.com")
    # Valid shape, hostile text in fields that must never be copied.
    make(
        runs,
        "exercise-20261108T100000Z",
        status="FAILED",
        failed_state=f"arn:aws:states:::{ACCOUNT}",
        states=[{"state": "s3://b/k", "seconds": 1.0}, {"state": "RunDbt", "seconds": 2.0}],
        note="user@example.com cloudfront.net",
    )
    (runs / "exercise-notjson.json").write_text("{not json", encoding="utf-8")
    (runs / "exercise-list.json").write_text("[]", encoding="utf-8")
    out = build(runs, tmp_path)
    for name, data in out.items():
        doc = json.loads(data)
        for text in strings(doc):
            assert showcase.scan_text(text) == [], (name, text)
            # Only a git blob SHA (40 hex characters) may hold 12 digits.
            assert not showcase._DIGITS_12.search(text) or showcase._SHA.fullmatch(text), name
    runs_doc = json.loads(out["runs.json"])
    kept = {r["execution"] for r in runs_doc["runs"]}
    assert kept == {"exercise-20261101T100000Z", "exercise-20261108T100000Z"}
    assert runs_doc["dropped"]["count"] == 15
    assert set(runs_doc["dropped"]["reasons"]) <= set(showcase.DROP_REASONS)
    failed = [r for r in runs_doc["runs"] if r["status"] == "FAILED"][0]
    assert [s["state"] for s in failed["steps"]][0] == "InvokeIngestion"  # fixed names only
    status = json.loads(out["status.json"])["queries"]
    assert status["latest_failed_step"]["value"] is None  # a hostile name names no step


def test_a_leak_in_the_conversion_fails_the_build_and_writes_nothing(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    out = tmp_path / "out"
    files = build(runs, tmp_path)
    showcase.write_atomic(out, files)
    before = {p.name: p.read_bytes() for p in out.iterdir()}

    real_row = showcase._row

    def leaky(rec, kind):
        row = real_row(rec, kind)
        row["execution"] = f"arn:aws:states:us-east-1:{ACCOUNT}:execution:x"
        return row

    monkeypatch.setattr(showcase, "_row", leaky)
    make(runs, "exercise-20261102T100000Z")  # a changed input, so the new build would differ
    with pytest.raises(showcase.RedactionError) as err:
        build(runs, tmp_path)
    assert "forbidden text 'arn:'" in str(err.value)
    assert ACCOUNT not in str(err.value)  # the message names the rule, never the value
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_a_planted_arn_in_the_comparison_input_fails_and_leaves_outputs_untouched(tmp_path):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    out = tmp_path / "out"
    showcase.write_atomic(out, build(runs, tmp_path))
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    bad = copy.deepcopy(COMPARISON_OK)
    bad["caveats"] = ["trial_data", f"arn:aws:iam::{ACCOUNT}:role/x"]
    (out / showcase.COMPARISON_INPUT).write_text(json.dumps(bad), encoding="utf-8")
    before[showcase.COMPARISON_INPUT] = (out / showcase.COMPARISON_INPUT).read_bytes()
    with pytest.raises(showcase.RedactionError) as err:
        build(runs, tmp_path, comparison_input=out / showcase.COMPARISON_INPUT)
    assert "forbidden text 'arn:'" in str(err.value) and ACCOUNT not in str(err.value)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before  # no temp file, no change


COMPARISON_OK = {
    "step": "RunTransform",
    "input": {"run_id": "exercise-20261101T100000Z", "events": 1000000},
    "measured_on": "2026-11-20",
    "trial": True,
    "engines": {
        "cerberus": {
            "run_seconds": 100.5,
            "usd": 0.25,
            "usd_per_million_events": 0.25,
            "cost_source": "run_record",
            "estimated": True,
        },
        "databricks": {
            "run_seconds": 90.0,
            "usd": 0.5,
            "usd_per_million_events": 0.5,
            "cost_source": "databricks_billing",
            "estimated": False,
        },
    },
    "caveats": ["trial_data", "one_step_only"],
}


def test_comparison_is_omitted_without_input_and_the_build_succeeds(tmp_path):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    out = tmp_path / "out"
    files = build(runs, tmp_path, comparison_input=out / showcase.COMPARISON_INPUT)
    assert sorted(files) == sorted(showcase.OUTPUTS)
    assert "comparison.json" not in build(runs, tmp_path)
    assert "comparison.json" not in showcase.build_files(REAL_RUNS)


def test_comparison_is_built_from_the_input_and_removed_when_the_input_goes(tmp_path):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    out = tmp_path / "out"
    out.mkdir()
    inp = out / showcase.COMPARISON_INPUT
    inp.write_text(json.dumps(COMPARISON_OK), encoding="utf-8")
    files = build(runs, tmp_path, comparison_input=inp)
    doc = json.loads(files["comparison.json"])
    assert doc["engines"]["databricks"]["cost_source"] == "databricks_billing"
    assert doc["generated_from"][0]["path"] == "out/comparison-input.json"
    showcase.write_atomic(out, files)
    assert (out / "comparison.json").is_file()
    inp.unlink()
    assert showcase.stale_files(out, build(runs, tmp_path)) == ["comparison.json"]
    showcase.write_atomic(out, build(runs, tmp_path))
    assert not (out / "comparison.json").exists()
    assert showcase.stale_files(out, build(runs, tmp_path)) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(step="NotAStep"),
        lambda d: d.update(trial=False),
        lambda d: d["engines"]["cerberus"].update(cost_source="invoice"),
        lambda d: d["engines"]["cerberus"].update(usd=float("nan")),
        lambda d: d["input"].update(run_id=f"exercise-{ACCOUNT}"),
        lambda d: d.update(caveats=["has space"]),
        lambda d: d.update(extra=1),
        lambda d: d.update(measured_on="user@example.com"),
    ],
)
def test_a_bad_comparison_input_fails(tmp_path, mutate):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    doc = copy.deepcopy(COMPARISON_OK)
    mutate(doc)
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(showcase.ShowcaseError):
        build(runs, tmp_path, comparison_input=inp)


def test_gate_rejects_each_forbidden_fragment_and_a_twelve_digit_string():
    doc = json.loads(showcase.build_files(REAL_RUNS)["runs.json"])
    steps = showcase._series().STEPS
    showcase.gate("runs.json", doc, steps)  # the real file passes
    for text in ("s3://b/k", "x.amazonaws.com", "d111.cloudfront.net", "a@b", f"id {ACCOUNT}"):
        bad = copy.deepcopy(doc)
        bad["generated_from"][0]["path"] = text
        with pytest.raises(showcase.RedactionError):
            showcase.gate("runs.json", bad, steps)
    unknown = copy.deepcopy(doc)
    unknown["runs"][0]["kind"] = "benchmark"
    with pytest.raises(showcase.RedactionError, match="allowlist"):
        showcase.gate("runs.json", unknown, steps)
    extra = copy.deepcopy(doc)
    extra["runs"][0]["note"] = "free text"
    with pytest.raises(showcase.RedactionError):
        showcase.gate("runs.json", extra, steps)


def test_a_sha_may_hold_twelve_digits_but_only_in_a_sha_field():
    doc = json.loads(showcase.build_files(REAL_RUNS)["runs.json"])
    steps = showcase._series().STEPS
    ok = copy.deepcopy(doc)
    ok["generated_from"][0]["sha"] = "1" * 12 + "a" * 28
    showcase.gate("runs.json", ok, steps)
    bad = copy.deepcopy(doc)
    bad["generated_from"][0]["path"] = "observability/" + "1" * 12
    with pytest.raises(showcase.RedactionError, match="12-digit"):
        showcase.gate("runs.json", bad, steps)


def test_scan_text_exact_account_match_and_no_echo():
    assert showcase.scan_text("nothing here") == []
    assert showcase.scan_text(f"balance {ACCOUNT}") == []  # no plain 12-digit rule
    assert showcase.scan_text(f"id {ACCOUNT}", ACCOUNT) == ["the exact account ID"]
    assert showcase.scan_text("id 999999999999", ACCOUNT) == []  # exact only
    found = showcase.scan_text("ARN:aws:x S3://b @", ACCOUNT)
    assert found == [
        "forbidden text 'arn:'",
        "forbidden text 's3://'",
        "forbidden text '@'",
    ]
    assert all(ACCOUNT not in f for f in found)
    with pytest.raises(ValueError) as err:
        showcase.scan_text("x", "1234")
    assert "1234" not in str(err.value)


def test_check_fails_on_a_stale_file_and_passes_when_fresh(tmp_path):
    runs = tmp_path / "runs"
    make(runs, "exercise-20261101T100000Z")
    files = build(runs, tmp_path)
    out = tmp_path / "out"
    assert showcase.stale_files(out, files) == list(files)  # nothing written yet
    showcase.write_atomic(out, files)
    assert showcase.stale_files(out, files) == []
    (out / "slo.json").write_text("{}", encoding="utf-8")
    assert showcase.stale_files(out, files) == ["slo.json"]


def test_status_values_for_two_records():
    ok = json.loads((REAL_RUNS / "exercise-20261015T145812Z.json").read_text())
    bad = json.loads((REAL_RUNS / "exercise-20261008T085728Z.json").read_text())
    entries = queries.queries(queries.load(showcase.QUERIES_PATH))
    only_bad = showcase.status_values([bad], entries)
    assert only_bad["latest_status"]["value"] == 0.0
    assert only_bad["latest_failed_step"]["value"] == "RunDbt"
    assert only_bad["last_success"]["value"] is None
    assert only_bad["latest_step_seconds"]["by_step"]["RunServingQuery"] is None
    both = showcase.status_values([bad, ok], entries)
    assert both["latest_status"]["value"] == 1.0
    assert both["latest_failed_step"]["value"] is None
    assert both["runs_90d"]["value"] == 2
    assert both["run_success_share_90d"]["value"] == pytest.approx(0.5)
    assert both["newest_finished_execution"]["execution"] == ok["execution"]


def test_cli_writes_checks_and_a_failed_build_leaves_the_previous_files(
    tmp_path, monkeypatch, capsys
):
    out = tmp_path / "out"
    args = ["--runs", str(REAL_RUNS), "--out", str(out)]
    assert showcase.main(args) == 0
    assert showcase.main([*args, "--check"]) == 0
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    assert sorted(before) == sorted(showcase.OUTPUTS)  # and no temp file
    assert before == showcase.build_files(REAL_RUNS)

    real_row = showcase._row

    def leaky(rec, kind):
        return {**real_row(rec, kind), "execution": "arn:aws:states:::execution:x"}

    monkeypatch.setattr(showcase, "_row", leaky)
    assert showcase.main(args) == 1
    assert "redaction gate failed" in capsys.readouterr().err
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before

    (out / "runs.json").write_text("{}", encoding="utf-8")
    monkeypatch.undo()
    assert showcase.main([*args, "--check"]) == 1
    assert "runs.json" in capsys.readouterr().err


def test_a_sha_shaped_value_with_twelve_digits_fails_outside_generated_from_sha():
    doc = json.loads(showcase.build_files(REAL_RUNS)["runs.json"])
    steps = showcase._series().STEPS
    value = "1" * 12 + "a" * 28
    for where in (("generated_from", 0, "path"), ("runs", 0, "execution")):
        bad = copy.deepcopy(doc)
        node = bad
        for part in where[:-1]:
            node = node[part]
        node[where[-1]] = value
        with pytest.raises(showcase.RedactionError):
            showcase.gate("runs.json", bad, steps)
    bad = copy.deepcopy(doc)
    bad["dropped"]["reasons"] = {"sha": 1}
    bad["generated_from"].append({"path": "x", "sha": "z" * 40})
    with pytest.raises(showcase.RedactionError):
        showcase.gate("runs.json", bad, steps)
