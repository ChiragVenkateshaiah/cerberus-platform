"""The named query set: the real file lints, dashboards use it, bad input fails by name."""

import copy
import json
from pathlib import Path

import pytest

from cerberus_console import config, queries

FIXTURES = Path(__file__).parent / "fixtures" / "queries"
REPO = Path(__file__).resolve().parents[2]
DASHBOARDS = sorted((REPO / "observability" / "grafana" / "dashboards").glob("*.json"))


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def doc() -> dict:
    return queries.load(config.QUERIES_FILE)


def entry(doc: dict, name: str) -> str:
    return next(q["expr"] for q in doc["queries"] if q["name"] == name)


def test_default_path_is_the_repo_file():
    assert config.QUERIES_FILE == REPO / "observability" / "queries" / "status.json"


def test_real_file_passes_lint(doc):
    assert queries.lint(doc) == []


def test_real_file_has_the_plan_entries(doc):
    assert len(doc["queries"]) == 17
    assert len(doc["metrics"]) == 14
    assert {m["scope"] for m in doc["metrics"]} == {"latest", "detail", "execution"}
    labels = {m["name"]: m["labels"] for m in doc["metrics"] if m["labels"]}
    assert labels == {
        "cerberus_run_step_failed": ["step"],
        "cerberus_step_duration_seconds": ["step"],
        "cerberus_run_info": ["execution"],
        "cerberus_execution_started_timestamp_seconds": ["execution"],
        "cerberus_execution_finished_timestamp_seconds": ["execution"],
    }


def test_there_are_dashboards_to_check():
    assert DASHBOARDS


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_every_repo_dashboard_passes(path, doc):
    assert queries.check_dashboard(json.loads(path.read_text(encoding="utf-8")), doc) == []


def test_dashboard_ok_fixture_passes(doc):
    assert queries.check_dashboard(fixture("dashboard_ok.json"), doc) == []


def test_hand_edited_dashboard_fails(doc):
    errors = queries.check_dashboard(fixture("dashboard_hand_edited.json"), doc)
    assert len(errors) == 1
    assert "'Status 7d'" in errors[0]
    assert "cerberus_run_status" in errors[0]
    assert "not a query-set entry" in errors[0]


def test_panel_nested_in_a_row_is_checked(doc):
    errors = queries.check_dashboard(fixture("dashboard_nested_row.json"), doc)
    assert len(errors) == 1
    assert "'Hidden dq'" in errors[0]


def test_untagged_panel_cannot_escape(doc):
    errors = queries.check_dashboard(fixture("dashboard_untagged_uses_status_metric.json"), doc)
    assert len(errors) == 1
    assert "'Untagged status'" in errors[0]


def test_bad_window_fixture_fails_with_named_messages():
    errors = queries.lint(fixture("status_bad_window.json"))
    text = "\n".join(errors)
    assert "queries: bare_status: window: cerberus_run_status must sit directly inside" in text
    assert "queries: wrong_window: window: cerberus_run_status inside last_over_time" in text
    assert "must use [30d], not [7d]" in text
    assert "queries: wrong_func: window:" in text


def test_normalise_keeps_spaces_inside_quotes():
    assert queries.normalise('a{step = "Run Dbt"} == 1') == 'a{step="Run Dbt"}==1'
    assert queries.normalise('x{a="p \\" q"}  + y') == 'x{a="p \\" q"}+y'
    assert queries.normalise("  last_over_time( m [30d] )\n") == "last_over_time(m[30d])"


def test_normalised_exprs_compare_equal(doc):
    spaced = "( last_over_time(  cerberus_run_step_failed[30d] )==   1 )"
    assert queries.normalise(spaced) == queries.normalise(entry(doc, "latest_failed_step"))


def test_tokenizer_ignores_strings_and_braces():
    toks = queries.tokenize('a{b="c d"}[30d]')
    assert toks == [
        ("ident", "a"),
        ("punct", "{"),
        ("ident", "b"),
        ("punct", "="),
        ("str", '"c d"'),
        ("punct", "}"),
        ("punct", "["),
        ("num", "30d"),
        ("punct", "]"),
    ]


