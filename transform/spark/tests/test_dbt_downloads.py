"""17.5: static checks on the downloads dbt project files (no dbt, no warehouse)."""

import calendar
import re
import time
from pathlib import Path

import generate_bulk_downloads as g

DBT = Path(g.__file__).resolve().parents[1] / "dbt"
MARTS = DBT / "models" / "marts" / "downloads"


def test_release_var_equals_the_generators_release():
    match = re.search(r'release_utc: "([^"]+)"', (DBT / "dbt_project.yml").read_text())
    assert match
    parsed = time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    assert calendar.timegm(parsed) * 1000 == g.RELEASE_UTC_MS


def test_five_downloads_models_all_named_fct():
    names = sorted(p.stem for p in MARTS.glob("*.sql"))
    assert names == [
        "fct_cdn_requests",
        "fct_cdn_run",
        "fct_download_sessions",
        "fct_isp_minute",
        "fct_release_window",
    ]


def test_cdn_model_names_only_allowlisted_columns():
    sql = (MARTS / "fct_cdn_requests.sql").read_text()
    code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "select *" not in code.lower()
    for forbidden in ("c_ip", "x_forwarded_for", "c_port", "cookie", "referer", "user_agent"):
        assert forbidden not in code.lower()


def test_gating_covers_every_downloads_node():
    project = (DBT / "dbt_project.yml").read_text()
    assert "enable_downloads: false" in project
    assert "enable_downloads_cdn: false" in project
    assert project.count("var('enable_downloads', false)") >= 5
