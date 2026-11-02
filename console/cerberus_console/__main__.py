"""CLI: python -m cerberus_console [--json] <command...>

Always runs as cerberus-console-cli: the caller's own credentials only assume
that role (aws.assumed_session). Runs the same dispatch as the Lambda, so the
grammar and the sanitising are the same. Exit codes: 0 ok, 2 refused or not
found, 3 unavailable.
"""

import sys

from cerberus_console import api, aws, config
from cerberus_console.sources import Sources

EXIT = {"refused": 2, "not_found": 2, "unavailable": 3}


def main(argv: list[str]) -> int:
    as_json = bool(argv) and argv[0] == "--json"
    words = argv[1:] if as_json else argv
    session = aws.build_sources(session=aws.assumed_session)
    sources = Sources(config.RUNS_DIR, session.sfn_factory, session.freshness_factory)
    resp = api.dispatch(words, sources)
    print(resp.to_json() if as_json else resp.body["text"])
    return 0 if resp.body["ok"] else EXIT[resp.body["error"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
