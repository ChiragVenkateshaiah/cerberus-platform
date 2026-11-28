"""Determinism, asset hashes, links, size and the chart section (no AWS, no network)."""

import hashlib
import shutil
from pathlib import Path

import pytest
from landing_helpers import (
    build_site,
    journey_records,
    parse,
    tree,
    write_charts,
    write_record,
)

from cerberus_landing import __main__ as cli
from cerberus_landing import build, page
from cerberus_terminal import build as terminal_build


def test_two_builds_are_byte_identical(tmp_path):
    charts = write_charts(tmp_path / "charts")
    a, b = tmp_path / "a", tmp_path / "b"
    info_a, _ = build_site(a, charts_dir=charts)
    info_b, _ = build_site(b, charts_dir=charts)
    assert tree(a) == tree(b)
    assert info_a.build_id == info_b.build_id


def test_build_id_changes_when_an_input_changes(tmp_path):
    runs = journey_records(tmp_path / "runs")
    write_record(runs, "exercise-20261101T100000Z")
    info_a, _ = build_site(tmp_path / "a", runs_dir=runs)
    write_record(runs, "exercise-20261101T100000Z", events_processed=6000)
    info_b, _ = build_site(tmp_path / "b", runs_dir=runs)
    assert info_a.build_id != info_b.build_id


def test_build_id_and_the_name_change_when_the_script_changes(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    shutil.copytree(build.PKG, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(build, "PKG", pkg)
    before, _ = build_site(tmp_path / "a")
    (pkg / "static" / "site.js").write_text("// changed\n", encoding="utf-8")
    after, html = build_site(tmp_path / "b")
    assert before.build_id != after.build_id
    old, new = (next(n for n in i.files if n.endswith(".js")) for i in (before, after))
    assert old != new and new in html and old not in html


def test_build_id_covers_the_console_modules(tmp_path, monkeypatch):
    console = tmp_path / "cerberus_console"
    console.mkdir()
    for name in build.CONSOLE_FILES:
        (console / name).write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(build, "CONSOLE", console)
    for name in build.CONSOLE_FILES:
        before, _ = build_site(tmp_path / f"a-{name}")
        (console / name).write_text("x = 2\n", encoding="utf-8")
        after, _ = build_site(tmp_path / f"b-{name}")
        assert before.build_id != after.build_id, name


def test_every_content_key_is_used():
    import re
    import tomllib

    text = (build.PKG / "content.toml").read_text(encoding="utf-8")
    c = tomllib.loads(text)
    code = "".join((build.PKG / n).read_text(encoding="utf-8") for n in ("page.py", "build.py"))
    dynamic = {"phases", "captions"}  # looked up by phase number / chart name
    for section, body in c.items():
        if section in dynamic:
            continue
        for key in body:
            if key in dynamic:
                continue
            assert re.search(rf"""\[["']{key}["']\]""", code), f"{section}.{key} is never used"


def test_asset_names_match_the_content_hash(tmp_path):
    out = tmp_path / "site"
    build_site(out, charts_dir=write_charts(tmp_path / "charts"))
    assets = [p for p in out.rglob("*") if p.is_file() and p.name != "index.html"]
    assert len(assets) == 6  # css, js, favicon, three charts
    for p in assets:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:10]
        assert p.name.split(".")[-2] == digest, p.name


def test_build_id_is_in_the_page(tmp_path):
    info, html = build_site(tmp_path / "site")
    metas = [a for a in parse(html).named("meta") if a.get("name") == "cerberus-build"]
    assert [m["content"] for m in metas] == [info.build_id]


def test_links_resolve_and_externals_are_allowlisted(tmp_path):
    out = tmp_path / "site"
    _, html = build_site(out, charts_dir=write_charts(tmp_path / "charts"))
    # The terminal page has its own build and publish; it lands beside this one.
    terminal = tmp_path / "terminal-site"
    terminal_build.build(terminal)
    p = parse(html)
    ids = {a["id"] for _, a in p.tags if "id" in a}
    refs = [(t, a[k]) for t, a in p.tags for k in ("href", "src") if k in a]
    assert refs
    for tag, ref in refs:
        if ref.startswith("#"):
            assert ref[1:] in ids, ref
        elif ref.startswith("https://"):
            assert tag == "a", (tag, ref)
            assert page.is_allowed_external(ref), ref
        else:
            assert "://" not in ref and not ref.startswith("//"), ref
            root = terminal if ref == page.TERMINAL_HREF else out
            assert (root / ref).is_file(), ref
    assert ("a", page.TERMINAL_HREF) in refs


def test_total_size_is_small(tmp_path):
    info, _ = build_site(tmp_path / "site", charts_dir=write_charts(tmp_path / "charts"))
    assert info.total_bytes < 150 * 1024


def test_the_terminal_link_says_invite_only(tmp_path):
    _, html = build_site(tmp_path / "site")
    assert page.TERMINAL_HREF == "terminal/index.html"
    assert f'href="{page.TERMINAL_HREF}">Sign in to the terminal (invite only)</a>' in html


def test_charts_present_gives_three_images_with_alt(tmp_path):
    _, html = build_site(tmp_path / "site", charts_dir=write_charts(tmp_path / "charts"))
    imgs = parse(html).named("img")
    assert len(imgs) == 3
    for img in imgs:
        assert img["alt"].strip()
        assert img["width"].isdigit() and img["height"].isdigit()
        assert img["src"].startswith("img/")


def test_charts_absent_gives_the_placeholder(tmp_path):
    out = tmp_path / "site"
    _, html = build_site(out, charts_dir=tmp_path / "does-not-exist")
    assert "Charts arrive with the Phase 8 results write-up." in html
    assert parse(html).named("img") == []
    assert not (out / "img").exists()


@pytest.mark.parametrize(
    "bad",
    [
        '<svg width="1" height="1"><title>t</title><script>x()</script></svg>',
        '<svg width="1" height="1"><title>t</title><rect onload="x()"/></svg>',
        '<svg width="1" height="1"><title>t</title><a href="https://x.example">y</a></svg>',
        '<svg width="1" height="1"><title>t</title><use xlink:href="#a"/></svg>',
        '<svg width="1" height="1"><rect/></svg>',  # no title
    ],
)
def test_a_bad_chart_fails_the_build(tmp_path, bad):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "run-time-per-state.svg").write_text(bad, encoding="utf-8")
    with pytest.raises(build.BuildError):
        build_site(tmp_path / "site", charts_dir=charts)


def test_cli_builds(tmp_path, capsys):
    rc = cli.main(["build", "--out", str(tmp_path / "site"), "--charts-dir", str(tmp_path / "x")])
    assert rc == 0
    assert (tmp_path / "site" / "index.html").is_file()
    assert "built 4 files" in capsys.readouterr().out


def test_cli_reports_a_bad_phases_file(tmp_path, capsys):
    bad = tmp_path / "Phases.md"
    bad.write_text("## Phase 0 -- nope\n", encoding="utf-8")
    rc = cli.main(["build", "--out", str(tmp_path / "site"), "--phases", str(bad)])
    assert rc == 1
    assert "Phases.md" in capsys.readouterr().err


def test_content_phases_must_match_phases_md(tmp_path):
    md = Path(__file__).resolve().parents[2] / "Phases.md"
    short = tmp_path / "Phases.md"
    short.write_text(md.read_text(encoding="utf-8").split("## Phase 13")[0], encoding="utf-8")
    with pytest.raises(build.BuildError, match="does not match"):
        build_site(tmp_path / "site", phases=short)
