# ruff: noqa: S311
# (A seeded generator on purpose: the run must be the same every time. Nothing here is secret.)
"""A seeded fuzz of the tool arguments (14.2b), like console/tests/test_fuzz.py.

Properties: `call` never raises; the answer is one of the fixed error dicts or an
ok answer that is printable ASCII and within the response cap; a refusal never
holds any part of the input.
"""

import json
import random
import re
import string
from pathlib import Path

from cerberus_agents import registry
from cerberus_agents.tools import build_registry

SEED = 142
CASES = 1500
RUNS = Path(__file__).resolve().parents[2] / "observability" / "scale" / "runs"
PRINTABLE = re.compile(r"[\x20-\x7e\n]*")
FIXED = (registry.REFUSED, registry.NOT_FOUND, registry.UNAVAILABLE, registry.BUDGET)
HOSTILE = list(" ;$|&<>`'\"\\(){}[]*?!~#%=,:@+/._") + [
    "\x00",
    "\x1b",
    "\x7f",
    "\n",
    "\r",
    "\x9b",
    "\u202e",
    "\u200b",
    "\ud800",
    "\u00e9",
    "\U0001f600",
]
TOKEN = string.ascii_letters + string.digits + "-"
TOOLS = [t["name"] for t in build_registry(RUNS).list_tools()]
GOOD_IDS = ["latest", "exercise-20261008T085728Z", "no-such-run", "x"]


def random_value(rng):
    pick = rng.random()
    if pick < 0.15:
        return rng.choice([None, 5, 1.5, True, [], {}, ["latest"], {"id": "latest"}, b"x"])
    if pick < 0.40:
        return rng.choice(GOOD_IDS + ["latest_status", "help", "cerberus"])
    n = rng.randint(0, 80)
    alphabet = TOKEN if pick < 0.65 else TOKEN + "".join(HOSTILE)
    return "".join(rng.choice(alphabet) for _ in range(n))


def random_call(rng):
    name = rng.choice(TOOLS + ["help", "nope", ""] + [random_value(rng)])
    shape = rng.random()
    if shape < 0.1:
        return name, random_value(rng)
    args = {}
    for key in rng.sample(["id", "name", "x"], rng.randint(0, 2)):
        args[key] = random_value(rng)
    return name, args


def test_seeded_fuzz_of_tool_arguments():
    rng = random.Random(SEED)
    reg = build_registry(RUNS, budget=10**9)
    ok = 0
    for _ in range(CASES):
        name, args = random_call(rng)
        out = reg.call(name, args)  # must never raise
        if out in FIXED:
            continue
        ok += 1
        assert out["ok"] is True
        assert PRINTABLE.fullmatch(out["text"])
        assert json.dumps(out, ensure_ascii=False).isascii()
        assert len(json.dumps(out, ensure_ascii=True)) <= registry.RESPONSE_BYTES
    assert ok > 50  # the run exercises the success path too


def test_a_refusal_never_echoes_the_input():
    rng = random.Random(SEED + 1)
    reg = build_registry(RUNS, budget=10**9)
    for _ in range(500):
        marker = "zq" + "".join(rng.choice(TOKEN) for _ in range(12)) + rng.choice(HOSTILE)
        for name, args in (("run", {"id": marker}), ("query", {"name": marker}), (marker, {})):
            out = reg.call(name, args)
            assert out in FIXED
            assert marker not in json.dumps(out)


def test_the_fuzz_is_repeatable():
    def run():
        rng = random.Random(SEED)
        reg = build_registry(RUNS, budget=10**9)
        return [json.dumps(reg.call(*random_call(rng)), sort_keys=True) for _ in range(200)]

    assert run() == run()
