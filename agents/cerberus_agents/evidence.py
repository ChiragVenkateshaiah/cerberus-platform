"""Evidence: only allowlisted tokens and numbers reach the review output.

A record is untrusted text. A string from it passes only if it is a step name
from the state machine, a fixed status, or a name that matches a strict
pattern. Anything else becomes None.
"""

import importlib.util
import re
import sys
from pathlib import Path

from cerberus_console import grammar

# series.py is stdlib only, so it loads by file path (no boto3, no package). This
# dynamic load of a fixed, repo-relative path is deliberate: it keeps the review
# core on the same code as the publisher, so the two cannot drift.
_SERIES = Path(__file__).resolve().parents[2] / "observability" / "status" / "series.py"
_spec = importlib.util.spec_from_file_location("cerberus_status_series", _SERIES)
series = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = series
_spec.loader.exec_module(series)

STEPS = tuple(series.STEPS)
STATUSES = ("SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT")
CHECK_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_LONG_DIGITS = re.compile(r"\d{12,}")


def _plain(value, pattern):
    if type(value) is not str or not pattern.fullmatch(value) or _LONG_DIGITS.search(value):
        return None
    return value


def execution_token(value):
    """The execution name when it is a console token with no 12-digit run, else None."""
    return _plain(value, grammar._TOKEN)


def check_name(value):
    return _plain(value, CHECK_NAME)


def step_name(value):
    return value if type(value) is str and value in STEPS else None


def status_token(value):
    return value if type(value) is str and value in STATUSES else None


def rounded(value):
    """Floats to 3 decimals so the output bytes do not depend on float noise."""
    return round(value, 3) if isinstance(value, float) else value


class Evidence:
    """An ordered list of evidence items with ids e1, e2, ..."""

    def __init__(self):
        self.items = []

    def add(self, rule, **fields):
        item = {"id": f"e{len(self.items) + 1}", "rule": rule}
        item.update({k: rounded(v) for k, v in fields.items()})
        self.items.append(item)
        return item["id"]
