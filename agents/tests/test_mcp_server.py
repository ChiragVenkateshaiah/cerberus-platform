"""The stdio MCP server driven through `serve(stdin, stdout)` (14.2c).

No subprocess: ruff bans it in the package, and a direct call tests the same code.
"""

import io
import json
import re
from pathlib import Path

import pytest
from hostile import ARGV, DATA_STRINGS

from cerberus_agents import mcp_server, registry
from cerberus_agents.mcp_server import serve
from cerberus_agents.tools import build_registry

RUNS = Path(__file__).resolve().parents[2] / "observability" / "scale" / "runs"
PROBE = "PROBE_zq7_distinctive_text"
ASCII_LINE = re.compile(r"[\x20-\x7e]*")


def run(lines, reg=None):
    """Feed raw input; return the list of parsed responses (each checked)."""
    raw = lines if isinstance(lines, str) else "".join(json.dumps(m) + "\n" for m in lines)
    out = io.StringIO()
    serve(io.StringIO(raw), out, reg or build_registry(RUNS))
    text = out.getvalue()
    assert text == "" or text.endswith("\n")
    responses = []
    for line in text.splitlines():
        assert ASCII_LINE.fullmatch(line), "response is not plain ASCII"
        msg = json.loads(line)
        assert msg["jsonrpc"] == "2.0"
        responses.append(msg)
    return responses


def req(rid, method, params=None):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(name, arguments=None, rid=1):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return run([req(rid, "tools/call", params)])[0]


