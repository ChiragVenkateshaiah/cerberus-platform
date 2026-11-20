"""The named query set for pipeline status (observability/queries/status.json).

One file holds the `metrics` catalogue and the named PromQL `queries`. Panels
must equal an entry, and alert rules must contain entries verbatim (ADR 0021,
amendments of 2026-11-12 and 2026-11-20). Stdlib only, plain json.loads. Nothing
in the console imports this module yet; 10.3 to 10.5 will.

Every function returns a list of error strings, empty when the input is fine.
"""

import json
import re
from pathlib import Path

from cerberus_console import config

NAME_MIN = 3
NAME_MAX = 64
MEANING_MAX = 120
SCOPES = ("latest", "detail", "execution")
# Function -> the only window it may use around a catalogue selector. The 90d
# exception is for the 10.4 error budget (ADR 0021 amendment, 2026-11-20).
ALLOWED_WINDOWS = {
    "last_over_time": "30d",
    "avg_over_time": "90d",
    "count_over_time": "90d",
}
QUOTES = ('"', "'", "`")
_NAME_START = "abcdefghijklmnopqrstuvwxyz"
_NAME_REST = _NAME_START + "0123456789_"
_IDENT_START = _NAME_START + _NAME_START.upper() + "_:"
_IDENT_REST = _IDENT_START + "0123456789"
_NUM_REST = _IDENT_REST + "."
# A `__name__` value made only of these characters means the same to Python `re`
# and to Prometheus (Go string unescaping, then RE2): no backslash, no class.
_SAFE_NAME_REGEX = _IDENT_REST + "|().*+?"


