"""Two screenshots of the pipeline-status dashboard, local only (plan 10.3b).

Not part of CI and not a test. `make status-render-shots` starts the throwaway
stack (run.sh with RENDER_CMD), then this script publishes the fixture runs in
two steps and takes a picture after each:

  1. the newest run failed  -> status-failed.png
  2. a later run passed     -> status-passed.png

It covers what /api/ds/query cannot: the transformations (x1000 dates, step
names and order, the runs-table join) and the value mappings, which run in the
browser. Look at the pictures by eye. Output goes to a git-ignored folder.

Needs CERBERUS_GRAFANA_URL and CERBERUS_PROM_URL (run.sh sets them) and
Playwright 1.65.1 (uv --with) with the cached chromium headless shell. The
samples are written at now-50 min, now-35 min and now-20 min, so a 2-hour view
shows the bands. The PNGs may show run times in October: they come from the
committed run records.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "observability" / "status"))
import publish  # noqa: E402

GRAFANA = os.environ["CERBERUS_GRAFANA_URL"].rstrip("/")
PROM = os.environ["CERBERUS_PROM_URL"].rstrip("/")
OUT = Path(os.environ.get("RENDER_SHOTS", ROOT / "observability/grafana/render_check/screenshots"))
RUNS = ROOT / "observability" / "scale" / "runs"
EARLY_PASS, FAILED, LATE_PASS = (
    "exercise-20261012T075045Z",
    "exercise-20261008T085728Z",
    "exercise-20261015T145812Z",
)
URL = f"{GRAFANA}/d/cerberus-pipeline-status?from=now-2h&to=now&kiosk"


def push(execution, minutes_ago):
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - minutes_ago * 60))
    record = RUNS / f"{execution}.json"
    argv = ["end", "--execution", execution, "--record", str(record), "--at", at]
    assert publish.main([*argv, "--url", f"{PROM}/api/v1/write"]) == 0


def shoot(browser, name):
    page = browser.new_context(viewport={"width": 1440, "height": 2400}).new_page()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(6000)
    path = OUT / name
    page.screenshot(path=str(path), full_page=True)
    print(f"wrote {path}", file=sys.stderr)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache = Path.home() / ".cache" / "ms-playwright"
    found = sorted(
        cache.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")
    )
    with sync_playwright() as pw:
        browser = (
            pw.chromium.launch(executable_path=str(found[-1])) if found else pw.chromium.launch()
        )
        try:
            push(EARLY_PASS, 50)
            push(FAILED, 35)
            shoot(browser, "status-failed.png")
            push(LATE_PASS, 20)
            shoot(browser, "status-passed.png")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
