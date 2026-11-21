"""Pin the 10.4b alert infrastructure in the Terraform text (plan 2026-11-20, ADR 0021).

No terraform binary and no AWS: the .tf files are read as text with the HCL
helpers of test_edge_config.py. What is pinned:

- the rule-group namespace name and the files it loads (they must exist);
- the one variable the Alertmanager template takes (`topic_arn`), and that the
  template has no other `${` or `%{` that templatefile() would read;
- the alerts topic policy: the default statement kept, plus the AMP statement
  limited by aws:SourceAccount and aws:SourceArn;
- no literal account ID and no `arn:aws:` literal in the new module;
- the workflow path filters and the ci_apply statement.
"""

import re
from pathlib import Path

from test_edge_config import (
    actions_of,
    attr,
    block,
    hcl_text,
    module_text,
    resource,
    statements,
    strings,
)

ROOT = Path(__file__).resolve().parents[2]
ALERTS_DIR = ROOT / "observability" / "alerts"
MODULE_DIR = ROOT / "terraform" / "modules" / "pipeline_alerts"
OBS_DIR = ROOT / "terraform" / "modules" / "observability"
OIDC_MAIN = ROOT / "terraform" / "modules" / "github_oidc" / "main.tf"
STANDING = ROOT / "terraform" / "envs" / "dev-standing" / "main.tf"

NAMESPACE_NAME = "cerberus-status"
TEMPLATE_VARIABLES = {"topic_arn"}

DEFAULT_ACTIONS = {
    "SNS:GetTopicAttributes",
    "SNS:SetTopicAttributes",
    "SNS:AddPermission",
    "SNS:RemovePermission",
    "SNS:DeleteTopic",
    "SNS:Subscribe",
    "SNS:ListSubscriptionsByTopic",
    "SNS:Publish",
}
AMP_TOPIC_ACTIONS = {"sns:Publish", "sns:GetTopicAttributes"}
CI_AMP_ACTIONS = {
    "aps:CreateRuleGroupsNamespace",
    "aps:PutRuleGroupsNamespace",
    "aps:DescribeRuleGroupsNamespace",
    "aps:DeleteRuleGroupsNamespace",
    "aps:ListRuleGroupsNamespaces",
    "aps:CreateAlertManagerDefinition",
    "aps:PutAlertManagerDefinition",
    "aps:DescribeAlertManagerDefinition",
    "aps:DeleteAlertManagerDefinition",
    "aps:ListTagsForResource",
    "aps:TagResource",
    "aps:UntagResource",
}


# --- the module ------------------------------------------------------------------


def test_the_namespace_is_named_and_loads_the_rules_file():
    text = module_text(MODULE_DIR)
    body = resource(text, "aws_prometheus_rule_group_namespace", "status")
    assert strings(attr(body, "name")) == [NAMESPACE_NAME]
    assert attr(body, "workspace_id") == "var.workspace_id"
    assert attr(body, "data") == 'file("${local.alerts_dir}/status.rules.yaml")'
    assert (ALERTS_DIR / "status.rules.yaml").is_file()


def test_the_alerts_dir_local_points_at_the_real_directory():
    text = module_text(MODULE_DIR)
    locals_body = block(text, "locals")
    dir_expr = strings(attr(locals_body, "alerts_dir"))
    assert dir_expr == ["${path.module}/../../../observability/alerts"]
    resolved = (MODULE_DIR / "../../../observability/alerts").resolve()
    assert resolved == ALERTS_DIR.resolve()


def test_the_alertmanager_definition_renders_with_only_topic_arn():
    text = module_text(MODULE_DIR)
    body = resource(text, "aws_prometheus_alert_manager_definition", "status")
    assert attr(body, "workspace_id") == "var.workspace_id"
    definition = attr(body, "definition")
    assert 'templatefile("${local.alerts_dir}/alertmanager.yaml.tftpl"' in definition
    given = set(re.findall(r"^\s*(\w+)\s*=\s*var\.", definition, flags=re.M))
    assert given == TEMPLATE_VARIABLES
    assert (ALERTS_DIR / "alertmanager.yaml.tftpl").is_file()


def test_the_template_uses_no_terraform_syntax_but_topic_arn():
    template = (ALERTS_DIR / "alertmanager.yaml.tftpl").read_text(encoding="utf-8")
    interpolations = set(re.findall(r"\$\{\s*([^}\s]+)\s*\}", template))
    assert interpolations == TEMPLATE_VARIABLES
    assert "%{" not in template
    assert "$${" not in template


