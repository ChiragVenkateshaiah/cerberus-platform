"""17.5: the downloads silver job on a real Spark, in the pinned throwaway container.

Gated on RUN_SPARK_DOCKER=1 (orchestration/verify.sh --full sets it). It runs
promote_downloads_spark.py in apache/spark:3.5.9 against a Hadoop catalog and
local directories, with the 10k sample as bronze, then asserts:

1. the first load adds every sample event;
2. a second run with no new manifest changes nothing;
3. a re-run (the manifest rewritten) re-reads the run and adds 0 rows;
4. a second run_id over the same days adds only its own rows;
5. a third run_id that repeats the first run's events and adds new ones adds
   only the new ones (the anti-join compares with earlier runs of the days);
6. a late manifest (older than the watermark) of a never-promoted run is taken,
   and is not taken again;
7. an event with an unparseable timestamp fails the job and appends nothing.

The container is removed on exit (--rm) and has no AWS credentials. It needs
network to resolve the Iceberg package from Maven Central once; the Ivy cache
is a host directory shared by the runs. No AWS call is made.
"""

import gzip
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SPARK_DOCKER") != "1", reason="set RUN_SPARK_DOCKER=1 (needs Docker)"
)

SPARK_DIR = Path(__file__).resolve().parents[1]
SAMPLE = SPARK_DIR.parents[1] / "data" / "samples" / "downloads" / "sample_10k.jsonl.gz"
IMAGE = "apache/spark:3.5.9"
ICEBERG = "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.2"
NOW = "2026-11-22T06:00:00Z"


def write_run(root, run_id, events):
    """Lay events out as the generator does: dt=<day>/part-*.json, manifest last."""
    run_dir = root / "downloads_bulk" / f"run_id={run_id}"
    by_day = {}
    for event in events:
        by_day.setdefault(event["occurred_at"][:10], []).append(event)
    for day, rows in by_day.items():
        part = run_dir / f"dt={day}"
        part.mkdir(parents=True)
        (part / "part-00000.json").write_text(
            "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
        )
    write_manifest(run_dir, run_id, len(events))
    return set(by_day)


def write_manifest(run_dir, run_id, count):
    time.sleep(1.1)  # file times must move forward past the last watermark
    (run_dir / "_manifest.json").write_text(json.dumps({"run_id": run_id, "events": count}))


def sample_events():
    with gzip.open(SAMPLE, "rt") as handle:
        return [json.loads(line) for line in handle]


def local_events(run_id, tmp_path):
    out = tmp_path / f"{run_id}.jsonl.gz"
    subprocess.run(
        [
            sys.executable,
            str(SPARK_DIR / "generate_bulk_downloads.py"),
            *["--run-id", run_id, "--events", "10000", "--now", NOW, "--local", str(out)],
        ],
        check=True,
        capture_output=True,
    )
    with gzip.open(out, "rt") as handle:
        return [json.loads(line) for line in handle]


class Promote:
    def __init__(self, tmp_path):
        self.work = tmp_path / "work"
        self.bronze = self.work / "bronze"
        self.warehouse = self.work / "warehouse"
        self.ivy = self.work / "ivy"
        for path in (self.work, self.bronze, self.warehouse, self.ivy):
            path.mkdir(exist_ok=True)
            path.chmod(0o777)  # the container's user is not the host user

    def run(self, fails=False):
        command = [
            "docker", "run", "--rm",
            "-v", f"{SPARK_DIR}:/job:ro",
            "-v", f"{self.work}:/work",
            IMAGE,
            # umask 000: the container's user is not the host user, and the host
            # must be able to delete what the job wrote.
            "bash", "-c", 'umask 000 && exec /opt/spark/bin/spark-submit "$@"', "_",
            "--packages", ICEBERG,
            "--conf", "spark.jars.ivy=/work/ivy",
            "/job/promote_downloads_spark.py",
            "--catalog-type", "hadoop",
            "--bronze-root", "file:///work/bronze/",
            "--warehouse", "file:///work/warehouse/",
            "--skip-maintenance",
        ]  # fmt: skip
        done = subprocess.run(command, capture_output=True, text=True, timeout=900)
        # Java creates some directories as 755 whatever the umask: open them up so
        # pytest can remove the temporary directory.
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{self.work}:/work", IMAGE,
             "chmod", "-R", "a+rwX", "/work"],
            capture_output=True,
        )  # fmt: skip
        output = done.stdout + done.stderr
        if fails:
            assert done.returncode != 0, output[-3000:]
        else:
            assert done.returncode == 0, output[-3000:]
        return output


def appended(output):
    match = re.search(r"appended (\d+) new events \(silver now (\d+)\)", output)
    assert match, output[-3000:]
    return int(match.group(1)), int(match.group(2))


def test_load_rerun_and_second_run(tmp_path):
    job = Promote(tmp_path)
    first = sample_events()
    assert len(first) > 9000
    first_days = write_run(job.bronze, "sample-v1", first)

    added, total = appended(job.run())
    assert (added, total) == (len(first), len(first))

    # 2. nothing new: no commit at all.
    assert "nothing new in bronze" in job.run()

    # 3. the generator's re-run rewrites the manifest: the run is read again, 0 rows added.
    write_manifest(job.bronze / "downloads_bulk" / "run_id=sample-v1", "sample-v1", len(first))
    assert appended(job.run()) == (0, len(first))

    # 4. a second run_id over the same days adds only its own rows.
    second = local_events("sample-v2", tmp_path)
    second_days = write_run(job.bronze, "sample-v2", second)
    assert first_days & second_days
    assert {e["event_id"] for e in first}.isdisjoint({e["event_id"] for e in second})
    added, total = appended(job.run())
    assert (added, total) == (len(second), len(first) + len(second))

    # 5. a run that repeats run 1's events and adds new ones adds only the new ones.
    third = local_events("sample-v3", tmp_path)
    write_run(job.bronze, "dup-v1", first + third)
    added, total = appended(job.run())
    assert (added, total) == (len(third), len(first) + len(second) + len(third))

    # 6. a late manifest: older than the watermark, run not in silver yet.
    late = local_events("late-v1", tmp_path)
    write_run(job.bronze, "late-v1", late)
    manifest = job.bronze / "downloads_bulk" / "run_id=late-v1" / "_manifest.json"
    older = time.time() - 3600
    os.utime(manifest, (older, older))
    before = len(first) + len(second) + len(third)
    assert appended(job.run()) == (len(late), before + len(late))
    assert "nothing new in bronze" in job.run()

    # 7. a null timestamp stops the job before the append; silver stays as it was.
    bad = dict(local_events("bad-v1", tmp_path)[0], occurred_at="2026-11-19Tgarbage")
    write_run(job.bronze, "bad-v1", [bad])
    assert "refusing to append: null occurred_at" in job.run(fails=True)
