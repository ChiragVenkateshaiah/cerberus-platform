"""The shared hostile corpus (9.6). One list of bad input, used by several tests.

test_grammar.py and test_sanitize.py take their cases from here;
test_hostile_corpus.py sends every case through the whole request path;
test_fuzz.py draws its alphabet from the same families.

Three shapes:
  BODIES       name -> a request body (a str, or a non-str) that must be refused
  B64_BODIES   name -> a body sent with isBase64Encoded = true, refused
  ARGV         name -> an argv value that must be refused by parse_argv
  DATA_STRINGS strings that must come out of the sanitiser as printable ASCII

Nothing here may become accepted input. A case that parses as a real command
belongs in the tests, not in this file.
"""

import base64
import json

# --- bodies -----------------------------------------------------------------

_VALID = '{"argv": ["status"]}'


def _padded(total_bytes: int) -> str:
    """A valid body made exactly total_bytes long with trailing spaces."""
    return _VALID + " " * (total_bytes - len(_VALID.encode("utf-8")))


BODIES = {
    "not json": "{nope",
    "not an object": '["status"]',
    "string": '"status"',
    "extra key": '{"argv": ["status"], "x": 1}',
    "no argv": "{}",
    "duplicate argv": '{"argv": ["status"], "argv": ["runs"]}',
    "over 2048 bytes": '{"argv": ["' + "a" * 2100 + '"]}',
    "missing body": None,
    "int body": 5,
    # --- 9.6 additions ---
    "empty string": "",
    "whitespace only": "   ",
    "bytes body": b'{"argv": ["status"]}',
    "list body": ["argv"],
    "dict body": {"argv": ["status"]},
    "true": "true",
    "null": "null",
    "argv null": '{"argv": null}',
    "argv string": '{"argv": "status"}',
    "argv object": '{"argv": {"0": "status"}}',
    "argv number": '{"argv": 5}',
    "argv empty": '{"argv": []}',
    "argv NaN": '{"argv": NaN}',
    "argv Infinity": '{"argv": Infinity}',
    "argv in list is NaN": '{"argv": [NaN]}',
    "argv 1e999": '{"argv": 1e999}',
    "argv token 1e999": '{"argv": [1e999]}',
    "argv big int": '{"argv": [' + "9" * 300 + "]}",
    "argv lone surrogate (JSON escape)": '{"argv": ["\\ud800"]}',
    "argv lone low surrogate (JSON escape)": '{"argv": ["\\udc00status"]}',
    "argv surrogate pair": '{"argv": ["\\ud83d\\ude00"]}',
    "raw lone surrogate": '{"argv": ["\ud800"]}',
    "raw lone surrogate in key": '{"\ud800": ["status"]}',
    "BOM before the object": "\ufeff" + _VALID,
    "BOM after the object": _VALID + "\ufeff",
    "escaped NUL token": '{"argv": ["status\\u0000"]}',
    "escaped newline token": '{"argv": ["status\\n"]}',
    "escaped CRLF token": '{"argv": ["status\\r\\n"]}',
    "escaped ESC token": '{"argv": ["\\u001b[31mstatus"]}',
    "trailing garbage": _VALID + " x",
    "two objects": _VALID + _VALID,
    "single quotes": "{'argv': ['status']}",
    "trailing comma": '{"argv": ["status",]}',
    "comment": '{"argv": ["status"]} // x',
    "unterminated string": '{"argv": ["status',
    "key with unicode escape twice": '{"argv": ["status"], "\\u0061rgv": ["runs"]}',
    "2049 bytes": _padded(2049),
    # Under 2048 characters, over 2048 bytes: the byte check, not the length check.
    "multibyte over 2048 bytes": '{"argv": ["' + "\xe9" * 1100 + '"]}',
    "emoji over 2048 bytes": '{"argv": ["' + "\U0001f600" * 600 + '"]}',
    "SQL": '{"argv": ["\' OR 1=1--"]}',
    "html": '{"argv": ["<script>alert(1)</script>"]}',
    "shell": '{"argv": ["status; id"]}',
    "nested 100 deep": '{"argv":' + "[" * 100 + "]" * 100 + "}",
    "nested 1500 deep": '{"argv":' + "[" * 1500 + "]" * 1500 + "}",
    "nested objects 1500 deep": '{"argv":' + '{"a":' * 1500 + "1" + "}" * 1500 + "}",
}

