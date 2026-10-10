"""Cerberus 8.4 -- the cross-layer data-quality suite, as Athena queries.

Each check is one query that returns `violations` (0 = pass) and a short
`detail`. Severity `error` fails the suite; `warn` is reported but accepted.
It complements, not repeats, the dbt tests in transform/dbt/models/marts/
schema.yml, which already cover gold's own unique / not_null / accepted_values
/ relationships: this suite checks across layers (bronze -> silver -> gold)
and silver's lifecycle rules (ADR 0003), which no single dbt model can see.

Runs as cerberus-transform (read on bronze, silver and gold, and Athena),
with no cluster: the collector calls run_suite() after each run, and it also
runs on its own:

    uv run --no-project --with boto3 python observability/scale/data_quality.py \\
        [--generator-run-id ID [--generator-manifest dt=COUNT ...]] [--full]

All queries start at once and are polled together, so the suite takes about
as long as its slowest query.

Since 8.5 silver is an incremental Iceberg table built from both bronze
prefixes, so bronze -> silver reconciles `payments/` and `payments_bulk/`
together, and `silver_caught_up` checks that no bronze object is newer than
the watermark in silver's own snapshots.

Since 8.6 bronze is checked as a ledger instead of re-scanned on every run
(at 10M events the full scans read 49 GB, and at 100M they would cost over
$1 a run). Bronze is append-only, so each generator run is checked once, in
full, when it is new: one query per dt against its `_manifest.json` (event
count, duplicates, keys present in silver), through the partition-projected
`bronze_payments_bulk_by_run`. From then on:

- the bronze event total is the sum of the manifests plus a count of the
  Lambda's small `payments/` prefix (`bronze_to_silver_count`, still exact);
- a free S3 listing compares every run's files and bytes with its manifest,
  so a deleted or rewritten old run still fails (`bulk_ledger_integrity`);
- data files in a run with no manifest fail on their own
  (`bulk_runs_without_manifest`), instead of as a silver count mismatch;
- `silver_caught_up` takes object times from the same listing.

What this no longer sees on every run is a silver change that keeps the
count and key uniqueness -- some rows lost and as many wrong rows gained.
`--full` adds back the whole-bronze key and duplicate checks for that; run it
before each milestone. Wrong values under correct keys are not covered by
either mode (a follow-up after Phase 8, docs/plan.md).
"""

import argparse
import json
import re
import sys
import time

import boto3

REGION = "us-east-1"
# 8.6: the suite's own workgroup (10 GiB cutoff); serving and dbt keep
# cerberus_platform's 1 GiB. See terraform/modules/athena/main.tf.
WORKGROUP = "cerberus_platform_dq"
DATABASE = "cerberus_platform"
QUERY_PROFILE = "cerberus-transform"
BRONZE_BUCKET = "cerberus-platform-bronze-131715059025"
BULK_PREFIX = "payments_bulk/"
MANIFEST = "_manifest.json"

# Which bronze prefixes silver is built from (both since 8.5, ADR 0017/0018).
SILVER_SOURCES = ("payments", "payments_bulk")

# Every bronze event silver is built from: the Lambda's payments/ (one JSON
# array per file, on one line: bronze_payments_raw) and the generator's
# payments_bulk/ (JSON Lines: bronze_payments_bulk).
BRONZE_PAYMENTS = """
bronze_payments AS (
    SELECT
        json_extract_scalar(e, '$.transaction_id') AS transaction_id,
        json_extract_scalar(e, '$.event_type') AS event_type
    FROM bronze_payments_raw
    CROSS JOIN UNNEST(CAST(json_parse(line) AS ARRAY(JSON))) AS t (e)
    UNION ALL
    SELECT transaction_id, event_type FROM bronze_payments_bulk
)"""

