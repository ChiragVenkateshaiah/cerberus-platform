import base64
import json

import pytest

from cerberus_console import grammar
from cerberus_console.api import REFUSED, dispatch, handle_body
from cerberus_console.sources import Sources

NOSRC = Sources(runs_dir=__import__("pathlib").Path("."))


def body(argv):
    return json.dumps({"argv": argv})


BAD_BODIES = {
    "not json": "{nope",
    "not an object": '["status"]',
    "string": '"status"',
    "extra key": '{"argv": ["status"], "x": 1}',
    "no argv": "{}",
    "duplicate argv": '{"argv": ["status"], "argv": ["runs"]}',
    "over 2048 bytes": '{"argv": ["' + "a" * 2100 + '"]}',
    "missing body": None,
    "int body": 5,
}


@pytest.mark.parametrize("name", BAD_BODIES)
def test_bad_body_is_refused(name):
    resp = handle_body(BAD_BODIES[name], False, NOSRC)
    assert resp.status == 400
    assert resp.body == REFUSED


def test_bad_base64_is_refused():
    assert handle_body("!!!not base64!!!", True, NOSRC).body == REFUSED
    # valid base64 of invalid UTF-8
    assert handle_body(base64.b64encode(b"\xff\xfe").decode(), True, NOSRC).body == REFUSED


def test_base64_body_is_accepted():
    raw = base64.b64encode(body(["help"]).encode()).decode()
    resp = handle_body(raw, True, NOSRC)
    assert resp.status == 200
    assert resp.body["command"] == "help"


def test_deeply_nested_json_is_refused():
    assert handle_body('{"argv":' + "[" * 1500 + "]" * 1500 + "}", False, NOSRC).body == REFUSED


BAD_ARGV = {
    "not a list": "status",
    "empty list": [],
    "nine tokens": ["help"] * 9,
    "65 chars": ["a" * 65],
    "int": [5],
    "bool": [True],
    "none": [None],
    "dict": [{"a": 1}],
    "nested list": [["status"]],
    "semicolon": ["status;"],
    "command substitution": ["$(id)"],
    "backtick": ["`id`"],
    "pipe": ["status|id"],
    "and": ["status&&id"],
    "redirect": ["status>x"],
    "space": ["status runs"],
    "newline": ["status\n"],
    "carriage return": ["status\r"],
    "nul": ["status\x00"],
    "dotdot": ["../"],
    "path": ["/etc/passwd"],
    "upper": ["STATUS"],
    "mixed case": ["Status"],
    "fullwidth": ["\uff53\uff54\uff41\uff54\uff55\uff53"],
    "rtl override": ["\u202estatus"],
    "zero width": ["sta\u200btus"],
    "dash h": ["-h"],
    "json flag": ["--json", "status"],
    "double cerberus": ["cerberus", "cerberus", "status"],
    "only cerberus": ["cerberus"],
    "extra arg": ["status", "extra"],
    "run without id": ["run"],
    "run two ids": ["run", "a", "b"],
    "run 65 chars": ["run", "a" * 65],
    "unknown command": ["ls"],
    "help unknown": ["help", "ls"],
    "cost two ids": ["cost", "a", "b"],
}


@pytest.mark.parametrize("name", BAD_ARGV)
def test_bad_argv_is_refused_with_fixed_text(name):
    argv = BAD_ARGV[name]
    for resp in (dispatch(argv, NOSRC), handle_body(body(argv), False, NOSRC)):
        assert resp.status == 400
        assert resp.body == REFUSED
        assert resp.to_json() == json.dumps(REFUSED, separators=(",", ":"))


def test_refusal_text_has_no_input_substring():
    probe = "zzqq-hostile-token"
    resp = dispatch([probe], NOSRC)
    assert probe not in resp.to_json()


@pytest.mark.parametrize(
    "argv,name,args",
    [
        (["status"], "status", ()),
        (["cerberus", "status"], "status", ()),
        (["run", "latest"], "run", ("latest",)),
        (["cost"], "cost", ()),
        (["cost", "exercise-20261013T055859Z"], "cost", ("exercise-20261013T055859Z",)),
        (["help", "slo"], "help", ("slo",)),
        (["a"], None, None),
    ],
)
def test_valid_commands(argv, name, args):
    if name is None:
        with pytest.raises(grammar.Refused):
            grammar.parse_argv(argv)
        return
    cmd = grammar.parse_argv(argv)
    assert (cmd.name, cmd.args) == (name, args)


def test_token_ending_in_newline_is_not_accepted():
    # fullmatch, not match with `$`
    with pytest.raises(grammar.Refused):
        grammar.parse_argv(["status\n"])
