"""Static checks on terminal.js and its parity with the repo (ADR 0024 amendment, 2026-11-12).

No browser here: these read the source text. The behaviour tests are in tests/js/.
"""

import http.client
import re
import threading
from pathlib import Path

import pytest

from cerberus_console import config, grammar
from cerberus_terminal import build, serve

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = build.STATIC / "terminal.js"
ADR = ROOT / "docs" / "adr" / "0024-demo-console.md"
EDGE_MAIN = ROOT / "terraform" / "modules" / "console_edge" / "main.tf"
EDGE_VARS = ROOT / "terraform" / "modules" / "console_edge" / "variables.tf"


def source() -> str:
    """terminal.js without comments, so the scan sees only code."""
    text = JS_PATH.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


FORBIDDEN = [
    r"\binnerHTML\b",
    r"\bouterHTML\b",
    r"\binsertAdjacentHTML\b",
    r"\bdocument\.write",
    r"\beval\s*\(",
    r"\bnew\s+Function\b",
    r"\blocalStorage\b",
    r"\bsetAttribute\s*\(\s*['\"]style",
    r"\.style\b",
    r"\bcssText\b",
    r"createElement\s*\(\s*['\"]style",
    r"createElement\s*\(\s*['\"]script",
    r"\brefresh_token\b",
    r"\bid_token\b",
    r"\bdocument\.cookie\b",
    r"\bXMLHttpRequest\b",
    r"\bWebSocket\b",
    r"\bsendBeacon\b",
    r"\bimportScripts\b",
    r"\bimport\s*\(",
    r"\bindexedDB\b",
]


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_terminal_js_avoids_forbidden_apis(pattern):
    assert re.search(pattern, source()) is None


def test_fetch_targets_only_the_api_the_config_and_the_token_endpoint():
    code = source()
    targets = re.findall(r"\bfetch\s*\(\s*([^,)\s]+)", code)
    assert sorted(targets) == ["API_PATH", "CONFIG_PATH", "tokenUrl"]
    assert re.search(r'const API_PATH = "/api/command";', code)
    assert re.search(r'const CONFIG_PATH = "config\.json";', code)
    assert re.search(r'const tokenUrl = cfg\.auth_domain \+ "/oauth2/token";', code)


def test_no_url_literals_except_the_auth_paths():
    code = source()
    assert "http://" not in code
    # The only "https://" is inside the auth-domain pattern.
    assert len(re.findall(r"https:", code)) == 1
    assert "amazoncognito" in code.split("AUTH_DOMAIN_RE")[1].split(";")[0]


def test_session_storage_is_used_only_for_the_two_keys():
    code = source()
    assert re.search(r'const PKCE_KEY = "cerberus-pkce";', code)
    assert re.search(r'const ENDED_KEY = "cerberus-ended";', code)
    calls = re.findall(r"\bsessionStorage\.(\w+)\(\s*([A-Za-z_]+)", code)
    assert calls, "sessionStorage is not used at all"
    assert len(calls) == len(re.findall(r"\bsessionStorage\b", code))
    assert {key for _, key in calls} == {"PKCE_KEY", "ENDED_KEY"}
    assert {method for method, _ in calls} <= {"getItem", "setItem", "removeItem"}


def test_the_token_is_a_module_variable_and_is_not_stored():
    code = source()
    assert re.search(r"^let token = null;", code, flags=re.MULTILINE)
    assert "access_token" in code
    # access_token is read from the response and handed on; it is never written to storage.
    for line in code.splitlines():
        if "setItem" in line:
            assert "token" not in line.lower().replace("pkce", ""), line


def test_the_start_call_waits_for_a_document():
    code = source()
    assert re.search(r'if \(typeof document !== "undefined"\) \{\s*start\(\);\s*\}', code)
    assert re.search(r'if \(typeof module !== "undefined"\) \{\s*module\.exports', code)


# ---- parity with the repo ----


