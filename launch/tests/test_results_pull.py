"""results_pull.py with a fake Athena client and a fake Cost Explorer client."""

# ruff: noqa: E501 -- fixture rows read better on one line each.

import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCH))

import results_pull as rp  # noqa: E402


def cells(row):
    return {"Data": [{"VarCharValue": c} for c in row]}


class FakeAthena:
    """Returns a header plus the given rows for every query; records each call."""

    def __init__(self, rows_for=None, header_for=None, pages=1):
        self.rows_for = rows_for or {}
        self.header_for = header_for or {}
        self.sql = {}
        self.calls = []
        self.pages = pages

    def start_query_execution(self, **kw):
        qid = f"q{len(self.sql)}"
        self.sql[qid] = kw["QueryString"]
        self.calls.append(kw)
        return {"QueryExecutionId": qid}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    @staticmethod
    def name_of(sql):
        for name, marker in (
            ("cdn_subrun", "with windows"),
            ("cdn_class", "as uri_class"),
            ("cdn_minute", "fct_cdn_requests"),
            ("release_window", "fct_release_window"),
            ("isp_minute", "fct_isp_minute"),
            ("cdn_run", "fct_cdn_run"),
        ):
            if marker in sql:
                return name
        return None

    def get_query_results(self, QueryExecutionId, MaxResults=1000, NextToken=None):
        sql = self.sql[QueryExecutionId]
        name = self.name_of(sql)
        if name is None:  # not one of the five queries
            return {"ResultSet": {"Rows": [cells(["x"])]}}
        header = self.header_for.get(name, rp.QUERIES[name][1].split())
        data = self.rows_for.get(name, [])
        rows = [header, *data]
        if self.pages > 1:
            size = -(-len(rows) // self.pages)
            start = int(NextToken or 0)
            chunk = rows[start : start + size]
            token = str(start + size) if start + size < len(rows) else None
            out = {"ResultSet": {"Rows": [cells(r) for r in chunk]}}
            if token:
                out["NextToken"] = token
            return out
        return {"ResultSet": {"Rows": [cells(r) for r in rows]}}


def good_rows():
    return {
        "release_window": [
            [
                "synthetic-exercise",
                "region_02",
                "2026-11-19 00:01:00.000",
                "1",
                "5",
                "0",
                "4",
                "2",
                "1.500",
                "0",
                "1",
            ],
            [
                "synthetic-exercise",
                "region_01",
                "2026-11-19 00:00:00.000",
                "0",
                "5",
                "0",
                "4",
                "2",
                "1.500",
                "0",
                "1",
            ],
        ],
        "isp_minute": [
            [
                "synthetic-exercise",
                "synthetic-isp-a",
                "2026-11-19 00:00:00.000",
                "3",
                "1",
                "0.5",
                "0.3",
            ]
        ],
        "cdn_run": [
            ["synthetic-a", "ALL", "10", "6", "1", "3", "0.6", "1.0", "20.0", "80.0", "complete"]
        ],
        "cdn_minute": [["synthetic-a", "2026-11-27 10:05:00.000", "10", "1.0"]],
        "cdn_class": [["synthetic-a", "SEA", "build", "10", "6", "1", "3", "1.0"]],
        "cdn_subrun": [
            ["synthetic-a", "d-1", "5", "5", "0", "0", "1.000000"],
            ["synthetic-a", "d-0", "10", "6", "1", "3", "0.600000"],
        ],
    }


def put_window(runs, session, sub, start=1795862000000, end=1795862600000, **extra):
    results = runs / session / "results"
    results.mkdir(parents=True, exist_ok=True)
    body = {"run": sub, "start_ms": start, "end_ms": end, **extra}
    (results / f"{sub}.window.json").write_text(json.dumps(body))


def pull(tmp_path, athena, sessions=("synthetic-a",), exercise="synthetic-exercise", runs=None):
    runs = runs if runs is not None else tmp_path.parent / "no-runs"
    return rp.pull_results(athena, list(sessions), exercise, tmp_path, date(2026, 11, 29), runs)


def test_pull_writes_sorted_csvs_with_fixed_headers_and_manifest(tmp_path):
    athena = FakeAthena(good_rows())
    manifest = pull(tmp_path, athena, ("synthetic-b", "synthetic-a"))
    assert {p.name for p in tmp_path.iterdir()} == {
        *(f"{n}.csv" for n in rp.QUERIES),
        "manifest.json",
    }
    with (tmp_path / "release_window.csv").open() as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == rp.QUERIES["release_window"][1].split()
    assert [r[1] for r in rows[1:]] == ["region_01", "region_02"]  # sorted
    assert manifest["session_run_ids"] == ["synthetic-a", "synthetic-b"]
    assert (
        manifest["pull_date"] == "2026-11-29"
        and manifest["exercise_run_id"] == "synthetic-exercise"
    )
    sql = (LAUNCH / "queries" / "cdn_run.sql").read_text()
    assert manifest["queries"]["cdn_run"] == {
        "sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "rows": 1,
    }
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest


def test_pull_bytes_are_stable(tmp_path):
    pull(tmp_path / "a", FakeAthena(good_rows()))
    pull(tmp_path / "b", FakeAthena(good_rows(), pages=3))
    for name in [*(f"{n}.csv" for n in rp.QUERIES), "manifest.json"]:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_run_id_check_before_substitution(tmp_path):
    for bad in ("Bad_ID", "x" * 41, "", "a'; drop table x; --", "has space"):
        with pytest.raises(rp.PullError):
            rp.render_sql("cdn_run", "synthetic-exercise", [bad])
        with pytest.raises(rp.PullError):
            rp.render_sql("release_window", bad, ["synthetic-a"])
    athena = FakeAthena(good_rows())
    with pytest.raises(rp.PullError):
        pull(tmp_path, athena, exercise="Bad")
    assert athena.calls == []  # nothing was sent
    sql = rp.render_sql("cdn_run", "synthetic-exercise", ["synthetic-b", "synthetic-a"])
    assert "in ('synthetic-a', 'synthetic-b')" in sql and "{" not in sql
    assert "run_id = 'synthetic-exercise'" in rp.render_sql(
        "release_window", "synthetic-exercise", ["x"]
    )


def test_row_cap_refused_and_nothing_written(tmp_path):
    rows = good_rows()
    rows["isp_minute"] = [
        ["r", "i", f"m{n:06d}", "1", "0", "0.1", "0.0"] for n in range(rp.MAX_ROWS + 1)
    ]
    with pytest.raises(rp.PullError, match="more than"):
        pull(tmp_path / "o", FakeAthena(rows))
    assert not (tmp_path / "o").exists()


def test_row_cap_allows_the_limit():
    data = [["r", "i", f"m{n:06d}", "1", "0", "0.1", "0.0"] for n in range(rp.MAX_ROWS)]
    assert (
        len(rp.check_rows("isp_minute", [rp.QUERIES["isp_minute"][1].split(), *data]))
        == rp.MAX_ROWS
    )


def test_twelve_digit_value_refused_without_printing_it(tmp_path, capsys):
    rows = good_rows()
    rows["cdn_minute"][0][2] = "1" + "2" * 11
    athena = FakeAthena(rows)
    rc = rp.main(
        [
            "results",
            "--session",
            "synthetic-a",
            "--exercise",
            "synthetic-exercise",
            "--out",
            str(tmp_path / "o"),
        ],
        athena=athena,
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "12-digit" in err and "2" * 11 not in err
    assert not (tmp_path / "o").exists()
    rows["cdn_minute"][0][2] = "1" + "2" * 12  # 13 digits is not a 12-digit run
    assert pull(tmp_path / "ok", FakeAthena(rows))["queries"]["cdn_minute"]["rows"] == 1


def test_unexpected_header_refused(tmp_path):
    athena = FakeAthena(good_rows(), header_for={"cdn_run": ["run_id", "pop"]})
    with pytest.raises(rp.PullError, match="header"):
        pull(tmp_path, athena)


def test_query_uses_the_dq_workgroup_and_database():
    athena = FakeAthena(good_rows())
    rp.run_query(athena, "select 1")
    assert athena.calls[0]["WorkGroup"] == "cerberus_platform_dq"
    assert athena.calls[0]["QueryExecutionContext"] == {"Database": "cerberus_platform"}


def test_failed_query_raises():
    class Failed(FakeAthena):
        def get_query_execution(self, QueryExecutionId):
            return {"QueryExecution": {"Status": {"State": "FAILED"}}}

    with pytest.raises(rp.PullError):
        rp.run_query(Failed(), "select 1")


def test_main_is_read_only_shape(tmp_path):
    src = (LAUNCH / "results_pull.py").read_text()
    for word in ("put_", "create_", "delete_", "update_"):
        assert word not in src


def test_fixture_extract_headers_match_the_pull():
    fx = Path(__file__).resolve().parent / "fixtures" / "synthetic" / "extracts"
    for name, (_, header) in rp.QUERIES.items():
        with (fx / f"{name}.csv").open() as handle:
            assert next(csv.reader(handle)) == header.split(), name


def test_subrun_query_takes_validated_windows_as_numbers(tmp_path):
    runs = tmp_path / "runs"
    put_window(runs, "synthetic-a", "d-0")
    put_window(runs, "synthetic-a", "d-1", 1795862700000, 1795862760000)
    athena = FakeAthena(good_rows())
    pull(tmp_path / "o", athena, runs=runs)
    (sql,) = [q for q in athena.sql.values() if "with windows" in q]
    assert "('synthetic-a', 'd-0', 1795862000000, 1795862600000)" in sql
    assert "('synthetic-a', 'd-1', 1795862700000, 1795862760000)" in sql
    assert "{" not in sql
    with (tmp_path / "o" / "cdn_subrun.csv").open() as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == rp.QUERIES["cdn_subrun"][1].split()
    assert [r[1] for r in rows[1:]] == ["d-0", "d-1"]  # sorted


@pytest.mark.parametrize(
    "bad",
    [
        {"start_ms": "1795862000000"},  # a string, not an int
        {"start_ms": 1.7958620000e12},  # a float
        {"start_ms": True},
        {"start_ms": 10**11},  # 12 digits
        {"start_ms": 10**13},  # 14 digits
        {"end_ms": 1795861000000},  # before the start
        {"run": "d-9"},  # the name differs from the file
        {"run": "d-0'; drop table x; --"},
    ],
)
def test_a_bad_window_adds_no_row_and_no_text_reaches_the_sql(tmp_path, bad):
    runs = tmp_path / "runs"
    put_window(runs, "synthetic-a", "d-0", **bad)
    athena = FakeAthena(good_rows())
    pull(tmp_path / "o", athena, runs=runs)
    assert not [q for q in athena.sql.values() if "with windows" in q]  # no query: no window
    with (tmp_path / "o" / "cdn_subrun.csv").open() as handle:
        assert len(list(csv.reader(handle))) == 1  # the header only


def test_a_window_file_name_that_is_not_a_sub_run_is_skipped(tmp_path):
    runs = tmp_path / "runs"
    put_window(runs, "synthetic-a", "d-0")
    (runs / "synthetic-a" / "results" / "x'y.window.json").write_text("{}")
    assert [w[:2] for w in rp.load_windows(runs, ["synthetic-a"])] == [("synthetic-a", "d-0")]
    with pytest.raises(rp.PullError):
        rp.windows_sql([("synthetic-a", "d-0'", 1795862000000, 1795862600000)])
    with pytest.raises(rp.PullError):
        rp.windows_sql([("Bad_ID", "d-0", 1795862000000, 1795862600000)])


def test_thirteen_digit_windows_are_not_refused_as_twelve_digit_runs(tmp_path):
    runs = tmp_path / "runs"
    put_window(runs, "synthetic-a", "d-0")
    manifest = pull(tmp_path / "o", FakeAthena(good_rows()), runs=runs)
    assert manifest["queries"]["cdn_subrun"]["rows"] == 2
