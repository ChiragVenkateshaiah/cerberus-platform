"""Pipeline status publisher, dry run only (plan 10.2, PR B).

  publish.py start --execution N [--started ISO] [--at ISO]
  publish.py end --execution N [--record PATH] [--at ISO]

It prints the series in Prometheus text format, with the publish timestamp in
ms. There is no network code in this PR; sending comes in a later PR.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import remote_write
import series

RUNS = Path(__file__).resolve().parents[1] / "scale" / "runs"


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


def build_parser():
    p = argparse.ArgumentParser(description="Cerberus pipeline status publisher (dry run).")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start", help="series written right after start-execution")
    s.add_argument("--execution", required=True)
    s.add_argument("--started", help="run start, ISO 8601 (default: the publish time)")
    s.add_argument("--at", help="publish time, ISO 8601 (default: now)")
    e = sub.add_parser("end", help="series written when the run has ended")
    e.add_argument("--execution", required=True)
    e.add_argument("--record", help="run record JSON (default: observability/scale/runs/N.json)")
    e.add_argument("--at", help="publish time, ISO 8601 (default: now)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
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
    print(
        f"# dry run: {len(rows)} series, request body {len(body)} bytes, not sent", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
