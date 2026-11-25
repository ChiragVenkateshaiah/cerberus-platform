"""Layer 1 of the byte control (ADR 0030 Decision 12): refuse a session over budget.

It refuses a session over 400 GB, and a month-to-date total plus the session
over 900 GB (the probe P bytes are in the session). Month-to-date is the larger
of the ledger's GB and CloudWatch BytesDownloaded. It prints the nftables
budget: planned bytes x 1.10, as a whole number of bytes. All GB are decimal
(1 GB = 1,000,000,000 bytes). The planned bytes are exact: they come from the
scenario files (launch/scenario.py): 64 MiB chunk requests plus the licence
response bodies, not from a stored number.

Usage: python3 launch/plan_bytes.py SCENARIO [--mtd-gb N] [--offline]
                                   [--distribution-id ID] [--ledger PATH]

SCENARIO is a, b, c, d, bcd or p. --mtd-gb gives the month-to-date directly (no
ledger, no AWS). --offline reads the ledger only and makes no AWS call.

Output (stdout, key=value): session_gb, probe_gb, mtd_gb, total_gb (GB to 3
places), session_bytes, probe_bytes, total_bytes (exact) and budget_bytes.
Exit 0 when allowed, 2 when refused, 3 on any error (fail closed).
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import scenario  # noqa: E402

LEDGER = HERE.parent / "observability" / "launch" / "ledger.jsonl"
SESSION_CAP_GB = Decimal("400")
MONTH_CAP_GB = Decimal("900")
BUDGET_FACTOR = Decimal("1.10")
GB = Decimal(1_000_000_000)


class Refused(Exception):
    pass


def scenario_bytes(name: str) -> int:
    """Exact planned bytes of the scenario itself, without the probe."""
    return scenario.session_plan(name).total_bytes


def scenario_gb(name: str) -> Decimal:
    """Planned GB of the scenario itself, without the probe (exact, not rounded)."""
    return Decimal(scenario_bytes(name)) / GB


def probe_bytes(name: str) -> int:
    """The probe P bytes: part of every live session, except P itself."""
    return 0 if name == "p" else scenario_bytes("p")


def probe_gb(name: str) -> Decimal:
    return Decimal(probe_bytes(name)) / GB


def budget_bytes(name: str) -> int:
    """The nftables budget of the instance: planned scenario bytes x 1.10.

    The probe runs from the laptop, not the instance, so it is not in it.
    """
    return int(
        (Decimal(scenario_bytes(name)) * BUDGET_FACTOR).to_integral_value(rounding=ROUND_CEILING)
    )


def evaluate(session_gb: Decimal, mtd_gb: Decimal) -> None:
    """Raise Refused when the session or the month is over its cap."""
    if session_gb > SESSION_CAP_GB:
        raise Refused(f"session {session_gb} GB is over the {SESSION_CAP_GB} GB cap")
    if mtd_gb + session_gb > MONTH_CAP_GB:
        raise Refused(f"month-to-date {mtd_gb} + session {session_gb} GB is over {MONTH_CAP_GB} GB")


def ledger_gb(path: Path) -> Decimal:
    """GB of earlier runs in the ledger. A missing file is zero; a bad line is an error."""
    if not path.exists():
        return Decimal(0)
    total = Decimal(0)
    for line in path.read_text().splitlines():
        if line.strip():
            total += Decimal(str(json.loads(line).get("gb", 0)))
    return total


def cloudwatch_gb(distribution_id: str) -> Decimal:
    """Month-to-date BytesDownloaded of one distribution. Any failure raises."""
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = subprocess.run(
        [
            "aws", "--region", "us-east-1", "cloudwatch", "get-metric-statistics",
            "--namespace", "AWS/CloudFront", "--metric-name", "BytesDownloaded",
            "--dimensions", f"Name=DistributionId,Value={distribution_id}",
            "Name=Region,Value=Global",
            "--start-time", start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--end-time", now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "--period", "86400", "--statistics", "Sum", "--output", "json",
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    points = json.loads(out).get("Datapoints", [])
    return sum((Decimal(str(p["Sum"])) for p in points), Decimal(0)) / GB


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario")
    ap.add_argument("--mtd-gb")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--distribution-id")
    ap.add_argument("--ledger", default=os.environ.get("LAUNCH_LEDGER", str(LEDGER)))
    args = ap.parse_args(argv)
    try:
        session = scenario_gb(args.scenario)
        probe = probe_gb(args.scenario)
        session_b = scenario_bytes(args.scenario)
        probe_b = probe_bytes(args.scenario)
        if args.mtd_gb is not None:
            mtd = Decimal(args.mtd_gb)
        else:
            mtd = ledger_gb(Path(args.ledger))
            if not args.offline and args.distribution_id:
                mtd = max(mtd, cloudwatch_gb(args.distribution_id))
        total = session + probe
        print(f"session_gb={scenario.gb(session_b)}")
        print(f"probe_gb={scenario.gb(probe_b)}")
        print(f"mtd_gb={mtd}")
        print(f"total_gb={scenario.gb(session_b + probe_b)}")
        print(f"session_bytes={session_b}")
        print(f"probe_bytes={probe_b}")
        print(f"total_bytes={session_b + probe_b}")
        print(f"budget_bytes={budget_bytes(args.scenario)}")
        evaluate(total, mtd)
    except Refused as err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return 2
    except Exception as err:  # fail closed: any error is a refusal to go on
        print(f"ERROR: {type(err).__name__}: {err}", file=sys.stderr)
        return 3
    print("allowed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
