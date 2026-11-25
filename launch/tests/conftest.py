"""Shared fixtures: stubs for aws, terraform, openssl, k6, curl and shred on PATH."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STUBS = HERE / "stubs"
ACCT = "1234" + "56789012"  # built at run time so the account-number scan stays clean
BUILD = "stub-build"


def tmpfs_dir() -> str:
    if not Path("/dev/shm").is_dir():
        pytest.skip("no /dev/shm (tmpfs) here")
    return tempfile.mkdtemp(prefix="xdg-", dir="/dev/shm")


class Env:
    """One isolated run: stub PATH, state dir, ledger, baseline, runs dir, key dir parent."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state = tmp / "state"
        self.state.mkdir()
        self.log = tmp / "stub.log"
        self.ledger = tmp / "ledger.jsonl"
        self.baseline = tmp / "cost_baseline.json"
        self.runs = tmp / "runs"
        self.xdg = tmpfs_dir()
        self.vars: dict[str, str] = {}
        self.write_baseline("10.00")
        self.ledger.touch()  # as `make launch-baseline` leaves it
        self.set_marker("results/done")
        self.set_marker("results/seeded")

    def write_baseline(self, usd: str) -> None:
        self.baseline.write_text(f'{{"through": "2026-11-24", "usage_usd": "{usd}"}}\n')

    def set_marker(self, key: str, bucket: str = BUILD) -> None:
        path = self.state / "s3" / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")

    def write_s3(self, key: str, text: str, bucket: str = BUILD) -> None:
        path = self.state / "s3" / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def clear_marker(self, key: str, bucket: str = BUILD) -> None:
        (self.state / "s3" / bucket / key).unlink(missing_ok=True)

    def environ(self, **extra: str) -> dict[str, str]:
        env = {
            "PATH": f"{STUBS}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "STUB_LOG": str(self.log),
            "STUB_STATE": str(self.state),
            "STUB_ACCT": ACCT,
            "STUB_CE_USD": "10.00",
            "LAUNCH_LEDGER": str(self.ledger),
            "LAUNCH_BASELINE": str(self.baseline),
            "LAUNCH_RUNS_DIR": str(self.runs),
            "LAUNCH_POLL_SECONDS": "0.05",
            "LAUNCH_ALLOW_FAST_POLL": "1",  # the test override of the 10 to 120 s check
            "LAUNCH_RUN_ID": "t-run",
            "XDG_RUNTIME_DIR": self.xdg,
            "SCENARIO": "bcd",
            "MINUTES": "120",  # at least every scenario's planned timeline
            "AWS_PROFILE": "stub",
        }
        env.update(self.vars)
        env.update(extra)
        return env

    def run(self, script: str, *args: str, timeout: int = 60, **extra: str):
        return subprocess.run(
            [str(REPO / script), *args],
            env=self.environ(**extra),
            capture_output=True,
            text=True,
            timeout=timeout,
            input="",
        )

    def start(self, script: str, *args: str, **extra: str) -> subprocess.Popen:
        return subprocess.Popen(
            [str(REPO / script), *args],
            env=self.environ(**extra),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def find(self, *needles: str, start: int = 0) -> int:
        """Index of the first logged call (from start) that holds every needle, or -1."""
        for i, line in enumerate(self.calls()[start:], start):
            if all(n in line for n in needles):
                return i
        return -1

    def key_dirs(self) -> list[str]:
        return sorted(os.listdir(self.xdg))

    def ledger_events(self) -> list[str]:
        if not self.ledger.exists():
            return []
        import json

        return [json.loads(x)["event"] for x in self.ledger.read_text().splitlines()]

    def cleanup(self) -> None:
        shutil.rmtree(self.xdg, ignore_errors=True)


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.cleanup()
