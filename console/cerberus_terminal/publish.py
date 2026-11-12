"""Which bucket keys are stale after a terminal publish (ADR 0024 amendment, 2026-11-12).

Stdlib only, and it runs no program: publish_terminal.sh does the AWS calls and
asks this module which remote keys the builder used to own and no longer makes.
The allowlist is the safety rule. A key that does not match TERMINAL_MANAGED
(index.html, healthz.txt, live.json, terminal/index.html, terminal/config.json
and every landing key) is never stale.
"""

import re
from pathlib import Path

# The hashed files the builder writes, and nothing else.
TERMINAL_MANAGED = re.compile(r"^terminal/terminal\.[0-9a-f]{10}\.(js|css)$")


def local_keys(directory: Path) -> set[str]:
    """Posix paths, relative to directory, of every file in the built site."""
    return {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}


def stale_keys(local: set[str], remote: list[str]) -> list[str]:
    """Remote keys the builder owns that the new build no longer has, sorted."""
    return sorted({k for k in remote if TERMINAL_MANAGED.fullmatch(k) and k not in local})
