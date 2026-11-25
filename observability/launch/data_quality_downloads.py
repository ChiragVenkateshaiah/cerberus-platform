"""Cerberus 17.5 -- the data-quality suite for the downloads family, as Athena queries.

Ten checks over one launch-exercise run, fail-closed (ADR 0030): a query that
cannot run, a manifest that cannot be read, a run with zero events and a table
that is missing all count as a FAIL, never a pass. Exit code 0 = no check
failed, 3 = a check failed (the same code the payments suite uses). Checks 8
and 9 are WARNINGS (ADR 0030 Decision 13): they show a distinct status
("warning", "partial", "unknown", "skipped"), are never counted as a plain
pass and do not change the exit code. Only a record or query that cannot be
read is a FAIL.

    1. bronze_to_silver_count     manifest events = bronze = silver, per day of the run
    2. event_id_unique            no event_id appears twice in silver
    3. lifecycle_valid            known event types; no install without licence and
                                  patch; nothing after `abandoned`
    4. bytes_in_range             0 <= bytes <= 212 * 10**9 (the title size)
    5. timestamps_in_window       occurred_at inside the window, occurred_at <= ingested_at
    6. no_license_before_release  no license_granted before the region's local release
    7. gold_sessions_match_silver fct_download_sessions rows = silver distinct (run, client)
    8. cdn_logs_present           WARNING: every launch run record that says CDN logs
                                  were collected has rows in fct_cdn_requests; with no
                                  such record it reports "skipped, telemetry only"
                                  (never a silent pass)
    9. cdn_logs_complete          WARNING: distinct x-edge-request-id rows per collected
                                  run versus the integer `k6_requests` in its run record;
                                  below 99% the status is "partial", a missing count is
                                  "unknown" (labelled partial, never "complete")
   10. no_account_or_arn_in_outputs  no 12-digit account number or ARN in the run records,
                                  exercise logs or this suite's own result text

Runs as cerberus-transform (Athena workgroup cerberus_platform_dq, bronze read for
the manifest), with no cluster:

    uv run --no-project --with boto3 python observability/launch/data_quality_downloads.py \\
        --run-id RUN_ID --bronze-bucket BUCKET [--json-out PATH]

bronze_downloads_bulk_by_run has injected partition projection, so every query on it
gives equality on both run_id and dt: one query per day, with the days from the
manifest. Checks that need ingested_at, client_id or event_family use silver.

A launch run record is observability/launch/runs/<run_id>/run.json (the layout 17.4's
launch_session.sh writes; launch_exercise.sh writes its record there too). This suite
reads two keys: `cdn_logs_collected`, which 17.4's launch_collect.sh sets to true after
its manifest upload (a missing key means not collected), and `k6_requests`, the integer
request count 17.4 writes (a missing or non-positive-integer value means "unknown").
An unreadable record, or a `cdn_logs_collected` that is not a JSON boolean, is a FAIL
(fail closed). dbt shows the same label in fct_cdn_run.logs_status (launch_exercise.sh
passes the counts as the dbt var `k6_requests_by_run`).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

REGION = "us-east-1"
WORKGROUP = "cerberus_platform_dq"
DATABASE = "cerberus_platform"
QUERY_PROFILE = "cerberus-transform"
MANIFEST = "_manifest.json"
BULK_PREFIX = "downloads_bulk/"

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ACCOUNT_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
ARN_RE = re.compile(r"arn:aws[a-z-]*:")

# The generator's constants (generate_bulk_downloads.py; a test compares them).
THRESHOLD_PCT = 99  # ADR 0030 Decision 13: below 99% the CDN marts are labelled partial
WARNING_CHECKS = {"cdn_logs_present", "cdn_logs_complete"}
TITLE_BYTES = 212 * 10**9
WINDOW_START = "2026-11-10 00:00:00"
WINDOW_END = "2026-11-22 00:00:00"
RELEASE_UTC = "2026-11-19 00:00:00"
EVENT_TYPES = (
    "preload_started chunk_completed stalled retried preload_completed license_requested "
    "license_granted patch_started patch_completed install_completed abandoned"
).split()

REPO = Path(__file__).resolve().parents[2]
DEFAULT_RECORDS = REPO / "observability" / "launch" / "runs"
DEFAULT_SCAN = [DEFAULT_RECORDS, REPO / "observability" / "launch" / "exercises"]
SCAN_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt", ".csv", ".html"}


def sql_list(items):
    return ", ".join("'" + item + "'" for item in items)


def silver_checks(run_id):
    """The checks that are one query each, over silver (and gold for check 7)."""
    types = sql_list(EVENT_TYPES)
    return [
        {
            "name": "event_id_unique",
            "about": "event_id is unique in silver (ADR 0030 Decision 7's key)",
            "sqls": [
                """/* check:event_id_unique */