def test_the_scripted_handshake():
    out = run(
        [
            req(1, "initialize", {"protocolVersion": "x", "capabilities": {}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            req(2, "tools/list"),
            req(3, "ping"),
        ]
    )
    assert [r["id"] for r in out] == [1, 2, 3]  # the notification got no reply
    init = out[0]["result"]
    assert init["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert init["capabilities"] == {"tools": {}}
    assert init["serverInfo"] == {
        "name": mcp_server.SERVER_NAME,
        "version": mcp_server.SERVER_VERSION,
    }
    assert out[2]["result"] == {}


def test_the_tool_list_equals_the_registry_list():
    tools = run([req(7, "tools/list")])[0]["result"]["tools"]
    assert tools == build_registry(RUNS).list_tools()
    assert len(tools) == 9
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"


def test_runs_review_and_queries_list():
    runs = call("runs")["result"]
    assert runs["isError"] is False
    assert runs["content"][0]["type"] == "text" and runs["content"][0]["text"]
    assert type(runs["structuredContent"]) is dict
    review = call("review", {"id": "latest"})["result"]
    assert review["isError"] is False and review["content"][0]["text"]
    assert call("queries_list")["result"]["isError"] is False


def test_query_with_a_valid_name_is_unavailable_offline():
    res = call("query", {"name": "latest_status"})["result"]
    assert res["isError"] is True
    assert res["content"][0]["text"] == registry.UNAVAILABLE["text"]
    assert "error" not in call("query", {"name": "latest_status"})  # not a JSON-RPC error


def test_a_refused_argument_and_an_unknown_tool_are_results_not_errors():
    for response in (call("runs", {"bogus": PROBE}), call(PROBE), call("run", {"id": 5})):
        assert "error" not in response
        res = response["result"]
        assert res["isError"] is True
        assert res["content"][0]["text"] == registry.REFUSED["text"]
        assert PROBE not in json.dumps(response)


@pytest.mark.parametrize(
    "message,code",
    [
        (req(1, PROBE), -32601),
        (req(1, "tools/call", {"arguments": {}}), -32602),
        (req(1, "tools/call", {"name": 5}), -32602),
        (req(1, "tools/call", PROBE), -32602),
        (req(1, "tools/list", [PROBE]), -32602),
        ({"jsonrpc": "2.0", "id": 1}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": 5}, -32600),
        ({"jsonrpc": "2.0", "id": {"a": PROBE}, "method": "ping"}, -32600),
        ([PROBE], -32600),
        (PROBE, -32600),
        (5, -32600),
        (None, -32600),
    ],
)
def test_wrong_shapes_get_fixed_errors(message, code):
    (response,) = run([message])
    assert response["error"]["code"] == code
    assert PROBE not in json.dumps(response)
    assert "result" not in response


def test_the_request_id_is_echoed_for_a_string_id():
    assert run([req("abc", "ping")])[0]["id"] == "abc"


@pytest.mark.parametrize("raw", ["{" + PROBE, PROBE, '{"a": ' + PROBE + "}", "[" * 60000])
def test_malformed_json_is_a_parse_error(raw):
    (response,) = run(raw + "\n")
    assert response["error"]["code"] == -32700 and response["id"] is None
    assert PROBE not in json.dumps(response)


def test_an_oversize_line_gets_one_fixed_error_and_the_session_continues():
    big = '{"jsonrpc":"2.0","id":1,"method":"' + PROBE * 20000 + '"}\n'
    assert len(big) > mcp_server.LINE_BYTES
    out = run(big + json.dumps(req(2, "ping")) + "\n")
    assert [r.get("id") for r in out] == [None, 2]
    assert out[0]["error"] == {"code": -32600, "message": mcp_server.LINE_TOO_LONG[1]}
    assert out[1]["result"] == {}
    assert PROBE not in json.dumps(out)


def test_a_line_of_exactly_the_cap_is_still_read():
    base = json.dumps({**req(1, "ping"), "x": ""})
    line = json.dumps({**req(1, "ping"), "x": "a" * (mcp_server.LINE_BYTES - len(base))})
    assert len(line) == mcp_server.LINE_BYTES
    assert run(line + "\n")[0]["result"] == {}


def _line_of(length):
    base = json.dumps({**req(1, "ping"), "x": ""})
    return json.dumps({**req(1, "ping"), "x": "a" * (length - len(base))})


def test_the_line_cap_accepts_the_cap_and_rejects_one_more():
    cap = mcp_server.LINE_BYTES
    assert run(_line_of(cap) + "\n")[0]["result"] == {}
    (response,) = run(_line_of(cap + 1) + "\n")
    assert response["error"]["message"] == mcp_server.LINE_TOO_LONG[1]
    (response,) = run(_line_of(cap + 1))  # no newline at end of input
    assert response["error"]["message"] == mcp_server.LINE_TOO_LONG[1]


def test_end_of_input_in_the_middle_of_a_line_is_still_answered():
    out = run(json.dumps(req(1, "ping")) + "\n" + json.dumps(req(2, "ping")))
    assert [r["id"] for r in out] == [1, 2]


@pytest.mark.parametrize("version", mcp_server.SUPPORTED_VERSIONS)
def test_a_supported_protocol_version_is_echoed(version):
    out = run([req(1, "initialize", {"protocolVersion": version})])
    assert out[0]["result"]["protocolVersion"] == version


@pytest.mark.parametrize("asked", [PROBE, "1999-01-01", 5, None, ["2025-06-18"], "MISSING"])
def test_an_unsupported_protocol_version_gets_the_constant(asked):
    params = {} if asked == "MISSING" else {"protocolVersion": asked}
    response = run([req(1, "initialize", params)])[0]
    assert response["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert PROBE not in json.dumps(response)


def test_notifications_get_no_reply():
    out = run(
        [
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": PROBE},
            {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "runs"}},
            {"jsonrpc": "2.0", "method": "ping", "params": PROBE},
        ]
    )
    assert out == []


def test_end_of_input_ends_cleanly_with_or_without_a_final_newline():
    assert run("") == []
    assert run("\n\n") == []
    assert run(json.dumps(req(1, "ping")))[0]["result"] == {}


def test_the_call_budget_still_applies_through_the_server():
    reg = build_registry(RUNS, budget=1)
    out = run([req(1, "tools/call", {"name": "runs"})] * 2, reg)
    assert out[0]["result"]["isError"] is False
    assert out[1]["result"]["isError"] is True
    assert out[1]["result"]["content"][0]["text"] == registry.BUDGET["text"]


def _hostile_arguments():
    for key, value in ARGV.items():
        yield f"argv:{key}", value
    for i, value in enumerate(DATA_STRINGS):
        yield f"data:{i}", {"id": value}
        yield f"name:{i}", {"name": value}


def _safe(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


@pytest.mark.parametrize(
    "tool", ["runs", "run", "cost", "dq", "slo", "review", "queries_list", "query", "status"]
)
def test_the_hostile_corpus_never_echoes_or_leaks_non_ascii(tool):
    reg = build_registry(RUNS)
    for label, arguments in _hostile_arguments():
        if _safe(arguments) is None:
            continue
        message = req(1, "tools/call", {"name": tool, "arguments": arguments})
        raw = json.dumps(message) + "\n"
        out = io.StringIO()
        serve(io.StringIO(raw), out, reg)
        reg.calls = 0
        text = out.getvalue()
        assert text.count("\n") == 1, label
        assert ASCII_LINE.fullmatch(text[:-1]), label
        response = json.loads(text)
        if "error" in response:
            assert response["error"]["code"] in (-32600, -32602), label
        for value in arguments.values() if type(arguments) is dict else []:
            if type(value) is str and len(value) > 3:
                assert value not in text, label


def test_a_normal_session_writes_nothing_to_stderr(capsys):
    run([req(1, "initialize"), req(2, "tools/list"), req(3, "tools/call", {"name": "runs"})])
    run('{"bad\n')
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_the_aws_flag_exits_2_with_a_fixed_message(capsys):
    assert mcp_server.main(["--aws"]) == 2
    err = capsys.readouterr().err
    assert err.strip() == mcp_server.AWS_NOT_AVAILABLE
