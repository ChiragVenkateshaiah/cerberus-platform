"""17.5: submit_job.sh renders the payments job exactly as before (binding correction 8).

aws, kubectl, terraform and sleep are stubs on PATH, so nothing reaches AWS.
Set SUBMIT_JOB_BASELINE to a copy of the pre-17.5 script (for example
`git show origin/main:transform/spark/submit_job.sh`) to compare the two
byte for byte; without it the test compares with the rendering the YAML implies.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SPARK_DIR = Path(__file__).resolve().parents[1]
BASELINE = os.environ.get("SUBMIT_JOB_BASELINE")

AWS_STUB = '#!/usr/bin/env bash\necho "aws $*" >>"$STUB_LOG"\n'
KUBECTL_STUB = """#!/usr/bin/env bash
echo "kubectl $*" >>"$STUB_LOG"
if [[ "$1" == apply ]]; then cp "$3" "$STUB_OUT/manifest.yaml"; fi
if [[ "$1" == get ]]; then echo COMPLETED; fi
"""
QUIET_STUB = '#!/usr/bin/env bash\necho "$(basename "$0") $*" >>"$STUB_LOG"\n'


def stub_dir(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("aws", AWS_STUB),
        ("kubectl", KUBECTL_STUB),
        ("terraform", QUIET_STUB),
        ("sleep", QUIET_STUB),
    ):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_script(script, tmp_path, env_extra):
    """Run a copy of `script` next to copies of the job files; return (manifest, calls)."""
    work = tmp_path / "spark"
    work.mkdir()
    for name in (
        "spark-application.yaml",
        "spark-application-promote-downloads.yaml",
        "promote_payments_spark.py",
        "promote_downloads_spark.py",
    ):
        shutil.copy(SPARK_DIR / name, work / name)
    shutil.copy(script, work / "submit_job.sh")
    out = tmp_path / "out"
    out.mkdir()
    env = {
        "PATH": f"{stub_dir(tmp_path)}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "STUB_LOG": str(tmp_path / "calls.log"),
        "STUB_OUT": str(out),
        **env_extra,
    }
    done = subprocess.run(
        ["bash", str(work / "submit_job.sh")], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr + done.stdout
    calls = (tmp_path / "calls.log").read_text()
    calls = re.sub(r"/tmp/tmp\.\w+|/[\w/.-]*/tmp\.\w+", "<MANIFEST>", calls)
    calls = calls.replace(str(work), "<DIR>")
    return (out / "manifest.yaml").read_bytes(), calls


def expected(url):
    text = (SPARK_DIR / "spark-application.yaml").read_text()
    if url:
        return text.replace("__OPENLINEAGE_URL__", url).encode()
    lines = [
        line
        for line in text.splitlines(keepends=True)
        if "spark.openlineage.transport.url:" not in line
    ]
    return (
        "".join(lines)
        .replace(
            'spark.openlineage.transport.type: "http"',
            'spark.openlineage.transport.type: "console"',
        )
        .encode()
    )


@pytest.mark.parametrize("url", ["http://lineage.example.invalid:5000", ""])
def test_default_rendering_is_the_payments_manifest(tmp_path, url):
    manifest, calls = run_script(SPARK_DIR / "submit_job.sh", tmp_path, {"OPENLINEAGE_URL": url})
    assert manifest == expected(url)
    assert "promote_payments_spark.py" in calls
    assert "cerberus-promote-payments" in calls
    assert "downloads" not in calls


@pytest.mark.skipif(not BASELINE, reason="SUBMIT_JOB_BASELINE not set")
@pytest.mark.parametrize("url", ["http://lineage.example.invalid:5000", ""])
def test_default_run_equals_the_baseline_script(tmp_path, url):
    new_dir, old_dir = tmp_path / "new", tmp_path / "old"
    new_dir.mkdir()
    old_dir.mkdir()
    env = {"OPENLINEAGE_URL": url}
    new = run_script(SPARK_DIR / "submit_job.sh", new_dir, env)
    old = run_script(Path(BASELINE), old_dir, env)
    assert new[0] == old[0]
    assert new[1] == old[1]


def test_downloads_overrides_render_the_downloads_manifest(tmp_path):
    env = {
        "OPENLINEAGE_URL": "",
        "APP_NAME": "cerberus-promote-downloads",
        "SCRIPT_NAME": "promote_downloads_spark.py",
        "MANIFEST_YAML": "spark-application-promote-downloads.yaml",
        "EXTRA_SED": "s|__SILVER_BUCKET__|silver-x|;s|__BRONZE_ROOT__|s3a://bronze-x/|;"
        "s|__WAREHOUSE__|s3://silver-x/iceberg/|",
    }
    manifest, calls = run_script(SPARK_DIR / "submit_job.sh", tmp_path, env)
    text = manifest.decode()
    assert "name: cerberus-promote-downloads" in text
    assert 's3a://silver-x/_spark_jobs/promote_downloads_spark.py"' in text
    assert '- "s3a://bronze-x/"' in text
    assert '- "s3://silver-x/iceberg/"' in text
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "__" in line]
    assert "_spark_jobs/promote_downloads_spark.py" in calls
