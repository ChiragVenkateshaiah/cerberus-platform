"""Output sanitising (ADR 0024 rule 4). Applied to `text` and to every string in `data`.

Only printable ASCII 0x20-0x7E and newline survive. A tab becomes a space and
every other character becomes "?". That removes ESC/CSI/OSC (including OSC 52),
C1 controls, DEL, NUL, bidi overrides, zero-width characters and U+2028/U+2029.
"""

import math
import re

from cerberus_console import config

_ARN_ACCOUNT = re.compile(r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)\d{12}")
TRUNCATED = "(truncated)"


def _chars(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\t":
            out.append(" ")
        elif ch == "\n" or " " <= ch <= "~":
            out.append(ch)
        else:
            out.append("?")
    # Backstop: ARNs are not rendered, but if one slips in, hide the account.
    return _ARN_ACCOUNT.sub(r"\1<ACCOUNT_ID>", "".join(out))


def clean_str(s: str, cap: int = config.FIELD_CHARS) -> str:
    s = _chars(s)
    return s if len(s) <= cap else s[: cap - 3] + "..."


def clean_text(s: str) -> str:
    s = _chars(s)
    if len(s) <= config.TEXT_BYTES:
        return s
    return s[: config.TEXT_BYTES - len(TRUNCATED) - 1] + "\n" + TRUNCATED


def clean_data(obj):
    """Recursively clean a JSON-shaped value. Lists are cut at the table cap."""
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, bool) or obj is None or isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {clean_str(str(k)): clean_data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_data(v) for v in list(obj)[: config.TABLE_ROWS]]
    return clean_str(str(obj))
