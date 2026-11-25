"""Check and filter CloudFront log files before they are copied to bronze.

Used by orchestration/launch_collect.sh. It reads every file in --in-dir (named
<16 hex of sha256(source key)>), and writes --out-dir/part-<name>.json plus
_manifest.json. Nothing is written unless every file passes (ADR 0030 Decision 10):

- every line is a JSON object whose keys are a subset of launch/cdn_fields.json;
- lines outside the session window are dropped (timestamp(ms) within start and end;
  an unusable timestamp refuses). They are dropped before the 12-digit scan, so
  traffic from before or after the session cannot block a collection;
- cs-uri-stem is replaced by "/other" unless it fully matches one of the known
  paths: /build|patch/<64 hex>.bin, /build|patch/manifest[-2].json or /license.
  A sha256 can hold a 12-digit run, so the stem is not scanned after that;
- no other value, except x-edge-request-id and timestamp(ms), of a kept line holds a
  12-digit run that is not part of a longer digit run (a possible account ID).
  The bound matters: a 13-digit timestamp must not match.

Output is uncompressed UTF-8 JSON Lines with the original key names. A gzip
input is accepted. The message of a refusal never holds a value.

Usage: cdn_filter.py --run-id ID --start-ms N --end-ms N --in-dir D --out-dir D
Exit 0 ok, 2 refused or error.
"""

import argparse
import gzip
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ALLOWLIST = Path(__file__).resolve().parent / "cdn_fields.json"
RUN_ID = re.compile(r"^[a-z0-9-]{1,40}$")
TWELVE = re.compile(r"(?<!\d)\d{12}(?!\d)")
EXEMPT = ("x-edge-request-id", "timestamp(ms)", "cs-uri-stem")
STEM = re.compile(r"/(build|patch)/[0-9a-f]{64}\.bin|/(build|patch)/manifest(-2)?\.json|/license")
OTHER = "/other"
PART = re.compile(r"^[0-9a-f]{16}$")


class Refused(Exception):
    pass


def allowlist() -> list[str]:
    return list(json.loads(ALLOWLIST.read_text())["fields"])


def read_text(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def filter_text(text: str, fields: list[str], start_ms: int, end_ms: int, label: str) -> list[str]:
    """Return the kept lines of one file. Raise Refused on the first bad line."""
    kept = []
    allowed = set(fields)
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        where = f"{label} line {number}"
        try:
            item = json.loads(line)
        except ValueError as err:
            raise Refused(f"{where} is not JSON") from err
        if not isinstance(item, dict):
            raise Refused(f"{where} is not an object")
        extra = sorted(set(item) - allowed)
        if extra:
            raise Refused(f"{where} has {len(extra)} field(s) outside the allowlist")
        try:
            stamp = int(item["timestamp(ms)"])
        except (KeyError, ValueError, TypeError) as err:
            raise Refused(f"{where} has no usable timestamp(ms)") from err
        if not start_ms <= stamp <= end_ms:
            continue
        if "cs-uri-stem" in item and not (
            isinstance(item["cs-uri-stem"], str) and STEM.fullmatch(item["cs-uri-stem"])
        ):
            item["cs-uri-stem"] = OTHER
        for key, value in item.items():
            if key not in EXEMPT and TWELVE.search(str(value)):
                raise Refused(f"{where} has a 12-digit value in {key}")
        kept.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    return kept


def run(run_id: str, start_ms: int, end_ms: int, in_dir: Path, out_dir: Path) -> dict:
    if not RUN_ID.match(run_id):
        raise Refused("run id must match ^[a-z0-9-]{1,40}$")
    if end_ms < start_ms:
        raise Refused("window end is before window start")
    fields = allowlist()
    parts: dict[str, str] = {}
    lines = 0
    for path in sorted(p for p in in_dir.iterdir() if p.is_file()):
        if not PART.match(path.name):
            raise Refused("an input file name is not 16 hex characters")
        kept = filter_text(read_text(path.read_bytes()), fields, start_ms, end_ms, path.name)
        lines += len(kept)
        parts[f"part-{path.name}.json"] = "".join(line + "\n" for line in kept)
    manifest = {
        "run_id": run_id,
        "files": len(parts),
        "lines": lines,
        "fields": fields,
        "window_start": start_ms,
        "window_end": end_ms,
        "collected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, body in parts.items():
        (out_dir / name).write_text(body, encoding="utf-8")
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--start-ms", type=int, required=True)
    ap.add_argument("--end-ms", type=int, required=True)
    ap.add_argument("--in-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    try:
        m = run(args.run_id, args.start_ms, args.end_ms, Path(args.in_dir), Path(args.out_dir))
    except (Refused, UnicodeDecodeError, OSError, EOFError) as err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return 2
    print(f"files={m['files']} lines={m['lines']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
