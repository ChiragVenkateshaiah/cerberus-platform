"""Wait for live.json to be ready (or, with --gone, to go away). Read-only, no password."""

import sys
import time
from datetime import UTC, datetime

from cerberus_live_check import http
from cerberus_live_check.report import parse_live

POLL_S = 15
BELL = "\a"


def read_live(standing: str, now: datetime | None = None) -> tuple[int, bool, dict, str]:
    """(http status, ready, info, reason). A network error is status 0."""
    url = f"{standing.rstrip('/')}/live.json?t={int(time.time())}"
    try:
        status, _headers, body = http.fetch(url, headers={"Cache-Control": "no-cache"})
    except OSError as err:
        return 0, False, {}, f"network error ({type(err).__name__})"
    if status != 200:
        return status, False, {}, f"live.json {status}"
    ready, info, reason = parse_live(body.decode("utf-8", "replace"), now or datetime.now(UTC))
    return status, ready, info, reason


def minutes_left(ends: datetime, now: datetime | None = None) -> int:
    return max(0, int((ends - (now or datetime.now(UTC))).total_seconds() // 60))


def wait_ready(standing: str, timeout_min: int, show_url: bool = False, poll_s: int = POLL_S):
    """Poll until ready. Returns the info dict, or None on timeout."""
    deadline = time.monotonic() + timeout_min * 60
    while True:
        status, ready, info, reason = read_live(standing)
        if ready:
            left = minutes_left(info["ends"])
            url = info["url"] if show_url else "URL hidden"
            print(
                f"READY live.json {status}; ends {info['ends']:%H:%M}Z ({left} min left); "
                f"{url}{BELL}",
                flush=True,
            )
            return info
        print(f"not ready: {reason}", flush=True)
        if time.monotonic() + poll_s > deadline:
            return None
        time.sleep(poll_s)


def run(standing: str, gone: bool, timeout_min: int, show_url: bool) -> int:
    if not gone:
        return 0 if wait_ready(standing, timeout_min, show_url) is not None else 3
    deadline = time.monotonic() + timeout_min * 60
    while True:
        status, _ready, _info, reason = read_live(standing)
        if status not in (0, 200):  # 0 is a network error: keep waiting
            print(f"GONE {reason}{BELL}", flush=True)
            return 0
        print(reason if status == 0 else "live.json still present", flush=True)
        if time.monotonic() + POLL_S > deadline:
            print("timeout", file=sys.stderr)
            return 3
        time.sleep(POLL_S)
