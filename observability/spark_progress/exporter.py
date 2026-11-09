#!/usr/bin/env python3
"""Spark progress exporter (ADR 0022 amendment, step 6c).

A Prometheus multi-target exporter. The agent scrapes
`/probe?target=<driver-ip>:4040`. The exporter reads that driver's Spark
status REST API and returns a few `cerberus_spark_*` series: rows made, rows
read, rows added, the current activity and finished tasks.

Standard library only, Python 3.10 (the apache/spark:3.5.9 image).

Sources: `/api/v1/applications`, then `/applications/<id>/jobs` and
`/applications/<id>/stages`. Not SQL: node metrics are empty while a query
runs (observability/spark_progress/CAPTURE.md).

Generator or silver is decided by the application name that the two scripts
set with `appName(...)`:
  - `cerberus-generate-bulk-payments` -> generator
  - `cerberus-promote-payments`       -> silver
Any other name emits no rows and the activity `waiting`, with the task total.
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GENERATOR_APP = "cerberus-generate-bulk-payments"
SILVER_APP = "cerberus-promote-payments"

FETCH_TIMEOUT_S = 2  # 3 sequential fetches must fit the 10 s scrape_timeout
TARGET_RE = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}$")
COMPACTION_PREFIX = "save at SparkBinPackFileRewriteRunner"
MAINTENANCE_PREFIXES = ("collect at", "collectAsList at")

ACTIVITIES = (
    "creating_payments",
    "saving_files",
    "reading_new_payments",
    "adding_to_clean_table",
    "tidying_files",
    "finishing",
    "waiting",
)


def fetch_json(url, timeout=FETCH_TIMEOUT_S):
    """GET a URL and parse JSON. Raises on any failure."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _latest_attempts(stages):
    """One entry per stageId (the highest attemptId), so retries count once.

    Rows can undercount after a stage retry: Spark re-runs only the missing
    partitions, and the newest attempt holds only those. Unverified; see
    CAPTURE.md, Known limits.
    """
    best = {}
    for s in stages:
        if not isinstance(s, dict) or not isinstance(s.get("stageId"), int):
            continue
        sid = s["stageId"]
        if sid not in best or _int(s.get("attemptId")) >= _int(best[sid].get("attemptId")):
            best[sid] = s
    return best


def compute(apps, jobs, stages):
    """Turn the three REST payloads into (rows, activity, tasks_completed).

    `rows` is a dict row-name -> int. It holds only the rows for the phase.
    Raises ValueError for a payload of the wrong shape.
    """
    if not isinstance(apps, list) or not isinstance(jobs, list) or not isinstance(stages, list):
        raise ValueError("unexpected payload shape")
    stage_by_id = _latest_attempts(stages)
    live = {sid: s for sid, s in stage_by_id.items() if s.get("status") != "SKIPPED"}
    jobs = [j for j in jobs if isinstance(j, dict) and isinstance(j.get("jobId"), int)]

    tasks = sum(_int(s.get("numCompleteTasks")) for s in live.values())
    app_name = apps[0].get("name") if apps and isinstance(apps[0], dict) else None
    running_jobs = [j for j in jobs if j.get("status") == "RUNNING"]

    def is_compaction(s):
        return str(s.get("name", "")).startswith(COMPACTION_PREFIX)

    if app_name == GENERATOR_APP:
        rows = {"payments_created": sum(_int(s.get("outputRecords")) for s in live.values())}
        write_done = any(
            _int(s.get("outputRecords")) > 0 and s.get("status") == "COMPLETE"
            for s in live.values()
        )
        # The count pass (`collect at` jobs) runs after the commit.
        counting = any(str(j.get("name", "")).startswith("collect at") for j in jobs)
        if not write_done:
            activity = "creating_payments"
        elif counting:
            activity = "finishing"
        else:
            activity = "saving_files"
        return rows, activity, tasks

    if app_name != SILVER_APP:
        return {}, "waiting", tasks

    append_jobs = sorted(
        (j for j in jobs if str(j.get("name", "")).startswith("append at")),
        key=lambda j: j["jobId"],
    )
    append_stage_ids = {sid for j in append_jobs for sid in j.get("stageIds") or []}

    # New payments read: the lowest-stageId stage with input records in the
    # first append job. A later run also scans the silver keys with the same
    # stage name, but at a higher stageId (CAPTURE.md, finding 1).
    first_ids = (
        sorted(sid for sid in (append_jobs[0].get("stageIds") or []) if sid in live)
        if (append_jobs)
        else []
    )
    new_read = 0
    for sid in first_ids:
        if _int(live[sid].get("inputRecords")) > 0:
            new_read = _int(live[sid]["inputRecords"])
            break

    # Added to the clean table: the append write stage (output records > 0).
    # Compaction stages carry output records too, so leave them out.
    added = sum(
        _int(s.get("outputRecords"))
        for sid, s in live.items()
        if sid in append_stage_ids and not is_compaction(s) and _int(s.get("outputRecords")) > 0
    )
    rows = {"new_payments_read": new_read, "added_to_clean_table": added}

    write_done = any(
        s.get("status") == "COMPLETE" and _int(s.get("outputRecords")) > 0
        for sid, s in live.items()
        if sid in append_stage_ids and not is_compaction(s)
    )
    active = [s for s in live.values() if s.get("status") == "ACTIVE"]
    tidying = any(is_compaction(s) for s in active) or (
        write_done and any(str(s.get("name", "")).startswith(MAINTENANCE_PREFIXES) for s in active)
    )
    if tidying:
        activity = "tidying_files"
    elif write_done and not running_jobs:
        activity = "finishing"
    else:
        # Reading until the scan stage is done, then adding. With no scan
        # stage yet (start-up, watermark read) it is still reading.
        scan = live.get(first_ids[0]) if first_ids else None
        scan_done = scan is not None and scan.get("status") == "COMPLETE"
        activity = "adding_to_clean_table" if scan_done else "reading_new_payments"
    return rows, activity, tasks