SELECT coalesce(sum(n - 1), 0) AS violations,
       cast(count(*) AS varchar) || ' duplicated event_ids' AS detail
FROM (SELECT count(*) AS n FROM download_events GROUP BY event_id HAVING count(*) > 1)"""
            ],
        },
        {
            "name": "lifecycle_valid",
            "about": "known event types; no install without a licence and a patch; "
            "no event after abandoned",
            "sqls": [
                f"""/* check:lifecycle_valid */
WITH c AS (
    SELECT client_id,
           min(CASE WHEN event_type = 'license_granted' THEN occurred_at END) AS lic,
           min(CASE WHEN event_type = 'patch_started' THEN occurred_at END) AS patch_s,
           min(CASE WHEN event_type = 'patch_completed' THEN occurred_at END) AS patch_c,
           min(CASE WHEN event_type = 'install_completed' THEN occurred_at END) AS inst,
           min(CASE WHEN event_type = 'abandoned' THEN occurred_at END) AS aband,
           max(occurred_at) AS last_at,
           count_if(event_type IS NULL OR event_type NOT IN ({types})) AS unknown_types
    FROM download_events WHERE run_id = '{run_id}' GROUP BY client_id
)
SELECT count_if(
           unknown_types > 0
           OR (inst IS NOT NULL AND (lic IS NULL OR patch_c IS NULL))
           OR (patch_s IS NOT NULL AND lic IS NULL)
           OR (aband IS NOT NULL AND last_at > aband)
       ) AS violations,
       cast(count(*) AS varchar) || ' clients, '
       || cast(sum(unknown_types) AS varchar) || ' unknown event types' AS detail
FROM c"""
            ],
        },
        {
            "name": "bytes_in_range",
            "about": f"bytes is between 0 and {TITLE_BYTES // 10**9} GB (the title size)",
            "sqls": [
                f"""/* check:bytes_in_range */
SELECT count_if(bytes IS NULL OR bytes < 0 OR bytes > {TITLE_BYTES}) AS violations,
       cast(count(*) AS varchar) || ' events checked' AS detail
FROM download_events WHERE run_id = '{run_id}'"""
            ],
        },
        {
            "name": "timestamps_in_window",
            "about": "occurred_at is inside the window and not after ingested_at",
            "sqls": [
                f"""/* check:timestamps_in_window */
SELECT count_if(
           occurred_at IS NULL OR ingested_at IS NULL
           OR occurred_at < TIMESTAMP '{WINDOW_START}' OR occurred_at >= TIMESTAMP '{WINDOW_END}'
           OR occurred_at > ingested_at
       ) AS violations,
       cast(count(*) AS varchar) || ' events checked' AS detail
FROM download_events WHERE run_id = '{run_id}'"""
            ],
        },
        {
            "name": "no_license_before_release",
            "about": "no license_granted before the region's local release (00:00 local)",
            "sqls": [
                f"""/* check:no_license_before_release */
SELECT count_if(
           coalesce(
               occurred_at < date_add(
                   'hour', -(try_cast(substr(region, 8) AS integer) - 12),
                   TIMESTAMP '{RELEASE_UTC}'),
               true)
       ) AS violations,
       cast(count(*) AS varchar) || ' licences checked' AS detail
FROM download_events WHERE run_id = '{run_id}' AND event_type = 'license_granted'"""
            ],
        },
        {
            "name": "gold_sessions_match_silver",
            "about": "fct_download_sessions has one row per silver (run_id, client_id)",
            "sqls": [
                f"""/* check:gold_sessions_match_silver */
SELECT abs(g.n - s.n) + if(s.n = 0, 1, 0) AS violations,
       'gold ' || cast(g.n AS varchar) || ', silver ' || cast(s.n AS varchar) AS detail
