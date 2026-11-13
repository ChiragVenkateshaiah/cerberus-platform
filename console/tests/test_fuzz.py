# ruff: noqa: S311
# (A seeded generator on purpose: the run must be the same every time. Nothing here is secret.)
"""A seeded fuzz of the grammar, the request path and the sanitiser (9.6).

Plain stdlib, no hypothesis: the grammar is a closed allowlist, so a hostile
alphabet finds the same faults, and the run is the same every time
(random.Random(96)). The properties:

  grammar    parse_argv raises only Refused. It accepts exactly what an
             independent model accepts, and only ASCII tokens of known commands.
  request    handle_body and lambda_handler never raise. Every status is in
             {200, 400, 404, 503}. Every 400 is the same bytes.
  sanitiser  output is in [\\x20-\\x7e\\n], within the caps, and idempotent.
  size       huge `data` stays within RESPONSE_BYTES; `data` nested 5000 deep
             becomes the fixed 503.
"""

import base64
import json
import random
import re
import string

import fakes
import pytest
from hostile import ARGV, BODIES, DATA_STRINGS

from cerberus_console import api, commands, config, grammar, sanitize
from cerberus_console.sources import Sources

SEED = 96
ARGV_CASES = 3000
BODY_CASES = 1000
SANITIZE_CASES = 1000
DATA_CASES = 400

REFUSED_WIRE = json.dumps(api.REFUSED, ensure_ascii=True, separators=(",", ":"))
UNAVAILABLE_WIRE = json.dumps(api.UNAVAILABLE, ensure_ascii=True, separators=(",", ":"))
STATUSES = {200, 400, 404, 503}
PRINTABLE = re.compile(r"[\x20-\x7e\n]*")
ARN_WITH_ACCOUNT = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:\d{12}")
NAMES = list(grammar.COMMANDS)

# One list of hostile characters per family in the corpus.
HOSTILE_CHARS = (
    list(" ;$|&<>`'\"\\(){}[]*?!~#%=,:@+/.")  # shell, path, quote, punctuation
    + ["\x00", "\x07", "\x08", "\t", "\n", "\x0b", "\x0c", "\r", "\x1b", "\x7f"]  # C0 and DEL
    + ["\x85", "\x9b", "\u00a0"]  # C1, no-break space
    + ["\u2028", "\u2029", "\u3000"]  # separators
    + ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]  # zero-width, BOM
    + ["\u202a", "\u202e", "\u2066", "\u2069"]  # bidi
    + ["\uff53", "\uff54", "\uff10"]  # fullwidth
    + ["\u212a", "\u017f", "\u0455", "\u0430", "\u03bf"]  # Kelvin, long s, lookalikes
    + ["\u0661", "\u0967"]  # other digits
    + ["\u0301", "\u0308"]  # combining
    + ["\ud800", "\udc00", "\udfff"]  # lone surrogates
    + ["\u00e9", "\U0001f600", "\U0010ffff"]  # multibyte
)
TOKEN_CHARS = string.ascii_letters + string.digits + "-"


def ok_token(tok):
    """An independent model of one allowed token: the first character is a letter or digit."""
    return (
        type(tok) is str
        and 1 <= len(tok) <= config.MAX_TOKEN_CHARS
        and all(c in TOKEN_CHARS for c in tok)
        and tok[0] != "-"
    )


def model_accepts(argv):
    """An independent model of parse_argv: does it accept, and as what?"""
    if not isinstance(argv, list) or not 1 <= len(argv) <= config.MAX_TOKENS:
        return None
    if not all(ok_token(t) for t in argv):
        return None
    if argv[0] == "cerberus":
        argv = argv[1:]
    if not argv or argv[0] not in grammar.COMMANDS:
        return None
    name, args = argv[0], argv[1:]
    low, high = grammar.COMMANDS[name]
    if not low <= len(args) <= high:
        return None
    if name == "help" and args and args[0] not in grammar.COMMANDS:
        return None
    return name, tuple(args)


def random_token(rng):
    pick = rng.random()
    if pick < 0.30:
        return rng.choice(NAMES + ["cerberus", "latest", "a", "exercise-20261013T055859Z"])
    if pick < 0.45:  # a real word with one hostile character put in
        word = rng.choice(NAMES)
        at = rng.randint(0, len(word))
        return word[:at] + rng.choice(HOSTILE_CHARS) + word[at:]
    if pick < 0.65:  # valid characters, any length up to a bit over the limit
        n = rng.randint(1, config.MAX_TOKEN_CHARS + 3)
        return "".join(rng.choice(TOKEN_CHARS) for _ in range(n))
    n = rng.randint(0, 12)
    return "".join(rng.choice(HOSTILE_CHARS + list(TOKEN_CHARS)) for _ in range(n))


