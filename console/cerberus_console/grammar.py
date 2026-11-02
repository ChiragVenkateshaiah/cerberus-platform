"""Input validation and the allowlist (ADR 0024 rules 1-3). Fail closed.

Every failure raises Refused. The caller answers with one fixed text that never
contains any part of the input.
"""

import base64
import binascii
import json
import re
from dataclasses import dataclass

from cerberus_console import config

REFUSED_TEXT = "Not an allowed command. Type help for the list."

# fullmatch, never match with `$`: `$` accepts a trailing newline. This one rule
# rejects shell metacharacters, spaces, "/", "..", control characters, NUL and
# all non-ASCII (lookalikes, bidi), and empty and over-long tokens.
_TOKEN = re.compile(rf"[A-Za-z0-9][A-Za-z0-9-]{{0,{config.MAX_TOKEN_CHARS - 1}}}", re.ASCII)

# name -> (fewest arguments, most arguments)
COMMANDS = {
    "help": (0, 1),
    "status": (0, 0),
    "runs": (0, 0),
    "run": (1, 1),
    "cost": (0, 1),
    "dq": (0, 1),
    "slo": (0, 0),
}


class Refused(Exception):
    pass


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Refused
    return dict(pairs)


def parse_body(body, is_base64: bool) -> list:
    """Rule 1: the request body -> the argv list (still unchecked)."""
    if not isinstance(body, str) or len(body) > config.MAX_BODY_BYTES:
        raise Refused
    try:
        raw = body.encode("utf-8")
        if len(raw) > config.MAX_BODY_BYTES:
            raise Refused
        if is_base64:
            raw = base64.b64decode(raw, validate=True)
            if len(raw) > config.MAX_BODY_BYTES:
                raise Refused
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, binascii.Error, RecursionError) as exc:
        raise Refused from exc
    if not isinstance(parsed, dict) or list(parsed) != ["argv"]:
        raise Refused
    return parsed["argv"]


def parse_argv(argv) -> Command:
    """Rules 2-4: the argv list -> a Command from the allowlist."""
    if not isinstance(argv, list) or not 1 <= len(argv) <= config.MAX_TOKENS:
        raise Refused
    for tok in argv:
        if type(tok) is not str or not _TOKEN.fullmatch(tok):
            raise Refused
    if argv[0] == "cerberus":
        argv = argv[1:]
    if not argv or argv[0] not in COMMANDS:
        raise Refused
    name, args = argv[0], tuple(argv[1:])
    low, high = COMMANDS[name]
    if not low <= len(args) <= high:
        raise Refused
    if name == "help" and args and args[0] not in COMMANDS:
        raise Refused
    return Command(name, args)