# Per-transaction event flags over silver, shared by the lifecycle checks.
SILVER_LIFECYCLE = """
lifecycle AS (
    SELECT
        transaction_id,
        count_if(event_type = 'created') AS created,
        count_if(event_type = 'authorized') AS authorized,
        count_if(event_type = 'settled') AS settled,
        count_if(event_type = 'failed') AS failed,
        count_if(event_type = 'refunded') AS refunded,
        min(CASE WHEN event_type = 'created' THEN event_timestamp END) AS created_at,
        min(CASE WHEN event_type = 'authorized' THEN event_timestamp END) AS authorized_at,
        min(CASE WHEN event_type IN ('settled', 'failed') THEN event_timestamp END) AS terminal_at,
        min(CASE WHEN event_type = 'refunded' THEN event_timestamp END) AS refunded_at
    FROM payments_events
    GROUP BY transaction_id
)"""

CHECKS = [
    # --- Reconciliation across layers ------------------------------------
    {
        "name": "silver_to_gold_transactions",
        "severity": "error",
        "about": "fct_transactions has one row per silver transaction, and no others",
        "sql": """
WITH s AS (SELECT DISTINCT transaction_id FROM payments_events),
g AS (SELECT transaction_id FROM fct_transactions)
SELECT count_if(g.transaction_id IS NULL) + count_if(s.transaction_id IS NULL) AS violations,
       cast(count_if(g.transaction_id IS NULL) AS varchar) || ' missing from gold, '
       || cast(count_if(s.transaction_id IS NULL) AS varchar) || ' only in gold' AS detail
FROM s FULL OUTER JOIN g ON s.transaction_id = g.transaction_id""",
    },
    {
        "name": "gold_status_matches_lifecycle",
        "severity": "error",
        "about": "fct_transactions.status is the transaction's last lifecycle state",
        "sql": f"""
WITH {SILVER_LIFECYCLE},
expected AS (
    SELECT transaction_id,
           CASE WHEN refunded > 0 THEN 'refunded' WHEN failed > 0 THEN 'failed'
                WHEN settled > 0 THEN 'settled' WHEN authorized > 0 THEN 'authorized'
                ELSE 'created' END AS status
    FROM lifecycle
)
SELECT count(*) AS violations,
       'e.g. ' || coalesce(arbitrary(f.transaction_id), '-') AS detail
FROM fct_transactions f JOIN expected e ON f.transaction_id = e.transaction_id
WHERE f.status <> e.status""",
    },
    # --- Uniqueness ---------------------------------------------------------
    {
        "name": "silver_duplicate_keys",
        "severity": "error",
        "about": "(transaction_id, event_type) is unique in silver (ADR 0017's MERGE key)",
        "sql": """
SELECT coalesce(sum(n - 1), 0) AS violations,
       cast(count(*) AS varchar) || ' duplicated keys' AS detail
FROM (SELECT count(*) AS n FROM payments_events
      GROUP BY transaction_id, event_type HAVING count(*) > 1)""",
    },
    # --- Lifecycle (ADR 0003) -----------------------------------------------
    {
        "name": "lifecycle_created_authorized",
        "severity": "error",
        "about": "every transaction has exactly one created and one authorized event",
        "sql": f"""
WITH {SILVER_LIFECYCLE}
SELECT count_if(created <> 1 OR authorized <> 1) AS violations,
       cast(count(*) AS varchar) || ' transactions' AS detail
FROM lifecycle""",
    },
    {
        "name": "lifecycle_one_terminal",
        "severity": "error",
        "about": "every transaction ends in exactly one of settled or failed",
        "sql": f"""
WITH {SILVER_LIFECYCLE}
SELECT count_if(settled + failed <> 1) AS violations,
       cast(count_if(failed = 1) AS varchar) || ' failed, '
       || cast(count_if(settled = 1) AS varchar) || ' settled' AS detail
FROM lifecycle""",
    },
    {
        "name": "lifecycle_refunds",
        "severity": "error",
        "about": "a refund only follows a settle, at most once",
        "sql": f"""
WITH {SILVER_LIFECYCLE}
SELECT count_if(refunded > 1 OR (refunded = 1 AND settled = 0)) AS violations,
       cast(count_if(refunded = 1) AS varchar) || ' refunded' AS detail
FROM lifecycle""",
    },
    {
        "name": "lifecycle_order",
        "severity": "error",
        "about": "created <= authorized <= settled/failed <= refunded in time",
        "sql": f"""
WITH {SILVER_LIFECYCLE}
SELECT count_if(
           authorized_at < created_at
           OR terminal_at < authorized_at
           OR refunded_at < terminal_at
       ) AS violations,
       'equal timestamps allowed (the clamp to now)' AS detail
FROM lifecycle""",
    },
    # --- Placement, nulls and values ------------------------------------------
    {
        "name": "silver_key_nulls",
        "severity": "error",
        "about": "no nulls in the columns every event must carry",
        "sql": """
SELECT count_if(transaction_id IS NULL OR event_type IS NULL OR event_timestamp IS NULL
                OR amount IS NULL OR currency IS NULL OR merchant_id IS NULL
                OR customer_id IS NULL OR payment_method_type IS NULL
                OR payment_method_token IS NULL OR loaded_at IS NULL) AS violations,
       cast(count(*) AS varchar) || ' events' AS detail
FROM payments_events""",
    },
    {
        "name": "amount_range_and_stability",
        "severity": "error",
        "about": "amount in [1.00, 999.99]; amount, currency, merchant, customer and token "
        "fixed per transaction",
        "sql": """
SELECT count_if(min_amount < 1.00 OR max_amount > 999.99 OR variants > 1) AS violations,
       cast(count_if(variants > 1) AS varchar) || ' unstable transactions' AS detail
FROM (
    SELECT transaction_id, min(amount) AS min_amount, max(amount) AS max_amount,
           count(DISTINCT (amount, currency, merchant_id, customer_id, payment_method_token))
               AS variants
    FROM payments_events GROUP BY transaction_id
)""",
    },
    {
        "name": "roster",
        "severity": "error",
        "about": "at most 15 merchants and 75 customers, each id with one name",
        "sql": """
SELECT greatest(m.ids - 15, 0) + greatest(c.ids - 75, 0) + m.renamed + c.renamed AS violations,
       cast(m.ids AS varchar) || ' merchants, ' || cast(c.ids AS varchar) || ' customers' AS detail
FROM (SELECT count(*) AS ids, count_if(names > 1) AS renamed
      FROM (SELECT merchant_id, count(DISTINCT merchant_name) AS names
            FROM payments_events GROUP BY merchant_id)) m,
     (SELECT count(*) AS ids, count_if(names > 1) AS renamed
      FROM (SELECT customer_id, count(DISTINCT (customer_name, customer_email)) AS names
            FROM payments_events GROUP BY customer_id)) c""",
    },
    {
        "name": "masking",
        "severity": "error",
        "about": "emails @example.com; cards carry brand + 4-digit last4; other methods "
        "carry neither",
        "sql": """
SELECT count_if(
           customer_email NOT LIKE '%@example.com'
           OR (payment_method_type = 'card'
               AND (payment_method_brand IS NULL
                    OR NOT regexp_like(coalesce(payment_method_last4, ''), '^[0-9]{4}$')))
           OR (payment_method_type <> 'card'
               AND (payment_method_brand IS NOT NULL OR payment_method_last4 IS NOT NULL))
       ) AS violations,
       cast(count_if(payment_method_type = 'card') AS varchar) || ' card events' AS detail
FROM payments_events""",
    },
    {
        "name": "token_format",
        "severity": "error",
        "about": "tokens are tok_ + 16 letters, or the legacy tok_ + 16 hex from before #50",
        "sql": """
SELECT count_if(NOT regexp_like(payment_method_token, '^tok_([a-z]{16}|[0-9a-f]{16})$'))
           AS violations,
       cast(count_if(regexp_like(payment_method_token, '^tok_[a-z]{16}$')) AS varchar)
       || ' letter tokens, '
       || cast(count_if(NOT regexp_like(payment_method_token, '^tok_[a-z]{16}$')) AS varchar)
       || ' legacy hex' AS detail
FROM payments_events""",
    },
    {
        "name": "token_digit_runs",
        "severity": "warn",
        "about": "tokens with a 13+ digit run (a DLP scanner reads them as card numbers); "
        "legacy hex tokens only, accepted since #50 (bronze is append-only)",
        "sql": """
SELECT count(DISTINCT payment_method_token) AS violations,
       'all in legacy hex tokens: '
       || cast(count_if(regexp_like(payment_method_token, '^tok_[0-9a-f]{16}$')) = count(*)
               AS varchar) AS detail
FROM payments_events
WHERE regexp_like(payment_method_token, '[0-9]{13,}')""",
    },
]


