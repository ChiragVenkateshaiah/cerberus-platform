"""The terminal build and publish rules (ADR 0024 amendment, 2026-11-12). No AWS, no network."""

import io
import json
import re
import sys
from pathlib import Path

import pytest

from cerberus_console import config
from cerberus_landing import publish as landing_publish
from cerberus_terminal import build, publish
from cerberus_terminal.__main__ import main

SCRIPT = Path(__file__).resolve().parents[1] / "publish_terminal.sh"

# An independent grep, not the builder's own scanner.
BANNED = re.compile(r"<script(?![^>]*\ssrc=)|<style|style=|\son[a-z]+\s*=|javascript:", re.I)

PROTECTED = [
    "healthz.txt",
    "live.json",
    "index.html",
    "terminal/index.html",
    "terminal/config.json",
    "site.0123456789.css",
    "favicon.0123456789.svg",
    "img/scale-cost.0123456789.svg",
]


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def site(tmp_path):
    out = tmp_path / "dist"
    build.build(out)
    return out


def test_build_writes_three_files_under_terminal(site):
    keys = publish.local_keys(site)
    assert "terminal/index.html" in keys
    assert len(keys) == 3
    assert not any(k.startswith("terminal/config") for k in keys)


def test_two_builds_are_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    info_a = build.build(a)
    info_b = build.build(b)
    assert tree(a) == tree(b)
    assert info_a == info_b


def test_build_id_is_64_hex_and_in_the_page(site):
    html = (site / "terminal" / "index.html").read_text(encoding="utf-8")
    ids = re.findall(r'<meta name="cerberus-build" content="([0-9a-f]{64})"', html)
    assert len(ids) == 1


