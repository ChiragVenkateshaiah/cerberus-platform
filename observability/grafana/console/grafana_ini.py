"""Render grafana.ini.tmpl for the console session (step 10).

Stdlib only and Python 3.9 compatible. The values come as one JSON object on
standard input, so no secret appears in an argument list:

    python3 -I grafana_ini.py grafana.ini.tmpl < values.json > grafana.ini
"""

import json
import re
import string
import sys

# An allowlist (9.6 hardening). The real values are hex, a URL with percent
# escapes, a Cognito client id or secret, a host name and a path. Anything else
# (space, quote, semicolon, hash, backtick, dollar, backslash, newline, a
# non-ASCII character) is refused, so a value cannot start an ini comment or
# a new line. A "%(" pair cannot get through either: "(" is not in the set.
_GOOD_VALUE = re.compile(r"[A-Za-z0-9._~:/?&=%@+-]+", re.ASCII)


def placeholders(template_text):
    """The names the template wants, in order of first use."""
    seen = []
    for match in string.Template.pattern.finditer(template_text):
        name = match.group("named") or match.group("braced")
        if name and name not in seen:
            seen.append(name)
    return seen


def render(template_text, values):
    """Fill the template. A missing, extra or unsafe value raises ValueError."""
    wanted = set(placeholders(template_text))
    if set(values) != wanted:
        problems = sorted(wanted ^ set(values))
        raise ValueError(f"values do not match the template: {', '.join(problems)}")
    for key, value in values.items():
        if not isinstance(value, str) or not value or not _GOOD_VALUE.fullmatch(value):
            raise ValueError(f"value for {key} is empty or has a character that is not allowed")
    return string.Template(template_text).substitute(values)


def main(argv):
    if len(argv) != 2:
        print("usage: grafana_ini.py TEMPLATE < values.json > grafana.ini", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        template_text = handle.read()
    sys.stdout.write(render(template_text, json.load(sys.stdin)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
