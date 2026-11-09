import re

import pytest
from fakes import FAKE_ACCOUNT

from cerberus_console import config, sanitize

ALLOWED = re.compile(r"[\x20-\x7e\n]*")

HOSTILE = [
    "\x1b[31mred",
    "\x1b]52;c;SGVsbG8=\x07",
    "\x1b]8;;http://x\x1b\\link",
    "\x9b31m",
    "a\x7fb",
    "\u202eevil",
    "a\u2028b\u2029c",
    "nul\x00byte",
    "zero\u200bwidth",
    "x" * 10000,
]


@pytest.mark.parametrize("raw", HOSTILE)
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


def test_account_id_in_arn_is_redacted():
    arn = f"arn:aws:states:us-east-1:{FAKE_ACCOUNT}:execution:x"
    out = sanitize.clean_str(arn)
    assert FAKE_ACCOUNT not in out
    assert out == "arn:aws:states:us-east-1:<ACCOUNT_ID>:execution:x"
    assert FAKE_ACCOUNT not in sanitize.clean_text(f"see {arn}")
