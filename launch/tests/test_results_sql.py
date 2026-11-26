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
    assert set(re.findall(r"\{[^}]*\}", text)) <= {"{run_id}", "{run_ids}"}
    tables = re.findall(r"from\s+(\S+)", code)
    assert tables and all(t.startswith("cerberus_platform.fct_") for t in tables)
    assert not re.search(r"(?<!\d)\d{12}(?!\d)", text)
