"""Accessibility basics and the colour contrast of the stylesheet."""

import re

from landing_helpers import build_site, parse, write_charts

from cerberus_landing.build import PKG


def _built(tmp_path):
    return build_site(tmp_path / "site", charts_dir=write_charts(tmp_path / "charts"))[1]


def test_document_basics(tmp_path):
    p = parse(_built(tmp_path))
    assert p.named("html")[0]["lang"] == "en"
    viewports = [a for a in p.named("meta") if a.get("name") == "viewport"]
    assert viewports and "width=device-width" in viewports[0]["content"]
    robots = [a for a in p.named("meta") if a.get("name") == "robots"]
    assert robots[0]["content"] == "noindex"
    assert p.text["title"].strip()
    for landmark in ("header", "nav", "main", "footer"):
        assert p.named(landmark), landmark
    skip = [a for a in p.named("a") if a.get("class") == "skip"]
    assert skip and skip[0]["href"] == "#main"


def test_one_h1_and_no_skipped_heading_levels(tmp_path):
    p = parse(_built(tmp_path))
    levels = [int(t[1]) for t, _ in p.tags if re.fullmatch(r"h[1-6]", t)]
    assert levels.count(1) == 1
    assert levels[0] == 1
    for prev, cur in zip(levels, levels[1:], strict=False):
        assert cur <= prev + 1, levels


def test_ids_are_unique_and_labels_resolve(tmp_path):
    p = parse(_built(tmp_path))
    ids = [a["id"] for _, a in p.tags if "id" in a]
    assert len(ids) == len(set(ids))
    for _, a in p.tags:
        if "aria-labelledby" in a:
            assert all(i in ids for i in a["aria-labelledby"].split())


def test_every_image_has_alt_and_size(tmp_path):
    for img in parse(_built(tmp_path)).named("img"):
        assert img["alt"].strip()
        assert img["width"] and img["height"]


def test_the_inline_svg_is_labelled(tmp_path):
    html = _built(tmp_path)
    svg = html[html.index("<svg") : html.index("</svg>") + 6]
    p = parse(svg)
    assert p.named("svg")[0]["role"] == "img"
    assert p.text["title"].strip()
    assert p.named("desc") and p.text["desc"].strip()
    assert "viewbox" in p.named("svg")[0]


def test_tables_have_captions_and_scoped_headers(tmp_path):
    html = _built(tmp_path)
    assert html.count("<table>") >= 1
    assert html.count("<table>") == html.count("<caption>")
    p = parse(html)
    for th in p.named("th"):
        assert th.get("scope") in ("col", "row")
    for region in [a for a in p.named("div") if a.get("class") == "scroll"]:
        assert region["tabindex"] == "0"
        assert region["role"] == "region" and region["aria-label"].strip()


def test_status_is_a_word_not_only_a_colour(tmp_path):
    p = parse(_built(tmp_path))
    badges = [a for t, a in p.tags if t == "span" and "badge" in a.get("class", "")]
    assert len(badges) == 14
    html = _built(tmp_path)
    assert re.search(r'class="badge [a-z-]+">(Complete|In progress|Planned)</span>', html)


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    ch = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _palettes():
    css = (PKG / "static" / "site.css").read_text(encoding="utf-8")
    light = css[css.index(":root") : css.index("@media (prefers-color-scheme: dark)")]
    dark = css[css.index("@media (prefers-color-scheme: dark)") :]
    dark = dark[: dark.index("*,")]
    grab = lambda block: dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", block))  # noqa: E731
    return grab(light), grab(dark)


def test_text_colours_meet_wcag_aa_in_both_modes():
    for palette in _palettes():
        for fg in ("ink", "ink-2", "accent"):
            for bg in ("bg", "surface", "surface-2"):
                assert _ratio(palette[fg], palette[bg]) >= 4.5, (fg, bg)
        assert _ratio(palette["on-accent"], palette["accent"]) >= 4.5


def test_the_stylesheet_has_dark_mode_and_a_phone_layout():
    css = (PKG / "static" / "site.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert "color-scheme: light dark" in css
    assert "min-width: 40rem" in css
    assert "min-height: 2.75rem" in css  # 44 px tap targets
