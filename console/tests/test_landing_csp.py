"""The built page must pass the edge CSP: no inline script or style, no handlers,
relative assets only. Includes negative fixtures so the scanner itself is tested.
"""

import http.client
import re
import threading

import pytest
from landing_helpers import build_site, write_charts

from cerberus_landing import build, serve

# An independent grep, not the builder's own scanner.
BANNED = re.compile(r"<script|<style|style=|\son[a-z]+\s*=|javascript:", re.IGNORECASE)

NEGATIVE = {
    "script element": "<p>x</p><script>alert(1)</script>",
    "script src": '<script src="app.js"></script>',
    "style element": "<style>p{color:red}</style>",
    "style attribute": '<p style="color:red">x</p>',
    "onclick": '<a href="#a" onclick="x()">x</a>',
    "onerror": '<img src="a.svg" onerror="x()" alt="">',
    "javascript url": '<a href="javascript:alert(1)">x</a>',
    "absolute stylesheet": '<link rel="stylesheet" href="https://cdn.example/a.css">',
    "protocol-relative src": '<img src="//cdn.example/a.svg" alt="">',
    "data url src": '<img src="data:image/svg+xml;base64,AAAA" alt="">',
    "external link not allowlisted": '<a href="https://example.com/">x</a>',
    "tab inside javascript url": '<a href="java\tscript:alert(1)">x</a>',
    "newline inside javascript url": '<a href="jav\nascript:alert(1)">x</a>',
    "srcset": '<img srcset="https://cdn.example/a.svg 2x" alt="">',
    "form action": '<form action="/x"><p>x</p></form>',
    "formaction": '<button formaction="/x">x</button>',
    "iframe": '<iframe src="a.html"></iframe>',
    "object": '<object data="a.svg"></object>',
    "embed": '<embed src="a.svg">',
    "base": '<base href="#x">',
    "meta refresh": '<meta http-equiv="refresh" content="0;url=a.html">',
    "lookalike github link": '<a href="https://github.com/ChiragVenkateshaiah/cerberus-platformX">x</a>',
}


@pytest.mark.parametrize("name", NEGATIVE)
def test_scanner_flags_each_banned_pattern(name):
    assert build.csp_problems(NEGATIVE[name]), name


def test_scanner_accepts_a_clean_fragment():
    ok = (
        '<link rel="stylesheet" href="site.abc.css"><a href="#x">x</a>'
        '<a href="https://github.com/ChiragVenkateshaiah/cerberus-platform/blob/main/a.md">x</a>'
        '<a href="https://chiragvenkateshaiah.github.io/cerberus-platform/dbt/">x</a>'
        '<img src="img/a.svg" alt="x">'
    )
    assert build.csp_problems(ok) == []


@pytest.mark.parametrize(
    "bad",
    [
        "<script>x()</script>",
        '<rect onclick="x()"/>',
        '<rect style="fill:red"/>',
        '<a href="https://x.example">x</a>',
        '<a xlink:href="#a">x</a>',
        '<a href="javascript:alert(1)">x</a>',
        '<a href="java&#9;script:alert(1)">x</a>',
        "<style>@import 'a.css';</style>",
        "<style>.a{fill:url(#g)}</style>",
        "<style>.a{fill:URL(https://x.example/a.png)}</style>",
        '<foreignObject><iframe src="a.html"></iframe></foreignObject>',
    ],
)
def test_chart_scanner_flags_unsafe_svg(bad):
    assert build.csp_problems(f"<svg>{bad}</svg>", "chart")


def test_chart_scanner_allows_an_internal_style_element():
    assert build.csp_problems("<svg><style>.a{fill:red}</style></svg>", "chart") == []


def test_the_built_page_is_clean(tmp_path):
    out = tmp_path / "site"
    _, html = build_site(out, charts_dir=write_charts(tmp_path / "charts"))
    assert build.csp_problems(html) == []
    assert BANNED.search(html) is None
    assert BANNED.search(next(out.glob("site.*.css")).read_text(encoding="utf-8")) is None


def test_the_stylesheet_loads_nothing_remote(tmp_path):
    out = tmp_path / "site"
    build_site(out)
    css = next(out.glob("site.*.css")).read_text(encoding="utf-8")
    assert "@import" not in css
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", css)


def test_the_architecture_svg_is_inline_and_clean():
    from cerberus_landing.build import PKG

    svg = (PKG / "architecture.svg").read_text(encoding="utf-8")
    assert build.csp_problems(svg) == []
    assert "<style" not in svg
    for adr in ("0005", "0009", "0011", "0016", "0017", "0018", "0019", "0022", "0024"):
        assert f"ADR {adr}" in svg, adr


def test_preview_policy_matches_the_edge_minus_two_parts():
    directives = dict(d.strip().split(" ", 1) for d in serve.CSP.split(";"))
    assert directives["script-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert "upgrade-insecure-requests" not in serve.CSP
    assert "cognito" not in serve.CSP.lower()
    assert "unsafe" not in serve.CSP


def test_preview_server_sends_the_csp_on_every_response(tmp_path):
    out = tmp_path / "site"
    build_site(out)
    server = serve.make_server(out, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert server.server_address[0] == "127.0.0.1"
        for path in ("/", "/missing"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            assert resp.getheader("Content-Security-Policy") == serve.CSP, path
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
