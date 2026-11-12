"""Checks the pinned console-session artifacts against compose.yaml (step 10).

Stdlib only. No AWS and no network.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
COMPOSE = (HERE.parent / "compose.yaml").read_text()
DOC = json.loads((HERE / "artifacts.json").read_text())
BY_NAME = {a["name"]: a for a in DOC["artifacts"]}
SCRIPT = (HERE / "stage_artifacts.sh").read_text()


def test_schema():
    assert DOC["schema"] == 1
    assert set(BY_NAME) == {"grafana", "grafana-amazonprometheus-datasource"}
    for a in DOC["artifacts"]:
        assert set(a) == {"name", "version", "arch", "url", "sha256", "size", "key"}
        assert isinstance(a["size"], int) and a["size"] > 0
        assert a["arch"] == "arm64"


def test_sha256_is_64_lowercase_hex():
    for a in DOC["artifacts"]:
        assert re.fullmatch(r"[0-9a-f]{64}", a["sha256"])


def test_urls_and_keys():
    for a in DOC["artifacts"]:
        u = urlparse(a["url"])
        assert u.scheme == "https"
        assert u.hostname in {"dl.grafana.com", "grafana.com"}
        assert a["key"].startswith("artifacts/grafana/")


def test_grafana_version_matches_compose():
    images = set(re.findall(r"image:\s*grafana/grafana:(\S+)", COMPOSE))
    assert images == {BY_NAME["grafana"]["version"]}


def test_plugin_version_matches_compose():
    pins = re.findall(r"grafana-amazonprometheus-datasource@(\S+)", COMPOSE)
    assert pins == [BY_NAME["grafana-amazonprometheus-datasource"]["version"]]


def test_script_has_no_bulk_or_bucket_echo():
    for bad in ("s3 sync", "s3 rm", "--recursive", 'echo "$BUCKET"', "echo $BUCKET"):
        assert bad not in SCRIPT
