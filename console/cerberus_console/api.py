"""dispatch / handle_body / lambda_handler: the one door every request goes through.

Fail closed (ADR 0024 rule 3): a request that is not exactly an allowed command
gets one fixed refusal; any exception that escapes a command becomes the fixed
"unavailable" answer. The exception is logged by type name only. No message,
traceback or input text reaches the response.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from cerberus_console import commands, config, grammar, records, sanitize
from cerberus_console.sources import Sources, Unavailable

log = logging.getLogger(__name__)

REFUSED = {"ok": False, "error": "refused", "text": grammar.REFUSED_TEXT}
NOT_FOUND = {
    "ok": False,
    "error": "not_found",
    "text": "No run with that id. Type runs for the list.",
}
UNAVAILABLE = {
    "ok": False,
    "error": "unavailable",
    "text": "That command is not available right now. Try again later.",
}
_STATUS = {"refused": 400, "not_found": 404, "unavailable": 503}


@dataclass
class Response:
    status: int
    body: dict

    def to_json(self) -> str:
        return json.dumps(self.body, ensure_ascii=True, separators=(",", ":"))


def _error(body: dict) -> Response:
    return Response(_STATUS[body["error"]], dict(body))


def _finish(command: str, data: dict, text: str) -> Response:
    body = {
        "ok": True,
        "command": command,
        "text": sanitize.clean_text(text),
        "data": sanitize.clean_data(data),
    }
    if len(json.dumps(body, ensure_ascii=True)) > config.RESPONSE_BYTES:
        # Cut the structured part first, then the text.
        body["data"] = {"truncated": True}
        body["text"] = body["text"][: config.RESPONSE_BYTES // 2] + "\n" + sanitize.TRUNCATED
    return Response(200, body)


def dispatch(argv, sources: Sources, now: datetime | None = None) -> Response:
    try:
        cmd = grammar.parse_argv(argv)
    except grammar.Refused:
        return _error(REFUSED)
    try:
        ctx = commands.Context(sources, records.load(sources.runs_dir), now or datetime.now(UTC))
        data, text = commands.run(cmd, ctx)
    except commands.NotFound:
        return _error(NOT_FOUND)
    except Unavailable:
        return _error(UNAVAILABLE)
    except Exception as exc:  # fail closed: nothing about it reaches the visitor
        log.warning("command failed: %s", type(exc).__name__)
        return _error(UNAVAILABLE)
    try:
        return _finish(cmd.name, data, text)
    except Exception as exc:
        log.warning("render failed: %s", type(exc).__name__)
        return _error(UNAVAILABLE)


def handle_body(body, is_base64: bool, sources: Sources, now: datetime | None = None) -> Response:
    try:
        argv = grammar.parse_body(body, bool(is_base64))
    except grammar.Refused:
        return _error(REFUSED)
    return dispatch(argv, sources, now)


_SOURCES: Sources | None = None


def lambda_handler(event, context, *, sources: Sources | None = None) -> dict:
    """HTTP API (payload v2) -> response. Step 7 puts this behind the console site."""
    global _SOURCES  # one warm container keeps its readers and their caches
    if sources is None:
        if _SOURCES is None:
            from cerberus_console import aws  # boto3 is imported there, only when needed

            _SOURCES = aws.build_sources(state_machine_arn=_env_arn())
        sources = _SOURCES
    if not isinstance(event, dict):
        resp = _error(REFUSED)
    else:
        resp = handle_body(event.get("body"), event.get("isBase64Encoded", False), sources)
    return {
        "statusCode": resp.status,
        "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
        "body": resp.to_json(),
    }


def _env_arn() -> str | None:
    return os.environ.get("CERBERUS_STATE_MACHINE_ARN") or None