def random_argv(rng):
    pick = rng.random()
    if pick < 0.04:
        return rng.choice([None, 5, 1.5, True, "status", {"a": 1}, b"x", ("status",), [[]]])
    if pick < 0.40:  # shaped like a real command: more of these are accepted
        name = rng.choice(NAMES)
        argv = ["cerberus"] if rng.random() < 0.2 else []
        argv.append(name)
        for _ in range(rng.randint(0, 3)):
            argv.append(rng.choice(NAMES + ["latest", "x1", "run-1"]))
        return argv
    argv = [random_token(rng) for _ in range(rng.randint(0, config.MAX_TOKENS + 2))]
    if argv and rng.random() < 0.05:
        argv[rng.randrange(len(argv))] = rng.choice([None, 7, ["x"], {"a": "b"}, False, 2.5])
    return argv


def test_the_fuzz_is_deterministic():
    one = [random_argv(random.Random(SEED)) for _ in range(5)]
    two = [random_argv(random.Random(SEED)) for _ in range(5)]
    assert one == two


# --- the grammar --------------------------------------------------------------


def test_parse_argv_matches_an_independent_model():
    rng = random.Random(SEED)
    accepted = 0
    for _ in range(ARGV_CASES):
        argv = random_argv(rng)
        expected = model_accepts(argv)
        try:
            cmd = grammar.parse_argv(argv)
        except grammar.Refused:
            assert expected is None, argv
            continue
        assert expected == (cmd.name, cmd.args), argv
        assert cmd.name in grammar.COMMANDS
        assert all(ok_token(a) and a.isascii() for a in cmd.args)
        accepted += 1
    # The run must reach both sides.
    assert 200 < accepted < ARGV_CASES - 200


def test_parse_argv_raises_only_refused_on_every_corpus_case_plus_mutations():
    rng = random.Random(SEED + 1)
    pool = [v for v in ARGV.values() if isinstance(v, list)]
    for _ in range(500):
        argv = list(rng.choice(pool))
        if argv and rng.random() < 0.7:
            i = rng.randrange(len(argv))
            if isinstance(argv[i], str):
                at = rng.randint(0, len(argv[i]))
                argv[i] = argv[i][:at] + rng.choice(HOSTILE_CHARS) + argv[i][at:]
        try:
            grammar.parse_argv(argv)
        except grammar.Refused:
            pass


# --- the request path -----------------------------------------------------------


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    return fakes.aws_sources(fakes.materialize_runs(tmp_path_factory.mktemp("runs")))


def mutate(rng, text):
    for _ in range(rng.randint(1, 3)):
        kind = rng.randrange(5)
        at = rng.randint(0, len(text))
        if kind == 0 and text:
            text = text[:at] + text[at + 1 :]
        elif kind == 1:
            text = text[:at] + rng.choice(HOSTILE_CHARS) + text[at:]
        elif kind == 2 and text:
            text = text[:at] + rng.choice(HOSTILE_CHARS + list('{}[]":,')) + text[at + 1 :]
        elif kind == 3:
            text = text[:at]
        else:
            text = text[:at] + text[at : at + 5] + text[at:]
    return text