FROM (SELECT count(*) AS n FROM fct_download_sessions WHERE run_id = '{run_id}') g,
     (SELECT count(*) AS n FROM (
          SELECT DISTINCT run_id, client_id FROM download_events WHERE run_id = '{run_id}')) s"""
            ],
        },
    ]


def count_check(run_id, manifest):
    """Check 1: one query per day, each pinning run_id and dt (injected projection)."""
    per_dt = manifest.get("per_dt") if isinstance(manifest, dict) else None
    if not isinstance(per_dt, dict) or not per_dt:
        return {
            "name": "bronze_to_silver_count",
            "about": "manifest, bronze and silver counts per day",
            "result": {"violations": None, "detail": "manifest has no per_dt: zero days found"},
        }
    sqls = []
    for dt, entry in sorted(per_dt.items()):
        want = entry.get("events") if isinstance(entry, dict) else None
        if not DAY_RE.match(dt) or not isinstance(want, int) or want <= 0:
            return {
                "name": "bronze_to_silver_count",
                "about": "manifest, bronze and silver counts per day",
                "result": {"violations": None, "detail": f"bad manifest entry for dt={dt!r}"},
            }
        sqls.append(
            f"""/* check:bronze_to_silver_count */
SELECT abs({want} - b.n) + abs({want} - s.n) AS violations,
       'dt={dt}: manifest {want}, bronze ' || cast(b.n AS varchar)
       || ', silver ' || cast(s.n AS varchar) AS detail
FROM (SELECT count(*) AS n FROM bronze_downloads_bulk_by_run
      WHERE run_id = '{run_id}' AND dt = '{dt}') b,
     (SELECT count(*) AS n FROM download_events
      WHERE run_id = '{run_id}'
        AND occurred_at >= TIMESTAMP '{dt} 00:00:00'
        AND occurred_at < TIMESTAMP '{dt} 00:00:00' + INTERVAL '1' DAY) s"""
        )
    return {
        "name": "bronze_to_silver_count",
        "about": "manifest, bronze and silver counts per day",
        "sqls": sqls,
    }


def read_manifest(s3, bucket, run_id):
    body = s3.get_object(Bucket=bucket, Key=f"{BULK_PREFIX}run_id={run_id}/{MANIFEST}")["Body"]
    return json.loads(body.read())


def collected_runs(records_dir):
    """({run_id: k6_requests or None} for records that say CDN logs were collected,
    problems reading records). k6_requests is None unless a positive integer."""
    runs, problems = {}, []
    directory = Path(records_dir)
    if not directory.is_dir():
        return runs, problems
    for path in sorted(directory.glob("*/run.json")):
        name = f"{path.parent.name}/{path.name}"
        try:
            record = json.loads(path.read_text())
            if not isinstance(record, dict):
                raise ValueError("not an object")
            collected = record.get("cdn_logs_collected", False)
            if not isinstance(collected, bool):
                raise ValueError("cdn_logs_collected is not a boolean")
            if collected:
                run_id = record.get("run_id")
                if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
                    raise ValueError("cdn_logs_collected without a valid run_id")
                k6 = record.get("k6_requests")
                valid = isinstance(k6, int) and not isinstance(k6, bool) and k6 > 0
                runs[run_id] = k6 if valid else None
        except (OSError, ValueError) as exc:
            problems.append(f"{name}: {exc}")
    return runs, problems


def cdn_check(records_dir):
    runs, problems = collected_runs(records_dir)
    about = "every run record that says CDN logs were collected has rows in fct_cdn_requests"
    if problems:
        return {
            "name": "cdn_logs_present",
            "about": about,
            "result": {"violations": None, "detail": "unreadable record: " + "; ".join(problems)},
        }
    if not runs:
        return {
            "name": "cdn_logs_present",
            "about": about,
            "result": {"violations": 0, "detail": "skipped, telemetry only", "skipped": True},
        }
    values = ", ".join(f"('{run}')" for run in sorted(runs))
    return {
        "name": "cdn_logs_present",
        "about": about,
        "sqls": [
            f"""/* check:cdn_logs_present */
SELECT count_if(n = 0) AS violations,
       cast(count(*) AS varchar) || ' collected runs, '
       || cast(count_if(n = 0) AS varchar) || ' with no rows' AS detail
FROM (SELECT r.run_id, count(c.request_id) AS n
      FROM (VALUES {values}) AS r (run_id)
      LEFT JOIN fct_cdn_requests c ON c.run_id = r.run_id GROUP BY r.run_id)"""
        ],
    }


def complete_check(records_dir):
    """Check 9: distinct x-edge-request-id rows per run versus k6_requests (>= 99%)."""
    runs, problems = collected_runs(records_dir)
    about = "CDN log lines per run versus the k6 request count (99% = complete)"
    name = "cdn_logs_complete"
    if problems:
        detail = "unreadable record: " + "; ".join(problems)
        return {"name": name, "about": about, "result": {"violations": None, "detail": detail}}
    if not runs:
        return {
            "name": name,
            "about": about,
            "result": {"violations": 0, "detail": "skipped, telemetry only", "skipped": True},
        }
    unknown = sorted(run for run, k6 in runs.items() if k6 is None)
    sqls = [
        f"""/* check:cdn_logs_complete */
