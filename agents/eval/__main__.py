"""`python -m agents.eval`: replay the cases, print the report, write nothing.

Run it with PYTHONPATH=agents:console from the repo root. Exit code 0 when the ADR 0025
bar is met, 1 when it is not, 2 when a case file is bad.
"""

import argparse
import sys

from . import score
from .answerers import ANSWERERS
from .cases import CaseError, load_cases


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m agents.eval", description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--answerer", choices=sorted(ANSWERERS), default="echo")
    args = parser.parse_args(argv)
    try:
        cases = load_cases()
    except CaseError as exc:
        print(f"case error: {exc}", file=sys.stderr)
        return 2
    report = score.run(ANSWERERS[args.answerer], cases)
    sys.stdout.write(score.dumps(report) if args.json else score.markdown(report, args.answerer))
    return 0 if report["bar"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
