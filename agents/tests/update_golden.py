"""Rewrite agents/tests/golden/*.json from the committed run records.

    python agents/tests/update_golden.py --update

Only an explicit `--update` writes. A normal test run never imports this file
and never writes a golden file. Review the diff before you commit it.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "console"), str(ROOT / "agents")]

from cerberus_console import config, records  # noqa: E402

from cerberus_agents import review  # noqa: E402

GOLDEN = HERE / "golden"


def golden_reviews(runs_dir=config.RUNS_DIR):
    """{file name: canonical review bytes} for every committed record."""
    recs = records.load(runs_dir).records
    return {f"{r['execution']}.json": review.dumps(review.review(r, recs)) for r in recs}


def main(argv):
    if argv != ["--update"]:
        print("usage: update_golden.py --update  (rewrites agents/tests/golden)")
        return 2
    GOLDEN.mkdir(exist_ok=True)
    for old in GOLDEN.glob("*.json"):
        old.unlink()
    for name, text in golden_reviews().items():
        (GOLDEN / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