def random_json(rng, depth=0):
    pick = rng.random()
    if depth > 4 or pick < 0.4:
        return rng.choice([None, True, 5, -1, 1.5, "", "status", "run", "$(id)", "\u202e"])
    if pick < 0.7:
        return [random_json(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {rng.choice(["argv", "x", "", "ARGV"]): random_json(rng, depth + 1) for _ in range(2)}


def random_body(rng):
    """(body, is_base64)"""
    pick = rng.random()
    if pick < 0.35:  # a valid body, damaged
        base = json.dumps({"argv": random_argv(rng)}, default=repr)
        text = mutate(rng, base)
    elif pick < 0.5:
        text = json.dumps(random_json(rng))
    elif pick < 0.7:
        text = json.dumps({"argv": [random_token(rng) for _ in range(rng.randint(0, 3))]})
    elif pick < 0.85:
        n = rng.randint(0, 60)
        text = "".join(rng.choice(HOSTILE_CHARS + list('{}[]":,argv')) for _ in range(n))
    else:  # near the size limit
        pad = rng.randint(config.MAX_BODY_BYTES - 40, config.MAX_BODY_BYTES + 40)
        text = '{"argv": ["help"]}' + " " * pad
    is_b64 = rng.random() < 0.3
    if is_b64 and rng.random() < 0.7:
        try:
            return base64.b64encode(text.encode("utf-8")).decode(), True
        except UnicodeEncodeError:
            return text, True
    return text, is_b64


def check_wire(out):
    assert out["statusCode"] in STATUSES
    assert out["headers"] == {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
    }
    assert out["body"].isascii()
    parsed = json.loads(out["body"])
    if out["statusCode"] == 400:
        assert out["body"] == REFUSED_WIRE
    elif out["statusCode"] == 200:
        assert parsed["ok"] is True
        assert len(out["body"]) <= config.RESPONSE_BYTES
        assert PRINTABLE.fullmatch(parsed["text"])
    return parsed


def test_random_bodies_never_raise_and_every_refusal_is_the_same_bytes(sources):
    rng = random.Random(SEED + 2)
    seen = {}
    for _ in range(BODY_CASES):
        raw, is_b64 = random_body(rng)
        resp = api.handle_body(raw, is_b64, sources)
        assert resp.status in STATUSES
        if resp.status == 400:
            assert resp.body == api.REFUSED
            assert resp.to_json() == REFUSED_WIRE
        out = api.lambda_handler(
            {"version": "2.0", "body": raw, "isBase64Encoded": is_b64}, None, sources=sources
        )
        check_wire(out)
        assert out["statusCode"] == resp.status
        seen[resp.status] = seen.get(resp.status, 0) + 1
    assert seen.get(400, 0) > 300 and seen.get(200, 0) > 5, seen


def test_random_argv_dispatch_statuses(sources):
    rng = random.Random(SEED + 3)
    seen = {}
    for _ in range(ARGV_CASES):
        argv = random_argv(rng)
        resp = api.dispatch(argv, sources)
        assert resp.status in STATUSES
        if model_accepts(argv) is None:
            assert resp.status == 400 and resp.to_json() == REFUSED_WIRE
        seen[resp.status] = seen.get(resp.status, 0) + 1
    assert seen[400] > 200 and seen[200] > 100, seen


def test_random_events_never_raise(sources):
    rng = random.Random(SEED + 4)
    junk = [None, 5, 1.5, True, "text", [], ["x"], {}, {"body": None}, {"body": 5}, b"x"]
    for _ in range(200):
        event = rng.choice(junk)
        if rng.random() < 0.5:
            event = {
                rng.choice(["body", "isBase64Encoded", "x"]): rng.choice(junk) for _ in range(2)
            }
        check_wire(api.lambda_handler(event, None, sources=sources))


def test_corpus_bodies_with_one_more_mutation_are_still_refused_or_ok(sources):
    rng = random.Random(SEED + 5)
    texts = [v for v in BODIES.values() if isinstance(v, str)]
    for _ in range(300):
        raw = mutate(rng, rng.choice(texts)[:400])
        resp = api.handle_body(raw, rng.random() < 0.2, sources)
        assert resp.status in STATUSES


# --- the sanitiser ----------------------------------------------------------------

RANGES = [
    (0x00, 0x7F),
    (0x80, 0x2FF),
    (0x2000, 0x206F),
    (0xD800, 0xDFFF),
    (0xFE00, 0xFEFF),
    (0xFF00, 0xFFEF),
    (0x1F300, 0x1F64F),
]
FRAGMENTS = [
    "\x1b[31m",
    "\x1b]52;c;SGVsbG8=\x07",
    "\x1b]8;;http://x\x1b\\",
    "arn:aws:states:us-east-1:123456789012:execution:x",
    "arn:aws:iam::1234567890123:role/x",
    "<script>",
    "\r\n",
]


def random_string(rng):
    parts = []
    for _ in range(rng.randint(0, 40)):
        pick = rng.random()
        if pick < 0.15:
            parts.append(rng.choice(FRAGMENTS))
        elif pick < 0.4:
            parts.append(rng.choice(DATA_STRINGS)[:50])
        else:
            lo, hi = rng.choice(RANGES)
            parts.append(chr(rng.randint(lo, hi)))
    text = "".join(parts)
    return text * 8 if rng.random() < 0.05 else text


def test_clean_str_and_clean_text_are_printable_capped_and_idempotent():
    rng = random.Random(SEED + 6)
    for _ in range(SANITIZE_CASES):
        raw = random_string(rng)
        one = sanitize.clean_str(raw)
        assert PRINTABLE.fullmatch(one) and len(one) <= config.FIELD_CHARS
        assert sanitize.clean_str(one) == one
        text = sanitize.clean_text(raw * rng.choice([1, 1, 5, 40]))
        assert PRINTABLE.fullmatch(text) and len(text) <= config.TEXT_BYTES
        assert sanitize.clean_text(text) == text
        assert not ARN_WITH_ACCOUNT.search(one) and not ARN_WITH_ACCOUNT.search(text)


def random_data(rng, depth=0):
    pick = rng.random()
    if depth > 5 or pick < 0.35:
        return rng.choice(
            [
                None,
                True,
                False,
                7,
                -3,
                2**70,
                1.5,
                float("nan"),
                float("inf"),
                random_string(rng),
                random_string(rng),
                object(),
                b"bytes",
            ]
        )
    if pick < 0.65:
        # Only the top level is wide enough to reach the table cap (50).
        sizes = [0, 2, 60, 120] if depth == 0 else [0, 1, 2]
        return [random_data(rng, depth + 1) for _ in range(rng.choice(sizes))]
    if pick < 0.75:
        return tuple(random_data(rng, depth + 1) for _ in range(2))
    return {
        rng.choice([random_string(rng), 5, None, ("t",)]): random_data(rng, depth + 1)
        for _ in range(rng.randint(0, 4))
    }


def walk(node):
    """Yield (kind, value) for every node of a cleaned value; fail on a stranger."""
    if isinstance(node, dict):
        for key, value in node.items():
            assert type(key) is str
            yield "str", key
            yield from walk(value)
    elif isinstance(node, list):
        assert len(node) <= config.TABLE_ROWS
        for value in node:
            yield from walk(value)
    elif isinstance(node, str):
        yield "str", node
    else:
        assert node is None or type(node) in (bool, int, float), type(node)
        if type(node) is float:
            assert node == node and node not in (float("inf"), float("-inf"))


def test_clean_data_output_is_json_safe_printable_capped_and_idempotent():
    rng = random.Random(SEED + 7)
    for _ in range(DATA_CASES):
        out = sanitize.clean_data(random_data(rng))
        for _, text in walk(out):
            assert PRINTABLE.fullmatch(text) and len(text) <= config.FIELD_CHARS
        json.dumps(out, allow_nan=False)
        assert sanitize.clean_data(out) == out


# --- the size bound (G3) ------------------------------------------------------------


def test_finish_bounds_the_response_for_huge_data():
    cases = [
        {f"key-{i}": "v" * 50 for i in range(10_000)},
        {"rows": [{"a": "x" * 200, "b": ["y" * 200] * 50} for _ in range(10)]},
        {"deep": [[["z" * 200] * 50] * 5] * 5},
        {"k" * 200: "\u202e" * 200},
        {f"{i}": {"x": "\U0001f600" * 200} for i in range(1000)},
    ]
    for data in cases:
        for text in ("t" * 100_000, "\u202e" * 50_000):
            resp = api._finish("status", data, text)
            assert resp.status == 200
            assert len(resp.to_json()) <= config.RESPONSE_BYTES
            assert PRINTABLE.fullmatch(resp.body["text"])


def test_finish_cuts_data_first_and_keeps_small_data():
    big = api._finish("status", {f"key-{i}": "v" * 50 for i in range(10_000)}, "hello")
    assert big.body["data"] == {"truncated": True}
    assert big.body["text"].endswith(sanitize.TRUNCATED)
    small = api._finish("status", {"a": 1, "b": ["x"]}, "hello")
    assert small.body["data"] == {"a": 1, "b": ["x"]}
    assert small.body["text"] == "hello"


def nested(depth, leaf="x", as_list=False):
    node = leaf
    for _ in range(depth):
        node = [node] if as_list else {"k": node}
    return node


class Unprintable:
    def __str__(self):
        raise RuntimeError("secret detail in a message")


def circular():
    loop = {}
    loop["self"] = loop
    return loop


@pytest.mark.parametrize(
    "data",
    [
        {"x": nested(5000)},
        {"x": nested(5000, as_list=True)},
        {"x": nested(1500)},
        circular(),
        {"x": Unprintable()},
    ],
    ids=["dict 5000", "list 5000", "dict 1500", "circular", "str raises"],
)
def test_unrenderable_data_becomes_the_fixed_503(sources, monkeypatch, data):
    monkeypatch.setitem(commands.HANDLERS, "runs", lambda ctx, args: (data, "text"))
    resp = api.dispatch(["runs"], sources)
    assert (resp.status, resp.body) == (503, api.UNAVAILABLE)
    assert resp.to_json() == UNAVAILABLE_WIRE
    out = api.lambda_handler(
        {"version": "2.0", "body": '{"argv": ["runs"]}', "isBase64Encoded": False},
        None,
        sources=sources,
    )
    assert out["statusCode"] == 503 and out["body"] == UNAVAILABLE_WIRE
    assert "secret detail" not in out["body"]


def test_a_bounded_amount_of_nesting_is_still_served(sources, monkeypatch):
    monkeypatch.setitem(commands.HANDLERS, "runs", lambda ctx, args: ({"x": nested(20)}, "t"))
    assert api.dispatch(["runs"], Sources(sources.runs_dir)).status == 200


def test_the_sources_fixture_is_the_fake_one(sources):
    assert isinstance(sources, Sources)