# --full only: today's whole-bronze checks, for the gap the ledger leaves (a
# silver change that keeps the count and key uniqueness). About 49 GB at 19M
# events -- before a milestone, not on every run.
FULL_CHECKS = [
    {
        "name": "bronze_to_silver_keys",
        "severity": "error",
        "about": "every bronze (transaction_id, event_type) is in silver, and nothing else is",
        "sql": f"""
WITH {BRONZE_PAYMENTS},
b AS (SELECT DISTINCT transaction_id, event_type FROM bronze_payments),
s AS (SELECT DISTINCT transaction_id, event_type FROM payments_events)
SELECT count_if(s.transaction_id IS NULL) + count_if(b.transaction_id IS NULL) AS violations,
       cast(count_if(s.transaction_id IS NULL) AS varchar) || ' only in bronze, '
       || cast(count_if(b.transaction_id IS NULL) AS varchar) || ' only in silver' AS detail
FROM b FULL OUTER JOIN s
  ON b.transaction_id = s.transaction_id AND b.event_type = s.event_type""",
    },
    {
        "name": "bulk_duplicate_keys",
        "severity": "error",
        "about": "(transaction_id, event_type) is unique across all generator runs",
        "sql": """
SELECT coalesce(sum(n - 1), 0) AS violations,
       cast(count(*) AS varchar) || ' duplicated keys' AS detail
FROM (SELECT count(*) AS n FROM bronze_payments_bulk
      GROUP BY transaction_id, event_type HAVING count(*) > 1)""",
    },
]