def js_minutes(name: str) -> int:
    match = re.search(rf"^const {name} = (\d+) \* 60 \* 1000;", source(), flags=re.MULTILINE)
    assert match, name
    return int(match.group(1))


def test_limits_match_the_adr():
    adr = " ".join(ADR.read_text(encoding="utf-8").split())
    assert int(re.search(r"a (\d+)-minute token", adr).group(1)) == js_minutes("LIMIT_MS") == 60
    assert int(re.search(r"a (\d+)-minute idle drop", adr).group(1)) == js_minutes("IDLE_MS") == 15
    assert f"min(sign-in + {js_minutes('LIMIT_MS')} minutes" in adr
    assert f"The idle drop is {js_minutes('IDLE_MS')} minutes" in adr


def test_the_ended_messages_match_the_limits():
    code = source()
    assert f"Session ended ({js_minutes('IDLE_MS')} minutes idle)" in code
    assert f"Session ended ({js_minutes('LIMIT_MS')}-minute limit)" in code


def test_every_ended_reason_has_a_message():
    code = source()
    block = re.search(r"const ENDED_TEXT = \{(.*?)\n\};", code, flags=re.DOTALL).group(1)
    keys = set(re.findall(r"^\s*([a-z]+):", block, flags=re.MULTILINE))
    assert keys == {"idle", "limit", "signout", "expired"}
    assert set(re.findall(r'\bend\("([a-z]+)"\)', code)) <= keys


def test_the_limit_is_not_longer_than_the_token_validity():
    text = EDGE_VARS.read_text(encoding="utf-8")
    block = re.search(r'variable "token_validity_minutes" \{(.*?)\n\}', text, flags=re.DOTALL)
    default = int(re.search(r"default\s*=\s*(\d+)", block.group(1)).group(1))
    assert js_minutes("LIMIT_MS") <= default
    assert js_minutes("IDLE_MS") < js_minutes("LIMIT_MS")


def test_command_names_match_the_grammar():
    match = re.search(r"^const COMMAND_NAMES = (\[.*?\]);", source(), flags=re.MULTILINE)
    names = re.findall(r'"([a-z]+)"', match.group(1))
    assert names == list(grammar.COMMANDS)
    assert "clear" not in names


def test_the_limits_in_the_page_are_the_servers_limits():
    # The page does not filter input. The maxlength is for usability (test_terminal_build).
    assert config.MAX_TOKENS * config.MAX_TOKEN_CHARS + config.MAX_TOKENS - 1 == 519


def test_the_config_patterns_match_the_plan():
    code = source()
    assert r"/^https:\/\/[a-z0-9-]+\.auth\.us-east-1\.amazoncognito\.com$/" in code
    assert r"/^[a-z0-9]{1,128}$/" in code


# ---- the preview server ----


def edge_csp() -> str:
    text = EDGE_MAIN.read_text(encoding="utf-8")
    block = re.search(r'content_security_policy = join\("; ", \[(.*?)\]\)', text, flags=re.DOTALL)
    parts = re.findall(r'"([^"]+)"', block.group(1))
    return "; ".join(parts)


def test_preview_policy_is_the_edge_policy_minus_upgrade_insecure_requests():
    edge = edge_csp().replace("${local.cognito_url}", "<cognito>")
    assert edge.endswith("; upgrade-insecure-requests")
    expected = edge.removesuffix("; upgrade-insecure-requests")
    assert serve.CSP.replace(serve.COGNITO, "<cognito>") == expected
    assert "unsafe" not in serve.CSP


def test_preview_server_sends_the_csp_on_every_response(tmp_path):
    build.build(tmp_path)
    server = serve.make_server(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert server.server_address[0] == "127.0.0.1"
        for path in ("/terminal/index.html", "/missing"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            assert resp.getheader("Content-Security-Policy") == serve.CSP
            assert resp.getheader("X-Content-Type-Options") == "nosniff"
            conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_preview_refuses_a_missing_build(tmp_path, capsys):
    assert serve.main(["--dir", str(tmp_path)]) == 1
    assert "make console-terminal" in capsys.readouterr().err
