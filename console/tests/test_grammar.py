import base64
import json

import pytest
from hostile import ARGV, B64_BODIES, BODIES, NOT_JSON_SAFE

from cerberus_console import grammar
from cerberus_console.api import REFUSED, dispatch, handle_body
from cerberus_console.sources import Sources

NOSRC = Sources(runs_dir=__import__("pathlib").Path("."))


def body(argv):
    return json.dumps({"argv": argv})


@pytest.mark.parametrize("name", BODIES)
def test_bad_body_is_refused(name):
    resp = handle_body(BODIES[name], False, NOSRC)
    assert resp.status == 400
    assert resp.body == REFUSED


@pytest.mark.parametrize("name", B64_BODIES)
def test_bad_base64_is_refused(name):
    resp = handle_body(B64_BODIES[name], True, NOSRC)
    assert resp.status == 400
    assert resp.body == REFUSED


def test_base64_body_is_accepted():
    raw = base64.b64encode(body(["help"]).encode()).decode()
    resp = handle_body(raw, True, NOSRC)
    assert resp.status == 200
    assert resp.body["command"] == "help"


def test_deeply_nested_json_is_refused():
    assert handle_body('{"argv":' + "[" * 1500 + "]" * 1500 + "}", False, NOSRC).body == REFUSED


@pytest.mark.parametrize("name", ARGV)
def test_bad_argv_is_refused_with_fixed_text(name):
    argv = ARGV[name]
    responses = [dispatch(argv, NOSRC)]
    if name not in NOT_JSON_SAFE:
        responses.append(handle_body(body(argv), False, NOSRC))
    for resp in responses:
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
