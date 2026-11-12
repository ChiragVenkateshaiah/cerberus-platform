"""Builds the terminal page into DIR/terminal/. Deterministic: the same inputs give the same bytes.

Inputs: the three files in static/, the console limits in cerberus_console/config.py
and this package's own code. No clock, no locale, no network. The script and the
stylesheet carry a hash of their content in the name, so the publish step can mark
them immutable. index.html and config.json are never hashed.
"""

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from cerberus_console import config

PKG = Path(__file__).resolve().parent
STATIC = PKG / "static"
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_CTRL = re.compile(r"[\t\r\n]")
_BANNED_TAGS = ("iframe", "object", "embed", "base", "style")
_URL_ATTRS = ("href", "src")
_BANNED_ATTRS = ("srcset", "action", "formaction")


class BuildError(Exception):
    pass


@dataclass(frozen=True)
class BuildInfo:
    build_id: str
    files: tuple[str, ...]
    total_bytes: int


def max_input_length() -> int:
    """The longest command line the server accepts: MAX_TOKENS tokens and the spaces between."""
    return config.MAX_TOKENS * config.MAX_TOKEN_CHARS + config.MAX_TOKENS - 1


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BANNED_TAGS:
            self.problems.append(f"{tag} element")
        if tag == "meta" and any(n == "http-equiv" for n, _ in attrs):
            self.problems.append("meta http-equiv")
        if tag == "script" and "src" not in {n for n, _ in attrs}:
            self.problems.append("inline script")
        for name, value in attrs:
            # Browsers drop tabs and newlines inside a URL, so "java\tscript:" still runs.
            value = _CTRL.sub("", value or "").strip()
            if name.startswith("on"):
                self.problems.append(f"event handler {name}")
            if name == "style":
                self.problems.append("style attribute")
            if name in _BANNED_ATTRS:
                self.problems.append(f"{name} attribute")
            if value.lower().startswith("javascript:"):
                self.problems.append("javascript: URL")
            if name in _URL_ATTRS and (_SCHEME.match(value) or value.startswith("//")):
                self.problems.append(f"non-relative {name} on {tag}: {value}")


def csp_problems(markup: str) -> list[str]:
    """What would break the edge CSP. An empty list means the page is clean."""
    scan = _Scan()
    scan.feed(markup)
    scan.close()
    problems = scan.problems
    # A script element that has a src and also a body still runs inline code.
    for body in re.findall(r"<script\b[^>]*>(.*?)</script>", markup, re.IGNORECASE | re.DOTALL):
        if body.strip():
            problems.append("script body")
    return problems


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def build(out: Path) -> BuildInfo:
    tmpl = (STATIC / "index.html.tmpl").read_bytes()
    js = (STATIC / "terminal.js").read_bytes()
    css = (STATIC / "terminal.css").read_bytes()
    maxlen = max_input_length()

    # The build id covers every input byte and the builder's own code.
    inputs = [("tmpl", tmpl), ("js", js), ("css", css), ("maxlen", str(maxlen).encode())]
    for path in sorted(PKG.glob("*.py")):
        inputs.append((f"code/{path.name}", path.read_bytes()))
    h = hashlib.sha256()
    for label, data in inputs:
        h.update(f"{label}\0{len(data)}\0".encode())
        h.update(data)
    build_id = h.hexdigest()

    js_name = f"terminal.{_digest(js)}.js"
    css_name = f"terminal.{_digest(css)}.css"
    html = (
        tmpl.decode("utf-8")
        .replace("@@BUILD@@", build_id)
        .replace("@@CSS@@", css_name)
        .replace("@@JS@@", js_name)
        .replace("@@MAXLEN@@", str(maxlen))
    )
    if "@@" in html:
        raise BuildError("index.html.tmpl has a placeholder the builder does not fill")
    problems = csp_problems(html)
    if problems:
        raise BuildError(f"index.html: {', '.join(sorted(set(problems)))}")

    files = [("index.html", html.encode("utf-8")), (js_name, js), (css_name, css)]
    target_dir = Path(out) / "terminal"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        (target_dir / name).write_bytes(data)
    return BuildInfo(
        build_id,
        tuple(sorted(f"terminal/{n}" for n, _ in files)),
        sum(len(b) for _, b in files),
    )
