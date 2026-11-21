"""The scorer and answerers (plan 14.3a): the ADR 0025 bar, a failing answerer, mutations."""

import copy

from eval import score
from eval.__main__ import main
from eval.answerers import ANSWERERS, bad_answerer, echo_answerer
from eval.cases import load_cases

CASES = load_cases()


def by_id(report, case_id):
    return next(r for r in report["cases"] if r["case_id"] == case_id)


def test_echo_answerer_passes_the_adr_bar():
    report = score.run(echo_answerer, CASES)
    assert report["bar"]["passed"] is True
    assert report["incidents"]["found"] == 5 and report["incidents"]["total"] == 6
    assert report["clean"]["false_findings"] == 0
    assert report["citations"]["validity"] == 1.0
    assert report["determinism"] == {
        "repeats": 3,
        "distinct_outputs": 1,
        "same_bytes": True,
        "digest": report["determinism"]["digest"],
    }
    assert [r["case_id"] for r in report["cases"] if r["status"] == "fail"] == []


def test_bad_answerer_fails_cited_claim_validity():
    report = score.run(bad_answerer, CASES)
    assert report["citations"]["claims"] > 0
    assert report["citations"]["valid"] == 0
    assert report["bar"]["cited_claims"] is False
    assert report["bar"]["passed"] is False


def test_bad_answerer_cites_an_invented_id():
    out = bad_answerer(
        {"findings": [{"rule": "run_failed", "evidence": ["e1"]}], "evidence": []}, {}
    )
    assert out["claims"][0]["evidence"] == ["e99"]


def test_a_claim_without_an_id_is_not_valid():
    assert not score.claim_is_valid({"rule": "run_failed", "evidence": []}, {"e1"})
    assert not score.claim_is_valid({"rule": "run_failed"}, {"e1"})
    assert not score.claim_is_valid({"rule": "run_failed", "evidence": ["e1", "e2"]}, {"e1"})
    assert score.claim_is_valid({"rule": "run_failed", "evidence": ["e1"]}, {"e1"})


def test_a_malformed_answer_does_not_crash_and_fails():
    report = score.run(lambda review_obj, case: {"claims": "nope"}, CASES)
    assert report["citations"]["claims"] == 0
    assert report["bar"]["passed"] is False  # no claims: nothing is found, nothing is cited


def test_the_spot_gap_is_reported_and_not_counted_as_found():
    report = score.run(echo_answerer, CASES)
    assert by_id(report, "gap_spot_interruption")["status"] == "gap"
    assert "gap_spot_interruption" not in report["incidents"]["found_ids"]
    assert "gap_spot_interruption" in report["incidents"]["gaps"]
    assert "gap_spot_interruption" in report["incidents"]["not_found"]
    text = score.markdown(report)
    assert "known gap: not_visible_in_record; not counted as found" in text


def test_glue_gap_is_documented_but_the_symptom_is_found():
    report = score.run(echo_answerer, CASES)
    assert by_id(report, "incident_glue_timeouts")["status"] == "ok"
    assert by_id(report, "incident_glue_timeouts")["gap"]


def test_accepted_extra_is_not_a_false_finding():
    report = score.run(echo_answerer, CASES)
    case = by_id(report, "incident_failed_1gib_cutoff")
    assert "step_slow" in case["claimed"] and case["extras"] == []


def test_a_mutation_that_reduces_a_label_is_caught():
    # Drop the accepted extra: the 1 GiB case now has an unlabelled claim and is not found.
    cases = copy.deepcopy(CASES)
    case = next(c for c in cases if c["case_id"] == "incident_failed_1gib_cutoff")
    case["label"]["accepted_extra"] = []
    report = score.run(echo_answerer, cases)
    assert by_id(report, "incident_failed_1gib_cutoff")["status"] == "fail"
    assert report["incidents"]["found"] == 4
    assert report["bar"]["incidents"] is False and report["bar"]["passed"] is False


def test_an_unlabelled_claim_on_a_clean_run_counts_as_false_findings():
    # Make a clean run look like it should be silent about a rule the core fires: use
    # a clean-labelled case on a record that has findings.
    cases = copy.deepcopy(CASES)
    case = next(c for c in cases if c["case_id"] == "incident_failed_rundbt")
    case["group"] = "clean"
    case["label"] = {"expect_none": True}
    report = score.run(echo_answerer, cases)
    assert report["clean"]["false_findings"] == 2
    assert report["bar"]["false_findings"] is False


def test_a_wrong_expectation_is_caught():
    cases = copy.deepcopy(CASES)
    case = next(c for c in cases if c["case_id"] == "clean_demo_100m")
    case["label"]["expect"] = [{"rule": "dq_errors"}]
    case["label"]["expect_none"] = False
    report = score.run(echo_answerer, cases)
    assert by_id(report, "clean_demo_100m")["status"] == "fail"
    assert "dq_errors" in by_id(report, "clean_demo_100m")["missing"]


def test_required_evidence_must_match_the_cited_item():
    cases = copy.deepcopy(CASES)
    case = next(c for c in cases if c["case_id"] == "incident_athena_queue")
    case["label"]["required_evidence"][0]["fields"]["queue_seconds"] = 1.0
    report = score.run(echo_answerer, cases)
    assert by_id(report, "incident_athena_queue")["status"] == "fail"


def test_the_synthetic_boundaries_hold():
    report = score.run(echo_answerer, CASES)
    for cid in ("syn_queue_59", "syn_queue_60", "syn_rundbt_169s"):
        assert by_id(report, cid)["claimed"] == []
    assert by_id(report, "syn_queue_61")["claimed"] == ["athena_queue"]
    assert by_id(report, "syn_rundbt_170s")["claimed"] == ["step_slow"]


def test_per_rule_metrics_are_present_and_exact():
    rules = score.run(echo_answerer, CASES)["rules"]
    for rule in ("run_failed", "dq_errors", "step_slow", "athena_queue"):
        assert rules[rule]["precision"] == 1.0 and rules[rule]["recall"] == 1.0


def test_same_input_same_bytes():
    a = score.dumps(score.run(echo_answerer, CASES))
    b = score.dumps(score.run(echo_answerer, load_cases()))
    assert a == b


def test_the_report_names_the_label_limit():
    text = score.markdown(score.run(echo_answerer, CASES))
    assert "not a recall estimate" in text


def test_command_line_exit_codes(capsys):
    assert main([]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["--answerer", "bad", "--json"]) == 1
    assert '"cited_claims": false' in capsys.readouterr().out


def test_answerer_registry():
    assert set(ANSWERERS) == {"echo", "bad"}
