"""Build the console dashboards, home dashboard and annotations (step 10).

Stdlib only and Python 3.9 compatible. Runs on the console host as

    python3 -I build.py --dashboards DIR --runs DIR --out DIR

`-I` leaves the script's folder off sys.path, so this file adds it itself,
which is how the sibling modules are found whatever the working directory is.

Writes:
    OUT/dashboards/<uid>.json   the three console dashboards plus cerberus-runs.json
    OUT/annotations.json        a list for POST /api/annotations (see load.py)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import annotations  # noqa: E402
import dashboards  # noqa: E402


def build(dashboards_dir, runs_dir, out_dir):
    records = annotations.load_records(runs_dir)
    if not records:
        raise SystemExit(f"build: no run records in {runs_dir}")
    repo = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path(dashboards_dir).glob("*.json"))
    ]
    newest = records[-1][1]
    console = dashboards.console_dashboards(repo, newest)
    console[dashboards.HOME_UID] = dashboards.home_dashboard([r for _, r in records])

    out = Path(out_dir)
    (out / "dashboards").mkdir(parents=True, exist_ok=True)
    for uid, dash in console.items():
        (out / "dashboards" / f"{uid}.json").write_text(
            json.dumps(dash, indent=2) + "\n", encoding="utf-8"
        )
    items = annotations.all_annotations(records)
    (out / "annotations.json").write_text(json.dumps(items) + "\n", encoding="utf-8")
    return len(console), len(records), len(items)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dashboards", required=True, help="repo dashboards directory")
    parser.add_argument("--runs", required=True, help="run records directory")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    n_dash, n_runs, n_ann = build(args.dashboards, args.runs, args.out)
    print(f"build: {n_dash} dashboards, {n_runs} runs, {n_ann} annotations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
