"""CLI: python -m cerberus_landing build --out DIR [--runs-dir D] [--phases F] [--charts-dir D]"""

import argparse
import sys
from pathlib import Path

from cerberus_landing import build

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_landing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the static site")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--runs-dir", type=Path, default=REPO / "observability" / "scale" / "runs")
    b.add_argument("--phases", type=Path, default=REPO / "Phases.md")
    b.add_argument("--charts-dir", type=Path, default=REPO / "docs" / "img" / "scale")
    args = parser.parse_args(argv)
    try:
        info = build.build(args.out, args.runs_dir, args.phases, args.charts_dir)
    except (build.BuildError, OSError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    print(f"built {len(info.files)} files, {info.total_bytes} bytes, build id {info.build_id[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
