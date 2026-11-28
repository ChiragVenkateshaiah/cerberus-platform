"""Static checks on the landing page's site.js and its parity with the repo (9.4a).

No browser here: these read the source text. The behaviour tests are in tests/js/.
"""

import re

import pytest
from landing_helpers import build_site, parse

from cerberus_landing import build
from cerberus_landing.__main__ import REPO
from cerberus_landing.showcase import scan_text

JS_PATH = build.PKG / "static" / "site.js"
SESSION_TF = REPO / "terraform" / "envs" / "dev-console" / "session.tf"


def source() -> str:
    """site.js without comments, so the scan sees only code."""
    text = JS_PATH.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(^|\s)//\s.*$", "", text, flags=re.MULTILINE)


FORBIDDEN = [
    r"\binnerHTML\b",
    r"\bouterHTML\b",
    r"\binsertAdjacentHTML\b",
    r"\bdocument\.write",
    r"\beval\s*\(",
    r"\bFunction\s*\(",
    r"\bset(Timeout|Interval)\s*\(\s*['\"`]",
    r"\blocalStorage\b",
    r"\bsessionStorage\b",
    r"\bindexedDB\b",
    r"\bdocument\.cookie\b",
    r"\bXMLHttpRequest\b",
    r"\bWebSocket\b",
    r"\bEventSource\b",
    r"\bsendBeacon\b",
    r"\bimportScripts\b",
    r"\bimport\b",
    r"\bcreateElement\b",
    r"\bsrcdoc\b",
    r"\bDOMParser\b",
    r"\bcreateContextualFragment\b",
    r"\bwindow\.open\b",
    r"\bpostMessage\b",
    r"\blocation\b",
    r"\.href\s*=(?!=)",
    r"\.style\b",
    r"\bcssText\b",
    r"\.on[a-z]+\s*=(?!=)",
]


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_site_js_avoids_forbidden_apis(pattern):
    assert re.search(pattern, source()) is None


def test_the_only_fetch_is_live_json_on_this_site_without_a_cache():
    code = source()
    calls = re.findall(r"\bfetch\s*\(([^;]*)\)\s*;", code)
    assert [" ".join(call.split()) for call in calls] == [
        'LIVE_PATH, { cache: "no-store", signal: AbortSignal.timeout(READ_TIMEOUT_MS), }'
    ]
    assert re.search(r'^const LIVE_PATH = "live\.json";', code, flags=re.MULTILINE)


def test_there_is_no_host_in_the_script():
    code = source()
    assert "http://" not in code
    assert "cloudfront" not in code.lower()
    # The only "https:" is inside the pattern that checks the session URL.
    assert len(re.findall(r"https:", code)) == 1
    assert "https:" in re.search(r"^const URL_RE = .*$", code, flags=re.MULTILINE).group()


def test_the_only_attributes_written_are_the_pressed_state_and_the_checked_href():
    code = source()
    assert re.findall(r"\.setAttribute\s*\(([^;]*)\)\s*;", code) == [
        '"href", live.href',
        '"aria-pressed", i === index ? "true" : "false"',
    ]
    assert re.findall(r"\.removeAttribute\s*\(([^;]*)\)\s*;", code) == ['"href"']


def test_the_script_writes_no_text_and_no_class():
    """Every word a reader sees is in the built page; the script only shows and hides."""
    code = source()
    for pattern in (r"\btextContent\b", r"\binnerText\b", r"\bclassName\b", r"\bclassList\b"):
        assert re.search(pattern, code) is None, pattern


def test_the_built_page_and_the_script_pass_the_redaction_scan(tmp_path):
    _, html = build_site(tmp_path / "site")
    assert scan_text(html) == []
    assert scan_text(JS_PATH.read_text(encoding="utf-8")) == []


def test_it_checks_every_60_seconds():
    code = source()
    assert re.search(r"^const CHECK_MS = 60 \* 1000;", code, flags=re.MULTILINE)
    assert "setInterval(check, CHECK_MS);" in code


def test_the_start_call_waits_for_a_document():
    code = source()
    assert re.search(r'if \(typeof document !== "undefined"\) \{\s*start\(\);\s*\}', code)
    assert re.search(r'if \(typeof module !== "undefined"\) \{\s*module\.exports', code)


# ---- parity with the repo ----


def live_json_fields() -> dict[str, str]:
    """The keys and expressions of the live.json object in envs/dev-console."""
    text = SESSION_TF.read_text(encoding="utf-8")
    block = re.search(r"content = jsonencode\(\{(.*?)\n\s*\}\)", text, flags=re.DOTALL).group(1)
    return dict(re.findall(r"^\s*([a-z]+)\s*=\s*(.+?)\s*$", block, flags=re.MULTILINE))


def test_the_fields_match_what_terraform_writes():
    fields = live_json_fields()
    assert set(fields) == {"schema", "url", "home", "started", "ends"}
    used = set(re.findall(r"\bdata\.([a-z]+)\b", source()))
    assert used == set(fields) - {"started"}  # nothing is decided on the start time
    assert fields["schema"] == "1"
    assert "data.schema !== 1" in source()
    assert fields["url"].startswith('"https://')
    assert re.fullmatch(r'"/[^/"\\][^"\\]*"', fields["home"])


def test_the_script_finds_its_elements_in_the_built_page(tmp_path):
    _, html = build_site(tmp_path / "site")
    code = source()
    wanted = re.findall(r'getElementById\("([a-z-]+)"\)', code)
    assert wanted == ["journey", "live-link"]
    tags = parse(html).tags
    assert [t for t, a in tags if a.get("id") == "live-link"] == ["a"]
    assert [t for t, a in tags if a.get("id") == "journey"] == ["section"]
    selectors = re.findall(r'querySelector(?:All)?\("\[([a-z-]+)\]"\)', code)
    assert set(selectors) == {"data-pick", "data-picker", "data-stepper", "data-step", "data-next"}
    assert len(selectors) == len(re.findall(r"querySelector(?:All)?\(", code))
    for name in selectors:
        assert any(name in a for _, a in tags), name


def test_every_station_button_leads_to_a_panel_with_one_next_button(tmp_path):
    _, html = build_site(tmp_path / "site")
    panels = dict(
        re.findall(r'<article class="panel" id="([^"]+)"(.*?)</article>', html, re.DOTALL)
    )
    steps = [a for a in parse(html).named("button") if "data-step" in a]
    assert [b["aria-controls"] for b in steps] == list(panels)
    ids = list(panels)
    for n, (pid, body) in enumerate(panels.items()):
        assert body.count("data-next") == 1, pid
        # "Next" names the following station of the same run; the last goes back to the first.
        target = ids[n - n % 4 + (n + 1) % 4]
        assert f'data-next aria-controls="{target}"' in body, pid