def render(success, rows=None, activity="waiting", tasks=0):
    """Prometheus text format. One fixed set of series."""
    out = [
        "# HELP cerberus_spark_probe_success 1 if the driver status API answered, else 0.",
        "# TYPE cerberus_spark_probe_success gauge",
        f"cerberus_spark_probe_success {1 if success else 0}",
    ]
    if success:
        out += [
            "# HELP cerberus_spark_rows Rows so far, by story row (Spark stage counters).",
            "# TYPE cerberus_spark_rows gauge",
        ]
        out += [f'cerberus_spark_rows{{row="{k}"}} {v}' for k, v in (rows or {}).items()]
        out += [
            "# HELP cerberus_spark_activity What the job is doing now. One series, value 1.",
            "# TYPE cerberus_spark_activity gauge",
            f'cerberus_spark_activity{{activity="{activity}"}} 1',
            "# HELP cerberus_spark_tasks_completed Finished tasks in stages that ran.",
            "# TYPE cerberus_spark_tasks_completed gauge",
            f"cerberus_spark_tasks_completed {tasks}",
        ]
    return "\n".join(out) + "\n"


def probe(target, fetch=fetch_json):
    """Probe one driver. Never raises: any failure gives probe_success 0.

    No application yet (driver up, Spark not registered) is a success with
    activity `waiting`.
    """
    try:
        base = f"http://{target}/api/v1/applications"
        apps = fetch(base)
        if not isinstance(apps, list):
            raise ValueError("applications is not a list")
        if not apps:
            return render(True, {}, "waiting", 0)
        app_id = urllib.parse.quote(str(apps[0]["id"]), safe="")
        jobs = fetch(f"{base}/{app_id}/jobs")
        stages = fetch(f"{base}/{app_id}/stages")
        rows, activity, tasks = compute(apps, jobs, stages)
        return render(True, rows, activity, tasks)
    except Exception as exc:  # noqa: BLE001 -- a probe must never crash the server
        print(f"probe {target!r} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return render(False)


class Handler(BaseHTTPRequestHandler):
    fetch = staticmethod(fetch_json)

    def _send(self, code, body, ctype="text/plain; version=0.0.4; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 -- http.server API
        url = urllib.parse.urlparse(self.path)
        if url.path == "/healthz":
            self._send(200, "ok\n")
        elif url.path == "/probe":
            target = urllib.parse.parse_qs(url.query).get("target", [""])[0]
            if not TARGET_RE.match(target):
                self._send(400, "missing or bad target\n")
            else:
                self._send(200, probe(target, self.fetch))
        else:
            self._send(404, "not found\n")

    def log_message(self, fmt, *args):
        pass


def main(port=9101):
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 9101)
