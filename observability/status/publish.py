"""Pipeline status publisher (plan 10.2, PR B, C and D).

  publish.py start --execution N [--started ISO] [--at ISO] [--url URL | --send]
  publish.py end --execution N [--record PATH] [--at ISO] [--url URL | --send [--force]]
  publish.py smoke [--at ISO] [--url URL | --send]

It prints the series in Prometheus text format, with the publish timestamp in
ms. Without --url or --send it is a dry run and makes no AWS call. With --url
it also POSTs the remote-write body, unsigned, to a local receiver. Only an
http URL on 127.0.0.1, ::1 or localhost is accepted; any other URL exits 2.
--send writes to AMP through aws_send.py (SigV4); it excludes --url. The
AWS code lives in aws_send.py; this module and aws_send.py may import urllib.
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

import aws_send
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

    def common(sp):
        sp.add_argument("--at", help="publish time, ISO 8601 (default: now)")
        sp.add_argument("--url", help="send unsigned to a local receiver (loopback http only)")
        sp.add_argument("--send", action="store_true", help="AWS WRITE: send to AMP, signed")

    s = sub.add_parser("start", help="series written right after start-execution")
    s.add_argument("--execution", required=True)
    s.add_argument("--started", help="run start, ISO 8601 (default: the publish time)")
    common(s)
    e = sub.add_parser("end", help="series written when the run has ended")
    e.add_argument("--execution", required=True)
    e.add_argument("--record", help="run record JSON (default: observability/scale/runs/N.json)")
    e.add_argument("--force", action="store_true", help="skip the newest-run guard (with --send)")
    common(e)
    m = sub.add_parser(
        "smoke", help="one cerberus_publisher_smoke sample (value = publish time), read back"
    )
    m.add_argument("--at", help="publish time, ISO 8601 (default: now)")
    m.add_argument("--url", help="send unsigned to a local receiver (loopback http only)")
    m.add_argument("--send", action="store_true", help="AWS WRITE: send to AMP, then read back")
    return p


def load_record(args, session_for):
    """The run record for `end`: the file, else (with --send) Step Functions."""
    path = Path(args.record) if args.record else RUNS / f"{args.execution}.json"
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as err:
        if not args.send or args.record:
            print(f"publish: cannot read the run record: {err}", file=sys.stderr)
            return None
        print(f"publish: no run record, reading Step Functions: {args.execution}", file=sys.stderr)
        return aws_send.record_from_history(session_for(), args.execution)
    except OSError as err:
        print(f"publish: cannot read the run record: {err}", file=sys.stderr)
        return None


def main(argv=None):
    args = build_parser().parse_args(argv)
    url = getattr(args, "url", None)
    if url and args.send:
        print("publish: --send and --url cannot be used together", file=sys.stderr)
        return 2
    if url and (problem := check_url(url)):
        print(f"publish: {problem}", file=sys.stderr)
        return 2
    try:
        return run(args, url)
    except aws_send.AwsError as err:
        print(f"publish: {err}", file=sys.stderr)
        return 1


def run(args, url):
    ts_ms = publish_ms(args.at)
    session = []  # one session per run, made on first use (never in a dry run)

    def session_for():
        if not session:
            session.append(aws_send.make_session())
        return session[0]

    record = None
    if args.command == "start":
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000))
        rows = series.start_series(args.execution, args.started or now)
    elif args.command == "smoke":
        # The value is the publish time: a read-back compares it exactly. The
        # execution label lets the alert-path check rule (CerberusAlertPathCheck)
        # name the smoke run in its email.
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts_ms / 1000))
        rows = [("cerberus_publisher_smoke", {"execution": f"smoke-{stamp}"}, ts_ms / 1000)]
    else:
        record = load_record(args, session_for)
        if record is None:
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
    if not url and not args.send:
        print(
            f"# dry run: {len(rows)} series, request body {len(body)} bytes, not sent",
            file=sys.stderr,
        )
        return 0
    if args.send:
        return send_to_amp(args, record, rows, body, ts_ms, session_for)
    try:
        status, reply = send(url, body)
    except (OSError, ValueError) as err:  # URLError and timeouts are OSError
        print(f"publish: send failed: {err}", file=sys.stderr)
        return 1
    print(f"# sent: {len(rows)} series, {len(body)} bytes, HTTP {status}", file=sys.stderr)
    if not 200 <= status < 300:
        print(f"publish: receiver replied HTTP {status}: {reply}", file=sys.stderr)
        return 1
    return 0


def send_to_amp(args, record, rows, body, ts_ms, session_for):
    target = aws_send.Target(session_for())
    if args.command == "end" and not args.force:
        finished = series.epoch(record["end"])
        try:
            stored = aws_send.newest_finished(target)
        except (aws_send.AwsError, ValueError, LookupError) as err:
            print(f"publish: warning: newest-run guard skipped: {err}", file=sys.stderr)
            stored = None
        if stored is not None and stored > finished:
            print(
                f"publish: refused: AMP holds a newer run end ({stored:.0f} > {finished:.0f});"
                " use --force",
                file=sys.stderr,
            )
            return 2
    status, reply = target.write(body)
    print(f"# sent to AMP: {len(rows)} series, {len(body)} bytes, HTTP {status}", file=sys.stderr)
    if not 200 <= status < 300:
        print(f"publish: AMP replied HTTP {status}: {reply}", file=sys.stderr)
        return 1
    if args.command == "smoke":
        if not aws_send.read_back_smoke(target, ts_ms):
            print("publish: smoke sample written but not visible on read-back", file=sys.stderr)
            return 1
        print("# smoke: sample read back", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
