"""The replay cases (plan 14.3a): schema, references, no account-like numbers."""

import copy
import json
import re

import pytest
from cerberus_console import config

from cerberus_agents import review
from eval import cases as cases_mod
from eval.cases import CASES_DIR, CaseError, load_cases, resolve_record, validate_case

CASES = load_cases()
LONG_DIGITS = re.compile(r"\d{12}")


def good():
    return copy.deepcopy(next(c for c in CASES if c["case_id"] == "incident_athena_queue"))


def test_case_counts_match_the_plan():
    groups = [c["group"] for c in CASES]
    assert groups.count("incident") == 6
    assert groups.count("clean") == 4
    assert groups.count("synthetic") == 7
    assert len({c["case_id"] for c in CASES}) == len(CASES)


def test_every_real_record_reference_exists():
    for case in CASES:
        name = case["record"] if isinstance(case["record"], str) else case["record"]["base"]
        assert (config.RUNS_DIR / name).is_file(), case["case_id"]
        assert resolve_record(case)["execution"]


def test_every_rule_in_a_label_is_known():
    for case in CASES:
        label = case["label"]
        rules = [i["rule"] for i in label["expect"] + label["required_evidence"]]
        rules += label["expect_absent"] + label["accepted_extra"]
        assert set(rules) <= set(review.RULES), case["case_id"]


def test_no_account_like_number_in_any_case_file():
    for path in CASES_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert not LONG_DIGITS.search(text), path.name
        assert "arn:aws" not in text.lower(), path.name


def test_case_files_hold_no_copied_record():
    for path in CASES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "states" not in data and "data_quality" not in data
        assert path.stat().st_size < 4096, path.name


def test_the_spot_gap_case_is_marked():
    spot = next(c for c in CASES if c["case_id"] == "gap_spot_interruption")
    assert spot["label"]["expect_found"] is False
    assert spot["label"]["reason"] == "not_visible_in_record"
    assert spot["gap"]


def test_synthetic_mutation_changes_only_the_set_path():
    case = next(c for c in CASES if c["case_id"] == "syn_queue_61")
    base = resolve_record({**case, "record": case["record"]["base"]})
    out = resolve_record(case)
    assert out["states"][2]["athena"]["queue_seconds"] == 61
    out["states"][2]["athena"]["queue_seconds"] = base["states"][2]["athena"]["queue_seconds"]
    assert out == base


def test_unknown_check_name_is_dropped_but_the_finding_stays():
    case = next(c for c in CASES if c["case_id"] == "syn_unknown_check_name")
    out = review.review(resolve_record(case), [])
    ev = next(e for e in out["evidence"] if e["rule"] == "dq_errors")
    assert ev["check"] is None and "brand_new_check" not in review.dumps(out)


@pytest.mark.parametrize(
    "edit",
    [
        lambda c: c.pop("source"),
        lambda c: c.update(extra=1),
        lambda c: c.update(case_id="Bad Id"),
        lambda c: c.update(group="other"),
        lambda c: c["label"]["expect"].append({"rule": "no_such_rule"}),
        lambda c: c["label"].update(accepted_extra=["no_such_rule"]),
        lambda c: c["label"].update(expect_none="yes"),
        lambda c: c["label"].update(expect_found=False),  # a gap needs a reason and a gap text
        lambda c: c.update(record="../secret.json"),
        lambda c: c.update(record={"base": "x.json", "set": {"a": 1}, "note": "n"}),
    ],
)
def test_validate_case_rejects_a_bad_case(edit):
    case = good()
    edit(case)
    with pytest.raises(CaseError):
        validate_case(case)


def write(tmp_path, case, name=None):
    (tmp_path / f"{name or case['case_id']}.json").write_text(json.dumps(case), encoding="utf-8")


def test_loader_accepts_a_good_case_and_rejects_bad_files(tmp_path):
    write(tmp_path, good())
    assert [c["case_id"] for c in load_cases(tmp_path)] == ["incident_athena_queue"]

    missing = good()
    missing["case_id"] = "missing_record"
    missing["record"] = "exercise-19990101T000000Z.json"
    write(tmp_path, missing)
    with pytest.raises(CaseError, match="does not exist"):
        load_cases(tmp_path)


def test_loader_rejects_a_twelve_digit_number(tmp_path):
    case = good()
    case["source"] = "account 123456789012"
    write(tmp_path, case)
    with pytest.raises(CaseError, match="12-digit"):
        load_cases(tmp_path)


def test_loader_rejects_a_mutation_path_that_does_not_exist(tmp_path):
    case = next(c for c in CASES if c["case_id"] == "syn_queue_61")
    case = copy.deepcopy(case)
    case["record"]["set"] = {"states.9.athena.queue_seconds": 61}
    write(tmp_path, case)
    with pytest.raises(CaseError, match="does not exist"):
        load_cases(tmp_path)


def test_loader_rejects_a_name_that_differs_from_case_id(tmp_path):
    write(tmp_path, good(), name="other_name")
    with pytest.raises(CaseError, match="file name"):
        load_cases(tmp_path)


def test_loader_rejects_bad_json_and_an_empty_dir(tmp_path):
    with pytest.raises(CaseError, match="no case files"):
        load_cases(tmp_path)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(CaseError, match="not valid JSON"):
        load_cases(tmp_path)


def test_module_exports():
    assert cases_mod.GROUPS == ("incident", "clean", "synthetic")
