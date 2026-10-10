"""Cerberus 8.6 -- one-off: write _manifest.json for generator runs made before 8.6.

Since 8.6 generate_bulk_payments.py writes payments_bulk/run_id=<id>/_manifest.json
itself, and the data-quality suite checks bronze as a ledger of those manifests
(data_quality.py's docstring). The three runs written before that have none.

Their per-dt event counts come from their run records in
observability/scale/runs/, and only from a record whose bulk_run_counts check
passed -- the suite verified those counts against the data when the run was
new. Files and bytes come from today's listing: trust on first use, the same
as a manifest the generator writes right after its own write.

Runs as cerberus-admin (cerberus-transform can't write bronze). Dry run by
default; --write writes the manifests, never over an existing one:

    AWS_PROFILE=cerberus-admin uv run --no-project --with boto3 \\
        python observability/scale/backfill_bulk_manifests.py [--write]
"""

import argparse
import json
import pathlib
import sys

import boto3
from data_quality import BRONZE_BUCKET, BULK_PREFIX, MANIFEST, bulk_files, list_bronze

RUNS_DIR = pathlib.Path(__file__).parent / "runs"


def verified_counts():
    """run_id -> (record name, per-dt counts) from records whose manifest check passed."""
    found = {}
    for path in sorted(RUNS_DIR.glob("*.json")):
        record = json.loads(path.read_text())
        generator = record.get("generator") or {}
        checks = (record.get("data_quality") or {}).get("checks", [])
        if any(c["name"] == "bulk_run_counts" and c["passed"] for c in checks):
            found[generator["run_id"]] = (path.name, generator["per_dt"])
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the manifests")
    args = parser.parse_args()

    s3 = boto3.Session(region_name="us-east-1").client("s3")
    objects, manifests = list_bronze(s3)
    files = bulk_files(objects)
    counts = verified_counts()

    missing = 0
    for run_id in sorted({run for run, _ in files} - set(manifests)):
        if run_id not in counts:
            print(f"{run_id}: no run record with a passing bulk_run_counts -- skipped")
            missing += 1
            continue
        record, per_dt = counts[run_id]
        listed = {dt: v for (run, dt), v in files.items() if run == run_id}
        if set(listed) != set(per_dt):
            print(f"{run_id}: listed dt {sorted(listed)} != record dt {sorted(per_dt)} -- skipped")
            missing += 1
            continue
        body = {
            "run_id": run_id,
            "events": sum(int(n) for n in per_dt.values()),
            "per_dt": {dt: {"events": int(n), **listed[dt]} for dt, n in sorted(per_dt.items())},
            "source": f"backfill_bulk_manifests.py from observability/scale/runs/{record}",
        }
        key = f"{BULK_PREFIX}run_id={run_id}/{MANIFEST}"
        print(
            f"{run_id}: {body['events']} events in {len(per_dt)} dt -> s3://{BRONZE_BUCKET}/{key}"
        )
        if args.write:
            s3.put_object(
                Bucket=BRONZE_BUCKET,
                Key=key,
                Body=json.dumps(body, sort_keys=True).encode(),
                ContentType="application/json",
                IfNoneMatch="*",
            )
    if not args.write:
        print("dry run -- pass --write to write")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
