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
# The check names found in the committed run records (data_quality.checks). A new
# check name must be added here, or it reads as `unknown_check` in the tools and is
# skipped by the review core. `new_run[dt=DAY]` is one check per day (DAY_CHECK).
KNOWN_CHECKS = frozenset(
    {
        "amount_range_and_stability",
        "bronze_to_silver_count",
        "bronze_to_silver_keys",
        "bulk_duplicate_keys",
        "bulk_ledger_integrity",
        "bulk_run_counts",
        "bulk_runs_without_manifest",
        "gold_status_matches_lifecycle",
        "lambda_keys_in_silver",
        "lifecycle_created_authorized",
        "lifecycle_one_terminal",
        "lifecycle_order",
        "lifecycle_refunds",
        "masking",
        "roster",
        "silver_caught_up",
        "silver_duplicate_keys",
        "silver_key_nulls",
        "silver_partition_placement",
        "silver_to_gold_transactions",
        "token_digit_runs",
        "token_format",
    }
)
DAY_CHECK = re.compile(r"new_run\[dt=\d{4}-\d{2}-\d{2}\]", re.ASCII)
UNKNOWN_CHECK = "unknown_check"
# Execution names in the committed records: a kind, up to 3 short segments, then a
# UTC stamp (the Z is missing on one old record).
EXECUTION_NAME = re.compile(
    r"(exercise|demo|rehearsal)(-[a-z0-9]{1,8}){0,3}-\d{8}T\d{6}Z?", re.ASCII
)
_LONG_DIGITS = re.compile(r"\d{12,}")


def _plain(value, pattern):
    if type(value) is not str or not pattern.fullmatch(value) or _LONG_DIGITS.search(value):
        return None
    return value


def execution_token(value):
    """The execution name when it has the committed shape and is a console token, else None."""
    if _plain(value, grammar._TOKEN) is None:
        return None
    return _plain(value, EXECUTION_NAME)


def check_name(value):
    """A known check name, else None."""
    if type(value) is str and (value in KNOWN_CHECKS or DAY_CHECK.fullmatch(value)):
        return value
    return None


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