# Window rule, direct on strings.
NAMES = ["cerberus_run_status", "cerberus_run_step_failed"]


@pytest.mark.parametrize(
    "expr",
    [
        "last_over_time(cerberus_run_status[30d])",
        "last_over_time(cerberus_run_step_failed[30d]) == 1",
        'last_over_time(cerberus_run_step_failed{step="RunDbt"}[30d]) == 1',
        "topk(1, last_over_time(cerberus_run_status[30d]))",
        "avg_over_time(cerberus_run_status[90d])",
        "count_over_time(cerberus_run_status[90d]) > 3",
        "1 - avg_over_time(cerberus_run_status[90d])",
        "up",
    ],
)
def test_window_rule_accepts(expr):
    assert queries.check_windows(expr, NAMES) == []


@pytest.mark.parametrize(
    "expr",
    [
        "cerberus_run_status",
        "cerberus_run_status == 0",
        "last_over_time(cerberus_run_status[7d])",
        "last_over_time(cerberus_run_status[90d])",
        "avg_over_time(cerberus_run_status[30d])",
        "max_over_time(cerberus_run_status[30d])",
        "last_over_time(cerberus_run_status[30d:1m])",
        "last_over_time((cerberus_run_status)[30d])",
        "topk(1, cerberus_run_status)",
        "last_over_time(cerberus_run_status[30d]) + cerberus_run_step_failed",
    ],
)
def test_window_rule_rejects(expr):
    assert queries.check_windows(expr, NAMES) != []


def test_label_value_naming_a_metric_is_not_a_selector():
    expr = 'last_over_time(cerberus_run_step_failed{step="cerberus_run_status"}[30d])'
    assert queries.check_windows(expr, NAMES) == []


def test_lint_rejects_a_bad_file(doc):
    bad = copy.deepcopy(doc)
    bad["queries"].append({"name": "Latest_Status", "expr": "up", "meaning": "x"})
    bad["queries"].append({"name": "latest_status", "expr": "up", "meaning": "dup\nline"})
    bad["queries"].append({"name": "tmpl_one", "expr": 'up{a="$x"}', "meaning": "x"})
    bad["queries"].append({"name": "tmpl_two", "expr": "up{{x}}", "meaning": "y" * 121})
    bad["queries"].append({"name": "unknown_metric", "expr": "cerberus_nope", "meaning": "x"})
    bad["metrics"].append(
        {"name": "cerberus_run_status", "labels": [], "scope": "x", "meaning": "m"}
    )
    text = "\n".join(queries.lint(bad))
    assert "bad name 'Latest_Status'" in text
    assert "duplicate name latest_status" in text
    assert "meaning must be one line" in text
    assert "tmpl_one: templating" in text
    assert "tmpl_two: templating" in text
    assert "over 120 characters" in text
    assert "cerberus_nope is not in the metrics catalogue" in text
    assert "metrics: duplicate name cerberus_run_status" in text
    assert "scope must be one of" in text


# label


def test_every_real_entry_has_a_label(doc):
    labels = [q["label"] for q in doc["queries"]]
    assert len(labels) == len(doc["queries"])
    assert entry_label(doc, "latest_status") == "Last run"
    assert entry_label(doc, "latest_failed_step") == "What broke"
    assert entry_label(doc, "latest_dq_passed") == "Data checks"
    assert entry_label(doc, "last_success") == "Last good data"
    assert entry_label(doc, "run_success_share_90d") == "Runs that passed (90 days)"


def entry_label(doc, name):
    return next(q["label"] for q in doc["queries"] if q["name"] == name)


def test_label_is_optional(doc):
    ok = copy.deepcopy(doc)
    del ok["queries"][0]["label"]
    assert queries.lint(ok) == []


