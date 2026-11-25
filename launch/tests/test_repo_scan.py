"""No private key text and no account ID in anything the launch tooling owns."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MARKER = " ".join(["PRIVATE", "KEY"])
TWELVE = re.compile(r"(?<!\d)\d{12}(?!\d)")
SKIP_DIRS = {".terraform", "__pycache__", ".pytest_cache"}


def owned_files():
    roots = [
        REPO / "launch",
        REPO / "terraform/envs/dev-launch",
        REPO / "terraform/modules/launch_edge",
    ]
    for root in roots:
        for path in root.rglob("*"):
            if (
                path.is_file()
                and not (SKIP_DIRS & set(path.parts))
                and path.name != ".terraform.lock.hcl"
            ):
                yield path
    yield from (REPO / "orchestration").glob("launch_*.sh")


def test_no_private_key_and_no_account_id():
    files = list(owned_files())
    assert len(files) > 20
    for path in files:
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        assert MARKER not in text, f"{path} holds private key text"
        assert not TWELVE.search(text), f"{path} holds a 12-digit run"


def test_scripts_never_enable_trace_output():
    for path in (REPO / "orchestration").glob("launch_*.sh"):
        for line in path.read_text().splitlines():
            assert not line.lstrip().startswith(("set -x", "set -o xtrace")), path
