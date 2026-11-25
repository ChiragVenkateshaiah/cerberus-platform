"""launch/seed.py: distinct, content-addressed chunks and the manifest (small chunks)."""

import hashlib
import json
import sys
from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCH))

import scenario  # noqa: E402
import seed  # noqa: E402


def make_sets(tmp_path: Path) -> Path:
    sets = scenario.load_sets()
    sets["chunk_bytes"] = 2048
    for name, n in (("build", 6), ("patch", 3), ("patch2", 3)):
        sets["sets"][name]["chunks"] = n
    path = tmp_path / "sets.json"
    path.write_text(json.dumps(sets))
    return path


def test_chunks_are_distinct_named_by_their_sha256_and_listed(tmp_path):
    sets = make_sets(tmp_path)
    manifest = seed.seed(sets, "build", tmp_path / "out", None)
    assert len(manifest["chunks"]) == 6 and manifest["chunk_bytes"] == 2048
    names = [c["key"] for c in manifest["chunks"]]
    assert len(set(names)) == 6  # distinct random content
    for c in manifest["chunks"]:
        data = (tmp_path / "out" / c["key"]).read_bytes()
        assert len(data) == c["bytes"] == 2048
        assert c["key"] == f"build/{hashlib.sha256(data).hexdigest()}.bin"
    on_disk = json.loads((tmp_path / "out" / "build.json").read_text())
    assert on_disk == manifest
    assert (tmp_path / "out" / "build" / "manifest.json").read_text() == (
        tmp_path / "out" / "build.json"
    ).read_text()


def test_the_two_patch_sets_share_no_object_and_no_manifest(tmp_path):
    sets = make_sets(tmp_path)
    a = seed.seed(sets, "patch", tmp_path / "out", None)
    b = seed.seed(sets, "patch2", tmp_path / "out", None)
    assert not {c["key"] for c in a["chunks"]} & {c["key"] for c in b["chunks"]}
    assert (tmp_path / "out" / "patch" / "manifest.json").exists()
    assert (tmp_path / "out" / "patch" / "manifest-2.json").exists()
    assert all(c["key"].startswith("patch/") for c in a["chunks"] + b["chunks"])


def test_the_real_sets_file_is_64_mib_chunks():
    sets = scenario.load_sets()
    assert sets["chunk_bytes"] == 64 * 1024 * 1024
    assert sets["sets"]["build"]["chunks"] * sets["chunk_bytes"] == 4 * 1024**3  # 4 GiB build
    assert sets["sets"]["patch"]["chunks"] * sets["chunk_bytes"] == 512 * 1024**2  # 512 MiB patch


def test_upload_calls_aws_s3_cp_per_chunk_and_the_manifest(tmp_path, monkeypatch):
    sets = make_sets(tmp_path)
    calls = []
    monkeypatch.setattr(
        seed,
        "aws_cp",
        lambda src, bucket, key: calls.append((bucket, key, Path(src).stat().st_size)),
    )
    seed.seed(sets, "patch2", tmp_path / "out", "stub-bucket")
    assert len(calls) == 4  # 3 chunks and the manifest
    assert calls[-1][1] == "patch/manifest-2.json"
    assert all(b == "stub-bucket" and k.startswith("patch/") for b, k, _ in calls)
    assert not list((tmp_path / "out" / "patch").glob("*.bin"))  # chunks are removed after upload


def test_seed_py_loads_on_the_python_of_the_instance():
    """AL2023 python3 is 3.9: PEP 604 hints need the future import."""
    source = Path(seed.__file__).read_text()
    assert "from __future__ import annotations" in source
    compile(source, "seed.py", "exec", dont_inherit=True)
