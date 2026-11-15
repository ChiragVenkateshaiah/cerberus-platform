"""The live-check harness (plan 2026-11-15): the pure parts only. No network, no Playwright."""

import json
import sys
from datetime import UTC, datetime

import pytest
from test_edge_config import COGNITO_URL, EDGE_HEADERS

from cerberus_console import grammar
from cerberus_live_check import report
from cerberus_live_check.redact import redact

HOSTS = {"d111abc.cloudfront.net": "<standing-cf>", "d222def.cloudfront.net": "<session-cf>"}
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


# --- redaction -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://d111abc.cloudfront.net/x", "https://<standing-cf>/x"),
        ("https://d222def.cloudfront.net/", "https://<session-cf>/"),
        ("account 123456789012 here", "account <ACCOUNT_ID> here"),
        ("pool us-east-1_AbC123xyz", "pool <POOL_ID>"),
        ("tok eyJhbGciOi.eyJzdWIiOi.sig_-x end", "tok <TOKEN> end"),
        ("sub 123e4567-e89b-12d3-a456-426614174000.", "sub <UUID>."),
        ("?code=abc123&state=xyz", "?code=<redacted>&state=<redacted>"),
        ("client_id=7abc&redirect_uri=https://x/y", "client_id=<redacted>&redirect_uri=<redacted>"),
    ],
)
def test_redact_each_pattern(raw, expected):
    assert redact(raw, HOSTS) == expected


def test_redact_is_idempotent():
    raw = "https://d111abc.cloudfront.net/?code=a&state=b 123456789012 us-east-1_Pool1 x"
    once = redact(raw, HOSTS)
    assert redact(once, HOSTS) == once


def test_redact_keeps_public_values():
    assert redact(COGNITO_URL, HOSTS) == COGNITO_URL
    for value in EDGE_HEADERS.values():
        assert redact(value, HOSTS) == value


# --- headers ---------------------------------------------------------------------


def test_headers_match():
    assert report.compare_headers(dict(EDGE_HEADERS), EDGE_HEADERS).status == "pass"


def test_headers_wrong_value():
    seen = {**EDGE_HEADERS, "x-frame-options": "SAMEORIGIN"}
    check = report.compare_headers(seen, EDGE_HEADERS)
    assert check.status == "fail"
    assert "x-frame-options" in check.observed


def test_headers_missing_key():
    seen = {k: v for k, v in EDGE_HEADERS.items() if k != "referrer-policy"}
    check = report.compare_headers(seen, EDGE_HEADERS)
    assert check.status == "fail"
    assert "referrer-policy: missing" in check.observed


def test_headers_upper_case_name_and_extra_header():
    seen = {k.upper(): v for k, v in EDGE_HEADERS.items()} | {"X-Cache": "Miss from cloudfront"}
    assert report.compare_headers(seen, EDGE_HEADERS).status == "pass"


# --- the typed lines and the commands ----------------------------------------------


def test_every_typed_line_is_refused_like_the_terminal_tokenises_it():
    typed = report.typed_lines()
    assert len(typed) == 1 + len(report.HOSTILE_NAMES) + 2
    for t in typed:
        with pytest.raises(grammar.Refused):
            grammar.parse_argv(report.tokenise(t.line))


def test_long_line_lengths():
    assert report.long_line_lengths() == (519, 520)
    by_name = {t.name: t for t in report.typed_lines()}
    assert len(by_name["519 characters"].line) == 519
    cut = by_name["520 characters (cut by maxlength)"]
    assert len(cut.line) == 520
    assert len(cut.expected_value) == 519


def test_typed_lines_keep_the_unicode_cases_exact():
    lines = {t.name: t.line for t in report.typed_lines()}
    assert lines["fullwidth"] == "ｓｔａｔｕｓ"
    assert lines["zero width"] == "sta​tus"
    assert lines["shell"] == "status; id"


