"""Shared helpers for the landing-page tests (not a test module)."""

import json
from html.parser import HTMLParser
from pathlib import Path

from cerberus_landing import build
from cerberus_landing.__main__ import REPO
from cerberus_landing.build import EXPECTED_CHARTS

HERE = Path(__file__).resolve().parent
FIXTURE_RUNS = HERE / "fixtures" / "runs"
REAL_RUNS = REPO / "observability" / "scale" / "runs"
PHASES_MD = REPO / "Phases.md"

CHART = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320" viewBox="0 0 640 320" '
    'role="img" aria-label="{t}"><title>{t}</title><style>.a{{fill:#2a78d6}}</style>'
    '<rect class="a" width="10" height="10"/></svg>'
)


def write_charts(directory: Path, names=EXPECTED_CHARTS) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / f"{name}.svg").write_text(CHART.format(t=f"Chart {name}"), encoding="utf-8")
    return directory


def write_record(directory: Path, stem: str, **over) -> Path:
    rec = {
        "execution": stem,
        "status": "SUCCEEDED",
        "start": "2026-11-01T10:00:00+00:00",
        "run_seconds": 125.0,
        "events_processed": 5000,
        "states": [{"state": "RunDbt", "seconds": 12.5}],
        "cost": {"usd_per_million_events": 1.5, "estimated": True, "complete": True},
        "data_quality": {"passed": True},
    }
    rec.update(over)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


def build_site(out: Path, runs_dir=REAL_RUNS, charts_dir=None, phases=PHASES_MD):
    charts_dir = charts_dir if charts_dir is not None else out.parent / "no-charts-here"
    info = build.build(out, runs_dir, phases, charts_dir)
    return info, (out / "index.html").read_text(encoding="utf-8")


def tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


class Tags(HTMLParser):
    """Collects (tag, attrs dict) and the text inside each tag name."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.text: dict[str, str] = {}
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k: v or "" for k, v in attrs}))
        self._stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data):
        for tag in set(self._stack):
            self.text[tag] = self.text.get(tag, "") + data

    def named(self, tag):
        return [a for t, a in self.tags if t == tag]


def parse(markup: str) -> Tags:
    p = Tags()
    p.feed(markup)
    p.close()
    return p
