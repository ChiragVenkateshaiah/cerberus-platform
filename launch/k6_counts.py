"""Sum the request counts of the k6 summaries of one run (for run.json).

k6 writes each summary with --summary-export (counters as {"count": N}). The
session passes the expected summary names (<scenario>-<index>, from
launch/scenario.py) and the probe P file. The counts are what
cdn_logs_complete compares with the CDN log lines (ADR 0030 Decision 13).

Usage: python3 launch/k6_counts.py --dir RESULTS_DIR --names b-0,c-0 [--probe FILE]
Prints one JSON object:
  {"k6_requests": N, "by_type": {"build": n, "patch": n, "licence": n, "manifest": n},
   "complete": true|false, "missing": [...]}
k6_requests is the sum of http_reqs (an integer). "complete" is false when an
expected summary is missing or unreadable; the sum then holds only what was read.
"""

import argparse
import json
import sys
from pathlib import Path

TYPES = ("build", "patch", "licence", "manifest")


def count(metrics: dict, name: str) -> int:
    value = metrics.get(name, {}).get("count", 0)
    if not isinstance(value, (int, float)) or value < 0 or int(value) != value:
        raise ValueError(f"{name} count is not a whole number")
    return int(value)


def collect(directory: Path, names: list[str], probe: Path | None) -> dict:
    files = [(n, directory / f"{n}.json") for n in names]
    if probe is not None:
        files.append(("probe-p", probe))
    total = 0
    by_type = dict.fromkeys(TYPES, 0)
    missing = []
    for name, path in files:
        try:
            metrics = json.loads(path.read_text())["metrics"]
            n = count(metrics, "http_reqs")
            types = {t: count(metrics, f"req_{t}") for t in TYPES}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            missing.append(name)
            continue
        total += n
        for t in TYPES:
            by_type[t] += types[t]
    return {"k6_requests": total, "by_type": by_type, "complete": not missing, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--names", default="")
    ap.add_argument("--probe")
    args = ap.parse_args(argv)
    names = [n for n in args.names.split(",") if n]
    print(json.dumps(collect(Path(args.dir), names, Path(args.probe) if args.probe else None)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