def list_bronze(s3):
    """Every data object under both bronze prefixes, plus the bulk manifests.

    Data objects exclude names starting with _ or . -- the same files Athena
    and the silver job's globs skip (_SUCCESS, _manifest.json, staging).
    """
    objects, manifests = [], {}
    for prefix in SILVER_SOURCES:
        pages = s3.get_paginator("list_objects_v2").paginate(
            Bucket=BRONZE_BUCKET, Prefix=f"{prefix}/"
        )
        for page in pages:
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name == MANIFEST and prefix == "payments_bulk":
                    run_id = re.search(r"run_id=([^/]+)/", obj["Key"]).group(1)
                    manifests[run_id] = obj["Key"]
                elif not name.startswith(("_", ".")):
                    objects.append(
                        {
                            "key": obj["Key"],
                            "bytes": obj["Size"],
                            "ms": int(obj["LastModified"].timestamp() * 1000),
                        }
                    )
    return objects, manifests


def read_ledger(s3, manifest_keys):
    """run_id -> the parsed _manifest.json."""
    return {
        run_id: json.loads(s3.get_object(Bucket=BRONZE_BUCKET, Key=key)["Body"].read())
        for run_id, key in sorted(manifest_keys.items())
    }


def bulk_files(objects):
    """(run_id, dt) -> {"objects", "bytes"} from the listing."""
    files = {}
    for obj in objects:
        m = re.match(rf"{BULK_PREFIX}run_id=([^/]+)/dt=([0-9-]{{10}})/", obj["key"])
        if m:
            entry = files.setdefault(m.groups(), {"objects": 0, "bytes": 0})
            entry["objects"] += 1
            entry["bytes"] += obj["bytes"]
    return files


