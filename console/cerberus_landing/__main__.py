"""CLI.

python -m cerberus_landing build --out DIR [--runs-dir D] [--phases F] [--charts-dir D]
python -m cerberus_landing stale --dir DIR   (a JSON list of remote keys on stdin)
"""

import argparse
import json
import sys
from pathlib import Path

from cerberus_landing import build, publish

REPO = Path(__file__).resolve().parents[2]


def stale(directory: Path) -> int:
    """Read remote keys (a JSON list, or null for an empty bucket); print the stale ones."""
    try:
        remote = json.load(sys.stdin)
        if remote is None:
            remote = []
        if not isinstance(remote, list) or not all(isinstance(k, str) for k in remote):
            raise ValueError("expected a JSON list of strings")
        local = publish.local_keys(directory)
        if "index.html" not in local:
            raise ValueError(f"{directory} has no index.html; refusing to compute stale keys")
    except (ValueError, OSError) as exc:
        print(f"stale failed: {exc}", file=sys.stderr)
        return 1
    for key in publish.stale_keys(local, remote):
        print(key)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_landing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the static site")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--runs-dir", type=Path, default=REPO / "observability" / "scale" / "runs")
    b.add_argument("--phases", type=Path, default=REPO / "Phases.md")
    b.add_argument("--charts-dir", type=Path, default=REPO / "docs" / "img" / "scale")
    s = sub.add_parser("stale", help="print the remote keys a publish should delete")
    s.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "stale":
        return stale(args.dir)
    try:
        info = build.build(args.out, args.runs_dir, args.phases, args.charts_dir)
    except (build.BuildError, OSError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    print(f"built {len(info.files)} files, {info.total_bytes} bytes, build id {info.build_id[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
