"""Every case in the shared hostile corpus goes through the whole request path (9.6).

parse_body -> handle_body -> lambda_handler (a full HTTP API v2 event). A refusal
is one fixed answer: status 400, the same 87 bytes, the same two headers. The
other two fixed answers (not found, unavailable) never contain input either.
"""

import base64
import json
from pathlib import Path

import fakes
import hostile
import pytest
from hostile import ARGV, B64_BODIES, BODIES, DATA_STRINGS, NOT_JSON_SAFE, body

from cerberus_console import commands, grammar
from cerberus_console.api import (
    NOT_FOUND,
    REFUSED,
    UNAVAILABLE,
    dispatch,
    handle_body,
    lambda_handler,
)
from cerberus_console.sources import Sources

NOSRC = Sources(runs_dir=fakes.FIXTURES)  # never read: a refusal happens before any source

REFUSED_WIRE = (
    '{"ok":false,"error":"refused","text":"Not an allowed command. Type help for the list."}'
)
HEADERS = {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"}


def v2_event(raw_body, is_base64=False):
    """The shape API Gateway sends for payload format 2.0."""
    return {
        "version": "2.0",
        "routeKey": "POST /api/command",
        "rawPath": "/api/command",
        "rawQueryString": "",
        "headers": {"content-type": "application/json", "authorization": "Bearer x"},
        "requestContext": {
            "http": {"method": "POST", "path": "/api/command"},
            "authorizer": {"jwt": {"claims": {"sub": "s"}, "scopes": ["openid"]}},
        },
        "body": raw_body,
        "isBase64Encoded": is_base64,
    }


def assert_fixed_refusal(out):
    assert out["statusCode"] == 400
    assert out["headers"] == HEADERS
    assert out["body"] == REFUSED_WIRE
    assert len(out["body"].encode("utf-8")) == 87


def test_the_fixed_refusal_is_87_bytes():
    assert json.dumps(REFUSED, ensure_ascii=True, separators=(",", ":")) == REFUSED_WIRE
    assert len(REFUSED_WIRE.encode("utf-8")) == 87


def test_the_corpus_source_is_ascii():
    # Every odd character is written as an escape, so no editor or formatter can alter it.
    assert Path(hostile.__file__).read_text(encoding="utf-8").isascii()


def test_corpus_is_not_empty():
    assert len(BODIES) >= 50 and len(B64_BODIES) >= 15 and len(ARGV) >= 120
    assert len(DATA_STRINGS) >= 35


# --- bodies ---------------------------------------------------------------


def refused_at_some_stage(raw, is_base64):
    """parse_body then parse_argv: the case must be refused by one of them."""
    with pytest.raises(grammar.Refused):
        grammar.parse_argv(grammar.parse_body(raw, is_base64))


@pytest.mark.parametrize("name", BODIES)
def test_body_through_every_layer(name):
    raw = BODIES[name]
    refused_at_some_stage(raw, False)
    resp = handle_body(raw, False, NOSRC)
    assert (resp.status, resp.body) == (400, REFUSED)
    assert resp.to_json() == REFUSED_WIRE
    assert_fixed_refusal(lambda_handler(v2_event(raw), None, sources=NOSRC))


@pytest.mark.parametrize("name", B64_BODIES)
def test_base64_body_through_every_layer(name):
    raw = B64_BODIES[name]
    refused_at_some_stage(raw, True)
    resp = handle_body(raw, True, NOSRC)
    assert (resp.status, resp.body) == (400, REFUSED)
    assert resp.to_json() == REFUSED_WIRE
    assert_fixed_refusal(lambda_handler(v2_event(raw, True), None, sources=NOSRC))


@pytest.mark.parametrize("name", BODIES)
def test_a_bad_body_is_also_refused_when_sent_as_base64(name):
    raw = BODIES[name]
    if isinstance(raw, str) and "\ud800" not in raw:
        wrapped = base64.b64encode(raw.encode("utf-8")).decode()
        assert_fixed_refusal(lambda_handler(v2_event(wrapped, True), None, sources=NOSRC))


# --- argv -----------------------------------------------------------------


@pytest.mark.parametrize("name", ARGV)
def test_argv_through_every_layer(name):
    argv = ARGV[name]
    with pytest.raises(grammar.Refused):
        grammar.parse_argv(argv)
    resp = dispatch(argv, NOSRC)
    assert (resp.status, resp.body) == (400, REFUSED)
    assert resp.to_json() == REFUSED_WIRE
    if name in NOT_JSON_SAFE:
        return
    raw = body(argv)
    refused_at_some_stage(raw, False)
    assert_fixed_refusal(lambda_handler(v2_event(raw), None, sources=NOSRC))
    wrapped = base64.b64encode(raw.encode("utf-8")).decode()
    assert_fixed_refusal(lambda_handler(v2_event(wrapped, True), None, sources=NOSRC))


def test_a_refusal_never_echoes_any_part_of_the_input():
    for name, argv in ARGV.items():
        if name in NOT_JSON_SAFE or not isinstance(argv, list):
            continue
        out = lambda_handler(v2_event(body(argv)), None, sources=NOSRC)
        for tok in argv:
            if isinstance(tok, str) and tok.isascii() and len(tok) >= 4 and tok not in REFUSED_WIRE:
                assert tok not in out["body"]


def test_every_refusal_in_the_corpus_is_the_same_bytes():
    wires = set()
    for raw in BODIES.values():
        wires.add(lambda_handler(v2_event(raw), None, sources=NOSRC)["body"])
    for raw in B64_BODIES.values():
        wires.add(lambda_handler(v2_event(raw, True), None, sources=NOSRC)["body"])
    for name, argv in ARGV.items():
        if name not in NOT_JSON_SAFE:
            wires.add(lambda_handler(v2_event(body(argv)), None, sources=NOSRC)["body"])
    assert wires == {REFUSED_WIRE}


@pytest.mark.parametrize(
    "event",
    [None, "text", 5, [], {}, {"body": None}, {"body": 5}, {"isBase64Encoded": True}, {"body": []}],
)
def test_events_that_are_not_a_request_are_refused(event):
    assert_fixed_refusal(lambda_handler(event, None, sources=NOSRC))


# --- the size boundary -----------------------------------------------------


def padded(total_bytes):
    valid = '{"argv": ["help"]}'
    return valid + " " * (total_bytes - len(valid))


def test_a_body_of_exactly_2048_bytes_is_read_and_2049_is_refused():
    assert len(padded(2048).encode()) == 2048
    ok = handle_body(padded(2048), False, NOSRC)
    assert (ok.status, ok.body["command"]) == (200, "help")
    assert handle_body(padded(2049), False, NOSRC).body == REFUSED


def test_the_limit_counts_bytes_not_characters():
    # 2048 characters pass the character check; 2049 bytes fail the byte check.
    # The body is refused by parse_body itself (not later), so the byte branch ran.
    two_over = padded(2047) + "\xe9"
    assert len(two_over) == 2048 and len(two_over.encode()) == 2049
    with pytest.raises(grammar.Refused):
        grammar.parse_body(two_over, False)
    assert handle_body(two_over, False, NOSRC).body == REFUSED


# --- the other two fixed answers -------------------------------------------


def wire(resp):
    return json.dumps(resp, ensure_ascii=True, separators=(",", ":"))


def test_not_found_is_fixed_and_has_no_input(tmp_path):
    runs = fakes.materialize_runs(tmp_path / "runs")
    src = fakes.aws_sources(runs)
    probe = "zzqq-probe-77"
    out = lambda_handler(v2_event(body(["run", probe])), None, sources=src)
    assert out["statusCode"] == 404
    assert out["headers"] == HEADERS
    assert out["body"] == wire(NOT_FOUND)
    assert probe not in out["body"]
    # Same bytes for a different probe.
    other = lambda_handler(v2_event(body(["run", "yyxx-other-1"])), None, sources=src)
    assert other["body"] == out["body"]


def test_unavailable_is_fixed_and_has_no_input(tmp_path, monkeypatch):
    runs = fakes.materialize_runs(tmp_path / "runs")
    src = fakes.aws_sources(runs)
    secret = "arn:aws:states:us-east-1:" + fakes.FAKE_ACCOUNT + ":execution:x SECRET-TEXT"

    def broken(ctx, args):
        raise fakes.Boom(secret)

    monkeypatch.setitem(commands.HANDLERS, "runs", broken)
    out = lambda_handler(v2_event(body(["runs"])), None, sources=src)
    assert out["statusCode"] == 503
    assert out["headers"] == HEADERS
    assert out["body"] == wire(UNAVAILABLE)
    assert "SECRET-TEXT" not in out["body"] and fakes.FAKE_ACCOUNT not in out["body"]
