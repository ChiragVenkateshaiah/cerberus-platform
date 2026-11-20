"""Pipeline status publisher (plan 10.2, PR B and PR C).

  publish.py start --execution N [--started ISO] [--at ISO] [--url URL]
  publish.py end --execution N [--record PATH] [--at ISO] [--url URL]

It prints the series in Prometheus text format, with the publish timestamp in
ms. Without --url it is a dry run. With --url it also POSTs the remote-write
body, unsigned, to a local receiver. Only an http URL on 127.0.0.1, ::1 or
localhost is accepted; any other URL exits 2. Sending to AMP comes in PR D.
This is the only module that may import urllib.
"""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import remote_write
import series

RUNS = Path(__file__).resolve().parents[1] / "scale" / "runs"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
TIMEOUT = 5  # seconds


def fmt_value(value):
    if math.isnan(value):
        return "NaN"
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def text_lines(rows, ts_ms):
    """Sorted Prometheus text exposition lines, one sample each."""
    lines = []
    for name, labels, value in sorted(rows, key=lambda s: (s[0], sorted(s[1].items()))):
        inner = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()))
        head = f"{name}{{{inner}}}" if inner else name
        lines.append(f"{head} {fmt_value(value)} {ts_ms}")
    return lines


def publish_ms(at):
    return round(series.epoch(at) * 1000) if at else int(time.time() * 1000)


def check_url(url):
    """Error text if `url` is not an http URL on a loopback host, else None."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018  (raises ValueError on a bad port)
    except ValueError as err:
        return f"bad --url: {err}"
    if parts.scheme != "http" or host not in LOOPBACK:
        return "--url must be http on 127.0.0.1, ::1 or localhost (unsigned, local only)"
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect becomes an HTTPError, so the body stays on loopback


# No proxy (an env proxy must not carry the body off the host), no redirect.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def send(url, body):
    """POST `body` unsigned. Returns (HTTP status, first 200 chars of the reply)."""
    req = urllib.request.Request(url, data=body, headers=remote_write.HEADERS, method="POST")
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read(200).decode("utf-8", "replace")


def build_parser():
    p = argparse.ArgumentParser(description="Cerberus pipeline status publisher (dry run).")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start", help="series written right after start-execution")
    s.add_argument("--execution", required=True)
    s.add_argument("--started", help="run start, ISO 8601 (default: the publish time)")
    s.add_argument("--at", help="publish time, ISO 8601 (default: now)")
    s.add_argument("--url", help="send unsigned to a local receiver (loopback http only)")
    e = sub.add_parser("end", help="series written when the run has ended")
    e.add_argument("--execution", required=True)
    e.add_argument("--record", help="run record JSON (default: observability/scale/runs/N.json)")
    e.add_argument("--at", help="publish time, ISO 8601 (default: now)")
    e.add_argument("--url", help="send unsigned to a local receiver (loopback http only)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.url and (problem := check_url(args.url)):
        print(f"publish: {problem}", file=sys.stderr)
        return 2
    ts_ms = publish_ms(args.at)
    if args.command == "start":
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000))
        rows = series.start_series(args.execution, args.started or now)
    else:
        path = Path(args.record) if args.record else RUNS / f"{args.execution}.json"
        try:
            record = json.loads(path.read_text())
        except OSError as err:
            print(f"publish: cannot read the run record: {err}", file=sys.stderr)
            return 2
        if record.get("execution") != args.execution:
            print(
                f"publish: record is for {record.get('execution')!r}, not {args.execution!r}",
                file=sys.stderr,
            )
            return 2
        rows = series.end_series(record)
    print("\n".join(text_lines(rows, ts_ms)))
    body = remote_write.snappy_block(remote_write.encode(rows, ts_ms))
    if not args.url:
        print(
            f"# dry run: {len(rows)} series, request body {len(body)} bytes, not sent",
            file=sys.stderr,
        )
        return 0
    try:
        status, reply = send(args.url, body)
    except (OSError, ValueError) as err:  # URLError and timeouts are OSError
        print(f"publish: send failed: {err}", file=sys.stderr)
        return 1
    print(f"# sent: {len(rows)} series, {len(body)} bytes, HTTP {status}", file=sys.stderr)
    if not 200 <= status < 300:
        print(f"publish: receiver replied HTTP {status}: {reply}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
