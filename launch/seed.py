"""Seed one object set: distinct random chunks, named by their sha256.

Run on the load generator (launch/scenarios/seed.py is copied from here by the
session) and by the tests. For set S in sets.json it makes `chunks` chunks of
`chunk_bytes` random bytes, names each <prefix>/<sha256>.bin (content-addressed,
immutable) and writes <OUT_DIR>/<S>.json, the manifest:
  {"set": S, "chunk_bytes": N, "chunks": [{"key": "<prefix>/<sha256>.bin", "bytes": N}, ...]}
With --bucket each chunk is uploaded and removed, then the manifest goes to the
set's manifest key (build/manifest.json, patch/manifest.json, ...). Without
--bucket the chunks stay under OUT_DIR (tests). k6 on the instance reads the
local manifest file; probe P and the laptop checks read the uploaded one.

Usage: python3 seed.py SETS_JSON SET OUT_DIR [--bucket B]
Standard library only; the only external call is `aws s3 cp`.
"""

from __future__ import annotations  # AL2023 python3 is 3.9

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

BLOCK = 1 << 20


def make_chunk(tmp: Path, nbytes: int) -> str:
    """Write nbytes of random data to tmp and return its sha256 hex."""
    h = hashlib.sha256()
    left = nbytes
    with tmp.open("wb") as f:
        while left > 0:
            block = os.urandom(min(BLOCK, left))
            h.update(block)
            f.write(block)
            left -= len(block)
    return h.hexdigest()


def aws_cp(src: Path, bucket: str, key: str) -> None:
    subprocess.run(
        ["aws", "s3", "cp", str(src), f"s3://{bucket}/{key}", "--only-show-errors"], check=True
    )


def seed(sets_file: Path, set_name: str, out_dir: Path, bucket: str | None) -> dict:
    sets = json.loads(sets_file.read_text())
    spec = sets["sets"][set_name]
    nbytes = sets["chunk_bytes"]
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".chunk-{set_name}.tmp"
    chunks, seen = [], set()
    for _ in range(spec["chunks"]):
        sha = make_chunk(tmp, nbytes)
        if sha in seen:
            raise RuntimeError("two chunks have the same content")
        seen.add(sha)
        key = f"{spec['prefix']}/{sha}.bin"
        if bucket:
            aws_cp(tmp, bucket, key)
            tmp.unlink()
        else:
            dest = out_dir / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(dest)
        chunks.append({"key": key, "bytes": nbytes})
    manifest = {"set": set_name, "chunk_bytes": nbytes, "chunks": chunks}
    path = out_dir / f"{set_name}.json"
    path.write_text(json.dumps(manifest) + "\n")
    if bucket:
        aws_cp(path, bucket, spec["manifest"])
    else:
        dest = out_dir / spec["manifest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(path.read_text())
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sets_json")
    ap.add_argument("set")
    ap.add_argument("out_dir")
    ap.add_argument("--bucket")
    args = ap.parse_args(argv)
    manifest = seed(Path(args.sets_json), args.set, Path(args.out_dir), args.bucket)
    print(f"seeded {args.set}: {len(manifest['chunks'])} chunks of {manifest['chunk_bytes']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