@pytest.mark.parametrize(
    ("label", "message"),
    [
        ("", "label must be a non-empty string"),
        ("   ", "label must be a non-empty string"),
        (7, "label must be a non-empty string"),
        ("two\nlines", "label must be one line"),
        ("x" * 61, "label is over 60 characters"),
        ("run {{step}}", "templating ($ or {{) is not allowed in label"),
        ("cost $5", "templating ($ or {{) is not allowed in label"),
    ],
)
def test_lint_rejects_a_bad_label(doc, label, message):
    bad = copy.deepcopy(doc)
    bad["queries"][0]["label"] = label
    assert any(message in e for e in queries.lint(bad)), queries.lint(bad)


def test_label_of_exactly_60_characters_is_accepted(doc):
    ok = copy.deepcopy(doc)
    ok["queries"][0]["label"] = "x" * 60
    assert queries.lint(ok) == []


# check_rule_expr


def test_rule_accepts_entry_compared_to_a_number(doc):
    assert queries.check_rule_expr(entry(doc, "latest_status") + " == 0", doc) == []


def test_rule_accepts_two_entries_joined(doc):
    e = entry(doc, "newest_finished_execution")
    expr = f"{e} * on() group_left(execution) {e}"
    assert queries.check_rule_expr(expr, doc) == []


def test_rule_accepts_the_failed_step_entry_with_its_comparison(doc):
    assert queries.check_rule_expr(entry(doc, "latest_failed_step"), doc) == []


def test_rule_accepts_whitespace_differences(doc):
    assert queries.check_rule_expr("last_over_time( cerberus_run_status[30d] )==0", doc) == []


def test_rule_fails_on_a_bare_metric_next_to_an_entry(doc):
    errors = queries.check_rule_expr(entry(doc, "latest_status") + " and cerberus_run_status", doc)
    assert len(errors) == 1
    assert "cerberus_run_status used outside a query-set entry" in errors[0]


def test_rule_fails_on_an_edited_entry(doc):
    assert queries.check_rule_expr("last_over_time(cerberus_run_status[7d]) == 0", doc) != []


def test_rule_without_catalogue_metrics_passes(doc):
    assert queries.check_rule_expr("up == 0", doc) == []


def test_rule_entry_inside_a_longer_name_does_not_count(doc):
    expr = "x" + entry(doc, "latest_status")
    assert queries.check_rule_expr(expr, doc) != []


def test_load_reads_a_given_path():
    assert queries.load(FIXTURES / "status_bad_window.json")["version"] == 1


# __name__ matchers, comments, other fields, operator wrapping

NAME_EXPRS = [
    'last_over_time({__name__="cerberus_dq_errors"}[1d])',
    'last_over_time({__name__=~"cerberus_.+"}[1d])',
    "{__name__ = 'cerberus_dq_errors'}",
]


@pytest.mark.parametrize("expr", NAME_EXPRS)
def test_name_matcher_is_rejected_in_lint(doc, expr):
    bad = copy.deepcopy(doc)
    bad["queries"].append({"name": "sneaky", "expr": expr, "meaning": "x"})
    assert any("queries: sneaky: `__name__` matcher is not allowed" in e for e in queries.lint(bad))


@pytest.mark.parametrize("expr", NAME_EXPRS)
def test_name_matcher_is_rejected_in_a_dashboard(doc, expr):
    dash = {"panels": [{"title": "P", "targets": [{"expr": expr}]}]}
    errors = queries.check_dashboard(dash, doc)
    assert any("`__name__` matcher is not allowed; use an entry" in e for e in errors)


@pytest.mark.parametrize("expr", NAME_EXPRS)
def test_name_matcher_is_rejected_in_a_rule(doc, expr):
    errors = queries.check_rule_expr(expr + " > 0", doc)
    assert any("`__name__` matcher is not allowed" in e for e in errors)


def test_name_in_a_string_is_not_a_matcher():
    assert queries.forbidden('up{a="__name__ # x"}') == []