SELECT if(count(DISTINCT request_id) * 100 < {THRESHOLD_PCT} * {k6}, 1, 0) AS violations,
       '{run}: ' || cast(count(DISTINCT request_id) AS varchar)
       || ' log lines of {k6} k6 requests' AS detail
FROM fct_cdn_requests WHERE run_id = '{run}'"""
        for run, k6 in sorted(runs.items())
        if k6 is not None
    ]
    check = {"name": name, "about": about, "unknown_runs": unknown}
    if sqls:
        check["sqls"] = sqls
    else:
        detail = f"unknown: no k6_requests in the record of {', '.join(unknown)}"
        check["result"] = {"violations": 0, "detail": detail}
    return check


def scan_text(text):
    hits = ACCOUNT_RE.findall(text) + ARN_RE.findall(text)
    return len(hits)


def scan_check(paths, explicit, results_text):
    """Check 9: files under `paths` plus the suite's own result text."""
    about = "no 12-digit account number or ARN in run records, exercise logs or results"
    files, problems = [], []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files += [p for p in sorted(path.rglob("*")) if p.suffix in SCAN_SUFFIXES]
        elif path.is_file():
            files.append(path)
        elif raw in explicit:
            problems.append(f"{path} does not exist")
    bad = scan_text(results_text)
    for path in files:
        try:
            bad += scan_text(path.read_text(errors="replace"))
        except OSError as exc:
            problems.append(f"{path.name}: {exc}")
    if problems or not files:
        detail = "; ".join(problems) if problems else "no output files found to scan"
        return {
            "name": "no_account_or_arn_in_outputs",
            "about": about,
            "result": {"violations": None, "detail": detail},
        }
    return {
        "name": "no_account_or_arn_in_outputs",
        "about": about,
        "result": {"violations": bad, "detail": f"{len(files)} files scanned, {bad} matches"},
    }


def run_queries(athena, checks, poll_seconds=1.0):
    """Start every SQL of every check, poll them all, and fill check['result']."""
    pending = []
    for check in checks:
        if "sqls" not in check:
            continue
        check["_parts"] = []
        for sql in check["sqls"]:
            part = {"sql": sql}
            try:
                part["query_id"] = athena.start_query_execution(
                    QueryString=sql,
                    WorkGroup=WORKGROUP,
                    QueryExecutionContext={"Database": DATABASE},
                )["QueryExecutionId"]
                pending.append(part)
            except Exception as exc:  # noqa: BLE001 -- a query that cannot start is a failure
                part["error"] = f"cannot start: {exc}"[:300]
            check["_parts"].append(part)
    scanned = 0
    while pending:
        time.sleep(poll_seconds)
        for part in list(pending):
            try:
                query = athena.get_query_execution(QueryExecutionId=part["query_id"])
                query = query["QueryExecution"]
                state = query["Status"]["State"]
                if state in ("QUEUED", "RUNNING"):
                    continue
                scanned += query.get("Statistics", {}).get("DataScannedInBytes", 0)
                if state != "SUCCEEDED":
                    reason = query["Status"].get("StateChangeReason", "")
                    part["error"] = f"{state}: {reason}"[:300]
                else:
                    rows = athena.get_query_results(QueryExecutionId=part["query_id"])
                    data = rows["ResultSet"]["Rows"][1]["Data"]
                    part["violations"] = int(data[0]["VarCharValue"])
                    part["detail"] = data[1].get("VarCharValue", "")
            except Exception as exc:  # noqa: BLE001 -- unreadable result is a failure
                part["error"] = f"unreadable result: {exc}"[:300]
            pending.remove(part)
    for check in checks:
        parts = check.pop("_parts", None)
        if parts is None:
            continue
        errors = [p["error"] for p in parts if "error" in p]
        if errors:
            check["result"] = {"violations": None, "detail": errors[0]}
        else:
            total = sum(p["violations"] for p in parts)
            detail = "; ".join(p["detail"] for p in parts)
            check["result"] = {"violations": total, "detail": detail[:300]}
    return scanned


