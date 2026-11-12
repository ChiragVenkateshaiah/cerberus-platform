"""Shared fixtures: the real run records and dashboards from the repo."""

import json

import pytest
from paths import REPO_DASHBOARDS, RUNS


@pytest.fixture(scope="session")
def records():
    out = [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(RUNS.glob("*.json"))]
    assert len(out) >= 17
    return out


@pytest.fixture(scope="session")
def repo_dashboards():
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(REPO_DASHBOARDS.glob("*.json"))
    ]