def test_the_new_module_has_no_account_id_or_arn_literal():
    for path in sorted(MODULE_DIR.glob("*.tf")):
        raw = path.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{12}\b", raw), path.name
        assert "arn:aws:" not in hcl_text(path), path.name


def test_dev_standing_wires_the_module_from_other_modules():
    text = hcl_text(STANDING)
    body = block(text, r'module\s+"pipeline_alerts"')
    assert attr(body, "workspace_id") == "module.prometheus_workspace.workspace_id"
    assert attr(body, "alerts_topic_arn") == "module.observability.alerts_topic_arn"
    obs = block(text, r'module\s+"observability"')
    assert attr(obs, "amp_workspace_arn") == "module.prometheus_workspace.workspace_arn"


# --- the topic policy ------------------------------------------------------------


def _topic_policy():
    body = resource(hcl_text(OBS_DIR / "alarms.tf"), "aws_sns_topic_policy", "alerts")
    assert attr(body, "arn") == "aws_sns_topic.alerts.arn"
    by_sid = {strings(s["Sid"])[0]: s for s in statements(body)}
    return by_sid, attr(body, "policy")


def test_the_topic_policy_keeps_the_default_statement():
    by_sid, policy = _topic_policy()
    default = by_sid["__default_statement_ID"]
    assert default["Effect"] == '"Allow"'
    assert actions_of(default) == DEFAULT_ACTIONS
    assert default["Resource"] == "aws_sns_topic.alerts.arn"
    assert re.search(
        r'Sid\s*=\s*"__default_statement_ID"\s*Effect\s*=\s*"Allow"\s*Principal\s*=\s*\{\s*AWS\s*=\s*"\*"\s*\}',
        policy,
    )
    assert re.fullmatch(
        r'\{\s*StringEquals\s*=\s*\{\s*"AWS:SourceOwner"\s*=\s*data\.aws_caller_identity\.current\.account_id\s*\}\s*\}',
        default["Condition"],
    ), default["Condition"]


def test_the_topic_policy_lets_only_this_workspace_of_amp_publish():
    by_sid, policy = _topic_policy()
    assert len(by_sid) == 2
    amp = by_sid["AllowAmpAlertmanagerPublish"]
    assert amp["Effect"] == '"Allow"'
    assert actions_of(amp) == AMP_TOPIC_ACTIONS
    assert amp["Resource"] == "aws_sns_topic.alerts.arn"
    assert re.search(r'Principal\s*=\s*\{\s*Service\s*=\s*"aps\.amazonaws\.com"\s*\}', policy)
    cond = amp["Condition"]
    assert re.search(
        r'StringEquals\s*=\s*\{\s*"aws:SourceAccount"\s*=\s*data\.aws_caller_identity\.current\.account_id\s*\}',
        cond,
    ), cond
    assert re.search(
        r'ArnLike\s*=\s*\{\s*"aws:SourceArn"\s*=\s*var\.amp_workspace_arn\s*\}', cond
    ), cond


def test_the_observability_module_has_no_literal_account_id():
    for path in sorted(OBS_DIR.glob("*.tf")):
        assert not re.search(r"\b\d{12}\b", path.read_text(encoding="utf-8")), path.name


def test_the_workspace_arn_variable_exists_without_a_default():
    # variables.tf holds heredocs, which the strict reader refuses: use a regex.
    raw = (OBS_DIR / "variables.tf").read_text(encoding="utf-8")
    m = re.search(r'variable\s+"amp_workspace_arn"\s*\{(.*?)\n\}', raw, flags=re.S)
    assert m, "variable amp_workspace_arn is missing"
    assert re.search(r"^\s*type\s*=\s*string\s*$", m.group(1), flags=re.M)
    assert not re.search(r"^\s*default\s*=", m.group(1), flags=re.M)


# --- the workflows and CI permissions -------------------------------------------


def test_both_terraform_workflows_trigger_on_the_alerts_directory():
    for name in ("terraform-plan.yml", "terraform-apply.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert '- "observability/alerts/**"' in text, name


def test_ci_apply_may_manage_amp_rules_and_alerting():
    text = hcl_text(OIDC_MAIN)
    body = resource(text, "aws_iam_role_policy", "ci_apply")
    by_sid = {strings(s["Sid"])[0]: s for s in statements(body)}
    stmt = by_sid["ManageAmpRulesAndAlerting"]
    assert stmt["Effect"] == '"Allow"'
    assert actions_of(stmt) == CI_AMP_ACTIONS
    resources = strings(stmt["Resource"])
    assert resources == [
        "arn:aws:aps:${var.region}:${var.account_id}:workspace/*",
        "arn:aws:aps:${var.region}:${var.account_id}:rulegroupsnamespace/*",
    ]