B64_BODIES = {
    "not base64": "!!!not base64!!!",
    "valid base64 of invalid UTF-8": base64.b64encode(b"\xff\xfe").decode(),
    "valid base64 of a BOM body": base64.b64encode(b"\xef\xbb\xbf" + _VALID.encode()).decode(),
    "base64 with a space": "e30 =",
    "base64 with a newline": base64.b64encode(_VALID.encode()).decode() + "\n",
    "url-safe alphabet": base64.urlsafe_b64encode(b"\xfb\xff\xfe").decode(),
    "missing padding": base64.b64encode(b'{"argv":[]}').decode().rstrip("="),
    "base64 of a raw lone surrogate": base64.b64encode(b'{"argv": ["\xed\xa0\x80"]}').decode(),
    "base64 of not json": base64.b64encode(b"{nope").decode(),
    "base64 of a list": base64.b64encode(b'["status"]').decode(),
    "base64 of an extra key": base64.b64encode(b'{"argv": ["status"], "x": 1}').decode(),
    "base64 of a shell token": base64.b64encode(b'{"argv": ["$(id)"]}').decode(),
    "base64 over 2048 characters": base64.b64encode(b"a" * 2000).decode(),
    "plain JSON sent as base64": _VALID,
    "empty": "",
    "int": 5,
    "None": None,
}

# --- argv -------------------------------------------------------------------

ARGV = {
    "not a list": "status",
    "empty list": [],
    "nine tokens": ["help"] * 9,
    "65 chars": ["a" * 65],
    "int": [5],
    "bool": [True],
    "none": [None],
    "dict": [{"a": 1}],
    "nested list": [["status"]],
    "semicolon": ["status;"],
    "command substitution": ["$(id)"],
    "backtick": ["`id`"],
    "pipe": ["status|id"],
    "and": ["status&&id"],
    "redirect": ["status>x"],
    "space": ["status runs"],
    "newline": ["status\n"],
    "carriage return": ["status\r"],
    "nul": ["status\x00"],
    "dotdot": ["../"],
    "path": ["/etc/passwd"],
    "upper": ["STATUS"],
    "mixed case": ["Status"],
    "fullwidth": ["\uff53\uff54\uff41\uff54\uff55\uff53"],
    "rtl override": ["\u202estatus"],
    "zero width": ["sta\u200btus"],
    "dash h": ["-h"],
    "json flag": ["--json", "status"],
    "double cerberus": ["cerberus", "cerberus", "status"],
    "only cerberus": ["cerberus"],
    "extra arg": ["status", "extra"],
    "run without id": ["run"],
    "run two ids": ["run", "a", "b"],
    "run 65 chars": ["run", "a" * 65],
    "unknown command": ["ls"],
    "help unknown": ["help", "ls"],
    "cost two ids": ["cost", "a", "b"],
    # --- 9.6 additions ---
    "tuple": ("status",),
    "empty token": [""],
    "empty argument": ["run", ""],
    "ten tokens": ["help"] * 10,
    "float": [1.5],
    "NaN": [float("nan")],
    "bytes": [b"status"],
    "set": [{"status"}],
    "lone surrogate": ["\ud800"],
    "lone surrogate in a command": ["sta\ud800tus"],
    "BOM": ["\ufeffstatus"],
    "combining acute": ["status\u0301"],
    "combining only": ["\u0301"],
    "decomposed e": ["e\u0301"],
    "Kelvin sign": ["\u212a"],
    "Kelvin sign in a word": ["\u212aostatus"],
    "long s": ["\u017ftatus"],
    "Cyrillic s": ["\u0455tatus"],
    "Cyrillic a": ["runs", "\u0430"],
    "Greek omicron": ["\u03bfk"],
    "Arabic-Indic digits": ["run", "\u0661\u0662\u0663"],
    "Devanagari digits": ["run", "\u0967\u0968"],
    "superscript two": ["run", "a\xb2"],
    "NEL": ["status\x85"],
    "NEL alone": ["\x85"],
    "vertical tab": ["status\x0b"],
    "form feed": ["status\x0c"],
    "tab": ["status\t"],
    "tab in the middle": ["sta\ttus"],
    "line separator": ["status\u2028"],
    "paragraph separator": ["status\u2029"],
    "no-break space": ["status\xa0"],
    "ideographic space": ["status\u3000"],
    "CRLF": ["status\r\n"],
    "CRLF injection": ["status\r\nX-Evil: 1"],
    "LF then command": ["status\nrun"],
    "leading newline": ["\nstatus"],
    "leading space": [" status"],
    "trailing space": ["status "],
    "percent-encoded semicolon": ["status%3B"],
    "percent-encoded space": ["status%20id"],
    "percent-encoded NUL": ["status%00"],
    "percent-encoded dotdot": ["%2e%2e%2f"],
    "SQL": ["' OR 1=1--"],
    "SQL union": ["run", "x' UNION SELECT 1--"],
    "SQL comment": ["status--"],
    "html script": ["<script>alert(1)</script>"],
    "html img": ["<img src=x onerror=alert(1)>"],
    "html entity": ["&lt;script&gt;"],
    "template injection": ["{{7*7}}"],
    "format string": ["%s%s%s%n"],
    "env expansion": ["${HOME}"],
    "glob": ["*"],
    "question mark": ["?"],
    "tilde": ["~"],
    "bang": ["!!"],
    "single quote": ["'status'"],
    "double quote": ['"status"'],
    "backslash": ["status\\"],
    "ESC sequence": ["\x1b[31mstatus"],
    "OSC 52": ["\x1b]52;c;SGVsbG8=\x07"],
    "C1 CSI": ["\x9b31m"],
    "DEL": ["status\x7f"],
    "bell": ["status\x07"],
    "backspace": ["status\x08"],
    "underscore": ["run_all"],
    "leading dash": ["-status"],
    "double dash": ["--help"],
    "dot": ["."],
    "dotdot token": [".."],
    "slash": ["/"],
    "colon": ["status:"],
    "at sign": ["@status"],
    "plus": ["status+"],
    "equals": ["a=b"],
    "comma": ["a,b"],
    "cerberus then unknown": ["cerberus", "ls"],
    "cerberus then empty": ["cerberus", ""],
    "cerberus then cerberus": ["cerberus", "cerberus"],
    "help three args": ["help", "status", "runs", "slo"],
    "run with a shell token": ["run", "$(id)"],
    "run with a path": ["run", "../../etc/passwd"],
    "run with fullwidth": ["run", "\uff41\uff42"],
    "cost with a long id": ["cost", "x" * 65],
    "dq with a newline": ["dq", "a\n"],
    "help with an unknown topic": ["help", "rm"],
    "upper case command with arg": ["RUN", "latest"],
    "65 chars after cerberus": ["cerberus", "a" * 65],
    "mixed list": ["status", 5],
    "nested empty list": [[]],
    "object with argv key": [{"argv": ["status"]}],
}