def entry_for(check):
    """One result row. status: pass, fail, skipped, warning, partial or unknown.

    An unreadable result (violations None) is always a fail. Of the warning checks
    only a real finding is a warning: it is not a pass and not a fail."""
    result = check["result"]
    name, violations = check["name"], result["violations"]
    entry = {"name": name, "severity": "error", "about": check["about"], **result}
    if violations is None:
        status = "fail"
    elif result.get("skipped"):
        status = "skipped"
    elif name == "cdn_logs_complete":
        if violations > 0:
            status = "partial"
        elif check.get("unknown_runs"):
            status = "unknown"
        else:
            status = "complete"
    elif violations == 0:
        status = "pass"
    elif name in WARNING_CHECKS:
        status = "warning"
    else:
        status = "fail"
    if name in WARNING_CHECKS:
        entry["severity"] = "warning"
        if violations is None:
            entry["severity"] = "error"
        if status == "unknown" and check.get("unknown_runs"):
            entry["detail"] = (
                f"{entry['detail']}; unknown (no k6_requests): " + ", ".join(check["unknown_runs"])
            )[:300]
    entry.update(status=status, passed=status in ("pass", "complete", "skipped"))
    return entry


def run_suite(
    session,
    run_id,
    bronze_bucket,
    records_dir=DEFAULT_RECORDS,
    scan_paths=None,
    explicit_scan=(),
    poll_seconds=1.0,
):
    started = time.time()
    if not RUN_ID_RE.match(run_id or ""):
        raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    athena = session.client("athena")
    s3 = session.client("s3")
    try:
        manifest = read_manifest(s3, bronze_bucket, run_id)
    except Exception as exc:  # noqa: BLE001 -- an unreadable manifest fails check 1
        manifest = None
        manifest_error = f"manifest unreadable: {exc}"[:300]
    first = count_check(run_id, manifest)
    if manifest is None:
        first["result"] = {"violations": None, "detail": manifest_error}
    checks = [first] + silver_checks(run_id) + [cdn_check(records_dir), complete_check(records_dir)]
    # Gold check 7 sits after the silver checks in the printed order; keep the plan's order.
    order = [
        "bronze_to_silver_count",
        "event_id_unique",
        "lifecycle_valid",
        "bytes_in_range",
        "timestamps_in_window",
        "no_license_before_release",
        "gold_sessions_match_silver",
        "cdn_logs_present",
        "cdn_logs_complete",
    ]
    checks.sort(key=lambda c: order.index(c["name"]))
    scanned = run_queries(athena, [c for c in checks if "result" not in c], poll_seconds)

    results = []
    for check in checks:
        results.append(entry_for(check))
    text = json.dumps(results)
    paths = DEFAULT_SCAN if scan_paths is None else scan_paths
    last = scan_check([str(p) for p in paths], set(explicit_scan), text)
    results.append(entry_for(last))
    errors = sum(1 for r in results if r["status"] == "fail")
    warnings = sum(1 for r in results if r["status"] in ("warning", "partial", "unknown"))
    return {
        "passed": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "checks": results,
        "run_id": run_id,
        "bytes_scanned": scanned,
        "seconds": round(time.time() - started, 1),
    }


def print_suite(suite):
    for r in suite["checks"]:
        marks = {"pass": "ok  ", "complete": "ok  ", "skipped": "skip", "fail": "FAIL"}
        mark = marks.get(r["status"], "WARN")
        print(f"  {mark} {r['name']:30} {str(r['violations']):>8}  {r['detail']}")
    verdict = "PASSED" if suite["passed"] else "FAILED"
    print(
        f"  downloads data quality {verdict}: {suite['errors']} error(s), "
        f"{suite['warnings']} warning(s), "
        f"{suite['bytes_scanned'] / 1e6:.1f} MB scanned in {suite['seconds']}s"
    )


def main(argv=None, session=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--bronze-bucket", required=True, help="read at runtime, never committed")
    parser.add_argument("--records-dir", default=str(DEFAULT_RECORDS))
    parser.add_argument(
        "--scan", action="append", default=None, help="a file or directory for check 9 (repeat)"
    )
    parser.add_argument("--json-out", help="write the result here (it is scanned first)")
    args = parser.parse_args(argv)
    if session is None:
        import boto3

        session = boto3.Session(profile_name=QUERY_PROFILE, region_name=REGION)
    try:
        suite = run_suite(
            session,
            args.run_id,
            args.bronze_bucket,
            records_dir=args.records_dir,
            scan_paths=args.scan,
            explicit_scan=args.scan or (),
        )
    except Exception as exc:  # noqa: BLE001 -- fail closed on anything unexpected
        print(f"  FAIL suite could not run: {exc}", file=sys.stderr)
        return 3
    print_suite(suite)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(suite, indent=2) + "\n")
    return 0 if suite["passed"] else 3


if __name__ == "__main__":
    sys.exit(main())
