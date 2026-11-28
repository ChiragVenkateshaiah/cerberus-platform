"""Publish safety: what the stale-key rule may delete (plan 2026-11-09)."""

import io
import json
import sys
from pathlib import Path

import pytest
from landing_helpers import build_site, write_charts

from cerberus_landing import publish
from cerberus_landing.__main__ import main

SCRIPT = Path(__file__).resolve().parents[1] / "publish_site.sh"

PROTECTED = [
    "healthz.txt",
    "live.json",
    "index.html",
    "terminal/index.html",
    "terminal/app.0123456789.js",
]


@pytest.fixture
def site(tmp_path):
    out = tmp_path / "site"
    build_site(out, charts_dir=write_charts(tmp_path / "charts"))
    return out


def test_every_built_file_but_index_is_managed(site):
    keys = publish.local_keys(site)
    assert "index.html" in keys
    for key in keys - {"index.html"}:
        assert publish.MANAGED.fullmatch(key), key


def test_protected_keys_are_never_stale(site):
    local = publish.local_keys(site)
    assert publish.stale_keys(local, PROTECTED) == []
    assert publish.stale_keys(set(), PROTECTED) == []


def test_old_hashed_assets_are_stale(site):
    old = [
        "site.0000000000.css",
        "site.0000000000.js",
        "favicon.0000000000.svg",
        "img/scale-cost.0000000000.svg",
    ]
    assert publish.stale_keys(publish.local_keys(site), old + PROTECTED) == sorted(old)


@pytest.mark.parametrize(
    "key",
    ["site.js", "site.0000000000.js.map", "terminal/site.0000000000.js", "other.0000000000.js"],
)
def test_other_script_keys_are_never_stale(key):
    assert publish.stale_keys(set(), [key]) == []


def test_current_assets_are_kept(site):
    local = publish.local_keys(site)
    assert publish.stale_keys(local, sorted(local)) == []


def _stale(monkeypatch, stdin, directory):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return main(["stale", "--dir", str(directory)])


def test_stale_null_prints_nothing(site, monkeypatch, capsys):
    assert _stale(monkeypatch, "null", site) == 0
    assert capsys.readouterr().out == ""


def test_stale_prints_one_key_per_line(site, monkeypatch, capsys):
    stdin = json.dumps([*PROTECTED, "site.0000000000.css"])
    assert _stale(monkeypatch, stdin, site) == 0
    assert capsys.readouterr().out == "site.0000000000.css\n"


@pytest.mark.parametrize("stdin", ["not json", '{"a": 1}', "[1, 2]"])
def test_stale_bad_input_exits_1(site, monkeypatch, stdin):
    assert _stale(monkeypatch, stdin, site) == 1


def test_stale_without_index_exits_1(tmp_path, monkeypatch):
    assert _stale(monkeypatch, "[]", tmp_path / "missing") == 1


def test_the_script_file_is_uploaded_before_the_page_with_its_headers():
    text = SCRIPT.read_text(encoding="utf-8")
    loop = text.index('for f in "$DIR"/site.*.js; do')
    block = text[loop : text.index("done", loop)]
    assert '--content-type "text/javascript; charset=utf-8" --cache-control "$IMMUTABLE"' in block
    assert loop < text.index('aws s3 cp "$DIR/index.html"')


def test_the_published_script_headers_are_checked():
    text = SCRIPT.read_text(encoding="utf-8")
    assert """grep -o 'site\\.[0-9a-f]\\{10\\}\\.js' "$BODY\"""" in text
    assert """grep -qi '^cache-control:.*immutable' "$HDR" || fail "$JS""" in text
    assert """grep -qi '^content-type:.*text/javascript' "$HDR\"""" in text


def test_script_never_syncs_or_bulk_deletes():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--delete" not in text
    assert "sync" not in text


@pytest.mark.parametrize("script", ["publish_site.sh", "publish_terminal.sh"])
def test_s3_rm_takes_no_transfer_only_flags(script):
    # `aws s3 rm` rejects --no-progress (exit 252), which cp accepts.
    text = (Path(__file__).resolve().parents[1] / script).read_text()
    removes = [line.strip() for line in text.splitlines() if line.strip().startswith("aws s3 rm ")]
    assert removes == ['aws s3 rm "s3://$BUCKET/$key" --only-show-errors']
