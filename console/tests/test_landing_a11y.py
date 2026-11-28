"""Accessibility basics and the colour contrast of the stylesheet."""

import re

from landing_helpers import PHASES_MD, build_site, parse, write_charts

from cerberus_landing import phases
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


def test_the_live_link_is_hidden_and_leads_nowhere_without_javascript(tmp_path):
    p = parse(_built(tmp_path))
    links = [a for a in p.named("a") if a.get("id") == "live-link"]
    assert len(links) == 1
    assert "hidden" in links[0] and "href" not in links[0]
    assert "invited sign-in" in p.text["a"]
    # Every link that a reader can see has somewhere to go.
    for a in p.named("a"):
        assert "href" in a or "hidden" in a, a
    # Classes such as .link set display, which would override the hidden attribute.
    css = (PKG / "static" / "site.css").read_text(encoding="utf-8")
    assert re.search(r"^\[hidden\] \{\s*display: none !important;\s*\}", css, flags=re.MULTILINE)


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
    start = html.index('<svg xmlns="http://www.w3.org/2000/svg" class="arch"')
    svg = html[start : html.index("</svg>", start) + 6]
    p = parse(svg)
    assert p.named("svg")[0]["role"] == "img"
    assert p.text["title"].strip()
    assert p.named("desc") and p.text["desc"].strip()
    assert "viewbox" in p.named("svg")[0]


def test_every_button_is_hidden_in_the_html(tmp_path):
    """Without JavaScript a button does nothing, so a reader must not see one."""
    html = _built(tmp_path)
    p = parse(html)
    buttons = p.named("button")
    assert len(buttons) == 3 + 3 * 4 + 3 * 4  # picks, station buttons, "Next"
    assert all(b["type"] == "button" for b in buttons)
    # Each button is hidden itself, or sits in a picker or stepper that is hidden.
    for b in buttons:
        assert "data-pick" in b or "data-step" in b or ("data-next" in b and "hidden" in b), b
    holders = [a for _, a in p.tags if "data-picker" in a or "data-stepper" in a]
    assert len(holders) == 4 and all("hidden" in a for a in holders)
    assert html.count("data-pick ") == 3  # all three are inside the one picker
    picker = html[html.index("data-picker") :]
    assert picker[: picker.index("</div>")].count("data-pick ") == 3
    for block in re.findall(r"<ol [^>]*data-stepper.*?</ol>", html, flags=re.DOTALL):
        assert block.count("data-step ") == 4


def test_without_javascript_every_run_and_panel_is_shown(tmp_path):
    p = parse(_built(tmp_path))
    shown = [a for _, a in p.tags if a.get("class") in ("run", "panel")]
    assert len(shown) == 3 + 12
    assert not any("hidden" in a for a in shown)


def test_buttons_control_real_elements_and_one_is_selected(tmp_path):
    p = parse(_built(tmp_path))
    by_id = {a["id"]: a for _, a in p.tags if "id" in a}
    for b in p.named("button"):
        assert b["aria-controls"] in by_id, b
    picks = [b for b in p.named("button") if "data-pick" in b]
    assert [b["aria-controls"] for b in picks] == ["run-1m", "run-10m", "run-100m"]
    assert [b["aria-pressed"] for b in picks] == ["false", "false", "true"]
    steps = [b for b in p.named("button") if "data-step" in b]
    assert [b["aria-pressed"] for b in steps] == ["true", "false", "false", "false"] * 3
    for panel in (a for a in by_id.values() if a.get("class") == "panel"):
        assert panel["tabindex"] == "-1"  # "Next" moves the focus to it
        assert panel["aria-labelledby"] in by_id


def test_the_time_bar_is_decoration_beside_a_written_value(tmp_path):
    html = _built(tmp_path)
    bars = [a for a in parse(html).named("svg") if a.get("class") == "bar"]
    assert len(bars) == 12
    assert all(a["aria-hidden"] == "true" for a in bars)
    value = r'<p class="time"><strong>[\d,.]+ s</strong> '
    written = value + r"<span>[\d.]+% of the [\d,.]+ s run</span></p>\n"
    assert len(re.findall(written + '<svg class="bar"', html)) == 12


def test_a_warning_is_an_icon_and_a_word(tmp_path):
    html = _built(tmp_path)
    warnings = re.findall(r'<p class="warn">(.*?)</p>', html, flags=re.DOTALL)
    assert warnings
    for w in warnings:
        assert w.startswith('<svg class="icon"') and 'aria-hidden="true"' in w
        assert "<strong>Warning:</strong>" in w


def test_status_is_a_word_not_only_a_colour(tmp_path):
    p = parse(_built(tmp_path))
    badges = [a for t, a in p.tags if t == "span" and "badge" in a.get("class", "")]
    assert len(badges) == len(phases.parse(PHASES_MD.read_text(encoding="utf-8")))
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


def test_the_bar_and_the_warning_icon_meet_three_to_one_in_both_modes():
    light, dark = _palettes()
    for palette in (light, dark):
        for bg in ("bg", "surface", "surface-2", "track"):
            assert _ratio(palette["bar"], palette[bg]) >= 3, bg
        assert _ratio(palette["warn"], palette["surface"]) >= 3
    # Dark mode picks its own values; none falls through from light mode.
    for name in ("bar", "track", "warn"):
        assert light[name] != dark[name], name


def test_the_bar_uses_one_hue_and_text_never_uses_it():
    css = (PKG / "static" / "site.css").read_text(encoding="utf-8")
    assert re.findall(r"var\(--bar\)", css) == ["var(--bar)"]
    assert re.search(r"\.bar-mark \{\s*fill: var\(--bar\);\s*\}", css)
    assert re.search(r"\.bar-track \{\s*fill: var\(--track\);\s*\}", css)


def test_motion_is_only_on_when_the_reader_allows_it():
    css = (PKG / "static" / "site.css").read_text(encoding="utf-8")
    assert css.count("scroll-behavior") == 1
    assert "transition" not in css and "animation" not in css
    allowed = css[css.index("@media (prefers-reduced-motion: no-preference)") :]
    assert "scroll-behavior: smooth" in allowed


def test_the_stylesheet_has_dark_mode_and_a_phone_layout():
    css = (PKG / "static" / "site.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert "color-scheme: light dark" in css
    assert "min-width: 40rem" in css
    assert "min-height: 2.75rem" in css  # 44 px tap targets
