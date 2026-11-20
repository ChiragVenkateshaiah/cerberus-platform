"""The alert rules and the Alertmanager template (plan 10.4a).

promtool (`make alerts-test`) proves what the rules do. These tests prove the
rules follow the query-set contract and that the files hold no account ID.
Needs PyYAML (requirements-dev.txt). No AWS, no Docker.
"""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from cerberus_console import config, queries

ALERTS = Path(__file__).resolve().parents[2] / "observability" / "alerts"
RULES = ALERTS / "status.rules.yaml"
TEMPLATE = ALERTS / "alertmanager.yaml.tftpl"
EXECUTION = "{{ $labels.execution }}"
NO_EXECUTION = {"CerberusErrorBudgetBurn"}  # the budget alert names no run
SEVERITIES = {"page", "ticket", "info"}
SUBJECT_MAX = 100  # the SNS subject limit
SUBJECT_PREFIX = "[Cerberus RESOLVED] "  # the longest status prefix


@pytest.fixture(scope="module")
def doc() -> dict:
    return queries.load(config.QUERIES_FILE)


@pytest.fixture(scope="module")
def groups() -> list[dict]:
    return yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]


@pytest.fixture(scope="module")
def rules(groups) -> list[dict]:
    return [r for g in groups for r in g["rules"]]


def test_one_group_with_five_rules(groups, rules):
    assert [g["name"] for g in groups] == ["cerberus-status"]
    assert groups[0]["interval"] == "60s"
    assert [r["alert"] for r in rules] == [
        "CerberusRunFailed",
        "CerberusDataQualityErrors",
        "CerberusRunNeverReported",
        "CerberusErrorBudgetBurn",
        "CerberusAlertPathCheck",
    ]


def test_no_recording_rules(rules):
    assert all("alert" in r and "record" not in r for r in rules)


def test_rule_names_are_unique(rules):
    names = [r["alert"] for r in rules]
    assert len(names) == len(set(names))


def test_every_expr_passes_check_rule_expr(rules, doc):
    for rule in rules:
        assert queries.check_rule_expr(rule["expr"], doc) == [], rule["alert"]


def test_every_expr_uses_a_query_set_entry_or_the_smoke_series(rules, doc):
    entries = [queries.normalise(q["expr"]) for q in doc["queries"]]
    for rule in rules:
        expr = queries.normalise(rule["expr"])
        if rule["alert"] == "CerberusAlertPathCheck":
            assert "cerberus_publisher_smoke" in expr  # not a catalogue metric
            continue
        assert any(e in expr for e in entries), rule["alert"]


def test_every_rule_has_for_and_severity(rules):
    for rule in rules:
        assert "for" in rule, rule["alert"]
        assert rule["labels"]["severity"] in SEVERITIES, rule["alert"]
    by_name = {r["alert"]: r for r in rules}
    assert by_name["CerberusRunFailed"]["for"] == "2m"
    assert by_name["CerberusDataQualityErrors"]["for"] == "2m"
    assert by_name["CerberusRunFailed"]["labels"]["severity"] == "page"
    assert by_name["CerberusRunNeverReported"]["labels"]["severity"] == "page"
    assert by_name["CerberusDataQualityErrors"]["labels"]["severity"] == "ticket"
    assert by_name["CerberusErrorBudgetBurn"]["labels"]["severity"] == "ticket"
    assert by_name["CerberusAlertPathCheck"]["labels"]["severity"] == "info"


def test_annotations_name_the_run(rules):
    for rule in rules:
        text = " ".join(rule["annotations"].values())
        assert rule["annotations"]["summary"] and rule["annotations"]["description"]
        if rule["alert"] in NO_EXECUTION:
            assert EXECUTION not in text, rule["alert"]
        else:
            assert EXECUTION in rule["annotations"]["description"], rule["alert"]


def test_run_alerts_carry_the_commands(rules):
    for rule in rules:
        if rule["alert"] in NO_EXECUTION | {"CerberusAlertPathCheck"}:
            continue
        description = rule["annotations"]["description"]
        assert f"cerberus run {EXECUTION}" in description, rule["alert"]
        assert f"make review RUN={EXECUTION}" in description, rule["alert"]


def test_every_join_is_explicit(rules):
    for rule in rules:
        expr = rule["expr"]
        for word in re.findall(r"\)\s+(and|or|unless)\s+(\w*)", expr):
            assert word[1] == "on", (rule["alert"], word)
        assert "ignoring(" not in expr
        if "group_left" in expr:
            assert "on() group_left(execution)" in expr, rule["alert"]


def test_alert_names_keep_the_subject_short(rules):
    # The subject is "[Cerberus RESOLVED] <alertname> <execution>"; the longest
    # run name in the repo must fit under the SNS limit.
    runs = ALERTS.parent / "scale" / "runs"
    longest_run = max(len(p.stem) for p in runs.glob("*.json"))
    for rule in rules:
        assert len(SUBJECT_PREFIX) + len(rule["alert"]) + 1 + longest_run <= SUBJECT_MAX


# the Alertmanager template


def load_render():
    spec = importlib.util.spec_from_file_location(
        "render_alertmanager", ALERTS / "render_alertmanager.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_template_has_only_the_topic_arn_variable():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert set(re.findall(r"\$\{(\w+)\}", text)) == {"topic_arn"}
    assert "%{" not in text


def test_template_and_rules_hold_no_account_id():
    for path in (TEMPLATE, RULES, ALERTS / "README.md", ALERTS / "render_alertmanager.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\d{12}", text), path.name
        assert "arn:aws" not in text.replace(load_render().DUMMY_ARN, ""), path.name


def test_rendered_definition_routes_to_sns_with_sigv4():
    render = load_render()
    definition = render.render("arn:aws:sns:us-east-1:dummy:topic")
    config_ = yaml.safe_load(definition["alertmanager_config"])
    (receiver,) = config_["receivers"]
    (sns,) = receiver["sns_configs"]
    assert sns["topic_arn"] == "arn:aws:sns:us-east-1:dummy:topic"
    assert sns["sigv4"] == {"region": "us-east-1"}
    assert sns["send_resolved"] is True
    assert config_["route"]["receiver"] == receiver["name"]
    assert config_["templates"] == list(definition["template_files"])


def test_template_defines_subject_and_message_with_execution():
    definition = load_render().render("arn:aws:sns:us-east-1:dummy:topic")
    body = definition["template_files"]["cerberus_sns"]
    assert 'define "cerberus.sns.subject"' in body
    assert 'define "cerberus.sns.message"' in body
    assert ".CommonLabels.execution" in body
    assert ".CommonLabels.alertname" in body


def test_route_timing_limits_repeat_emails():
    definition = load_render().render("arn:aws:sns:us-east-1:dummy:topic")
    route = yaml.safe_load(definition["alertmanager_config"])["route"]
    assert route["group_wait"] == "30s"
    assert route["group_interval"] == "5m"
    assert route["repeat_interval"] == "24h"


def test_subject_truncates_the_execution():
    body = load_render().render("arn:aws:sns:us-east-1:dummy:topic")["template_files"][
        "cerberus_sns"
    ]
    # `make alerts-test` renders a 80-character execution through amtool; here the
    # literal is checked: the 46-character fixed part plus 50 is under 100.
    assert '{{ printf "%.50s" . }}' in body
    assert len("[Cerberus RESOLVED] CerberusDataQualityErrors ") + 50 <= SUBJECT_MAX


def test_never_reported_counts_a_missing_finish_as_time_zero(rules):
    expr = next(r for r in rules if r["alert"] == "CerberusRunNeverReported")["expr"]
    assert "or on() vector(0)" in expr
