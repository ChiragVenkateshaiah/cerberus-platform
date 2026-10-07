"""Cerberus 8.3 -- collects the Phase 8 metric set for one orchestrated run.

Definitions, sources and caveats live in docs/scale-metrics.md; this script
is the "where each number comes from" half, in code. One run in, one JSON
record out (observability/scale/runs/<execution>.json), plus a short
summary on stdout.

    uv run --no-project --with boto3 python observability/scale/collect_run_metrics.py \
        --execution demo-7-8-take1-20261006T075445 [--cost] [--generator-run-id ID]

    # the next day, once Cost Explorer has posted:
    uv run --no-project --with boto3 python observability/scale/collect_run_metrics.py \
        --execution demo-7-8-take1-20261006T075445 --cost-only

Read-only, with two narrow exceptions: one Athena count(*) against silver
(run as cerberus-transform, since cerberus-admin can't start queries -- 7.3),
and, only with --cost, one Cost Explorer request, which AWS bills at $0.01.
Everything else runs as cerberus-admin.

Collect right after the run, before the next one: the S3 sizes and the
silver count are a snapshot of "now", not of the run's moment.
"""

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = "us-east-1"
ACCOUNT_ID = "131715059025"
STATE_MACHINE = f"arn:aws:states:{REGION}:{ACCOUNT_ID}:stateMachine:cerberus-platform-orchestration"
WORKGROUP = "cerberus_platform"
DATABASE = "cerberus_platform"
AMP_ALIAS = "cerberus-platform"
BUCKET = "cerberus-platform-{layer}-" + ACCOUNT_ID
ADMIN_PROFILE = "cerberus-admin"
QUERY_PROFILE = "cerberus-transform"

# Athena bills each query for at least 10 MB, rounded up to the next MB.
ATHENA_MIN_BILLED_BYTES = 10 * 1024 * 1024
ATHENA_USD_PER_TB = 5.0
OUT_DIR = Path(__file__).resolve().parent / "runs"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execution", required=True, help="Step Functions execution name")
    parser.add_argument(
        "--cost",
        action="store_true",
        help="query Cost Explorer for the run's UTC day ($0.01; data posts about a day later)",
    )
    parser.add_argument(
        "--cost-only",
        action="store_true",
        help="add or refresh only the cost section of an existing record ($0.01), "
        "leaving its run-time snapshot untouched -- the day-after step",
    )
    parser.add_argument(
        "--generator-run-id",
        help="also size bronze/payments_bulk/run_id=<ID>/ (a generate_bulk.sh run)",
    )
    parser.add_argument(
        "--events-processed",
        type=int,
        help="events this run processed; defaults to the silver total, right for the "
        "current full rebuild but not for an incremental run (8.5)",
    )
    return parser.parse_args()


def state_timings(sfn, execution_arn):
    execution = sfn.describe_execution(executionArn=execution_arn)
    entered, states = {}, []
    pages = sfn.get_paginator("get_execution_history").paginate(executionArn=execution_arn)
    for page in pages:
        for event in page["events"]:
            if event["type"] == "TaskStateEntered":
                entered[event["stateEnteredEventDetails"]["name"]] = event["timestamp"]
            elif event["type"] == "TaskStateExited":
                name = event["stateExitedEventDetails"]["name"]
                start, end = entered[name], event["timestamp"]
                states.append({"state": name, "start": start, "end": end})
    return execution, states


def athena_queries(athena, start, end):
    """Every query in the workgroup submitted between start and end.

    ListQueryExecutions returns newest first, so paging stops at the first
    query older than start. One GetQueryExecution per id: cerberus-admin has
    no BatchGetQueryExecution.
    """
    found = []
    for page in athena.get_paginator("list_query_executions").paginate(WorkGroup=WORKGROUP):
        for query_id in page["QueryExecutionIds"]:
            query = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
            submitted = query["Status"]["SubmissionDateTime"]
            if submitted < start:
                return found
            if submitted <= end:
                found.append(query)
    return found


def athena_by_state(queries, states):
    result = {}
    for state in states:
        mine = [
            q
            for q in queries
            if state["start"] <= q["Status"]["SubmissionDateTime"] <= state["end"]
        ]
        scanned = sum(q["Statistics"].get("DataScannedInBytes", 0) for q in mine)
        billed = sum(
            max(
                ATHENA_MIN_BILLED_BYTES,
                math.ceil(q["Statistics"].get("DataScannedInBytes", 0) / 2**20) * 2**20,
            )
            for q in mine
        )
        result[state["state"]] = {
            "queries": len(mine),
            "bytes_scanned": scanned,
            "bytes_billed": billed,
            "usd": round(billed / 1e12 * ATHENA_USD_PER_TB, 6),
        }
    return result


