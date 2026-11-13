import re

import pytest
from fakes import FAKE_ACCOUNT
from hostile import DATA_STRINGS

from cerberus_console import config, sanitize

ALLOWED = re.compile(r"[\x20-\x7e\n]*")


@pytest.mark.parametrize("raw", DATA_STRINGS)
def test_str_and_text_are_printable_ascii_within_caps(raw):
    s = sanitize.clean_str(raw)
    assert ALLOWED.fullmatch(s)
    assert len(s) <= config.FIELD_CHARS
    t = sanitize.clean_text(raw * 3)
    assert ALLOWED.fullmatch(t)
    assert len(t) <= config.TEXT_BYTES


def test_escape_bytes_become_question_marks():
    assert sanitize.clean_str("\x1b[31m") == "?[31m"
    assert sanitize.clean_str("a\tb") == "a b"


def test_long_field_is_cut_with_ellipsis():
    s = sanitize.clean_str("x" * 500)
    assert len(s) == config.FIELD_CHARS
    assert s.endswith("...")


def test_clean_data_recurses_and_caps_lists():
    data = {"k\x1b": ["a\x1b", {"n": float("nan")}, 3, True, None] + list(range(100))}
    out = sanitize.clean_data(data)
    assert list(out) == ["k?"]
    assert len(out["k?"]) == config.TABLE_ROWS
    assert out["k?"][0] == "a?"
    assert out["k?"][1] == {"n": None}
    assert out["k?"][3] is True


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lone\ud800s", "lone?s"),
        ("\ufeffbom", "?bom"),
        ("e\u0301", "e?"),
        ("\u212a\u017f\u0455", "???"),
        ("\u0661\u0662", "??"),
        ("nel\x85vt\x0bff\x0c", "nel?vt?ff?"),
        ("a\r\nb", "a?\nb"),
        ("%3B' OR 1=1--", "%3B' OR 1=1--"),
        ("\U0001f600", "?"),
    ],
)
def test_exact_output_for_the_new_hostile_families(raw, expected):
    assert sanitize.clean_str(raw) == expected


def test_clean_data_cleans_every_hostile_string_as_key_and_value():
    data = {s: [s, {s: s}] for s in DATA_STRINGS}
    seen = []

    def walk(node):
        if isinstance(node, str):
            seen.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(sanitize.clean_data(data))
    assert seen
    assert all(ALLOWED.fullmatch(s) and len(s) <= config.FIELD_CHARS for s in seen)


@pytest.mark.xfail(strict=True, reason="known gap, recorded in 9.6c")
def test_a_thirteen_digit_account_is_fully_redacted():
    out = sanitize.clean_str("arn:aws:iam::1234567890123:role/x")
    assert not re.search(r"<ACCOUNT_ID>\d", out)


@pytest.mark.xfail(strict=True, reason="known gap, recorded in 9.6c")
def test_a_twelve_digit_s3_bucket_name_is_redacted():
    assert "123456789012" not in sanitize.clean_str("arn:aws:s3:::123456789012-data")


def test_account_id_in_arn_is_redacted():
    arn = f"arn:aws:states:us-east-1:{FAKE_ACCOUNT}:execution:x"
    out = sanitize.clean_str(arn)
    assert FAKE_ACCOUNT not in out
    assert out == "arn:aws:states:us-east-1:<ACCOUNT_ID>:execution:x"
    assert FAKE_ACCOUNT not in sanitize.clean_text(f"see {arn}")
