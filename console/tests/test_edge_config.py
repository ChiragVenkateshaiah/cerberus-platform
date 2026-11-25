"""Pin the security-relevant edge, API, Cognito and IAM config in the Terraform text (9.6).

No terraform binary and no AWS: the .tf files are read as text. The parser is
small and strict. It strips comments, finds a block by its header and matches
braces with an eye on strings, and it fails loudly (AssertionError) when a block
or an attribute is missing, duplicated or unbalanced. A refactor that moves a
value must update this file on purpose.

EDGE_HEADERS is the one list of expected response headers. The live check
(`curl -sI https://<cf>/terminal/index.html`, plan 2026-11-13 section 7) compares
the real response with the same constants.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = ROOT / "terraform" / "modules" / "console_edge"
ROLES_DIR = ROOT / "terraform" / "modules" / "console_roles"

# --- expected values: one place -------------------------------------------------

COGNITO_URL = "https://cerberus-console.auth.us-east-1.amazoncognito.com"

# The live response headers (names are lower case, as HTTP/2 shows them).
EDGE_HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "content-security-policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            f"connect-src 'self' {COGNITO_URL}",
            f"form-action 'self' {COGNITO_URL}",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "object-src 'none'",
            "upgrade-insecure-requests",
        ]
    ),
}

API_ROUTE = "POST /api/command"
API_SCOPES = ["openid"]
THROTTLE_RATE = 1
THROTTLE_BURST = 3
LAMBDA_TIMEOUT = 25
CLI_WRITE_ACTIONS = {
    "athena:StartQueryExecution",
    "athena:StopQueryExecution",
    "s3:PutObject",
    "s3:AbortMultipartUpload",
}
LAMBDA_LOG_ACTIONS = {"logs:CreateLogStream", "logs:PutLogEvents"}
RESULTS_RESOURCE = "${var.athena_results_bucket_arn}/${var.athena_results_prefix}*"
READ_PREFIXES = ("Get", "List", "Describe")
NON_PREFIX_READS = {"aps:QueryMetrics"}  # 10.5c: a read, though its name has no read prefix


# --- a small, strict reader for the HCL we use ----------------------------------


def hcl_text(path):
    return strip_comments(path.read_text(encoding="utf-8"), path.name)


def module_text(directory):
    """Every .tf file of a module, comments removed, joined. A moved block is still found."""
    files = sorted(directory.glob("*.tf"))
    assert files, f"no .tf files in {directory}"
    return "\n".join(hcl_text(f) for f in files)


def strip_comments(text, name="text"):
    """The text with comments removed. Strings are kept whole."""
    assert "<<" not in text, f"{name}: heredocs are not supported by this reader"
    out, i, in_str = [], 0, False
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\":
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif ch == "#" or text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.index("*/", i)
            i = end + 2
            continue
        else:
            out.append(ch)
        i += 1
    assert not in_str, f"{name}: unterminated string"
    return "".join(out)


def depths(text):
    """The bracket depth at each character (strings skipped). Fails when unbalanced."""
    out, depth, in_str, i = [], 0, False, 0
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(depth)
            if ch == "\\":
                out.append(depth)
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(depth)
        elif ch in "{[(":
            out.append(depth)
            depth += 1
        elif ch in "}])":
            depth -= 1
            assert depth >= 0, "unbalanced brackets"
            out.append(depth)
        else:
            out.append(depth)
        i += 1
    assert depth == 0 and not in_str, "unbalanced brackets or string"
    return out


def close_of(text, open_at):
    """The index of the bracket that closes the one at open_at."""
    depth_map = depths(text)
    for j in range(open_at + 1, len(text)):
        if depth_map[j] == depth_map[open_at] and text[j] in "}])":
            return j
    raise AssertionError("no closing bracket")


def blocks(text, header):
    """Bodies of every top-level block whose header matches the regex `header`."""
    depth_map = depths(text)
    found = []
    for m in re.finditer(rf"^[ \t]*{header}[ \t]*\{{", text, flags=re.M):
        start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        if depth_map[start] != 0:
            continue
        open_at = m.end() - 1
        found.append(text[open_at + 1 : close_of(text, open_at)])
    return found


def block(text, header):
    found = blocks(text, header)
    assert len(found) == 1, f"expected one block {header!r}, found {len(found)}"
    return found[0]


def resource(text, kind, name):
    return block(text, rf'resource\s+"{kind}"\s+"{name}"')


def resources_of(text, kind):
    return blocks(text, rf'resource\s+"{kind}"\s+"[^"]+"')


def nested(body, name):
    """The one nested block `name { ... }` directly inside body."""
    depth_map = depths(body)
    found = []
    for m in re.finditer(rf"^[ \t]*{name}[ \t]*\{{", body, flags=re.M):
        start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        if depth_map[start] == 0:
            found.append(body[m.end() : close_of(body, m.end() - 1)])
    assert len(found) == 1, f"expected one nested block {name!r}, found {len(found)}"
    return found[0]


def attr(body, name):
    """The raw text of the top-level attribute `name = value` in body."""
    depth_map = depths(body)
    found = []
    for m in re.finditer(rf"^[ \t]*({name})[ \t]*=[ \t]*", body, flags=re.M):
        if depth_map[m.start(1)] != 0:
            continue
        end = m.end()
        while end < len(body) and not (body[end] == "\n" and depth_map[end] == 0):
            end += 1
        found.append(body[m.end() : end].strip())
    assert len(found) == 1, f"expected one attribute {name!r}, found {len(found)}"
    return found[0]


def strings(value):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', value)


def one_string(value):
    got = strings(value)
    assert len(got) == 1 and value.strip() == f'"{got[0]}"', value
    return got[0]


def statements(policy_body):
    """The Statement objects of a jsonencode({...}) policy, as dicts of raw attributes."""
    policy = attr(policy_body, "policy")
    m = re.search(r"Statement\s*=\s*\[", policy)
    assert m, "no Statement list"
    open_at = m.end() - 1
    inner = policy[open_at + 1 : close_of(policy, open_at)]
    depth_map = depths(inner)
    out = []
    for j, ch in enumerate(inner):
        if ch == "{" and depth_map[j] == 0:
            body = inner[j + 1 : close_of(inner, j)]
            fields = {}
            for name in (
                "Sid",
                "Effect",
                "Action",
                "Resource",
                "NotAction",
                "NotResource",
                "Condition",
            ):
                found = [
                    mm
                    for mm in re.finditer(rf"^[ \t]*{name}[ \t]*=", body, flags=re.M)
                    if depths(body)[mm.start()] == 0
                ]
                if found:
                    fields[name] = attr(body, name)
            assert "Action" in fields, fields
            out.append(fields)
    assert out, "no statements found"
    return out


def actions_of(statement):
    return set(strings(statement["Action"]))


# --- the parser itself fails loudly ---------------------------------------------------


def test_the_reader_fails_loudly():
    text = module_text(EDGE_DIR)
    with pytest.raises(AssertionError):
        resource(text, "aws_cloudfront_distribution", "missing")
    with pytest.raises(AssertionError):
        attr("a = 1\nb = 2\n", "c")
    with pytest.raises(AssertionError):
        attr("a = 1\na = 2\n", "a")
    with pytest.raises(AssertionError):
        depths("resource {")
    with pytest.raises(AssertionError):
        nested("x {\n}\n", "y")


def test_the_reader_reads_a_known_block():
    text = hcl_text(EDGE_DIR / "main.tf")
    body = resource(text, "aws_apigatewayv2_route", "command")
    assert one_string(attr(body, "route_key")) == API_ROUTE


def test_a_comment_or_string_with_a_brace_does_not_confuse_the_reader():
    sample = strip_comments('a = "x{"\n# } stray\nb {\n  c = 1\n}\n// {\n/* } */\n')
    assert one_string(attr(sample, "a")) == "x{"
    assert attr(nested(sample, "b"), "c") == "1"


# --- the edge: CloudFront headers ------------------------------------------------------


@pytest.fixture(scope="module")
def edge():
    return module_text(EDGE_DIR)


@pytest.fixture(scope="module")
def variables():
    return module_text(EDGE_DIR)


@pytest.fixture(scope="module")
def roles():
    return module_text(ROLES_DIR)


def terraform_headers(edge_text):
    """The headers the response headers policy sets, as the live response shows them."""
    policy = resource(edge_text, "aws_cloudfront_response_headers_policy", "security")
    sec = nested(policy, "security_headers_config")
    csp_block = nested(sec, "content_security_policy")
    assert attr(csp_block, "override") == "true"
    joined = attr(csp_block, "content_security_policy")
    assert joined.startswith('join("; ", [')
    csp = "; ".join(strings(joined)[1:]).replace("${local.cognito_url}", COGNITO_URL)
    hsts = nested(sec, "strict_transport_security")
    assert attr(hsts, "override") == "true"
    assert not re.search(r"include_subdomains|preload", hsts)
    assert attr(nested(sec, "content_type_options"), "override") == "true"
    frame = nested(sec, "frame_options")
    assert attr(frame, "override") == "true"
    referrer = nested(sec, "referrer_policy")
    assert attr(referrer, "override") == "true"
    custom = nested(nested(policy, "custom_headers_config"), "items")
    assert attr(custom, "override") == "true"
    return {
        "strict-transport-security": f"max-age={attr(hsts, 'access_control_max_age_sec')}",
        "x-content-type-options": "nosniff",  # this block has no value: the header is fixed
        "x-frame-options": one_string(attr(frame, "frame_option")),
        "referrer-policy": one_string(attr(referrer, "referrer_policy")),
        "permissions-policy": one_string(attr(custom, "value")),
        "content-security-policy": csp,
    }


def test_the_policy_sets_exactly_the_expected_headers(edge):
    assert terraform_headers(edge) == EDGE_HEADERS


def test_the_custom_header_is_permissions_policy(edge):
    policy = resource(edge, "aws_cloudfront_response_headers_policy", "security")
    custom = nested(nested(policy, "custom_headers_config"), "items")
    assert one_string(attr(custom, "header")) == "Permissions-Policy"


def test_the_csp_has_no_unsafe_source_and_closes_the_dangerous_directives():
    csp = EDGE_HEADERS["content-security-policy"]
    directives = csp.split("; ")
    assert "unsafe" not in csp and "*" not in csp.replace("'self'", "")
    assert "frame-ancestors 'none'" in directives
    assert "object-src 'none'" in directives
    assert "base-uri 'none'" in directives
    assert "default-src 'self'" in directives
    assert "upgrade-insecure-requests" in directives
    assert len(directives) == len(set(d.split()[0] for d in directives))


def test_the_cognito_url_in_the_csp_is_built_from_the_variable_defaults(edge, variables):
    locals_ = block(edge, r"locals")
    assert (
        one_string(attr(locals_, "cognito_url"))
        == "https://${var.cognito_domain_prefix}.auth.${var.region}.amazoncognito.com"
    )
    prefix = one_string(attr(block(variables, r'variable\s+"cognito_domain_prefix"'), "default"))
    region = one_string(attr(block(variables, r'variable\s+"region"'), "default"))
    assert f"https://{prefix}.auth.{region}.amazoncognito.com" == COGNITO_URL


def test_both_cache_behaviours_use_the_security_policy(edge):
    dist = resource(edge, "aws_cloudfront_distribution", "this")
    default = nested(dist, "default_cache_behavior")
    ordered = nested(dist, "ordered_cache_behavior")  # exactly one: a new one must be added here
    for body in (default, ordered):
        assert (
            attr(body, "response_headers_policy_id")
            == "aws_cloudfront_response_headers_policy.security.id"
        )


def test_viewer_protocols(edge):
    dist = resource(edge, "aws_cloudfront_distribution", "this")
    default = nested(dist, "default_cache_behavior")
    ordered = nested(dist, "ordered_cache_behavior")
    assert one_string(attr(default, "viewer_protocol_policy")) == "redirect-to-https"
    assert one_string(attr(ordered, "viewer_protocol_policy")) == "https-only"
    assert strings(attr(default, "allowed_methods")) == ["GET", "HEAD"]
    assert one_string(attr(ordered, "path_pattern")) == "/api/*"
    assert (
        attr(ordered, "cache_policy_id") == "data.aws_cloudfront_cache_policy.caching_disabled.id"
    )
    origins = blocks(dist, r"origin")
    assert len(origins) == 2  # the site (S3, OAC) and the API
    api = [o for o in origins if re.search(r"^[ \t]*custom_origin_config[ \t]*\{", o, re.M)]
    assert len(api) == 1
    custom = nested(api[0], "custom_origin_config")
    assert one_string(attr(custom, "origin_protocol_policy")) == "https-only"
    assert strings(attr(custom, "origin_ssl_protocols")) == ["TLSv1.2"]


def test_the_site_bucket_stays_private(edge):
    pab = resource(edge, "aws_s3_bucket_public_access_block", "site")
    for name in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert attr(pab, name) == "true"


# --- the API ---------------------------------------------------------------------------


def test_one_route_with_a_jwt_authorizer_and_the_openid_scope(edge):
    assert len(resources_of(edge, "aws_apigatewayv2_route")) == 1
    route = resource(edge, "aws_apigatewayv2_route", "command")
    assert one_string(attr(route, "route_key")) == API_ROUTE
    assert one_string(attr(route, "authorization_type")) == "JWT"
    assert attr(route, "authorizer_id") == "aws_apigatewayv2_authorizer.jwt.id"
    assert strings(attr(route, "authorization_scopes")) == API_SCOPES


def test_the_authorizer_checks_the_issuer_and_the_spa_client_audience(edge):
    assert len(resources_of(edge, "aws_apigatewayv2_authorizer")) == 1
    auth = resource(edge, "aws_apigatewayv2_authorizer", "jwt")
    assert one_string(attr(auth, "authorizer_type")) == "JWT"
    assert strings(attr(auth, "identity_sources")) == ["$request.header.Authorization"]
    jwt = nested(auth, "jwt_configuration")
    assert one_string(attr(jwt, "issuer")) == "https://${aws_cognito_user_pool.this.endpoint}"
    assert attr(jwt, "audience") == "[aws_cognito_user_pool_client.spa.id]"


def test_no_cors_and_no_second_api_or_stage(edge):
    assert len(resources_of(edge, "aws_apigatewayv2_api")) == 1
    assert "cors_configuration" not in edge
    assert len(resources_of(edge, "aws_apigatewayv2_stage")) == 1
    assert len(resources_of(edge, "aws_apigatewayv2_integration")) == 1
    assert len(resources_of(edge, "aws_apigatewayv2_deployment")) == 0


def test_the_stage_throttle_is_the_variable_defaults_and_nothing_overrides_it(edge, variables):
    stage = resource(edge, "aws_apigatewayv2_stage", "default")
    settings = nested(stage, "default_route_settings")
    assert attr(settings, "throttling_rate_limit") == "var.throttle_rate_limit"
    assert attr(settings, "throttling_burst_limit") == "var.throttle_burst_limit"
    assert not re.search(r"(?<![\w])route_settings\s*\{", stage)  # no per-route override
    rate = attr(block(variables, r'variable\s+"throttle_rate_limit"'), "default")
    burst = attr(block(variables, r'variable\s+"throttle_burst_limit"'), "default")
    assert (int(rate), int(burst)) == (THROTTLE_RATE, THROTTLE_BURST)


def test_the_lambda_timeout_is_25_seconds(edge, variables):
    fn = resource(edge, "aws_lambda_function", "command")
    assert attr(fn, "timeout") == "var.lambda_timeout_seconds"
    default = attr(block(variables, r'variable\s+"lambda_timeout_seconds"'), "default")
    assert int(default) == LAMBDA_TIMEOUT


def test_only_the_api_may_invoke_the_lambda_and_only_for_the_one_route(edge):
    perms = resources_of(edge, "aws_lambda_permission")
    assert len(perms) == 1
    perm = resource(edge, "aws_lambda_permission", "api_invoke")
    assert one_string(attr(perm, "principal")) == "apigateway.amazonaws.com"
    assert one_string(attr(perm, "source_arn")).endswith("/*/POST/api/command")


# --- Cognito ---------------------------------------------------------------------------


def test_the_cognito_client_is_a_public_code_flow_client_with_the_minimum_surface(edge):
    assert len(resources_of(edge, "aws_cognito_user_pool_client")) == 1
    client = resource(edge, "aws_cognito_user_pool_client", "spa")
    assert attr(client, "generate_secret") == "false"
    assert attr(client, "allowed_oauth_flows_user_pool_client") == "true"
    assert strings(attr(client, "allowed_oauth_flows")) == ["code"]
    assert strings(attr(client, "allowed_oauth_scopes")) == ["openid"]
    assert strings(attr(client, "explicit_auth_flows")) == ["ALLOW_REFRESH_TOKEN_AUTH"]
    assert strings(attr(client, "supported_identity_providers")) == ["COGNITO"]
    assert one_string(attr(client, "prevent_user_existence_errors")) == "ENABLED"
    assert attr(client, "callback_urls") == "[local.callback_url]"


def test_the_user_pool_is_invite_only(edge):
    assert len(resources_of(edge, "aws_cognito_user_pool")) == 1
    pool = resource(edge, "aws_cognito_user_pool", "this")
    assert attr(nested(pool, "admin_create_user_config"), "allow_admin_create_user_only") == "true"
    assert one_string(attr(pool, "deletion_protection")) == "ACTIVE"
    recovery = nested(nested(pool, "account_recovery_setting"), "recovery_mechanism")
    assert one_string(attr(recovery, "name")) == "admin_only"


# --- IAM -----------------------------------------------------------------------------------


def test_console_cli_has_one_policy_and_nothing_else_is_attached_to_it(edge, roles):
    assert len(resources_of(roles, "aws_iam_role_policy_attachment")) == 0
    assert len(resources_of(edge, "aws_iam_role_policy_attachment")) == 0
    assert len(resources_of(edge, "aws_iam_user_policy")) == 0
    on_cli = [
        body
        for body in resources_of(roles, "aws_iam_role_policy")
        if attr(body, "role") == "aws_iam_role.console_cli.id"
    ]
    assert len(on_cli) == 1
    # The edge module adds only the logs policy, by role name.
    edge_policies = resources_of(edge, "aws_iam_role_policy")
    assert len(edge_policies) == 1
    assert attr(edge_policies[0], "role") == "var.console_cli_role_name"
    assert "managed_policy_arns" not in roles and "managed_policy_arns" not in edge


def cli_statements(roles_text):
    body = resource(roles_text, "aws_iam_role_policy", "console_cli")
    return statements(body)


def test_console_cli_write_set_is_exactly_the_four_actions(roles):
    stmts = cli_statements(roles)
    write = set()
    for st in stmts:
        assert one_string(st["Effect"]) == "Allow"
        assert "NotAction" not in st and "NotResource" not in st
        for action in actions_of(st):
            assert "*" not in action, action
            op = action.split(":", 1)[1]
            if not op.startswith(READ_PREFIXES) and action not in NON_PREFIX_READS:
                write.add(action)
    assert write == CLI_WRITE_ACTIONS


def test_s3_writes_are_only_on_the_results_prefix(roles):
    stmts = cli_statements(roles)
    holders = [st for st in stmts if actions_of(st) & {"s3:PutObject", "s3:AbortMultipartUpload"}]
    assert len(holders) == 1
    assert one_string(holders[0]["Resource"]) == RESULTS_RESOURCE
    assert actions_of(holders[0]) == {"s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"}
    # No other statement grants s3:PutObject, and no statement names a bare "*" resource.
    for st in stmts:
        assert "*" not in [s for s in strings(st["Resource"]) if s == "*"]


def test_athena_writes_are_only_on_the_console_workgroup(roles):
    holders = [st for st in cli_statements(roles) if "athena:StartQueryExecution" in actions_of(st)]
    assert len(holders) == 1
    assert actions_of(holders[0]) >= {"athena:StopQueryExecution"}
    resource_text = one_string(holders[0]["Resource"])
    assert resource_text.endswith(":workgroup/${var.athena_workgroup_name}")


def test_console_cli_cannot_write_gold_or_the_catalog_or_start_the_pipeline(roles):
    allowed = set()
    for st in cli_statements(roles):
        allowed |= actions_of(st)
    for denied in (
        "s3:DeleteObject",
        "s3:PutObjectAcl",
        "glue:UpdateTable",
        "glue:CreateTable",
        "glue:DeleteTable",
        "states:StartExecution",
        "states:StopExecution",
        "athena:CreateWorkGroup",
        "athena:UpdateWorkGroup",
        "iam:PassRole",
        "iam:*",
        "*",
    ):
        assert denied not in allowed


def test_the_lambda_log_policy_is_logs_only_on_one_log_group(edge):
    policy = resource(edge, "aws_iam_role_policy", "console_cli_logs")
    stmts = statements(policy)
    assert len(stmts) == 1
    assert one_string(stmts[0]["Effect"]) == "Allow"
    assert actions_of(stmts[0]) == LAMBDA_LOG_ACTIONS
    assert one_string(stmts[0]["Resource"]) == "${aws_cloudwatch_log_group.command.arn}:*"


# --- the two console alarms (9.7, ADR 0026) -------------------------------------------

ALARMS = {
    "api_5xx": {
        "alarm_name": "cerberus-console-api-5xx",
        "namespace": "AWS/ApiGateway",
        "metric_name": "5xx",
        "dimensions": "{ ApiId = aws_apigatewayv2_api.this.id }",
        "threshold": "3",
    },
    "lambda_errors": {
        "alarm_name": "cerberus-console-lambda-errors",
        "namespace": "AWS/Lambda",
        "metric_name": "Errors",
        "dimensions": "{ FunctionName = aws_lambda_function.command.function_name }",
        "threshold": "1",
    },
}


def test_exactly_the_two_console_alarms_exist(edge):
    assert len(resources_of(edge, "aws_cloudwatch_metric_alarm")) == len(ALARMS)
    for name in ALARMS:
        resource(edge, "aws_cloudwatch_metric_alarm", name)


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_each_alarm_watches_the_expected_metric_and_threshold(edge, name):
    want = ALARMS[name]
    alarm = resource(edge, "aws_cloudwatch_metric_alarm", name)
    assert one_string(attr(alarm, "alarm_name")) == want["alarm_name"]
    assert one_string(attr(alarm, "namespace")) == want["namespace"]
    assert one_string(attr(alarm, "metric_name")) == want["metric_name"]
    assert attr(alarm, "dimensions") == want["dimensions"]
    assert one_string(attr(alarm, "statistic")) == "Sum"
    assert attr(alarm, "period") == "300"
    assert attr(alarm, "evaluation_periods") == "1"
    assert attr(alarm, "threshold") == want["threshold"]
    assert one_string(attr(alarm, "comparison_operator")) == "GreaterThanOrEqualToThreshold"


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_no_traffic_is_not_a_breach_and_both_states_notify_the_alerts_topic(edge, name):
    alarm = resource(edge, "aws_cloudwatch_metric_alarm", name)
    assert one_string(attr(alarm, "treat_missing_data")) == "notBreaching"
    assert attr(alarm, "alarm_actions") == "[var.alarm_topic_arn]"
    assert attr(alarm, "ok_actions") == "[var.alarm_topic_arn]"
    tags = attr(alarm, "tags")
    assert re.search(r'^\s*Phase\s*=\s*"9"\s*$', tags, flags=re.M), tags
    assert re.search(r'^\s*Component\s*=\s*"console"\s*$', tags, flags=re.M), tags


def test_the_topic_comes_from_the_observability_module(edge):
    var = block(edge, r'variable\s+"alarm_topic_arn"')
    assert attr(var, "type") == "string"
    assert not re.search(r"^[ \t]*default[ \t]*=", var, flags=re.M)  # the caller must pass it
    env = hcl_text(ROOT / "terraform" / "envs" / "dev-standing" / "main.tf")
    module = block(env, r'module\s+"console_edge"')
    assert attr(module, "alarm_topic_arn") == "module.observability.alerts_topic_arn"


# --- 10.5c: the status view's AMP read and the queries file in the zip -----------------

DEV_STANDING = ROOT / "terraform" / "envs" / "dev-standing"
QUERIES_REPO_FILE = ROOT / "observability" / "queries" / "status.json"
QUERIES_ZIP_NAME = "observability/queries/status.json"


def test_the_only_aps_statement_is_query_metrics_on_the_workspace_arn(roles):
    policy = resource(roles, "aws_iam_role_policy", "console_cli")
    aps = [s for s in statements(policy) if any(a.startswith("aps:") for a in actions_of(s))]
    assert len(aps) == 1
    assert strings(aps[0]["Action"]) == ["aps:QueryMetrics"]
    assert aps[0]["Resource"] == "var.amp_workspace_arn"
    assert one_string(aps[0]["Effect"]) == "Allow"
    assert "Condition" not in aps[0] and "NotAction" not in aps[0]
    assert "workspace/*" not in policy and "aps:*" not in policy


def test_the_lambda_zip_carries_the_queries_file(edge):
    locals_ = block(edge, r"locals")
    assert attr(locals_, "queries_file") == '"${local.repo_root}/observability/queries/status.json"'
    assert one_string(attr(locals_, "queries_in_zip")) == QUERIES_ZIP_NAME
    assert one_string(attr(locals_, "queries_in_task")) == "/var/task/${local.queries_in_zip}"
    archive = block(edge, r'data\s+"archive_file"\s+"command"')
    sources = [
        b for b in re.findall(r"^[ \t]*source[ \t]*\{(.*?)^[ \t]*\}", archive, re.M | re.S) if b
    ]
    direct = [
        b for b in sources if "content" in b and "filename" in b and "local.queries_file" in b
    ]
    assert len(direct) == 1
    assert attr(direct[0], "content") == "file(local.queries_file)"
    assert attr(direct[0], "filename") == "local.queries_in_zip"
    # the zipped content is the repo file: the path ends at the committed file
    assert QUERIES_REPO_FILE.is_file()
    assert QUERIES_REPO_FILE.relative_to(ROOT).as_posix() == QUERIES_ZIP_NAME


def test_the_lambda_env_has_the_queries_file_and_the_amp_url(edge):
    fn = resource(edge, "aws_lambda_function", "command")
    env = attr(nested(fn, "environment"), "variables")
    assert re.search(r"CERBERUS_QUERIES_FILE\s*=\s*local\.queries_in_task\b", env)
    assert re.search(r"CERBERUS_AMP_QUERY_URL\s*=\s*var\.amp_query_url\b", env)
    # the zip path and the task path agree with the default the code expects
    assert "/var/task/" + QUERIES_ZIP_NAME == "/var/task/observability/queries/status.json"


def test_the_amp_url_has_no_default_and_comes_from_the_workspace_endpoint(variables):
    var = block(variables, r'variable\s+"amp_query_url"')
    assert not re.search(r"^[ \t]*default[ \t]*=", var, re.M)
    dev = module_text(DEV_STANDING)
    console_edge = block(dev, r'module\s+"console_edge"')
    assert attr(console_edge, "amp_query_url") == "module.prometheus_workspace.prometheus_endpoint"
