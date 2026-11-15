"""CLI.

python -m cerberus_live_check watch  --standing URL [--gone] [--timeout-min N] [--show-url]
python -m cerberus_live_check verify --standing URL [--no-sign-in] [--no-wait] [--out DIR]
                                     [--chromium PATH] [--timeout-min N]

Exit codes: 0 ok, 1 a check failed, 2 the password was found in the report (nothing written),
3 watch timed out. The password comes from getpass or CERBERUS_CHECK_PASSWORD, never an argument.
"""

import argparse
import sys


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_live_check")
    sub = parser.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="wait for live.json (or its removal)")
    w.add_argument("--standing", required=True)
    w.add_argument("--gone", action="store_true", help="wait until live.json is not 200")
    w.add_argument("--timeout-min", type=int, default=30)
    w.add_argument(
        "--show-url", action="store_true", help="print the session URL (your terminal only)"
    )

    v = sub.add_parser("verify", help="run the live checks and write a redacted report")
    v.add_argument("--standing", required=True)
    v.add_argument("--no-sign-in", action="store_true", help="public checks only; no password")
    v.add_argument(
        "--no-wait", action="store_true", help="do not wait for live.json; record L1 as it is"
    )
    v.add_argument("--timeout-min", type=int, default=30)
    v.add_argument(
        "--out", help="report directory (default console/live-check-reports/<UTC stamp>)"
    )
    v.add_argument("--chromium", help="path to a chromium or headless-shell binary")

    args = parser.parse_args(argv)
    if not args.standing.startswith("https://"):
        print("--standing must start with https://", file=sys.stderr)
        return 2
    if args.cmd == "watch":
        from cerberus_live_check import watch

        return watch.run(args.standing, args.gone, args.timeout_min, args.show_url)
    from cerberus_live_check import verify

    return verify.run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
