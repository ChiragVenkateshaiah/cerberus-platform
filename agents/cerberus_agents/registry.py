"""The tool registry (plan 14.2b): tools as plain data, one door to call them.

A `Tool` is a name, a description, a JSON-Schema input (a dict) and a handler.
`list_tools()` returns the schemas in the order they were registered; 14.2c
exposes that same list over MCP, so it is a plain data structure and nothing
here knows about MCP. Everything fails closed and answers with the console's
fixed texts: no part of the input is ever echoed (ADR 0024 rules 3 and 4).
"""

import copy
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from cerberus_console import api, commands, grammar, sanitize
from cerberus_console.sources import Unavailable

log = logging.getLogger(__name__)

# One response is at most this many bytes of JSON (same cap as the console).
RESPONSE_BYTES = 65536
# Calls one registry instance answers before it refuses (a loop guard for 14.4).
CALL_BUDGET = 100

REFUSED = api.REFUSED
NOT_FOUND = api.NOT_FOUND
UNAVAILABLE = api.UNAVAILABLE
BUDGET = {"ok": False, "error": "budget", "text": "Tool call budget used up."}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict = field(default_factory=dict)  # JSON-Schema property dicts, by name
    required: tuple = ()
    # handler(arguments: dict) -> (data, text). It raises grammar.Refused,
    # commands.NotFound or Unavailable; anything else becomes UNAVAILABLE.
    handler: Callable = None

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": copy.deepcopy(self.properties),
                "required": list(self.required),
                "additionalProperties": False,
            },
        }


class Registry:
    def __init__(self, budget: int = CALL_BUDGET):
        self._tools: dict[str, Tool] = {}
        self.budget = budget
        self.calls = 0

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError("duplicate tool")
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    @staticmethod
    def _check(tool: Tool, arguments) -> dict:
        """Arguments must be an object of known keys with string values."""
        if arguments is None:
            arguments = {}
        if type(arguments) is not dict:
            raise grammar.Refused
        for key, value in arguments.items():
            if type(key) is not str or key not in tool.properties or type(value) is not str:
                raise grammar.Refused
        if any(r not in arguments for r in tool.required):
            raise grammar.Refused
        return arguments

    def call(self, name, arguments=None) -> dict:
        """Run one tool. Returns {ok, tool, text, data} or one fixed error dict."""
        self.calls += 1
        if self.calls > self.budget:
            return dict(BUDGET)
        tool = self._tools.get(name) if type(name) is str else None
        if tool is None:
            return dict(REFUSED)
        try:
            data, text = tool.handler(self._check(tool, arguments))
        except grammar.Refused:
            return dict(REFUSED)
        except commands.NotFound:
            return dict(NOT_FOUND)
        except Unavailable:
            return dict(UNAVAILABLE)
        except Exception as exc:  # fail closed: nothing about it reaches the caller
            log.warning("tool failed: %s", type(exc).__name__)
            return dict(UNAVAILABLE)
        try:
            return _finish(tool.name, data, text)
        except Exception as exc:
            log.warning("render failed: %s", type(exc).__name__)
            return dict(UNAVAILABLE)


def _finish(name: str, data, text: str) -> dict:
    body = {
        "ok": True,
        "tool": name,
        "text": sanitize.clean_text(text),
        "data": sanitize.clean_data(data),
    }
    if len(json.dumps(body, ensure_ascii=True)) > RESPONSE_BYTES:
        # Cut the structured part first, then the text.
        body["data"] = {"truncated": True}
        body["text"] = body["text"][: RESPONSE_BYTES // 2] + "\n" + sanitize.TRUNCATED
    return body