def test_comment_is_rejected(doc):
    bad = copy.deepcopy(doc)
    bad["queries"].append({"name": "commented", "expr": "up # cerberus_run_status", "meaning": "x"})
    assert any("PromQL comments are not allowed" in e for e in queries.lint(bad))
    dash = {"panels": [{"title": "P", "targets": [{"expr": "up # note"}]}]}
    assert any("PromQL comments" in e for e in queries.check_dashboard(dash, doc))


def test_dodge_fields_fixture_reports_every_case(doc):
    errors = queries.check_dashboard(fixture("dashboard_dodge_fields.json"), doc)
    text = "\n".join(errors)
    assert text.count("status metric in field 'query'") == 2
    assert "status metric in field 'definition'" in text
    assert "`__name__` matcher is not allowed" in text
    assert len(errors) == 4


def test_exempt_fields_may_name_a_metric(doc):
    dash = {"panels": [{"title": "cerberus_run_status", "description": "cerberus_dq_errors"}]}
    assert queries.check_dashboard(dash, doc) == []


def test_operator_entry_must_be_wrapped(doc):
    bad = copy.deepcopy(doc)
    expr = "last_over_time(cerberus_run_step_failed[30d]) == 1"
    bad["queries"].append({"name": "unwrapped", "expr": expr, "meaning": "x"})
    errors = queries.lint(bad)
    assert any("queries: unwrapped: an expr with a top-level operator" in e for e in errors)


def test_operator_helpers():
    assert not queries.has_top_level_operator(queries.tokenize("topk(1, a + b)"))
    assert queries.has_top_level_operator(queries.tokenize("a and b"))
    assert queries.is_wrapped(queries.tokenize("(a == 1)"))
    assert not queries.is_wrapped(queries.tokenize("(a) == (b)"))


def test_wrapped_entry_keeps_its_meaning_under_multiplication(doc):
    rule = "2 * " + entry(doc, "latest_failed_step")
    assert queries.normalise(rule) == "2*(last_over_time(cerberus_run_step_failed[30d])==1)"
    assert queries.check_rule_expr(rule, doc) == []


@pytest.mark.parametrize(
    ("expr", "rejected"),
    [
        ('{__name__=~"spark_application_.+"}', False),
        ('{__name__="spark_x"}', False),
        ("{{__name__}}", False),
        ('{__name__=~".+_status"}', True),
        ('{__name__!="spark_x"}', True),
        ('{__name__!~"spark_.+"}', True),
        ('{__name__=~"("}', True),
        # Prometheus unescapes the string (Go rules) and uses RE2; Python sees raw text.
        (r'{__name__="cerberus\x5fdq_errors"}', True),
        (r'{__name__=~"cerberus\\_dq_errors"}', True),
        ('{__name__=~"cerberus[[:punct:]]dq[[:punct:]]errors"}', True),
        ('{__name__=""}', True),
    ],
)
def test_dashboard_allows_a_name_matcher_that_misses_the_catalogue(doc, expr, rejected):
    dash = {"panels": [{"title": "P", "targets": [{"expr": expr}]}]}
    assert bool(queries.check_dashboard(dash, doc)) is rejected


def test_every_expr_names_only_cerberus_metrics_and_no_name_matcher(doc):
    """The role can read the whole workspace, so the fixed queries stay on cerberus_ series."""
    import re

    words = {"by", "without", "on", "ignoring", "bool", "and", "or", "unless", "NaN"}
    for q in doc["queries"]:
        expr = q["expr"]
        assert "__name__" not in expr, q["name"]
        text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)  # drop label values
        text = re.sub(r"\{[^}]*\}", "", text)  # drop label matchers
        text = re.sub(r"\[[^\]]*\]", "", text)  # drop range selectors
        text = re.sub(r"\b(?:by|without|on|ignoring)\s*\([^)]*\)", "", text)
        metrics = [
            i
            for i in re.findall(r"[A-Za-z_:][A-Za-z0-9_:]*(?![\w:]|\s*\()", text)
            if i not in words and not re.fullmatch(r"\d+[smhdwy]", i)
        ]
        assert metrics, q["name"]
        for m in metrics:
            assert m.startswith("cerberus_"), (q["name"], m)