class Amp:
    def __init__(self, session):
        workspaces = session.client("amp").list_workspaces(alias=AMP_ALIAS)["workspaces"]
        workspace_id = workspaces[0]["workspaceId"]
        self.base = (
            f"https://aps-workspaces.{REGION}.amazonaws.com/workspaces/{workspace_id}/api/v1/"
        )
        self.credentials = session.get_credentials().get_frozen_credentials()

    def query(self, promql, at):
        # quote_via=quote: SigV4 signs %20, and urlencode's default '+' fails it (403).
        params = urllib.parse.urlencode(
            {"query": promql, "time": at.isoformat()}, quote_via=urllib.parse.quote
        )
        request = AWSRequest(method="GET", url=f"{self.base}query?{params}")
        SigV4Auth(self.credentials, "aps", REGION).add_auth(request)
        with urllib.request.urlopen(
            urllib.request.Request(request.url, headers=dict(request.headers))
        ) as response:
            return json.load(response)["data"]["result"]


def prometheus_metrics(amp, start, end):
    window = f"{max(60, math.ceil((end - start).total_seconds()))}s"
    series = amp.query(f'max_over_time(count({{__name__=~".+"}})[{window}:15s])', end)
    per_app = {}
    for metric, key in [
        ("metrics_executor_totalInputBytes_bytes_total", "spark_input_bytes"),
        ("metrics_executor_totalShuffleWrite_bytes_total", "spark_shuffle_write_bytes"),
    ]:
        # A counter per executor that resets with each application: the max
        # inside the window is that executor's total; sum over executors.
        promql = f"sum by (spark_app) (max_over_time({metric}[{window}]))"
        for row in amp.query(promql, end):
            per_app.setdefault(row["metric"].get("spark_app", "?"), {})[key] = int(
                float(row["value"][1])
            )
    return {
        "peak_active_series": int(float(series[0]["value"][1])) if series else None,
        "spark": per_app,
    }


def prefix_size(s3, layer, prefix):
    objects = size = 0
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=BUCKET.format(layer=layer), Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            objects += 1
            size += obj["Size"]
    return {"objects": objects, "bytes": size}


def silver_counts(session):
    athena = session.client("athena")
    query_id = athena.start_query_execution(
        QueryString="SELECT count(*), count(DISTINCT transaction_id) FROM payments_events",
        WorkGroup=WORKGROUP,
        QueryExecutionContext={"Database": DATABASE},
    )["QueryExecutionId"]
    while True:
        query = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        if query["Status"]["State"] not in ("QUEUED", "RUNNING"):
            break
        time.sleep(1)
    if query["Status"]["State"] != "SUCCEEDED":
        raise SystemExit(f"silver count failed: {query['Status'].get('StateChangeReason')}")
    row = athena.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"][1]["Data"]
    return int(row[0]["VarCharValue"]), int(row[1]["VarCharValue"])