def ledger_integrity(ledger, files, generator_run_id=None, generator_manifest=None):
    """Every run's dt= directories match its manifest's files and bytes."""
    problems = []
    for run_id, manifest in ledger.items():
        listed = {dt: v for (run, dt), v in files.items() if run == run_id}
        for dt in sorted(set(manifest["per_dt"]) | set(listed)):
            want = manifest["per_dt"].get(dt)
            have = listed.get(dt)
            if not want or not have:
                problems.append(f"{run_id} dt={dt} {'not in manifest' if have else 'missing'}")
            elif (want["objects"], want["bytes"]) != (have["objects"], have["bytes"]):
                problems.append(
                    f"{run_id} dt={dt} {have['objects']} files/{have['bytes']} B, "
                    f"manifest {want['objects']}/{want['bytes']}"
                )
    if generator_run_id and generator_manifest:
        stored = ledger.get(generator_run_id, {}).get("per_dt", {})
        logged = {dt: int(n) for dt, n in generator_manifest.items()}
        if {dt: v["events"] for dt, v in stored.items()} != logged:
            problems.append(f"{generator_run_id}: _manifest.json differs from the generator log")
    events = sum(m["events"] for m in ledger.values())
    detail = f"{len(ledger)} runs, {events} events" + (
        "; " + "; ".join(problems[:3]) if problems else ", files and bytes match"
    )
    return {"violations": len(problems), "detail": detail}


def runs_without_manifest(ledger, files):
    """Bulk data under a run_id= with no _manifest.json (an unfinished run)."""
    orphans = sorted({run for run, _ in files} - set(ledger))
    return {
        "violations": len(orphans),
        "detail": ("runs " + ", ".join(orphans)) if orphans else "every run has a manifest",
    }


def ledger_checks(ledger, objects):
    """The bronze total and catch-up checks, from the ledger and the listing."""
    ledger_events = sum(m["events"] for m in ledger.values())
    # VALUES, not ARRAY[...]: an array constructor takes at most 254
    # arguments, and bronze has more files than that.
    if objects:
        files = "SELECT ms FROM (VALUES " + ", ".join(str(o["ms"]) for o in objects) + ") AS t (ms)"
    else:
        files = "SELECT CAST(NULL AS bigint) AS ms WHERE false"
    return [
        {
            "name": "bronze_to_silver_count",
            "severity": "error",
            "about": "silver holds exactly as many events as bronze: the bulk manifests plus "
            "the Lambda's payments/ (no bronze key repeats, so the job's dedup removes nothing)",
            "sql": f"""
WITH raw AS (
    SELECT count(*) AS n FROM bronze_payments_raw
    CROSS JOIN UNNEST(CAST(json_parse(line) AS ARRAY(JSON))) AS t (e)
)
SELECT abs({ledger_events} + r.n - s.n) AS violations,
       'bronze ' || cast({ledger_events} + r.n AS varchar) || ' (manifests {ledger_events}, '
       || 'payments/ ' || cast(r.n AS varchar) || '), silver ' || cast(s.n AS varchar) AS detail
FROM raw r, (SELECT count(*) AS n FROM payments_events) s""",
        },
        {
            "name": "silver_caught_up",
            "severity": "error",
            "about": "no bronze object is newer than the bronze watermark in silver's snapshots "
            "(the incremental job missed nothing); object times from an S3 listing",
            "sql": f"""
WITH watermark AS (
    SELECT max(CAST(summary['cerberus.bronze_watermark'] AS bigint)) AS ms
    FROM "payments_events$snapshots"
),
files AS ({files})
SELECT count_if(f.ms > coalesce(w.ms, -1)) AS violations,
       cast(count(*) AS varchar) || ' bronze files, watermark '
       || coalesce(cast(from_unixtime(arbitrary(w.ms) / 1000) AS varchar), 'none') AS detail
FROM files f CROSS JOIN watermark w""",
        },
        {
            "name": "lambda_keys_in_silver",
            "severity": "error",
            "about": "every payments/ (transaction_id, event_type) is in silver",
            "sql": """
WITH b AS (
    SELECT DISTINCT
        json_extract_scalar(e, '$.transaction_id') AS transaction_id,
        json_extract_scalar(e, '$.event_type') AS event_type
    FROM bronze_payments_raw
    CROSS JOIN UNNEST(CAST(json_parse(line) AS ARRAY(JSON))) AS t (e)
),
s AS (SELECT DISTINCT transaction_id, event_type FROM payments_events)
SELECT count_if(s.transaction_id IS NULL) AS violations,
       cast(count(*) AS varchar) || ' payments/ keys, '
       || cast(count_if(s.transaction_id IS NULL) AS varchar) || ' not in silver' AS detail
FROM b LEFT JOIN s ON b.transaction_id = s.transaction_id AND b.event_type = s.event_type""",
        },
    ]


