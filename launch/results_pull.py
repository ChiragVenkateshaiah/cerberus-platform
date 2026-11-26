"""Pull the launch results from Athena and Cost Explorer into small CSV extracts (17.7).

READ-ONLY, owner-run. Two subcommands:

  results --session ID [--session ID ...] --exercise ID [--out DIR]
      Runs the five queries in launch/queries/ over the gold downloads marts
      (Athena workgroup, database and profile of the data-quality suite) and
      writes observability/launch/extracts/<name>.csv plus manifest.json (the
      run ids, the pull date, the sha256 and row count of each SQL).
  cost [--out DIR]
      Cost Explorer, record type Usage (ledger.CE_FILTER): the November total
      and the daily cost by service, 2026-11-25 to 2026-11-30. Writes cost.json.

Every run id must match ^[a-z0-9-]{1,40}$ before it goes into a query. A query
that returns more than 20,000 rows, a header that differs from the one the
render expects, or a value that holds a 12-digit run (a possible account
number) is refused and nothing is written for it. The render
(launch/results_render.py) reads the files and needs no AWS.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "observability" / "launch"))

import data_quality_downloads as dq  # noqa: E402
import ledger  # noqa: E402

QUERY_DIR = HERE / "queries"
EXTRACTS = ROOT / "observability" / "launch" / "extracts"
RUN_ID = re.compile(r"^[a-z0-9-]{1,40}$")
ACCOUNT = dq.ACCOUNT_RE  # exactly 12 digits, no digit next to them
MAX_ROWS = 20_000
PAGE = 1000
CE_START = "2026-11-25"
CE_END = "2026-12-01"  # exclusive: the exception ends 2026-11-30

# name -> (which id the SQL takes, the header the render expects)
QUERIES = {
    "release_window": (
        "exercise",
        "run_id region minute_at minutes_from_release license_requests early_license_denials "
        "licenses_granted clients_with_chunk chunk_mb stalls installs",
    ),
    "isp_minute": (
        "exercise",
        "run_id isp minute_at active_clients stalled_clients modelled_gbps stall_rate",
    ),
    "cdn_run": (
        "sessions",
        "run_id pop requests hits refresh_hits origin_misses hit_ratio bytes_mb "
        "server_ttfb_p50_ms server_ttfb_p99_ms logs_status",
    ),
    "cdn_minute": ("sessions", "run_id minute_at requests bytes_mb"),
    "cdn_class": (
        "sessions",
        "run_id pop uri_class requests hits refresh_hits origin_misses bytes_mb",
    ),
}


class PullError(Exception):
    pass


def check_id(value: str, what: str) -> str:
    if not RUN_ID.match(value or ""):
        raise PullError(f"{what} must match ^[a-z0-9-]{{1,40}}$")
    return value


def sql_text(name: str) -> str:
    return (QUERY_DIR / f"{name}.sql").read_text()


def render_sql(name: str, exercise: str, sessions: list[str]) -> str:
    """The SQL of a query with the run ids put in (each checked first)."""
    check_id(exercise, "--exercise")
    if not sessions:
        raise PullError("at least one --session is required")
    for item in sessions:
        check_id(item, "--session")
    quoted = ", ".join(f"'{item}'" for item in sorted(set(sessions)))
    return sql_text(name).replace("{run_ids}", quoted).replace("{run_id}", exercise)


def run_query(athena, sql: str, poll_seconds: float = 1.0) -> list[list[str]]:
    """Run one query and return every row, the header first. Any failure raises."""
    started = athena.start_query_execution(
        QueryString=sql,
        WorkGroup=dq.WORKGROUP,
        QueryExecutionContext={"Database": dq.DATABASE},
    )["QueryExecutionId"]
    while True:
        query = athena.get_query_execution(QueryExecutionId=started)["QueryExecution"]
        state = query["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            raise PullError(f"a query ended {state}")
        time.sleep(poll_seconds)
    rows: list[list[str]] = []
    token = None
    while True:
        kwargs = {"QueryExecutionId": started, "MaxResults": PAGE}
        if token:
            kwargs["NextToken"] = token
        page = athena.get_query_results(**kwargs)
        for row in page["ResultSet"]["Rows"]:
            rows.append([cell.get("VarCharValue", "") for cell in row["Data"]])
        if len(rows) > MAX_ROWS + 1:
            raise PullError(f"a query returned more than {MAX_ROWS} rows")
        token = page.get("NextToken")
        if not token:
            return rows


def check_rows(name: str, rows: list[list[str]]) -> list[list[str]]:
    """Header check, row cap, 12-digit refusal. Returns the data rows, sorted."""
    header = QUERIES[name][1].split()
    if not rows or rows[0] != header:
        raise PullError(f"{name}: the header is not the expected one")
    data = rows[1:]
    if len(data) > MAX_ROWS:
        raise PullError(f"{name}: more than {MAX_ROWS} rows")
    for row in data:
        if len(row) != len(header):
            raise PullError(f"{name}: a row has the wrong number of columns")
        if any(ACCOUNT.search(cell) for cell in row):
            raise PullError(f"{name}: a value holds a 12-digit run, refused")
    return sorted(data)


def write_csv(path: Path, header: list[str], data: list[list[str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(data)


def pull_results(
    athena, sessions: list[str], exercise: str, out: Path, today: date | None = None
) -> dict:
    """Run all queries first, then write the files: a refusal leaves nothing half written."""
    checked: dict[str, tuple[str, list[list[str]]]] = {}
    for name in QUERIES:
        sql = render_sql(name, exercise, sessions)
        checked[name] = (sql, check_rows(name, run_query(athena, sql)))
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "exercise_run_id": exercise,
        "session_run_ids": sorted(set(sessions)),
        "pull_date": (today or datetime.now(UTC).date()).isoformat(),
        "queries": {},
    }
    for name, (_sql, data) in checked.items():
        write_csv(out / f"{name}.csv", QUERIES[name][1].split(), data)
        # The hash is of the SQL file as committed, not of the run ids put into it.
        manifest["queries"][name] = {
            "sha256": hashlib.sha256(sql_text(name).encode()).hexdigest(),
            "rows": len(data),
        }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def ce_pages(ce, **kwargs) -> list[dict]:
    rows = []
    token = None
    while True:
        page = ce.get_cost_and_usage(**kwargs, **({"NextPageToken": token} if token else {}))
        rows.extend(page["ResultsByTime"])
        token = page.get("NextPageToken")
        if not token:
            return rows


def pull_cost(ce, out: Path) -> dict:
    """The November Usage total and the daily cost by service. Credits are excluded."""
    flt = json.loads(ledger.CE_FILTER)
    common = {"Metrics": ["UnblendedCost"], "Filter": flt}
    month = ce_pages(
        ce,
        TimePeriod={"Start": ledger.MONTH_START, "End": ledger.MONTH_END},
        Granularity="MONTHLY",
        **common,
    )
    total = sum((Decimal(r["Total"]["UnblendedCost"]["Amount"]) for r in month), Decimal(0))
    daily = []
    for day in ce_pages(
        ce,
        TimePeriod={"Start": CE_START, "End": CE_END},
        Granularity="DAILY",
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        **common,
    ):
        for group in day["Groups"]:
            usd = Decimal(group["Metrics"]["UnblendedCost"]["Amount"]).quantize(Decimal("0.0001"))
            if usd != 0:
                start, service = day["TimePeriod"]["Start"], group["Keys"][0]
                daily.append({"date": start, "service": service, "usd": str(usd)})
    daily.sort(key=lambda d: (d["date"], d["service"]))
    result = {
        "record_type": "Usage",
        "month": ledger.MONTH_START[:7],
        "month_total_usd": str(total.quantize(Decimal("0.0001"))),
        "daily_from": CE_START,
        "daily": daily,
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if ACCOUNT.search(text):
        raise PullError("cost: a value holds a 12-digit run, refused")
    out.mkdir(parents=True, exist_ok=True)
    (out / "cost.json").write_text(text)
    return result


def main(argv=None, athena=None, ce=None, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("results")
    r.add_argument("--session", action="append", required=True)
    r.add_argument("--exercise", required=True)
    r.add_argument("--out", default=str(EXTRACTS))
    c = sub.add_parser("cost")
    c.add_argument("--out", default=str(EXTRACTS))
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        if args.cmd == "results":
            for item in [args.exercise, *args.session]:
                check_id(item, "run id")  # before any client is made
            if athena is None:
                import boto3

                athena = boto3.Session(profile_name=dq.QUERY_PROFILE, region_name=dq.REGION).client(
                    "athena"
                )
            manifest = pull_results(athena, args.session, args.exercise, Path(args.out), today)
            for name, info in sorted(manifest["queries"].items()):
                print(f"{name}: {info['rows']} rows")
        else:
            if ce is None:
                import boto3

                ce = boto3.Session(region_name="us-east-1").client("ce")  # AWS_PROFILE applies
            result = pull_cost(ce, Path(args.out))
            print(f"cost.json: {len(result['daily'])} daily rows")
        return 0
    except PullError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    except Exception as err:  # fail closed, and never print a value
        print(f"ERROR: {type(err).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