def load(path: Path = config.QUERIES_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def metric_names(doc: dict) -> list[str]:
    return [m["name"] for m in doc.get("metrics", []) if isinstance(m, dict) and "name" in m]


def queries(doc: dict) -> list[dict]:
    return [q for q in doc.get("queries", []) if isinstance(q, dict)]


def _string_end(text: str, i: int) -> int:
    """Index just past the quoted string that starts at text[i]."""
    quote = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\" and quote != "`":
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return len(text)  # unterminated: the string runs to the end


def normalise(expr: str) -> str:
    """Strip whitespace outside quoted strings; keep it inside."""
    out = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in QUOTES:
            end = _string_end(expr, i)
            out.append(expr[i:end])
            i = end
        else:
            if not ch.isspace():
                out.append(ch)
            i += 1
    return "".join(out)


def tokenize(expr: str) -> list[tuple[str, str]]:
    """Split PromQL into (kind, text). Kinds: str, ident, num, punct.

    Whitespace is dropped. A quoted string is one token, so a brace or a metric
    name inside a label value never counts. `$var` and other odd characters
    become single punct tokens, so Grafana templates do not break it.
    """
    toks: list[tuple[str, str]] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
        elif ch in QUOTES:
            end = _string_end(expr, i)
            toks.append(("str", expr[i:end]))
            i = end
        elif ch in _IDENT_START:
            j = i + 1
            while j < n and expr[j] in _IDENT_REST:
                j += 1
            toks.append(("ident", expr[i:j]))
            i = j
        elif ch.isdigit():
            j = i + 1
            while j < n and expr[j] in _NUM_REST:
                j += 1
            toks.append(("num", expr[i:j]))
            i = j
        else:
            toks.append(("punct", ch))
            i += 1
    return toks


def _selectors(toks: list[tuple[str, str]], names: set[str]) -> list[tuple[int, str]]:
    """(token index, name) of each selector-position identifier in `names`.

    Identifiers inside `{...}` are label names, and an identifier followed by
    `(` is a function, so neither counts.
    """
    found = []
    depth = 0
    for i, (kind, text) in enumerate(toks):
        if kind == "punct" and text == "{":
            depth += 1
        elif kind == "punct" and text == "}":
            depth = max(0, depth - 1)
        elif kind == "ident" and depth == 0 and text in names:
            if i + 1 < len(toks) and toks[i + 1] == ("punct", "("):
                continue
            found.append((i, text))
    return found


def mentioned(expr: str, names: list[str]) -> list[str]:
    """The catalogue metrics that `expr` names as a selector."""
    return [name for _, name in _selectors(tokenize(expr), set(names))]


def _is(tok: tuple[str, str], kind: str, text: str) -> bool:
    return tok == (kind, text)


NAME_MATCHER_MSG = "`__name__` matcher is not allowed; use an entry"
COMMENT_MSG = "PromQL comments are not allowed in a status query"
EXEMPT_KEYS = ("title", "description", "content")
_BINARY_WORDS = ("and", "or", "unless")
_BINARY_CHARS = "+-*/%^=<>!"


def forbidden(expr: str) -> list[str]:
    """`__name__` matchers and `#` comments, outside quoted strings."""
    toks = tokenize(expr)
    errors = []
    if ("ident", "__name__") in toks:
        errors.append(NAME_MATCHER_MSG)
    if ("punct", "#") in toks:
        errors.append(COMMENT_MSG)
    return errors


def name_matcher_may_hit(expr: str, names: list[str]) -> bool:
    """True if a `__name__` matcher in `expr` could select a catalogue metric.

    Dashboards only. Some existing dashboards select other series with
    `{__name__=~"spark_..."}`, so a dashboard may use `__name__` when each
    matcher provably misses the catalogue. `=` must name a non-catalogue metric,
    `=~` must not fully match any catalogue name (Prometheus anchors regexes),
    and `!=`, `!~` or anything unparseable counts as a hit. A value outside
    `[A-Za-z0-9_:|().*+?]` also counts as a hit, because Prometheus unescapes
    the string and uses RE2, which Python cannot model. A bare `__name__`
    with no operator (a legend template) is not a matcher.
    """
    toks = tokenize(expr)
    for i, tok in enumerate(toks):
        if tok != ("ident", "__name__"):
            continue
        j = i + 1
        op = ""
        while j < len(toks) and toks[j][0] == "punct" and toks[j][1] in "=!~":
            op += toks[j][1]
            j += 1
        if not op:
            continue  # not a matcher, e.g. the Grafana legend `{{__name__}}`
        if j >= len(toks) or toks[j][0] != "str" or len(toks[j][1]) < 2:
            return True
        value = toks[j][1][1:-1]
        if not value or any(c not in _SAFE_NAME_REGEX for c in value):
            return True
        if op == "=":
            if value in names:
                return True
        elif op == "=~":
            try:
                pattern = re.compile(value)
            except re.error:
                return True
            if any(pattern.fullmatch(n) for n in names):
                return True
        else:
            return True
    return False


def has_top_level_operator(toks: list[tuple[str, str]]) -> bool:
    depth = 0
    for kind, text in toks:
        if kind == "punct" and text in "([{":
            depth += 1
        elif kind == "punct" and text in ")]}":
            depth -= 1
        elif depth == 0 and (
            (kind == "punct" and text in _BINARY_CHARS)
            or (kind == "ident" and text in _BINARY_WORDS)
        ):
            return True
    return False


def is_wrapped(toks: list[tuple[str, str]]) -> bool:
    """True when one pair of parentheses encloses the whole expression."""
    if not toks or toks[0] != ("punct", "(") or toks[-1] != ("punct", ")"):
        return False
    depth = 0
    for i, (kind, text) in enumerate(toks):
        if kind == "punct" and text == "(":
            depth += 1
        elif kind == "punct" and text == ")":
            depth -= 1
            if depth == 0 and i != len(toks) - 1:
                return False
    return True


def check_windows(expr: str, names: list[str]) -> list[str]:
    """Every catalogue selector must be the direct argument of a window function.

    `last_over_time(<sel>[30d])`, or `avg_over_time` / `count_over_time` with
    `[90d]`. A selector may carry `{...}` matchers. A bare selector, a wrong
    window, a wrong function or a subquery (`[30d:1m]`) all fail.
    """
    errors = []
    toks = tokenize(expr)
    for i, name in _selectors(toks, set(names)):
        j = i + 1
        if j < len(toks) and _is(toks[j], "punct", "{"):
            while j < len(toks) and not _is(toks[j], "punct", "}"):
                j += 1
            j += 1
        shape_ok = (
            j + 2 < len(toks)
            and _is(toks[j], "punct", "[")
            and toks[j + 1][0] == "num"
            and _is(toks[j + 2], "punct", "]")
            and j + 3 < len(toks)
            and _is(toks[j + 3], "punct", ")")
        )
        func_ok = (
            i >= 2
            and _is(toks[i - 1], "punct", "(")
            and toks[i - 2][0] == "ident"
            and toks[i - 2][1] in ALLOWED_WINDOWS
        )
        if not (shape_ok and func_ok):
            errors.append(
                f"window: {name} must sit directly inside last_over_time(<selector>[30d]) "
                f"(or avg_over_time/count_over_time with [90d]) in: {expr}"
            )
            continue
        func, window = toks[i - 2][1], toks[j + 1][1]
        if window != ALLOWED_WINDOWS[func]:
            errors.append(
                f"window: {name} inside {func} must use [{ALLOWED_WINDOWS[func]}], "
                f"not [{window}] in: {expr}"
            )
    return errors


def lint(doc: dict) -> list[str]:
    """Check the query-set file itself."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["file: top level must be an object"]
    if doc.get("version") != 1:
        errors.append("file: version must be 1")

    metrics = doc.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        errors.append("metrics: must be a non-empty list")
        metrics = []
    seen_metrics: set[str] = set()
    for m in metrics:
        name = m.get("name") if isinstance(m, dict) else None
        if not isinstance(name, str) or not name.startswith("cerberus_"):
            errors.append(f"metrics: bad entry {m!r}: name must be a string starting cerberus_")
            continue
        if name in seen_metrics:
            errors.append(f"metrics: duplicate name {name}")
        seen_metrics.add(name)
        labels = m.get("labels")
        if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
            errors.append(f"metrics: {name}: labels must be a list of strings")
        if m.get("scope") not in SCOPES:
            errors.append(f"metrics: {name}: scope must be one of {', '.join(SCOPES)}")
        errors.extend(_check_meaning("metrics", name, m.get("meaning")))

    entries = doc.get("queries")
    if not isinstance(entries, list) or not entries:
        errors.append("queries: must be a non-empty list")
        entries = []
    seen: set[str] = set()
    names = sorted(seen_metrics)
    for q in entries:
        name = q.get("name") if isinstance(q, dict) else None
        if not isinstance(name, str) or not _valid_name(name):
            errors.append(
                f"queries: bad name {name!r}: use ^[a-z][a-z0-9_]{{{NAME_MIN - 1},{NAME_MAX - 1}}}$"
            )
            continue
        if name in seen:
            errors.append(f"queries: duplicate name {name}")
        seen.add(name)
        errors.extend(_check_meaning("queries", name, q.get("meaning")))
        expr = q.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            errors.append(f"queries: {name}: expr must be a non-empty string")
            continue
        if "$" in expr or "{{" in expr:
            errors.append(f"queries: {name}: templating ($ or {{{{) is not allowed in expr")
        errors.extend(f"queries: {name}: {e}" for e in forbidden(expr))
        toks = tokenize(expr)
        if has_top_level_operator(toks) and not is_wrapped(toks):
            errors.append(
                f"queries: {name}: an expr with a top-level operator must be wrapped "
                "in parentheses, so `2 * <entry>` keeps its meaning"
            )
        for _, ident in _all_cerberus(expr):
            if ident not in seen_metrics:
                errors.append(f"queries: {name}: {ident} is not in the metrics catalogue")
        errors.extend(f"queries: {name}: {e}" for e in check_windows(expr, names))
    return errors


def _valid_name(name: str) -> bool:
    return (
        NAME_MIN <= len(name) <= NAME_MAX
        and name[0] in _NAME_START
        and all(c in _NAME_REST for c in name)
    )


def _check_meaning(section: str, name: str, meaning: object) -> list[str]:
    if not isinstance(meaning, str) or not meaning.strip():
        return [f"{section}: {name}: meaning must be a non-empty string"]
    if "\n" in meaning or "\r" in meaning:
        return [f"{section}: {name}: meaning must be one line"]
    if len(meaning) > MEANING_MAX:
        return [f"{section}: {name}: meaning is over {MEANING_MAX} characters"]
    if "$" in meaning or "{{" in meaning:
        return [f"{section}: {name}: templating ($ or {{{{) is not allowed in meaning"]
    return []


def _all_cerberus(expr: str) -> list[tuple[int, str]]:
    toks = tokenize(expr)
    depth = 0
    out = []
    for i, (kind, text) in enumerate(toks):
        if kind == "punct" and text == "{":
            depth += 1
        elif kind == "punct" and text == "}":
            depth = max(0, depth - 1)
        elif kind == "ident" and depth == 0 and text.startswith("cerberus_"):
            out.append((i, text))
    return out


def _walk_strings(node: object, title: str, key: str = ""):
    """Yield (panel title, key, string) for every string value in a dashboard.

    A generic walk, so panels nested in rows (collapsed or not), targets,
    templating variables and any other field are all seen. No tag is needed.
    A list item keeps the key of its list.
    """
    if isinstance(node, dict):
        here = node["title"] if isinstance(node.get("title"), str) else title
        for k, value in node.items():
            yield from _walk_strings(value, here, k)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item, title, key)
    elif isinstance(node, str):
        yield title, key, node


def check_dashboard(dashboard: dict, doc: dict) -> list[str]:
    """Only a target `expr` equal to an entry (normalised) may read a status metric."""
    names = metric_names(doc)
    nameset = set(names)
    known = {normalise(q["expr"]) for q in queries(doc) if isinstance(q.get("expr"), str)}
    errors = []
    for title, key, text in _walk_strings(dashboard, "(no title)"):
        if key in EXEMPT_KEYS:
            continue
        if key == "expr":
            errors.extend(
                f"dashboard: panel {title!r}: {e}: {text}"
                for e in forbidden(text)
                if e != NAME_MATCHER_MSG or name_matcher_may_hit(text, names)
            )
            used = mentioned(text, names)
            if used and normalise(text) not in known:
                errors.append(
                    f"dashboard: panel {title!r} uses {', '.join(sorted(set(used)))} but its expr "
                    f"is not a query-set entry: {text}"
                )
            continue
        toks = tokenize(text)
        if any(k == "ident" and t in nameset for k, t in toks) or name_matcher_may_hit(text, names):
            errors.append(
                f"dashboard: {title!r}: status metric in field {key!r}; only a panel target "
                f"`expr` equal to an entry may read it"
            )
    return errors


def _remove_entry(text: str, entry: str) -> str:
    """Replace each whole-token occurrence of `entry` in `text` with a placeholder."""
    out = []
    i = 0
    while i < len(text):
        at = text.find(entry, i)
        if at < 0:
            break
        end = at + len(entry)
        before_ok = at == 0 or text[at - 1] not in _IDENT_REST
        after_ok = end == len(text) or text[end] not in _NUM_REST
        if before_ok and after_ok:
            out.append(text[i:at] + "Q")
            i = end
        else:
            out.append(text[i : at + 1])
            i = at + 1
    out.append(text[i:])
    return "".join(out)


def check_rule_expr(expr: str, doc: dict) -> list[str]:
    """Remove every entry the rule contains verbatim; no catalogue metric may remain."""
    errors = [f"rule: {e} in: {expr}" for e in forbidden(expr)]
    names = metric_names(doc)
    left = normalise(expr)
    entries = sorted(
        (normalise(q["expr"]) for q in queries(doc) if isinstance(q.get("expr"), str)),
        key=len,
        reverse=True,
    )
    for entry in entries:
        left = _remove_entry(left, entry)
    remaining = mentioned(left, names)
    if remaining:
        errors.append(
            f"rule: {', '.join(sorted(set(remaining)))} used outside a query-set entry in: {expr}"
        )
    return errors