def new_run_checks(run_id, manifest):
    """The one full check of a new generator run: one query per dt, each
    reading only run_id=<id>/dt=<dt>/ and one day of silver."""
    if manifest is None:
        return [
            {
                "name": "new_run",
                "severity": "error",
                "about": f"payments_bulk/run_id={run_id}/ checked against its manifest",
                "result": {"violations": 1, "detail": "no _manifest.json for this run"},
            }
        ]
    checks = []
    for dt, want in sorted(manifest["per_dt"].items()):
        checks.append(
            {
                "name": f"new_run[dt={dt}]",
                "severity": "error",
                "about": f"payments_bulk/run_id={run_id}/dt={dt}/: the manifest's event count, "
                "no duplicate keys, every key in silver",
                "sql": f"""
WITH s AS (
    SELECT DISTINCT transaction_id, event_type FROM payments_events
    WHERE event_timestamp >= TIMESTAMP '{dt} 00:00:00'
      AND event_timestamp < TIMESTAMP '{dt} 00:00:00' + INTERVAL '1' DAY
),
t AS (
    SELECT count(*) AS n,
           count(DISTINCT b.transaction_id || ':' || b.event_type) AS k,
           count_if(s.transaction_id IS NULL) AS m
    FROM bronze_payments_bulk_by_run b
    LEFT JOIN s ON b.transaction_id = s.transaction_id AND b.event_type = s.event_type
    WHERE b.run_id = '{run_id}' AND b.dt = '{dt}'
)
SELECT abs(n - {int(want["events"])}) + (n - k) + m AS violations,
       cast(n AS varchar) || ' events (manifest {int(want["events"])}), '
       || cast(n - k AS varchar) || ' duplicated, ' || cast(m AS varchar) || ' not in silver'
       AS detail
FROM t""",
            }
        )
    return checks


