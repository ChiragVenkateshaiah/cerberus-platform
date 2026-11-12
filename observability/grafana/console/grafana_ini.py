"""Render grafana.ini.tmpl for the console session (step 10).

Stdlib only and Python 3.9 compatible. The values come as one JSON object on
standard input, so no secret appears in an argument list:

    python3 -I grafana_ini.py grafana.ini.tmpl < values.json > grafana.ini
"""

import json
import re
import string
import sys

# A value must stay on one line and must not start an ini comment or quote.
_BAD_VALUE = re.compile(r'[\r\n;#"`$]|%\(')


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
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or _BAD_VALUE.search(value)
        ):
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
