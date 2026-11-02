"""The gold tables the IAM role may read must equal the tables the freshness
query names (config.GOLD_TABLES). The Terraform variable lands with PR 6a; until
it is on this branch the test skips."""

import re
from pathlib import Path

import pytest

from cerberus_console import config

VARIABLES = Path(__file__).resolve().parents[2] / "terraform/modules/console_roles/variables.tf"


def test_gold_table_names_match_config():
    text = VARIABLES.read_text() if VARIABLES.exists() else ""
    block = re.search(r'variable\s+"gold_table_names"\s*\{(.*?)\n\}', text, re.S)
    if block is None:
        pytest.skip(
            "gold_table_names is not in console_roles/variables.tf yet (it lands with PR 6a)"
        )
    default = re.search(r"default\s*=\s*\[(.*?)\]", block.group(1), re.S)
    assert default, "gold_table_names has no default"
    tables = re.findall(r'"([^"]+)"', default.group(1))
    assert tuple(tables) == config.GOLD_TABLES


def test_freshness_sql_names_exactly_the_gold_tables():
    for table in config.GOLD_TABLES:
        assert f'"{config.DATABASE}"."{table}$snapshots"' in config.FRESHNESS_SQL
    assert config.FRESHNESS_SQL.count("$snapshots") == len(config.GOLD_TABLES)
