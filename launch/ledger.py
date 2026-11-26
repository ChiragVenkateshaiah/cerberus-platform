"""The launch cost ledger and the $25 stop rule (ADR 0030 Decision 12).

Attributable spend = November Usage (credits excluded, all services, from Cost
Explorer) minus the baseline through 2026-11-24, plus the ledger. The ledger
holds an estimate appended before each run and corrected at exit. It overlaps
with the reported figure on purpose, so the rule errs on the side of refusing.

The CLI is the contract with 17.5 (launch_exercise.sh):

  ledger.py guard   --next-usd N      exit 0 only if the run is allowed; non-zero on
                                      every error and on a refusal (1 refused, 2 error)
  ledger.py record  --run-id ID --kind session|exercise --estimate-usd N [--gb N]
  ledger.py correct --run-id ID --usd N
  ledger.py estimate --minutes M --gb G [--mtd-gb X]    print the run estimate in USD
  ledger.py baseline                  READ-ONLY: write cost_baseline.json once; also create an
                                      empty ledger if there is none (an existing one is kept)

`launch-destroy` and `launch-collect` never call guard. cost_baseline.json is the
owner's to generate (`make launch-baseline`); no number in it is invented here.
Paths can be overridden with --ledger and --baseline (or LAUNCH_LEDGER and
LAUNCH_BASELINE), for tests.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE.parent / "observability" / "launch" / "ledger.jsonl"
BASELINE = HERE / "cost_baseline.json"
RUN_ID = re.compile(r"^[a-z0-9-]{1,40}$")
KINDS = ("session", "exercise")
STOP_USD = Decimal("25.00")
MONTH_START = "2026-11-01"
MONTH_END = "2026-12-01"  # exclusive: the exception ends 2026-11-30
BASELINE_THROUGH = "2026-11-24"
BASELINE_END = "2026-11-25"  # exclusive
# ADR 0030 Decision 12: one all-in hourly rate (launch plan section 6), GB over
# the free tier at list price, and a flat allowance. The allowance is an
# unverified choice of 17.4.
HOURLY_USD = Decimal("0.40")
PER_GB_USD = Decimal("0.085")
FREE_TIER_GB = Decimal("1000")
ALLOWANCE_USD = Decimal("1.00")
TEARDOWN_MINUTES = 30
CE_FILTER = json.dumps({"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}})


class LedgerError(Exception):
    pass


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def parse_usd(text: str, what: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as err:
        raise LedgerError(f"{what} is not a number") from err
    if not value.is_finite() or value < 0:
        raise LedgerError(f"{what} must be a number of 0 or more")
    return value


def estimate(minutes: Decimal, gb: Decimal, mtd_gb: Decimal = Decimal(0)) -> Decimal:
    """Instance hours (plus teardown) at the all-in rate, GB over free tier, allowance."""
    hours = (minutes + TEARDOWN_MINUTES) / 60
    over = max(Decimal(0), mtd_gb + gb - FREE_TIER_GB) - max(Decimal(0), mtd_gb - FREE_TIER_GB)
    return money(hours * HOURLY_USD + over * PER_GB_USD + ALLOWANCE_USD)


def read_entries(path: Path) -> dict[str, dict]:
    """run_id -> {"estimate": Decimal, "usd": Decimal}. A bad line is an error."""
    runs: dict[str, dict] = {}
    if not path.exists():
        return runs
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            run_id = item["run_id"]
            if item["event"] == "record":
                if run_id in runs:
                    raise LedgerError(f"ledger line {number}: run {run_id} recorded twice")
                est = Decimal(str(item["estimate_usd"]))
                runs[run_id] = {"estimate": est, "usd": est, "gb": Decimal(str(item.get("gb", 0)))}
            elif item["event"] == "correct":
                runs[run_id]["usd"] = Decimal(str(item["usd"]))
            else:
                raise LedgerError(f"ledger line {number}: unknown event")
        except LedgerError:
            raise
        except (ValueError, KeyError, InvalidOperation, TypeError) as err:
            raise LedgerError(f"ledger line {number} is not valid") from err
    return runs


def append(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    item["at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = (json.dumps(item, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def usage_total(start: str, end: str) -> Decimal:
    """Cost Explorer Usage (credits excluded) for [start, end). Any failure raises."""
    cmd = [
        "aws", "--region", "us-east-1", "ce", "get-cost-and-usage",
        "--time-period", f"Start={start},End={end}",
        "--granularity", "MONTHLY", "--metrics", "UnblendedCost",
        "--filter", CE_FILTER, "--output", "json",
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        rows = json.loads(out)["ResultsByTime"]
        return sum((Decimal(r["Total"]["UnblendedCost"]["Amount"]) for r in rows), Decimal(0))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, InvalidOperation) as err:
        raise LedgerError("Cost Explorer could not be read") from err


def read_baseline(path: Path) -> Decimal:
    if not path.exists():
        raise LedgerError("cost_baseline.json is absent: run `make launch-baseline` first")
    try:
        data = json.loads(path.read_text())
        if data["through"] != BASELINE_THROUGH:
            raise LedgerError("cost_baseline.json does not end at 2026-11-24")
        return parse_usd(str(data["usage_usd"]), "baseline usage_usd")
    except (ValueError, KeyError, TypeError) as err:
        raise LedgerError("cost_baseline.json is not valid") from err


def guard(next_usd: Decimal, ledger: Path, baseline: Path) -> tuple[bool, str]:
    base = read_baseline(baseline)
    # Fail closed: a deleted ledger would hide earlier spend. `baseline` creates it empty.
    if not ledger.exists():
        raise LedgerError(
            "the ledger file is absent: run `make launch-baseline` (it creates an empty one)"
        )
    end = min(
        (datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
        MONTH_END,
    )
    reported = usage_total(MONTH_START, end) - base
    if reported < 0:
        raise LedgerError("reported spend is below the baseline: the baseline is wrong")
    ledgered = sum((r["usd"] for r in read_entries(ledger).values()), Decimal(0))
    total = reported + ledgered + next_usd
    text = (
        f"attributable: reported {money(reported)} + ledger {money(ledgered)} "
        f"+ next {money(next_usd)} = {money(total)} (stop above {STOP_USD})"
    )
    return total <= STOP_USD, text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", default=os.environ.get("LAUNCH_LEDGER", str(LEDGER)))
    ap.add_argument("--baseline", default=os.environ.get("LAUNCH_BASELINE", str(BASELINE)))
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("guard")
    g.add_argument("--next-usd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--run-id", required=True)
    r.add_argument("--kind", required=True, choices=KINDS)
    r.add_argument("--estimate-usd", required=True)
    r.add_argument("--gb", default="0")
    c = sub.add_parser("correct")
    c.add_argument("--run-id", required=True)
    c.add_argument("--usd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--minutes", required=True)
    e.add_argument("--gb", required=True)
    e.add_argument("--mtd-gb", default="0")
    sub.add_parser("baseline")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    ledger, baseline = Path(args.ledger), Path(args.baseline)
    try:
        if args.cmd == "guard":
            ok, text = guard(parse_usd(args.next_usd, "--next-usd"), ledger, baseline)
            print(text)
            if not ok:
                print("REFUSED: the $25 stop rule", file=sys.stderr)
            return 0 if ok else 1
        if args.cmd == "record":
            if not RUN_ID.match(args.run_id):
                raise LedgerError("run id must match ^[a-z0-9-]{1,40}$")
            est = parse_usd(args.estimate_usd, "--estimate-usd")
            gb = parse_usd(args.gb, "--gb")
            if args.run_id in read_entries(ledger):
                raise LedgerError(f"run {args.run_id} is already in the ledger")
            append(ledger, {"event": "record", "run_id": args.run_id, "kind": args.kind,
                            "estimate_usd": str(est), "gb": str(gb)})  # fmt: skip
            return 0
        if args.cmd == "correct":
            usd = parse_usd(args.usd, "--usd")
            if args.run_id not in read_entries(ledger):
                raise LedgerError(f"run {args.run_id} is not in the ledger")
            append(ledger, {"event": "correct", "run_id": args.run_id, "usd": str(usd)})
            return 0
        if args.cmd == "estimate":
            print(estimate(parse_usd(args.minutes, "--minutes"), parse_usd(args.gb, "--gb"),
                           parse_usd(args.mtd_gb, "--mtd-gb")))  # fmt: skip
            return 0
        if baseline.exists():
            raise LedgerError("cost_baseline.json exists: it is recorded once, not rewritten")
        # Only on the first baseline: a rerun must not hide a lost ledger.
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.touch(exist_ok=True)  # never truncates
        usd = usage_total(MONTH_START, BASELINE_END)
        baseline.write_text(json.dumps({
            "through": BASELINE_THROUGH, "record_type": "Usage", "credits": "excluded",
            "usage_usd": str(usd),
        }, indent=2) + "\n")  # fmt: skip
        print(f"baseline written through {BASELINE_THROUGH}: {money(usd)} USD")
        return 0
    except LedgerError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    except Exception as err:  # fail closed
        print(f"ERROR: {type(err).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
