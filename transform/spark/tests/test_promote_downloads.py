"""Tests for the 17.5 downloads silver job's pure helpers. No Spark, no AWS."""

import ast
import re
import sys
from pathlib import Path

import promote_downloads_spark as p
import pytest

SOURCE = Path(p.__file__).read_text()


def test_run_id_of_reads_the_path():
    assert p.run_id_of("s3a://b/downloads_bulk/run_id=e1m-20261126/dt=2026-11-19/part-0.json") == (
        "e1m-20261126"
    )
    assert p.run_id_of("file:/x/downloads_bulk/run_id=sample-v1/_manifest.json") == "sample-v1"
    assert p.run_id_of("s3a://b/downloads_bulk/run_id=/dt=2026-11-19/part-0.json") is None
    assert p.run_id_of("s3a://b/payments_bulk/dt=2026-11-19/part-0.json") is None


def test_select_runs_takes_only_manifests_newer_than_the_watermark():
    manifests = [("a", 100), ("b", 200), ("c", 300)]
    everything = {"a", "b", "c"}
    assert p.select_runs(manifests, 0) == (["a", "b", "c"], 300)
    assert p.select_runs(manifests, 200, everything) == (["c"], 300)
    # Equal is not newer: a run already in silver is not read again.
    assert p.select_runs(manifests, 300, everything) == ([], 300)


def test_select_runs_never_moves_the_watermark_back():
    assert p.select_runs([], 500) == ([], 500)
    assert p.select_runs([("a", 100)], 500, {"a"}) == ([], 500)


def test_a_rewritten_manifest_selects_the_run_again():
    # A re-run deletes and rewrites the manifest, so its time moves forward.
    runs, watermark = p.select_runs([("a", 100)], 0)
    assert (runs, watermark) == (["a"], 100)
    assert p.select_runs([("a", 150)], watermark, {"a"}) == (["a"], 150)


def test_a_late_manifest_for_a_never_promoted_run_is_taken():
    # b finished after c was promoted: its manifest is older than the watermark.
    manifests = [("b", 200), ("c", 300)]
    assert p.select_runs(manifests, 300, {"c"}) == (["b"], 300)


def test_a_manifest_in_the_same_second_as_the_watermark_is_taken():
    manifests = [("a", 1000), ("b", 1000)]
    # a was promoted and set the watermark; b has the same time and is not in silver.
    assert p.select_runs(manifests, 1000, {"a"}) == (["b"], 1000)


def test_a_late_manifest_older_than_the_overlap_is_not_taken():
    watermark = 10 * p.LATE_OVERLAP_MS
    old = watermark - p.LATE_OVERLAP_MS - 1
    assert p.select_runs([("x", old)], watermark, set()) == ([], watermark)
    assert p.select_runs([("x", old + 1)], watermark, set()) == (["x"], watermark)


def test_a_promoted_run_is_not_read_again_on_a_rerun_of_the_job():
    # Idempotent: after both runs are in silver, nothing is selected.
    manifests = [("b", 200), ("c", 300)]
    assert p.select_runs(manifests, 300, {"b", "c"}) == ([], 300)


def test_null_keys_stop_the_job_before_the_append():
    assert p.null_key_message({"event_id": 0, "occurred_at": 0, "ingested_at": 0}) is None
    message = p.null_key_message({"event_id": 2, "occurred_at": 0, "ingested_at": 5})
    assert "event_id in 2 rows" in message and "ingested_at in 5 rows" in message
    assert "occurred_at" not in message


def test_the_null_check_runs_before_the_append():
    assert SOURCE.index("null_key_message(null_key_counts") < SOURCE.index(".append()")


def test_runs_without_a_manifest_are_never_listed():
    # A run still being written has data files and no manifest: run_manifests
    # globs only `_manifest.json`, so select_runs never sees it.
    assert "_manifest.json" in p.MANIFEST_NAME
    assert p.select_runs([], 0) == ([], 0)


def test_touched_days_come_from_dt_directories():
    files = [
        "s3a://b/downloads_bulk/run_id=r1/dt=2026-11-19/part-0.json",
        "s3a://b/downloads_bulk/run_id=r1/dt=2026-11-18/part-1.json",
        "s3a://b/downloads_bulk/run_id=r2/dt=2026-11-19/part-0.json",
    ]
    assert p.touched_days(files) == ["2026-11-18", "2026-11-19"]


def test_touched_days_is_none_when_any_path_has_no_day():
    files = ["s3a://b/downloads_bulk/run_id=r1/dt=2026-11-19/part-0.json", "s3a://b/other.json"]
    assert p.touched_days(files) is None


def test_day_bounds_cross_a_month_end():
    assert p.day_bounds("2026-11-30") == ("2026-11-30 00:00:00", "2026-12-01 00:00:00")


def test_the_job_has_no_account_id_or_arn():
    assert not re.search(r"\b\d{12}\b", SOURCE)
    assert "arn:aws" not in SOURCE


def test_bucket_arguments_are_required(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x"])
    with pytest.raises(SystemExit):
        p.parse_args()
    monkeypatch.setattr(sys, "argv", ["x", "--bronze-root", "s3a://b", "--warehouse", "s3://w"])
    args = p.parse_args()
    assert args.bronze_root == "s3a://b/"
    assert args.warehouse == "s3://w/"


def test_create_table_matches_the_envelope_and_partitions_by_day():
    columns = re.findall(r"^\s{4}(\w+) \w+,?$", p.CREATE_TABLE, flags=re.M)
    assert columns == [
        "event_id",
        "event_family",
        "event_type",
        "occurred_at",
        "ingested_at",
        "schema_version",
        "client_id",
        "platform",
        "region",
        "isp",
        "bytes",
        "duration_ms",
        "throughput_mbps",
        "http_status",
        "run_id",
        "loaded_at",
    ]
    assert "PARTITIONED BY (days(occurred_at))" in p.CREATE_TABLE
    assert "'format-version' = '2'" in p.CREATE_TABLE


def test_the_key_is_event_id_alone_and_the_read_fails_fast():
    assert p.KEY == ["event_id"]
    assert '"mode", "FAILFAST"' in SOURCE
    ast.parse(SOURCE)  # python 3.10 syntax
