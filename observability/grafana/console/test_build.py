"""build.py end to end under `python3 -I`, and the grafana.ini template."""

import json
import subprocess
import sys

import annotations as ann
import grafana_ini
import pytest
from paths import HERE, REPO_DASHBOARDS, RUNS


def test_build_runs_isolated_from_another_cwd(tmp_path, records):
    out = tmp_path / "out"
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    cmd = [
        sys.executable,
        "-I",
        str(HERE / "build.py"),
        "--dashboards",
        str(REPO_DASHBOARDS),
        "--runs",
        str(RUNS),
        "--out",
        str(out),
    ]
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    names = sorted(p.name for p in (out / "dashboards").glob("*.json"))
    assert names == [
        "cerberus-run-live.json",
        "cerberus-run-story.json",
        "cerberus-runs.json",
        "cerberus-spark-on-eks.json",
    ]
    items = json.loads((out / "annotations.json").read_text(encoding="utf-8"))
    assert len(items) == len(ann.all_annotations(records))


TEMPLATE = (HERE / "grafana.ini.tmpl").read_text(encoding="utf-8")
VALUES = {
    "http_addr": "127.0.0.1",
    "basic_auth_enabled": "true",
    "root_url": "https://example.invalid/",
    "secret_key": "k" * 32,
    "admin_password": "p" * 24,
    "client_id": "cid",
    "client_secret": "csecret",
    "cognito_domain": "auth.example.invalid",
    "signout_redirect_url": "https://auth.example.invalid/logout?client_id=cid",
    "dashboards_dir": "/var/lib/grafana/dashboards",
}


def test_template_placeholders_and_render():
    assert set(grafana_ini.placeholders(TEMPLATE)) == set(VALUES)
    text = grafana_ini.render(TEMPLATE, VALUES)
    assert "$" not in text
    assert text.index("http_addr = 127.0.0.1") < text.index("[auth]")
    for needle in (
        "disable_login_form = true",
        "login_maximum_lifetime_duration = 2h",
        "login_maximum_inactive_lifetime_duration = 30m",
        "role_attribute_path = 'Viewer'",
        "role_attribute_strict = true",
        "use_pkce = true",
        "login_attribute_path = sub",
        "preinstall_disabled = true",
    ):
        assert needle in text


def test_render_rejects_bad_values():
    with pytest.raises(ValueError):
        grafana_ini.render(TEMPLATE, {**VALUES, "secret_key": "a\nb"})
    with pytest.raises(ValueError):
        grafana_ini.render(TEMPLATE, {k: v for k, v in VALUES.items() if k != "root_url"})
    with pytest.raises(ValueError):
        grafana_ini.render(TEMPLATE, {**VALUES, "extra": "x"})
    for bad in (" padded", "a$b", "a`b", "a%(x)s", "a;b"):
        with pytest.raises(ValueError):
            grafana_ini.render(TEMPLATE, {**VALUES, "client_secret": bad})
