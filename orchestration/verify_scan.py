"""List added lines and new files that hold a 12-digit run (a possible account ID).

It checks the added lines of `git diff -U0 <base>` and every untracked file. It
prints `file:line` only, never the text, so an account ID can never reach a log.
It exits 1 when it finds something. A line is allowed when it holds a sha256
digest, the fake test account 123456789012, a whole 40-hex blob SHA field, or
a whole provider hash line (`"zh:" + 64 hex`) in a file named
`.terraform.lock.hcl`.

Usage: python3 orchestration/verify_scan.py [base]   (default origin/main)
"""

import re
import subprocess
import sys

RUN = re.compile(r"\d{12}")
SHA_FIELD = re.compile(r'"sha"\s*:\s*"[0-9a-f]{40}"')
LOCK_HASH = re.compile(r'^\s*"zh:[0-9a-f]{64}",?\s*$')
LOCK_FILE = ".terraform.lock.hcl"
MAX_BYTES = 1_000_000


def allowed(line: str, path: str = "") -> bool:
    return (
        "sha256" in line
        or "123456789012" in line
        or bool(SHA_FIELD.search(line))
        or (path.endswith(LOCK_FILE) and bool(LOCK_HASH.match(line)))
    )


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def added_lines(base: str):
    path, number = None, 0
    for raw in git("diff", "-U0", base, "--", ".").splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            number = int(match.group(1)) if match else 0
        elif raw.startswith("+") and path:
            yield path, number, raw[1:]
            number += 1


def untracked_lines():
    for path in git("ls-files", "-o", "--exclude-standard").splitlines():
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_BYTES + 1)
        except OSError:
            continue
        if len(data) > MAX_BYTES or b"\0" in data:
            continue
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            yield path, number, line


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    hits = [
        f"{path}:{number}"
        for path, number, line in [*added_lines(base), *untracked_lines()]
        if RUN.search(line) and not allowed(line, path)
    ]
    for hit in hits:
        print(f"12-digit run at {hit}")
    print(f"scan: {'FOUND ' + str(len(hits)) if hits else 'clean'}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
