"""Which bucket keys are stale after a publish (ADR 0024; plan 2026-11-09).

Stdlib only, and it runs no program: publish_site.sh does the AWS calls and
asks this module which remote keys the builder used to own and no longer
makes. The allowlist is the safety rule. A key that does not match MANAGED
(index.html, healthz.txt, live.json, anything under terminal/) is never stale.
"""

import re
from pathlib import Path

# The hashed files the builder writes, and nothing else.
MANAGED = re.compile(
    r"site\.[0-9a-f]{10}\.css"
    r"|favicon\.[0-9a-f]{10}\.svg"
    r"|img/[a-z0-9-]+\.[0-9a-f]{10}\.svg"
)


def local_keys(directory: Path) -> set[str]:
    """Posix paths, relative to directory, of every file in the built site."""
    return {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}


def stale_keys(local: set[str], remote: list[str]) -> list[str]:
    """Remote keys the builder owns that the new build no longer has, sorted."""
    return sorted({k for k in remote if MANAGED.fullmatch(k) and k not in local})
