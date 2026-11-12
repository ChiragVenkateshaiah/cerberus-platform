"""Repo paths shared by the tests."""

from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_DASHBOARDS = HERE.parent / "dashboards"
RUNS = HERE.parents[1] / "scale" / "runs"