def test_commands_all_parse():
    cmds = report.commands()
    assert set(grammar.COMMANDS) == {c.split()[0] for c in cmds}
    assert "run latest" in cmds
    for cmd in cmds:
        grammar.parse_argv(cmd.split())


# --- live.json -------------------------------------------------------------------


def _live(**over):
    base = {
        "schema": 1,
        "url": "https://d222def.cloudfront.net/",
        "home": "/d/cerberus-runs",
        "started": "2026-11-15T11:00:00Z",
        "ends": "2026-11-15T13:00:00Z",
    }
    return json.dumps({**base, **over})


def test_parse_live_future_is_ready():
    ready, info, _ = report.parse_live(_live(), NOW)
    assert ready
    assert info["url"].startswith("https://")


def test_parse_live_past_is_stale():
    ready, _, reason = report.parse_live(_live(ends="2026-11-15T11:30:00Z"), NOW)
    assert not ready
    assert "past" in reason


def test_parse_live_missing_key():
    data = json.loads(_live())
    del data["ends"]
    assert not report.parse_live(json.dumps(data), NOW)[0]


def test_parse_live_http_url_and_bad_schema_and_junk():
    assert not report.parse_live(_live(url="http://x/"), NOW)[0]
    assert not report.parse_live(_live(schema=2), NOW)[0]
    assert not report.parse_live("{nope", NOW)[0]


# --- the report writer ---------------------------------------------------------------


def test_write_redacts_and_returns_the_exit_code(tmp_path):
    checks = [report.Check("A", "pass", "x", "https://d111abc.cloudfront.net/ 123456789012")]
    assert report.write(tmp_path, checks, "", HOSTS) == 0
    text = (tmp_path / "report.md").read_text() + (tmp_path / "report.json").read_text()
    assert "d111abc" not in text
    assert "123456789012" not in text
    assert report.write(tmp_path / "two", [report.Check("B", "fail")], "", HOSTS) == 1


def test_write_refuses_when_the_secret_is_present(tmp_path):
    checks = [report.Check("A", "fail", "x", "oops hunter2-secret leaked")]
    assert report.write(tmp_path / "out", checks, "hunter2-secret", HOSTS) == 2
    assert not (tmp_path / "out").exists()


def test_check_rejects_an_unknown_status():
    with pytest.raises(ValueError, match="bad status"):
        report.Check("A", "maybe")


# --- CI must not need Playwright ---------------------------------------------------


def test_importing_the_package_does_not_import_playwright():
    from cerberus_live_check import __main__, browser, http, shared, verify, watch

    assert all([__main__, browser, http, shared, verify, watch])
    assert "playwright" not in sys.modules


def test_write_refuses_when_the_secret_appears_only_after_redaction(tmp_path):
    # The raw text holds a 12-digit number; redaction turns it into "<ACCOUNT_ID>".
    checks = [report.Check("A", "pass", "x", "id 123456789012")]
    assert report.write(tmp_path / "out", checks, "<ACCOUNT_ID>", HOSTS) == 2
    assert not (tmp_path / "out").exists()


def test_get_password_is_none_with_no_sign_in_even_if_the_env_var_is_set(monkeypatch):
    from cerberus_live_check import verify

    monkeypatch.setenv(verify.PASSWORD_ENV, "not-a-real-password")
    assert verify.get_password(True) is None


def test_shot_never_screenshots_a_cognito_page(tmp_path):
    from cerberus_live_check import browser

    class Page:
        url = "https://cerberus-console.auth.us-east-1.amazoncognito.com/login?x=1"
        calls = 0

        def screenshot(self, **_kwargs):
            Page.calls += 1

    assert browser.shot(Page(), tmp_path, "x") == ""
    assert Page.calls == 0


def test_on_cognito_checks_the_host_not_the_query_string():
    from cerberus_live_check import browser

    assert browser.on_cognito(COGNITO_URL + "/login")
    assert not browser.on_cognito("https://d111abc.cloudfront.net/?redirect_uri=" + COGNITO_URL)