# "status--" has a valid token shape (letters, digits, "-") but is not a command:
# it is here because the allowlist is on the name as well as on the shape.

# ARGV cases that json.dumps cannot carry as the same value (a tuple becomes a
# list, bytes and a set cannot be encoded). Only dispatch() gets these.
NOT_JSON_SAFE = {"tuple", "bytes", "set"}

# --- strings for the sanitiser ---------------------------------------------

DATA_STRINGS = [
    "\x1b[31mred",
    "\x1b]52;c;SGVsbG8=\x07",
    "\x1b]8;;http://x\x1b\\link",
    "\x9b31m",
    "a\x7fb",
    "\u202eevil",
    "a\u2028b\u2029c",
    "nul\x00byte",
    "zero\u200bwidth",
    "x" * 10000,
    # --- 9.6 additions ---
    "lone\ud800surrogate",
    "\udc00",
    "\ufeffbom",
    "e\u0301 combining",
    "\u212a kelvin",
    "\u017f long s",
    "\u0455 cyrillic",
    "\u0661\u0662 arabic digits",
    "nel\x85here",
    "vt\x0bff\x0c",
    "crlf\r\ninjection",
    "bell\x07 backspace\x08",
    "%3B percent",
    "' OR 1=1--",
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[x](javascript:alert(1))",
    "\U0001f600 emoji",
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069",
    "\u200b\u200c\u200d\u2060\ufeff",
    "\x00" * 50,
    "\x1b" * 50,
    "tab\tin\ttext",
    "line1\nline2\n\nline3",
    "arn:aws:states:us-east-1:123456789012:execution:x",
    "\xe9" * 500,
    "a" * 199 + "\u202e",
    "",
]


def body(argv) -> str:
    """argv -> the JSON body a browser would send. Lone surrogates are escaped."""
    return json.dumps({"argv": argv})