def test_build_id_changes_when_the_script_changes(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    for name in ("index.html.tmpl", "terminal.js", "terminal.css"):
        (static / name).write_bytes((build.STATIC / name).read_bytes())
    monkeypatch.setattr(build, "STATIC", static)
    before = build.build(tmp_path / "a")
    (static / "terminal.js").write_text("// changed\n", encoding="utf-8")
    after = build.build(tmp_path / "b")
    assert before.build_id != after.build_id


def test_built_keys_match_terminal_managed_except_index(site):
    keys = publish.local_keys(site)
    for key in keys - {"terminal/index.html"}:
        assert publish.TERMINAL_MANAGED.fullmatch(key), key
        assert not landing_publish.MANAGED.fullmatch(key), key


def test_the_page_names_its_hashed_assets(site):
    html = (site / "terminal" / "index.html").read_text(encoding="utf-8")
    for key in publish.local_keys(site) - {"terminal/index.html"}:
        assert key.removeprefix("terminal/") in html


def test_the_built_page_is_clean(site):
    html = (site / "terminal" / "index.html").read_text(encoding="utf-8")
    assert build.csp_problems(html) == []
    assert BANNED.search(html) is None
    css = next((site / "terminal").glob("terminal.*.css")).read_text(encoding="utf-8")
    assert BANNED.search(css) is None
    assert "@import" not in css
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", css)


def test_the_page_has_the_accessible_parts(site):
    html = (site / "terminal" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<div id="log"[^>]*role="log"[^>]*aria-live="polite"', html)
    assert '<label for="cmd-input"' in html
    assert 'id="cmd-input"' in html
    assert 'name="viewport"' in html
    assert '<html lang="en">' in html


def test_maxlength_matches_the_server_limits(site):
    html = (site / "terminal" / "index.html").read_text(encoding="utf-8")
    expected = config.MAX_TOKENS * config.MAX_TOKEN_CHARS + config.MAX_TOKENS - 1
    assert re.findall(r'maxlength="(\d+)"', html) == [str(expected)]


def test_the_stylesheet_follows_the_system_colour_scheme(site):
    css = next((site / "terminal").glob("terminal.*.css")).read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    # 16px or more on the input stops mobile zoom.
    block = re.search(r"\.cmd-input\s*\{[^}]*font-size:\s*([\d.]+)rem", css)
    assert block and float(block.group(1)) >= 1.0


NEGATIVE = {
    "inline script": "<script>alert(1)</script>",
    "script with src and body": '<script src="a.js">alert(1)</script>',
    "style element": "<style>p{color:red}</style>",
    "style attribute": '<p style="color:red">x</p>',
    "onclick": '<button onclick="x()">x</button>',
    "javascript url": '<a href="javascript:alert(1)">x</a>',
    "tab inside javascript url": '<a href="java\tscript:alert(1)">x</a>',
    "absolute script": '<script src="https://cdn.example/a.js"></script>',
    "protocol-relative link": '<link rel="stylesheet" href="//cdn.example/a.css">',
    "iframe": '<iframe src="a.html"></iframe>',
    "base": '<base href="/">',
    "form action": '<form action="/x"></form>',
    "meta http-equiv": '<meta http-equiv="refresh" content="0">',
}


@pytest.mark.parametrize("bad", NEGATIVE.values(), ids=NEGATIVE.keys())
def test_scanner_flags_unsafe_markup(bad):
    assert build.csp_problems(f"<p>x</p>{bad}")


def test_scanner_passes_a_clean_page():
    page = '<link rel="stylesheet" href="a.css"><script src="a.js"></script>'
    assert build.csp_problems(page) == []


# ---- publish rules ----


def test_protected_keys_are_never_stale(site):
    local = publish.local_keys(site)
    assert publish.stale_keys(local, PROTECTED) == []
    assert publish.stale_keys(set(), PROTECTED) == []


def test_old_hashed_assets_are_stale(site):
    old = ["terminal/terminal.0000000000.js", "terminal/terminal.0000000000.css"]
    assert publish.stale_keys(publish.local_keys(site), old + PROTECTED) == sorted(old)


def test_current_assets_are_kept(site):
    local = publish.local_keys(site)
    assert publish.stale_keys(local, sorted(local)) == []


@pytest.mark.parametrize(
    "key",
    [
        "terminal/terminal.0000000000.map",
        "terminal/terminal.000000000.js",
        "terminal/terminal.0000000000.js.bak",
        "terminal/other/terminal.0000000000.js",
        "terminal/Terminal.0000000000.js",
        "terminal.0000000000.js",
        "x/terminal/terminal.0000000000.js",
    ],
)
def test_near_misses_are_never_stale(key):
    assert publish.stale_keys(set(), [key]) == []


def test_landing_and_terminal_patterns_are_disjoint(site):
    terminal_keys = [*publish.local_keys(site), "terminal/terminal.0000000000.js"]
    landing_keys = [
        "site.0123456789.css",
        "favicon.0123456789.svg",
        "img/scale-cost.0123456789.svg",
        "terminal/site.0123456789.css",
        "terminal/img/scale-cost.0123456789.svg",
    ]
    for key in terminal_keys:
        assert not landing_publish.MANAGED.fullmatch(key), key
    for key in landing_keys:
        assert not publish.TERMINAL_MANAGED.fullmatch(key), key
    # The landing rule can never reach anything under terminal/.
    assert landing_publish.stale_keys(set(), terminal_keys) == []
    assert publish.stale_keys(set(), landing_keys) == []


def _stale(monkeypatch, stdin, directory):
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return main(["stale", "--dir", str(directory)])


def test_stale_null_prints_nothing(site, monkeypatch, capsys):
    assert _stale(monkeypatch, "null", site) == 0
    assert capsys.readouterr().out == ""


def test_stale_prints_one_key_per_line(site, monkeypatch, capsys):
    stdin = json.dumps([*PROTECTED, "terminal/terminal.0000000000.css"])
    assert _stale(monkeypatch, stdin, site) == 0
    assert capsys.readouterr().out == "terminal/terminal.0000000000.css\n"


@pytest.mark.parametrize("stdin", ["not json", '{"a": 1}', "[1, 2]"])
def test_stale_bad_input_exits_1(site, monkeypatch, stdin):
    assert _stale(monkeypatch, stdin, site) == 1


def test_stale_without_a_built_page_exits_1(tmp_path, monkeypatch):
    assert _stale(monkeypatch, "[]", tmp_path / "missing") == 1


def test_build_cli_reports_and_writes(tmp_path, capsys):
    assert main(["build", "--out", str(tmp_path / "o")]) == 0
    assert "built 3 files" in capsys.readouterr().out


# ---- the publish script ----


def test_script_never_syncs_or_bulk_deletes():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--delete" not in text
    assert "sync" not in text
    assert "--recursive" not in text
    assert "set -euo pipefail" in text


def test_script_deletes_one_key_at_a_time_and_only_stale_ones():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count("aws s3 rm") == 1
    assert 'aws s3 rm "s3://$BUCKET/$key"' in text
    assert "cerberus_terminal stale" in text


def test_script_never_echoes_the_bucket():
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if re.match(r"\s*(echo|printf)\b", line):
            assert "$BUCKET" not in line, line


def test_script_invalidates_only_the_terminal_path_and_uploads_the_page_last():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--paths '/terminal/*'" in text
    assert "'/*'" not in text
    last_upload = text.rindex("aws s3 cp")
    assert text[last_upload:].startswith('aws s3 cp "$DIR/terminal/index.html"')
    assert text.index("create-invalidation") > last_upload


def test_script_sets_the_content_types_and_cache_headers():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'text/javascript; charset=utf-8" --cache-control "$IMMUTABLE"' in text
    assert 'text/css; charset=utf-8" --cache-control "$IMMUTABLE"' in text
    assert 'application/json" --cache-control "no-cache"' in text
    assert 'text/html; charset=utf-8" --cache-control "no-cache"' in text
    assert 'IMMUTABLE="public, max-age=31536000, immutable"' in text