def run_suite(session=None, generator_run_id=None, generator_manifest=None, full=False):
    session = session or boto3.Session(profile_name=QUERY_PROFILE, region_name=REGION)
    athena = session.client("athena")
    s3 = session.client("s3")
    started = time.time()

    # The ledger: a listing and the manifests, a few S3 calls. If it can't be
    # read, the checks built on it fail -- the suite fails closed.
    try:
        objects, manifest_keys = list_bronze(s3)
        ledger = read_ledger(s3, manifest_keys)
        files = bulk_files(objects)
        checks = [
            {
                "name": "bulk_ledger_integrity",
                "severity": "error",
                "about": "every generator run's files and bytes match its _manifest.json",
                "result": ledger_integrity(ledger, files, generator_run_id, generator_manifest),
            },
            {
                "name": "bulk_runs_without_manifest",
                "severity": "error",
                "about": "no payments_bulk/ run has data but no _manifest.json",
                "result": runs_without_manifest(ledger, files),
            },
        ] + ledger_checks(ledger, objects)
        if generator_run_id:
            checks += new_run_checks(generator_run_id, ledger.get(generator_run_id))
    except Exception as exc:  # noqa: BLE001 -- any ledger failure fails the suite
        ledger = {}
        checks = [
            {
                "name": "bronze_ledger",
                "severity": "error",
                "about": "the bronze listing and manifests the ledger checks are built on",
                "result": {"violations": None, "detail": f"unreadable: {exc}"[:300]},
            }
        ]
    checks += [dict(c) for c in CHECKS] + ([dict(c) for c in FULL_CHECKS] if full else [])

    for check in checks:
        if "sql" not in check:
            continue
        check["query_id"] = athena.start_query_execution(
            QueryString=check["sql"],
            WorkGroup=WORKGROUP,
            QueryExecutionContext={"Database": DATABASE},
        )["QueryExecutionId"]

    results, scanned = [], 0
    for check in checks:
        if "result" in check:
            result = {"name": check["name"], "severity": check["severity"], "about": check["about"]}
            violations = check["result"]["violations"]
            result.update(check["result"], passed=violations == 0)
            results.append(result)
    pending = [check for check in checks if "sql" in check]
    while pending:
        time.sleep(1)
        for check in list(pending):
            query = athena.get_query_execution(QueryExecutionId=check["query_id"])
            query = query["QueryExecution"]
            state = query["Status"]["State"]
            if state in ("QUEUED", "RUNNING"):
                continue
            pending.remove(check)
            scanned += query["Statistics"].get("DataScannedInBytes", 0)
            result = {"name": check["name"], "severity": check["severity"], "about": check["about"]}
            if state != "SUCCEEDED":
                # A check that can't run is a failure of the suite, not a pass.
                result.update(
                    violations=None,
                    detail=f"{state}: {query['Status'].get('StateChangeReason', '')}"[:300],
                    passed=False,
                )
            else:
                rows = athena.get_query_results(QueryExecutionId=check["query_id"])
                values = [d.get("VarCharValue") for d in rows["ResultSet"]["Rows"][1]["Data"]]
                violations = int(values[0])
                result.update(violations=violations, detail=values[1], passed=violations == 0)
            results.append(result)

    order = {check["name"]: i for i, check in enumerate(checks)}
    results.sort(key=lambda r: order[r["name"]])
    errors = sum(1 for r in results if not r["passed"] and r["severity"] == "error")
    warnings = sum(1 for r in results if not r["passed"] and r["severity"] == "warn")
    return {
        "passed": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "checks": results,
        "bytes_scanned": scanned,
        "seconds": round(time.time() - started, 1),
        "silver_sources": list(SILVER_SOURCES),
        "mode": "full" if full else "ledger",
        "ledger": {
            "runs": len(ledger),
            "events": sum(m["events"] for m in ledger.values()),
            "new_run": generator_run_id,
        },
    }


def print_suite(suite):
    for r in suite["checks"]:
        mark = "ok  " if r["passed"] else ("WARN" if r["severity"] == "warn" else "FAIL")
        print(f"  {mark} {r['name']:30} {str(r['violations']):>8}  {r['detail']}")
    verdict = "PASSED" if suite["passed"] else "FAILED"
    print(
        f"  data quality {verdict}: {suite['errors']} error(s), {suite['warnings']} warning(s), "
        f"{suite['bytes_scanned'] / 1e6:.1f} MB scanned in {suite['seconds']}s"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--generator-run-id")
    parser.add_argument(
        "--generator-manifest",
        nargs="*",
        default=[],
        metavar="dt=COUNT",
        help="the generator's per-dt counts, as printed in its [generate] lines",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="also re-check every bronze key and duplicate (about 49 GB at 19M events) -- "
        "before a milestone, not every run",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()
    manifest = dict(item.split("=", 1) for item in args.generator_manifest)
    suite = run_suite(
        generator_run_id=args.generator_run_id, generator_manifest=manifest, full=args.full
    )
    if args.json:
        print(json.dumps(suite, indent=2))
    else:
        print_suite(suite)
    return 0 if suite["passed"] else 3


if __name__ == "__main__":
    sys.exit(main())
