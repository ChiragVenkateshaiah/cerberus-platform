"""Check records, the pure comparisons, and the report writer. No network, no browser."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from cerberus_console import grammar
from cerberus_live_check import shared
from cerberus_live_check.redact import redact
from cerberus_terminal.build import max_input_length

STATUSES = ("pass", "fail", "record", "skip")

# The hostile ARGV cases the live terminal check types (plan 2026-11-15 section 2).
HOSTILE_NAMES = (
    "fullwidth",
    "zero width",
    "command substitution",
    "backtick",
    "html img",
    "run with a path",
    "rtl override",
    "SQL",
)


@dataclass
class Check:
    id: str
    status: str
    expected: str = ""
    observed: str = ""
    note: str = ""

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"bad status {self.status!r}")


@dataclass(frozen=True)
class Typed:
    name: str
    line: str
    # What the input box must hold after the paste: the line, or the line cut at maxlength.
    expected_value: str


def compare_headers(observed: dict[str, str], expected: dict[str, str]) -> Check:
    """Names are case-insensitive, values must match exactly, extra headers are ignored."""
    seen = {k.lower(): v for k, v in observed.items()}
    diffs = []
    for name, want in expected.items():
        got = seen.get(name.lower())
        if got is None:
            diffs.append(f"{name}: missing")
        elif got != want:
            diffs.append(f"{name}: expected {want!r}, got {got!r}")
    if diffs:
        return Check("D1a", "fail", f"{len(expected)} headers match", "; ".join(diffs))
    return Check("D1a", "pass", f"{len(expected)} headers match", f"all {len(expected)} match")


def parse_live(json_text: str, now: datetime) -> tuple[bool, dict, str]:
    """Ready only when schema is 1, url is https and ends is in the future (stale = not ready)."""
    try:
        data = json.loads(json_text)
    except ValueError:
        return False, {}, "live.json does not parse"
    if not isinstance(data, dict) or data.get("schema") != 1:
        return False, {}, "schema is not 1"
    url = data.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return False, {}, "url is not https"
    try:
        ends = datetime.fromisoformat(str(data["ends"]))
    except (KeyError, ValueError):
        return False, {}, "ends is missing or does not parse"
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=UTC)
    if ends <= now:
        return False, {}, "ends is in the past (stale file)"
    return True, {"url": url, "home": data.get("home", ""), "ends": ends}, "ready"


def typed_lines() -> list[Typed]:
    """Every line the browser types: the shell case, the hostile cases and the two long lines."""
    hostile = shared.hostile()
    shell = json.loads(hostile.BODIES["shell"])["argv"][0]
    out = [Typed("shell", shell, shell)]
    for name in HOSTILE_NAMES:
        line = " ".join(hostile.ARGV[name])
        out.append(Typed(name, line, line))
    longest = max_input_length()
    out.append(Typed(f"{longest} characters", "a" * longest, "a" * longest))
    cut = Typed(f"{longest + 1} characters (cut by maxlength)", "a" * (longest + 1), "a" * longest)
    return [*out, cut]


def commands() -> list[str]:
    """One valid line for each command in the grammar: no arguments, and `run latest`."""
    return [f"{name} latest" if name == "run" else name for name in grammar.COMMANDS]


def tokenise(line: str) -> list[str]:
    """terminal.js: line.trim().split(/\\s+/)."""
    return re.split(r"\s+", line.strip())


def long_line_lengths() -> tuple[int, int]:
    return max_input_length(), max_input_length() + 1


def _markdown(checks: list[Check], meta: dict) -> str:
    lines = ["# Live check report", ""]
    for key, value in meta.items():
        lines.append(f"- {key}: {value}")
    lines += ["", "| id | status | expected | observed | note |", "|---|---|---|---|---|"]
    for c in checks:
        cells = [c.id, c.status, c.expected, c.observed, c.note]
        lines.append(
            "| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in cells) + " |"
        )
    counts = {s: sum(1 for c in checks if c.status == s) for s in STATUSES}
    lines += ["", "Counts: " + ", ".join(f"{k} {v}" for k, v in counts.items()), ""]
    return "\n".join(lines)


def write(
    directory: Path,
    checks: list[Check],
    secret: str,
    hosts: dict[str, str] | None = None,
    meta: dict | None = None,
) -> int:
    """Write report.json and report.md, redacted. Exit code: 0 ok, 1 a check failed, 2 secret found.

    The secret is checked in the text before redaction too, so a leak is never hidden by it.
    Nothing is written when the secret is present.
    """
    meta = meta or {}
    as_json = json.dumps({"meta": meta, "checks": [asdict(c) for c in checks]}, indent=2)
    as_md = _markdown(checks, meta)
    if secret and any(secret in redact(t, hosts) or secret in t for t in (as_json, as_md)):
        return 2
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(redact(as_json, hosts), encoding="utf-8")
    (directory / "report.md").write_text(redact(as_md, hosts), encoding="utf-8")
    return 1 if any(c.status == "fail" for c in checks) else 0


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
