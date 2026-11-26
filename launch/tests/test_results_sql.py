"""The 17.7 result queries parse as Trino (sqlglot), once the run ids are put in."""

import re
import sys
from pathlib import Path

import pytest

sqlglot = pytest.importorskip("sqlglot")

LAUNCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCH))

import results_pull as rp  # noqa: E402


@pytest.mark.parametrize("name", sorted(rp.QUERIES))
def test_query_parses_as_trino_and_selects_the_expected_columns(name):
    sql = rp.render_sql(name, "synthetic-exercise", ["synthetic-a", "synthetic-b"])
    (tree,) = sqlglot.parse(sql, read="trino")
    columns = [e.alias_or_name for e in tree.expressions]
    assert columns == rp.QUERIES[name][1].split()


@pytest.mark.parametrize("name", sorted(rp.QUERIES))
def test_only_the_run_id_placeholders_and_gold_marts(name):
    text = rp.sql_text(name)
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    assert set(re.findall(r"\{[^}]*\}", text)) <= {"{run_id}", "{run_ids}", "{windows}"}
    tables = re.findall(r"(?:from|join)\s+(\S+)", code)
    assert tables and all(t.startswith("cerberus_platform.fct_") or t == "windows" for t in tables)
    assert any(t.startswith("cerberus_platform.fct_") for t in tables)
    assert not re.search(r"(?<!\d)\d{12}(?!\d)", text)


def test_subrun_query_parses_with_real_windows_and_uses_only_numbers():
    windows = [
        ("synthetic-a", "d-0", 1795862000000, 1795862600000),
        ("synthetic-a", "d-1", 1795862700000, 1795862760000),
    ]
    sql = rp.render_sql("cdn_subrun", "synthetic-exercise", ["synthetic-a"], windows)
    (tree,) = sqlglot.parse(sql, read="trino")
    assert [e.alias_or_name for e in tree.expressions] == rp.QUERIES["cdn_subrun"][1].split()
    assert "('synthetic-a', 'd-1', 1795862700000, 1795862760000)" in sql and "{" not in sql
