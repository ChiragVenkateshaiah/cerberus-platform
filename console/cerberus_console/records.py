"""Loads the run records in git (observability/scale/runs/*.json).

Tolerant by design: a record may lack keys (older runs) or carry new ones (the
next run). A file that does not parse, is too large or has no execution name is
skipped and counted, never fatal. Plain json.loads only.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from cerberus_console import config


@dataclass
class RecordSet:
    records: list[dict] = field(default_factory=list)  # newest first
    skipped: int = 0

    def get(self, execution: str) -> dict | None:
        for rec in self.records:
            if rec["execution"] == execution:
                return rec
        return None


def load(runs_dir: Path = config.RUNS_DIR) -> RecordSet:
    out = RecordSet()
    try:
        files = sorted(Path(runs_dir).glob("*.json"))
    except OSError:
        return out
    seen = set()
    for path in files[: config.MAX_RECORD_FILES]:
        try:
            if path.stat().st_size > config.MAX_RECORD_BYTES:
                raise ValueError("too large")
            rec = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rec, dict) or not isinstance(rec.get("execution"), str):
                raise ValueError("not a run record")
        except (OSError, ValueError, RecursionError):
            out.skipped += 1
            continue
        if rec["execution"] in seen:
            out.skipped += 1
            continue
        seen.add(rec["execution"])
        out.records.append(rec)
    out.records.sort(key=lambda r: (str(r.get("start") or ""), r["execution"]), reverse=True)
    return out


def dig(obj, *path, default=None):
    """obj[path[0]][path[1]]... or default when any step is missing or not a dict."""
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return default
        obj = obj[key]
    return obj


def number(obj, *path):
    """A finite number at the path, or None. Booleans are not numbers here."""
    v = dig(obj, *path)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return v


def text(obj, *path):
    v = dig(obj, *path)
    return v if isinstance(v, str) else None


def state(rec: dict, name: str) -> dict | None:
    states = rec.get("states")
    if not isinstance(states, list):
        return None
    for st in states:
        if isinstance(st, dict) and st.get("state") == name:
            return st
    return None
