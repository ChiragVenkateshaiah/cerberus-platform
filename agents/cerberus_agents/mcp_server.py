"""The local stdio MCP server (plan 14.2c, ADR 0025).

Newline-delimited JSON-RPC 2.0 over stdin and stdout, stdlib only. It serves the
registry (registry.py) and nothing else: no network, no write, named-input tools.
A client such as Claude Code starts it as a child process.

Rules, all fail closed:
- Every error text is fixed. No part of a request is ever echoed or logged.
- One input line is at most 64 KiB. A longer line gets one fixed error and the
  rest of that line is discarded.
- A notification (no `id`) never gets a reply.
- A refused or unavailable tool call is a normal result with `isError` true.
- Every response is one line of ASCII JSON. Logs go to stderr and hold no content.
"""

import argparse
import io
import json
import logging
import sys
from pathlib import Path

from cerberus_agents.registry import Registry
from cerberus_agents.tools import build_registry

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"  # unverified against a real client (plan, risks)
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "cerberus-review"
SERVER_VERSION = "0.1.0"
LINE_BYTES = 65536
DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[2] / "observability" / "scale" / "runs"

PARSE_ERROR = (-32700, "Parse error.")
INVALID_REQUEST = (-32600, "Invalid request.")
METHOD_NOT_FOUND = (-32601, "Method not found.")
INVALID_PARAMS = (-32602, "Invalid params.")
LINE_TOO_LONG = (-32600, "Request line too long.")
AWS_NOT_AVAILABLE = "not available yet (IAM step)"


def _error(rid, err) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": err[0], "message": err[1]}}


def _result(rid, result) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _tool_result(out: dict) -> dict:
    ok = out.get("ok") is True
    if ok:
        structured = out.get("data")
        if type(structured) is not dict:
            structured = {"value": structured}
    else:
        structured = {"ok": False, "error": str(out.get("error", "unavailable"))}
    return {
        "content": [{"type": "text", "text": str(out.get("text", ""))}],
        "structuredContent": structured,
        "isError": not ok,
    }


def handle(registry: Registry, message) -> dict | None:
    """One parsed message -> one response dict, or None for a notification."""
    if type(message) is not dict:
        return _error(None, INVALID_REQUEST)
    has_id = "id" in message
    rid = message.get("id")
    if has_id and type(rid) not in (str, int):
        return _error(None, INVALID_REQUEST)
    method = message.get("method")
    if type(method) is not str:
        return _error(rid if has_id else None, INVALID_REQUEST)
    params = message.get("params")
    if "params" in message and type(params) is not dict:
        return _error(rid, INVALID_PARAMS) if has_id else None

    if not has_id:  # a notification: act on none, reply to none
        return None

    if method == "initialize":
        asked = (params or {}).get("protocolVersion")
        version = asked if type(asked) is str and asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return _result(
            rid,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": registry.list_tools()})
    if method == "tools/call":
        params = params or {}
        name = params.get("name")
        if type(name) is not str:
            return _error(rid, INVALID_PARAMS)
        return _result(rid, _tool_result(registry.call(name, params.get("arguments"))))
    return _error(rid, METHOD_NOT_FOUND)


def _read_line(stdin):
    """(line, too_long). line is None at end of input. An over-long line is drained."""
    line = stdin.readline(LINE_BYTES + 1)
    if line == "":
        return None, False
    if len(line) > LINE_BYTES and not line.endswith("\n"):
        while True:
            rest = stdin.readline(LINE_BYTES)
            if rest == "" or rest.endswith("\n"):
                break
        return "", True
    return line, False


def serve(stdin, stdout, registry: Registry) -> None:
    """Answer requests until stdin closes."""

    def send(response: dict) -> None:
        stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
        stdout.flush()

    while True:
        line, too_long = _read_line(stdin)
        if line is None:
            return
        if too_long:
            send(_error(None, LINE_TOO_LONG))
            continue
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            send(_error(None, PARSE_ERROR))
            continue
        try:
            response = handle(registry, message)
        except Exception as exc:  # fail closed; log the type only
            log.warning("request failed: %s", type(exc).__name__)
            response = _error(None, INVALID_REQUEST)
        if response is not None:
            send(response)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_agents.mcp_server")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--aws", action="store_true")
    args = parser.parse_args(argv)
    if args.aws:
        print(AWS_NOT_AVAILABLE, file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    registry = build_registry(runs_dir=args.runs_dir)
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")
    serve(stdin, sys.stdout, registry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
