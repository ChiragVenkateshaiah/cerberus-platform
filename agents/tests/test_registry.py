"""The registry on its own: tool list, schemas, response cap, call budget (14.2b)."""

import json

import pytest

from cerberus_agents import registry
from cerberus_agents.registry import Registry, Tool
from cerberus_agents.tools import build_registry

EXPECTED = (
    "status",
    "runs",
    "run",
    "cost",
    "dq",
    "slo",
    "review",
    "queries_list",
    "query",
)


def test_the_tool_list_is_stable_and_complete():
    tools = build_registry().list_tools()
    assert tuple(t["name"] for t in tools) == EXPECTED
    assert tools == build_registry().list_tools()  # same data every time
    assert "help" not in {t["name"] for t in tools}


def test_the_list_is_plain_json_data():
    tools = build_registry().list_tools()
    assert json.loads(json.dumps(tools)) == tools


@pytest.mark.parametrize("tool", build_registry().list_tools(), ids=lambda t: t["name"])
def test_each_schema_is_a_closed_object_schema(tool):
    assert set(tool) == {"name", "description", "inputSchema"}
    assert tool["description"].isascii() and tool["description"]
    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) <= set(schema["properties"])
    for prop in schema["properties"].values():
        assert prop["type"] == "string"
        assert "pattern" in prop or "enum" in prop


def test_the_aws_tools_say_they_are_offline():
    by_name = {t["name"]: t for t in build_registry().list_tools()}
    assert "Offline" in by_name["status"]["description"]
    assert "Offline" in by_name["run"]["description"]


def test_the_query_enum_is_the_entry_set():
    by_name = {t["name"]: t for t in build_registry().list_tools()}
    enum = by_name["query"]["inputSchema"]["properties"]["name"]["enum"]
    assert len(enum) == 17 and "latest_status" in enum


def test_a_listed_schema_is_a_copy():
    reg = build_registry()
    reg.list_tools()[0]["inputSchema"]["properties"]["x"] = {}
    assert "x" not in reg.list_tools()[0]["inputSchema"]["properties"]


def test_duplicate_registration_is_an_error():
    reg = Registry()
    reg.register(Tool("a", "d", handler=lambda a: ({}, "")))
    with pytest.raises(ValueError):
        reg.register(Tool("a", "d", handler=lambda a: ({}, "")))


def test_unknown_tool_and_bad_argument_shapes_are_refused():
    reg = build_registry()
    for name in ("nope", "help", None, 5, ["status"], "status "):
        assert reg.call(name) == registry.REFUSED
    for args in ([], "x", 5, {"id": 5}, {"x": "y"}, {1: "a"}, {"id": None}):
        assert reg.call("run", args) == registry.REFUSED
    assert reg.call("run") == registry.REFUSED  # id is required
    assert reg.call("status", {"id": "x"}) == registry.REFUSED  # no arguments allowed


# ---- response cap -----------------------------------------------------------


def _huge_registry():
    reg = Registry()
    deep = [["x" * 150] * 50 for _ in range(50)]  # 50 x 50 strings: over the cap
    reg.register(Tool("big", "d", handler=lambda a: ({"a": [deep] * 50}, "t" * 40000)))
    return reg


def test_the_response_cap_is_64_kib():
    assert registry.RESPONSE_BYTES == 65536


def test_an_oversize_response_is_cut_with_a_fixed_marker():
    out = _huge_registry().call("big")
    assert out["ok"] is True
    assert out["data"] == {"truncated": True}
    assert out["text"].endswith("(truncated)")
    assert len(json.dumps(out, ensure_ascii=True)) <= registry.RESPONSE_BYTES


def test_a_normal_response_is_within_the_cap():
    out = build_registry().call("runs")
    assert out["ok"] is True
    assert len(json.dumps(out, ensure_ascii=True)) <= registry.RESPONSE_BYTES


# ---- call budget ------------------------------------------------------------


def test_the_budget_constant_and_default():
    assert registry.CALL_BUDGET == 100
    assert Registry().budget == registry.CALL_BUDGET


def test_calls_past_the_budget_get_the_fixed_budget_answer():
    reg = build_registry(budget=3)
    for _ in range(3):
        assert reg.call("slo")["ok"] is True
    for _ in range(2):
        assert reg.call("slo") == registry.BUDGET
    assert reg.call("nope") == registry.BUDGET  # refused calls count too


def test_each_instance_has_its_own_counter():
    a, b = build_registry(budget=1), build_registry(budget=1)
    assert a.call("slo")["ok"] is True
    assert a.call("slo") == registry.BUDGET
    assert b.call("slo")["ok"] is True


def test_a_handler_failure_is_the_fixed_unavailable_text():
    def boom(args):
        raise RuntimeError("secret detail arn:aws:x:us-east-1:" + "1" * 12)

    reg = Registry()
    reg.register(Tool("boom", "d", handler=boom))
    assert reg.call("boom") == registry.UNAVAILABLE
