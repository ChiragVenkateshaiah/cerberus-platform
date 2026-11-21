"""The replay cases (plan 14.3): format, loader and validation.

A case names a run record and says what a correct review must claim about it.
Real records are referenced by file name in observability/scale/runs; they are
never copied. A synthetic case is `{base, set: {path: value}, note}`: a real
record with a documented change, to test a threshold edge.

    case = {case_id, group, record, label, source, gap}
    label = {expect[{rule, step?}], expect_absent[rule], expect_none, accepted_extra[rule],
             required_evidence[{rule, fields}], expect_found?, reason?}

`group` is `incident` (one of the six in ADR 0025), `clean` or `synthetic`.
`label.expect_found: false` marks a known gap: the record cannot show the incident,
so the case is reported as a gap and never counts as found.
"""

import copy
import json
import re
from pathlib import Path

from cerberus_console import config

from cerberus_agents.review import RULES

CASES_DIR = Path(__file__).resolve().parent / "cases"
GROUPS = ("incident", "clean", "synthetic")
CASE_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")
LONG_DIGITS = re.compile(r"\d{12}")
RECORD_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json")
LABEL_KEYS = {
    "expect",
    "expect_absent",
    "expect_none",
    "accepted_extra",
    "required_evidence",
    "expect_found",
    "reason",
}
CASE_KEYS = {"case_id", "group", "record", "label", "source", "gap"}


class CaseError(ValueError):
    """A case file breaks the format."""


def _check(cond, name, message):
    if not cond:
        raise CaseError(f"{name}: {message}")


def _rule_list(value, name, what):
    _check(isinstance(value, list), name, f"{what} must be a list")
    for rule in value:
        _check(rule in RULES, name, f"unknown rule id in {what}: {rule!r}")


def validate_label(label, name):
    _check(isinstance(label, dict), name, "label must be an object")
    _check(set(label) <= LABEL_KEYS, name, f"unknown label keys {sorted(set(label) - LABEL_KEYS)}")
    expect = label.get("expect", [])
    _check(isinstance(expect, list), name, "expect must be a list")
    for item in expect:
        _check(isinstance(item, dict) and set(item) <= {"rule", "step"}, name, "bad expect item")
        _check(item.get("rule") in RULES, name, f"unknown rule id in expect: {item.get('rule')!r}")
        _check(isinstance(item.get("step", ""), str), name, "expect step must be a string")
    _rule_list(label.get("expect_absent", []), name, "expect_absent")
    _rule_list(label.get("accepted_extra", []), name, "accepted_extra")
    _check(isinstance(label.get("expect_none", False), bool), name, "expect_none must be a bool")
    _check(isinstance(label.get("expect_found", True), bool), name, "expect_found must be a bool")
    reason = label.get("reason")
    _check(reason is None or isinstance(reason, str), name, "reason must be a string")
    req = label.get("required_evidence", [])
    _check(isinstance(req, list), name, "required_evidence must be a list")
    for item in req:
        _check(isinstance(item, dict) and set(item) == {"rule", "fields"}, name, "bad evidence")
        _check(
            item["rule"] in RULES, name, f"unknown rule id in required_evidence: {item['rule']!r}"
        )
        _check(isinstance(item["fields"], dict), name, "required_evidence fields must be an object")
    if label.get("expect_none"):
        _check(not expect, name, "expect_none and expect cannot both be set")
    if label.get("expect_found", True) is False:
        _check(bool(reason), name, "a gap case (expect_found false) needs a reason")


def validate_case(case, name="case"):
    """Schema check of one parsed case. Raises CaseError."""
    _check(isinstance(case, dict), name, "a case must be an object")
    _check(set(case) == CASE_KEYS, name, f"keys must be exactly {sorted(CASE_KEYS)}")
    _check(
        isinstance(case["case_id"], str) and CASE_ID.fullmatch(case["case_id"]),
        name,
        "bad case_id",
    )
    _check(case["group"] in GROUPS, name, f"group must be one of {GROUPS}")
    _check(isinstance(case["source"], str) and case["source"], name, "source is required")
    _check(case["gap"] is None or isinstance(case["gap"], str), name, "gap is null or a string")
    record = case["record"]
    if isinstance(record, str):
        _check(RECORD_FILE.fullmatch(record) is not None, name, "bad record file name")
    else:
        _check(
            isinstance(record, dict) and set(record) == {"base", "set", "note"},
            name,
            "a synthetic record is {base, set, note}",
        )
        _check(RECORD_FILE.fullmatch(str(record["base"])) is not None, name, "bad base file name")
        _check(isinstance(record["set"], dict) and record["set"], name, "set must be an object")
        _check(isinstance(record["note"], str) and record["note"], name, "note is required")
    _check(
        (case["group"] == "synthetic") == isinstance(record, dict),
        name,
        "synthetic group and a mutation record go together",
    )
    validate_label(case["label"], name)
    if case["label"].get("expect_found", True) is False:
        _check(bool(case["gap"]), name, "a gap case needs a gap text")


def _set_path(record, path, value, name):
    parts = path.split(".")
    node = record
    for part in parts[:-1]:
        node = _step(node, part, path, name)
    last = parts[-1]
    if isinstance(node, list):
        _check(last.isdigit() and int(last) < len(node), name, f"path {path} does not exist")
        node[int(last)] = value
    else:
        _check(isinstance(node, dict) and last in node, name, f"path {path} does not exist")
        node[last] = value


def _step(node, part, path, name):
    if isinstance(node, list):
        _check(part.isdigit() and int(part) < len(node), name, f"path {path} does not exist")
        return node[int(part)]
    _check(isinstance(node, dict) and part in node, name, f"path {path} does not exist")
    return node[part]


def read_record(file_name, runs_dir):
    path = Path(runs_dir) / file_name
    _check(path.is_file(), file_name, "referenced record does not exist")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_record(case, runs_dir=None):
    """The run record of a case: the named file, or the base with the mutation applied."""
    runs_dir = config.RUNS_DIR if runs_dir is None else runs_dir
    record = case["record"]
    if isinstance(record, str):
        return read_record(record, runs_dir)
    out = copy.deepcopy(read_record(record["base"], runs_dir))
    for path, value in record["set"].items():
        _set_path(out, path, value, case["case_id"])
    return out


def load_cases(cases_dir=None, runs_dir=None):
    """All cases, sorted by case_id. Raises CaseError on the first bad case."""
    cases_dir = CASES_DIR if cases_dir is None else Path(cases_dir)
    cases, seen = [], set()
    files = sorted(cases_dir.glob("*.json"))
    _check(bool(files), str(cases_dir), "no case files")
    for path in files:
        text = path.read_text(encoding="utf-8")
        _check(not LONG_DIGITS.search(text), path.name, "a 12-digit number is not allowed")
        try:
            case = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CaseError(f"{path.name}: not valid JSON ({exc.msg})") from None
        validate_case(case, path.name)
        _check(case["case_id"] == path.stem, path.name, "case_id must equal the file name")
        _check(case["case_id"] not in seen, path.name, "duplicate case_id")
        seen.add(case["case_id"])
        resolve_record(case, runs_dir)  # the file exists and every mutation path resolves
        cases.append(case)
    return sorted(cases, key=lambda c: c["case_id"])