def day_cost(session, day):
    """One Cost Explorer request ($0.01): the day's usage cost by service and
    usage type, for us-east-1 plus global.

    Not filtered on the Project tag: the EKS node instances are untagged
    (managed node groups don't inherit the provider's default_tags), and
    they are the largest line. The platform is the only workload in
    us-east-1, so the region is the boundary. Cost Explorer's own
    per-request charge is excluded.
    """
    ce = session.client("ce", region_name="us-east-1")
    response = ce.get_cost_and_usage(
        TimePeriod={"Start": day.isoformat(), "End": (day + timedelta(days=1)).isoformat()},
        Granularity="DAILY",
        Metrics=["UnblendedCost", "UsageQuantity"],
        Filter={
            "And": [
                {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
                {"Dimensions": {"Key": "REGION", "Values": [REGION, "global", "NoRegion"]}},
            ]
        },
        GroupBy=[
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
        ],
    )
    result = response["ResultsByTime"][0]
    by_service, cluster_hours = {}, 0.0
    for group in result["Groups"]:
        service, usage_type = group["Keys"]
        if service == "AWS Cost Explorer":
            continue
        usd = float(group["Metrics"]["UnblendedCost"]["Amount"])
        by_service[service] = round(by_service.get(service, 0.0) + usd, 6)
        if "AmazonEKS-Hours:perCluster" in usage_type:
            cluster_hours += float(group["Metrics"]["UsageQuantity"]["Amount"])
    total = round(sum(by_service.values()), 6)
    return {
        "day": day.isoformat(),
        "estimated": result.get("Estimated", True),
        "usd": total,
        "by_service": dict(sorted(by_service.items(), key=lambda kv: -kv[1])),
        "eks_cluster_hours": round(cluster_hours, 3),
        "usd_per_cluster_hour": round(total / cluster_hours, 4) if cluster_hours else None,
    }


def add_cost(record, admin):
    start = datetime.fromisoformat(record["start"])
    cost = day_cost(admin, start.date())
    athena_usd = sum(state["athena"]["usd"] for state in record["states"])
    rate = cost["usd_per_cluster_hour"]
    run_usd = rate * record["run_seconds"] / 3600 + athena_usd if rate else None
    cost["run_usd"] = round(run_usd, 4) if run_usd is not None else None
    cost["usd_per_million_events"] = (
        round(run_usd / (record["events_processed"] / 1e6), 2) if run_usd is not None else None
    )
    cost["collected_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    record["cost"] = cost


def print_cost(cost):
    print(
        f"  day {cost['day']} ${cost['usd']} (estimated={cost['estimated']}), "
        f"{cost['eks_cluster_hours']} cluster-h, run ${cost['run_usd']}, "
        f"${cost['usd_per_million_events']}/M events"
    )


def main():
    args = parse_args()
    admin = boto3.Session(profile_name=ADMIN_PROFILE, region_name=REGION)
    out = OUT_DIR / f"{args.execution}.json"

    if args.cost_only:
        record = json.loads(out.read_text())
        add_cost(record, admin)
        out.write_text(json.dumps(record, indent=2) + "\n")
        print(f"{args.execution}: cost refreshed in {out.name}")
        print_cost(record["cost"])
        return
    execution_arn = STATE_MACHINE.replace(":stateMachine:", ":execution:") + ":" + args.execution

    execution, states = state_timings(admin.client("stepfunctions"), execution_arn)
    start, end = execution["startDate"], execution["stopDate"]
    run_seconds = (end - start).total_seconds()

    athena = athena_by_state(athena_queries(admin.client("athena"), start, end), states)
    prometheus = prometheus_metrics(Amp(admin), start, end)
    s3 = admin.client("s3")
    storage = {
        "bronze_payments": prefix_size(s3, "bronze", "payments/"),
        "bronze_payments_bulk": prefix_size(s3, "bronze", "payments_bulk/"),
        "silver_payments": prefix_size(s3, "silver", "payments/"),
        "gold": prefix_size(s3, "gold", ""),
    }
    if args.generator_run_id:
        storage["generator_run"] = prefix_size(
            s3, "bronze", f"payments_bulk/run_id={args.generator_run_id}/"
        )

    silver_events, silver_transactions = silver_counts(
        boto3.Session(profile_name=QUERY_PROFILE, region_name=REGION)
    )
    events_processed = args.events_processed or silver_events

    state_rows = []
    for state in states:
        seconds = (state["end"] - state["start"]).total_seconds()
        state_rows.append(
            {
                "state": state["state"],
                "seconds": round(seconds, 1),
                "events_per_second": round(events_processed / seconds) if seconds else None,
                "athena": athena[state["state"]],
            }
        )

    record = {
        "execution": args.execution,
        "status": execution["status"],
        "start": start.astimezone(UTC).isoformat(),
        "end": end.astimezone(UTC).isoformat(),
        "run_seconds": round(run_seconds, 1),
        "events_processed": events_processed,
        "events_per_second": round(events_processed / run_seconds),
        "silver": {"events": silver_events, "transactions": silver_transactions},
        "states": state_rows,
        "athena_totals": {
            key: sum(a[key] for a in athena.values())
            for key in ("queries", "bytes_scanned", "bytes_billed")
        },
        "prometheus": prometheus,
        "storage_snapshot": storage,
        # 8.4 builds the suite; until then this stays empty on purpose.
        "data_quality": None,
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    if args.cost:
        add_cost(record, admin)

    OUT_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")

    print(f"{args.execution}: {execution['status']}, {run_seconds:.0f}s, {events_processed} events")
    for row in state_rows:
        print(
            f"  {row['state']:16} {row['seconds']:7.1f}s  athena {row['athena']['queries']:3} "
            f"queries {row['athena']['bytes_scanned']:>12} B scanned"
        )
    print(f"  peak series {prometheus['peak_active_series']}, spark {prometheus['spark']}")
    if "cost" in record:
        print_cost(record["cost"])
    print(f"  wrote {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")


if __name__ == "__main__":
    main()
