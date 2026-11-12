"""CLI.

python -m cerberus_terminal build --out DIR
python -m cerberus_terminal stale --dir DIR   (a JSON list of remote keys on stdin)
"""

import argparse
import json
import sys
from pathlib import Path

from cerberus_terminal import build, publish


def stale(directory: Path) -> int:
    """Read remote keys (a JSON list, or null for an empty bucket); print the stale ones."""
    try:
        remote = json.load(sys.stdin)
        if remote is None:
            remote = []
        if not isinstance(remote, list) or not all(isinstance(k, str) for k in remote):
            raise ValueError("expected a JSON list of strings")
        local = publish.local_keys(directory)
        if "terminal/index.html" not in local:
            raise ValueError(
                f"{directory} has no terminal/index.html; refusing to compute stale keys"
            )
    except (ValueError, OSError) as exc:
        print(f"stale failed: {exc}", file=sys.stderr)
        return 1
    for key in publish.stale_keys(local, remote):
        print(key)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_terminal")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the terminal page")
    b.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("stale", help="print the remote keys a publish should delete")
    s.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "stale":
        return stale(args.dir)
    try:
        info = build.build(args.out)
    except (build.BuildError, OSError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    print(f"built {len(info.files)} files, {info.total_bytes} bytes, build id {info.build_id[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
