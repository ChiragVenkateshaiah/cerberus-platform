"""Builds the site into a directory. Deterministic: the same inputs give the same bytes.

Inputs: content.toml, Phases.md, the run records, the optional scale charts and
the files in this package. No clock, no locale, no network. Asset names carry a
hash of their content, so the publish step can mark them immutable.
"""

import hashlib
import re
import tomllib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from cerberus_landing import page, phases, runs

PKG = Path(__file__).resolve().parent
EXPECTED_CHARTS = ("cost-per-million-events", "run-time-per-state", "transform-throughput")
MAX_CHART_BYTES = 64 * 1024
CONSOLE = PKG.parent / "cerberus_console"
CONSOLE_FILES = ("records.py", "sanitize.py", "grammar.py", "config.py")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_CTRL = re.compile(r"[\t\r\n]")
_BANNED_TAGS = ("iframe", "object", "embed", "base", "form")
_URL_ATTRS = ("href", "xlink:href", "src")
_BANNED_ATTRS = ("srcset", "action", "formaction")


class BuildError(Exception):
    pass


@dataclass(frozen=True)
class BuildInfo:
    build_id: str
    files: tuple[str, ...]
    total_bytes: int


class _Scan(HTMLParser):
    def __init__(self, kind: str):
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.problems: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.problems.append("script element")
        if tag == "style" and self.kind != "chart":
            self.problems.append("style element")
        if tag == "style":
            self._in_style = True
        if tag in _BANNED_TAGS:
            self.problems.append(f"{tag} element")
        if tag == "meta" and any(n == "http-equiv" for n, _ in attrs):
            self.problems.append("meta http-equiv")
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
            if name in _URL_ATTRS:
                self._link(tag, name, value)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style and self.kind == "chart":
            lowered = data.lower()
            if "@import" in lowered:
                self.problems.append("@import in a chart style")
            if "url(" in lowered:
                self.problems.append("url( in a chart style")

    def _link(self, tag, name, value):
        if self.kind == "chart":
            self.problems.append(f"{name} in a chart")
        elif value.startswith("#"):
            return
        elif tag == "a" and name == "href" and page.is_allowed_external(value):
            return
        elif _SCHEME.match(value) or value.startswith("//"):
            self.problems.append(f"non-relative {name} on {tag}: {value}")


def csp_problems(markup: str, kind: str = "page") -> list[str]:
    """What would break the edge CSP or the link rules. kind is "page" or "chart"."""
    scan = _Scan(kind)
    scan.feed(markup)
    scan.close()
    return scan.problems


class _Chart(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root: dict = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "svg" and not self.root:
            self.root = {k: v or "" for k, v in attrs}
        self._in_title = tag == "title" and not self.title

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _chart_size(root: dict) -> tuple[int, int]:
    try:
        return int(float(root["width"])), int(float(root["height"]))
    except (KeyError, ValueError):
        pass
    try:
        _, _, w, h = root["viewbox"].split()
        return int(float(w)), int(float(h))
    except (KeyError, ValueError):
        raise BuildError("chart has no usable width/height or viewBox") from None


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def _read_charts(charts_dir: Path, c: dict):
    """(Chart list, [(path in output, bytes)], [input label, bytes]). Empty if absent."""
    charts, outputs, inputs = [], [], []
    captions = c["scale"]["captions"]
    for stem in EXPECTED_CHARTS:
        path = charts_dir / f"{stem}.svg"
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > MAX_CHART_BYTES:
            raise BuildError(f"{path.name} is larger than {MAX_CHART_BYTES} bytes")
        markup = data.decode("utf-8")
        problems = csp_problems(markup, "chart")
        if problems:
            raise BuildError(f"{path.name}: {', '.join(problems)}")
        parsed = _Chart()
        parsed.feed(markup)
        title = " ".join(parsed.title.split())
        if not title:
            raise BuildError(f"{path.name} has no <title>")
        width, height = _chart_size(parsed.root)
        name = f"img/{stem}.{_digest(data)}.svg"
        charts.append(page.Chart(name, title, width, height, captions.get(stem, "")))
        outputs.append((name, data))
        inputs.append((f"chart/{stem}", data))
    return charts, outputs, inputs


def build(out: Path, runs_dir: Path, phases_file: Path, charts_dir: Path) -> BuildInfo:
    content_bytes = (PKG / "content.toml").read_bytes()
    c = tomllib.loads(content_bytes.decode("utf-8"))
    phases_bytes = phases_file.read_bytes()
    try:
        plist = phases.parse(phases_bytes.decode("utf-8"))
    except phases.PhasesError as exc:
        raise BuildError(f"Phases.md: {exc}") from exc
    if sorted(c["phases"]) != sorted(f"p{p.number}" for p in plist):
        raise BuildError("content.toml [phases] does not match the phases in Phases.md")

    latest, largest, n_records, n_ok = runs.pick(runs_dir)
    charts, chart_outputs, chart_inputs = _read_charts(charts_dir, c)

    css = (PKG / "static" / "site.css").read_bytes()
    favicon = (PKG / "static" / "favicon.svg").read_bytes()
    arch = (PKG / "architecture.svg").read_text(encoding="utf-8")
    problems = csp_problems(arch)
    if problems:
        raise BuildError(f"architecture.svg: {', '.join(problems)}")

    # The build id covers every input byte and the builder's own code.
    inputs = [("content", content_bytes), ("phases", phases_bytes), ("css", css)]
    inputs += [("favicon", favicon), ("architecture", arch.encode("utf-8"))]
    inputs += chart_inputs
    for path in sorted(Path(runs_dir).glob("*.json")):
        inputs.append((f"run/{path.name}", path.read_bytes()))
    for path in sorted(PKG.glob("*.py")):
        inputs.append((f"code/{path.name}", path.read_bytes()))
    for name in CONSOLE_FILES:  # the page reads records through these modules
        inputs.append((f"code/cerberus_console/{name}", (CONSOLE / name).read_bytes()))
    h = hashlib.sha256()
    for label, data in inputs:
        h.update(f"{label}\0{len(data)}\0".encode())
        h.update(data)
    build_id = h.hexdigest()

    css_name = f"site.{_digest(css)}.css"
    icon_name = f"favicon.{_digest(favicon)}.svg"
    index = page.render(
        c, plist, latest, largest, n_records, n_ok, charts, arch, css_name, icon_name, build_id
    )
    problems = csp_problems(index)
    if problems:
        raise BuildError(f"index.html: {', '.join(sorted(set(problems)))}")

    files = [
        ("index.html", index.encode("utf-8")),
        (css_name, css),
        (icon_name, favicon),
        *chart_outputs,
    ]
    out = Path(out)
    for name, data in files:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return BuildInfo(build_id, tuple(sorted(n for n, _ in files)), sum(len(b) for _, b in files))
