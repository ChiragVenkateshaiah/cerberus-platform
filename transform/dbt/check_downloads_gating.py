"""17.5: assert the downloads gating from a parsed manifest (target/manifest.json).

    dbt parse                                       && python check_downloads_gating.py default
    dbt parse --vars '{enable_downloads: true, enable_downloads_cdn: true}' \
                                                    && python check_downloads_gating.py enabled
    dbt parse --vars '{enable_downloads: true}'     && python check_downloads_gating.py silver-only

default: no downloads model, source or test, so the scheduled build is unchanged.
enabled: all 5 models and both sources. silver-only: the 3 silver models, no CDN.
Exits 1 on any mismatch. Stdlib only; reads the manifest, never a warehouse.
"""

import json
import sys
from pathlib import Path

SILVER = {"fct_download_sessions", "fct_isp_minute", "fct_release_window"}
CDN = {"fct_cdn_requests", "fct_cdn_run"}
PAYMENTS = {"fct_transactions", "dim_merchants", "dim_customers"}


def main(mode, manifest_path="target/manifest.json"):
    manifest = json.loads(Path(manifest_path).read_text())
    models = {
        n["name"]
        for n in manifest["nodes"].values()
        if n["resource_type"] == "model" and n["config"].get("enabled", True)
    }
    sources = {
        s["name"]
        for s in manifest["sources"].values()
        if s["source_name"] == "cerberus_downloads" and s["config"].get("enabled", True)
    }
    tests = [
        n
        for n in manifest["nodes"].values()
        if n["resource_type"] == "test"
        and "downloads" in n["original_file_path"]
        and n["config"].get("enabled", True)
    ]
    want_models = {"default": set(), "enabled": SILVER | CDN, "silver-only": SILVER}[mode]
    want_sources = {
        "default": set(),
        "enabled": {"download_events", "bronze_downloads_cdn"},
        "silver-only": {"download_events"},
    }[mode]
    problems = []
    if not PAYMENTS <= models:
        problems.append(f"payments models missing: {sorted(PAYMENTS - models)}")
    got = models & (SILVER | CDN)
    if got != want_models:
        problems.append(f"downloads models {sorted(got)}, want {sorted(want_models)}")
    if sources != want_sources:
        problems.append(f"downloads sources {sorted(sources)}, want {sorted(want_sources)}")
    if mode == "default" and tests:
        problems.append(f"{len(tests)} downloads tests present in the default parse")
    if mode != "default" and not tests:
        problems.append("no downloads tests in the enabled parse")
    print(
        f"{mode}: models {sorted(got)}; sources {sorted(sources)}; "
        f"downloads tests {len(tests)}; total models {len(models)}"
    )
    for problem in problems:
        print(f"FAIL {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("default", "enabled", "silver-only"):
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
