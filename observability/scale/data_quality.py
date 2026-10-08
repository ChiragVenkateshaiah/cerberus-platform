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
        [--generator-run-id ID --generator-manifest dt=COUNT ...]

All queries start at once and are polled together, so the suite takes about
as long as its slowest query.

Since 8.5 silver is an incremental Iceberg table built from both bronze
prefixes, so bronze -> silver reconciles `payments/` and `payments_bulk/`
together, and `silver_caught_up` checks that no bronze object is newer than
the watermark in silver's own snapshots. `payments_bulk/` keeps its own
per-run manifest and duplicate checks too.
"""

import argparse
import json
import sys
import time

import boto3

REGION = "us-east-1"
WORKGROUP = "cerberus_platform"
DATABASE = "cerberus_platform"
QUERY_PROFILE = "cerberus-transform"

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
        "name": "bronze_to_silver_count",
        "severity": "error",
        "about": "silver holds exactly as many events as bronze, both prefixes (no bronze key "
        "repeats, so the job's dedup removes nothing)",
        "sql": f"""
WITH {BRONZE_PAYMENTS}
SELECT abs(b.n - s.n) AS violations,
       'bronze ' || cast(b.n AS varchar) || ', silver ' || cast(s.n AS varchar) AS detail
FROM (SELECT count(*) AS n FROM bronze_payments) b,
     (SELECT count(*) AS n FROM payments_events) s""",
    },
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
        "name": "silver_caught_up",
        "severity": "error",
        "about": "no bronze object is newer than the bronze watermark in silver's snapshots "
        "(the incremental job missed nothing)",
        "sql": """
WITH watermark AS (
    SELECT max(CAST(summary['cerberus.bronze_watermark'] AS bigint)) AS ms
    FROM "payments_events$snapshots"
),
bronze_files AS (
    SELECT DISTINCT "$path" AS path, to_unixtime("$file_modified_time") * 1000 AS ms
    FROM bronze_payments_raw
    UNION ALL
    SELECT DISTINCT "$path", to_unixtime("$file_modified_time") * 1000 FROM bronze_payments_bulk
)
SELECT count_if(b.ms > coalesce(w.ms, -1)) AS violations,
       'watermark ' || coalesce(cast(from_unixtime(w.ms / 1000) AS varchar), 'none') AS detail
FROM bronze_files b CROSS JOIN watermark w""",
    },
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
    # --- payments_bulk/ (ADR 0018): its own checks, on top of the reconciliation -
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


def bulk_run_check(run_id, manifest):
    """Per-dt event counts for one generator run against its [generate] manifest."""
    expected = " UNION ALL ".join(
        f"SELECT '{dt}' AS dt, {int(count)} AS n" for dt, count in sorted(manifest.items())
    )
    return {
        "name": "bulk_run_counts",
        "severity": "error",
        "about": f"payments_bulk/run_id={run_id}/ holds exactly the generator's per-dt counts",
        "sql": f"""
WITH expected AS ({expected}),
actual AS (
    SELECT regexp_extract("$path", 'dt=([0-9-]{{10}})', 1) AS dt, count(*) AS n
    FROM bronze_payments_bulk
    WHERE "$path" LIKE '%/run_id={run_id}/%'
    GROUP BY 1
)
SELECT count_if(coalesce(e.n, -1) <> coalesce(a.n, -1)) AS violations,
       cast(coalesce(sum(a.n), 0) AS varchar) || ' written, '
       || cast(coalesce(sum(e.n), 0) AS varchar) || ' in the manifest' AS detail
FROM expected e FULL OUTER JOIN actual a ON e.dt = a.dt""",
    }


def run_suite(session=None, generator_run_id=None, generator_manifest=None):
    session = session or boto3.Session(profile_name=QUERY_PROFILE, region_name=REGION)
    athena = session.client("athena")
    checks = list(CHECKS)
    if generator_run_id and generator_manifest:
        checks.append(bulk_run_check(generator_run_id, generator_manifest))

    started = time.time()
    for check in checks:
        check["query_id"] = athena.start_query_execution(
            QueryString=check["sql"],
            WorkGroup=WORKGROUP,
            QueryExecutionContext={"Database": DATABASE},
        )["QueryExecutionId"]

    results, scanned = [], 0
    pending = list(checks)
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
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()
    manifest = dict(item.split("=", 1) for item in args.generator_manifest)
    suite = run_suite(generator_run_id=args.generator_run_id, generator_manifest=manifest)
    if args.json:
        print(json.dumps(suite, indent=2))
    else:
        print_suite(suite)
    return 0 if suite["passed"] else 3


if __name__ == "__main__":
    sys.exit(main())
