"""Plain-text tables and key/value blocks. ASCII only (sanitize.py enforces it)."""

from cerberus_console import config


def table(headers: list[str], rows: list[list]) -> str:
    shown = rows[: config.TABLE_ROWS]
    cells = [[str(c) for c in headers]] + [["-" if c is None else str(c) for c in r] for r in shown]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in cells]
    if len(rows) > len(shown):
        lines.append(f"({len(rows) - len(shown)} more not shown)")
    return "\n".join(lines)


def kv(pairs: list[tuple[str, object]]) -> str:
    width = max((len(k) for k, _ in pairs), default=0)
    return "\n".join(f"{k.ljust(width)}  {'-' if v is None else v}" for k, v in pairs)


def money(v) -> str:
    return "-" if v is None else f"${v:.4f}"


def num(v, digits: int = 0) -> str:
    if v is None:
        return "-"
    return f"{v:,.{digits}f}"
