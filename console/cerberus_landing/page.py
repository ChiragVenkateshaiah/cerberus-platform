"""Renders index.html. A string.Template skeleton plus section builders.

Text from content.toml is author-controlled and goes through html.escape. Text
that came from the repo's data (run records, Phases.md) goes through
cerberus_console.sanitize and then html.escape. There is no script, no style
element or attribute and no event handler anywhere (the edge CSP forbids them).
"""

import html
from dataclasses import dataclass
from string import Template

from cerberus_console.sanitize import clean_str
from cerberus_landing.phases import STATUS_WORD, Phase
from cerberus_landing.runs import RunView

GITHUB = "https://github.com/ChiragVenkateshaiah/cerberus-platform"
PAGES = "https://chiragvenkateshaiah.github.io/cerberus-platform/"
EXTERNAL_PREFIXES = (GITHUB, PAGES)


def is_allowed_external(url: str) -> bool:
    """Only this repo and its Pages site; a longer name such as ...-platformX is refused."""
    return any(url == p or url.startswith(p.rstrip("/") + "/") for p in EXTERNAL_PREFIXES)


# Step 9.5 sets this to "terminal/index.html". A static link cannot start the
# sign-in (the PKCE code verifier needs JavaScript), so 9.4 shows no link.
TERMINAL_HREF: str | None = None

ADR_DIR = f"{GITHUB}/tree/main/docs/adr"
ADR_0022 = f"{GITHUB}/blob/main/docs/adr/0022-live-observability-for-a-recorded-run.md"
SCALE_DOC = f"{GITHUB}/blob/main/docs/scale-metrics.md"
PHASES_DOC = f"{GITHUB}/blob/main/Phases.md"
RUNS_URL = f"{GITHUB}/blob/main/observability/scale/runs"

PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<meta name="description" content="$description">
<meta name="robots" content="noindex">
<meta name="cerberus-build" content="$build_id">
<link rel="icon" href="$favicon" type="image/svg+xml">
<link rel="stylesheet" href="$css">
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<header class="top">
<div class="wrap">
<nav aria-label="Sections">
<ul class="nav">
$nav
</ul>
</nav>
<p class="kicker">$kicker</p>
<h1>$h1</h1>
<p class="lede">$lede</p>
<p class="cost">$cost</p>
$stats
</div>
</header>
<main id="main">
$sections
</main>
<footer class="foot">
<div class="wrap">
<ul>
$footer_links
</ul>
<p>$privacy</p>
</div>
</footer>
</body>
</html>
""")


@dataclass(frozen=True)
class Chart:
    src: str  # relative, content-hashed
    alt: str
    width: int
    height: int
    caption: str


def e(text: str) -> str:
    """Author text -> HTML."""
    return html.escape(text, quote=True)


def d(text: str) -> str:
    """Repo data -> HTML (sanitised first)."""
    return html.escape(clean_str(text), quote=True)


def _stat(number: str, label: str) -> str:
    return f'<div class="stat"><dt>{d(label)}</dt><dd>{d(number)}</dd></div>'


def _stats(phases: list[Phase], latest, largest, n_records: int, n_ok: int, c: dict) -> str:
    h = c["hero"]
    done = sum(1 for p in phases if p.status == "complete")
    items = [_stat(f"{done} of {len(phases)}", h["stat_phases"])]
    if n_records:
        items.append(_stat(str(n_records), f"{h['stat_runs']} ({n_ok} {h['stat_succeeded']})"))
    if largest is not None:
        items.append(_stat(largest.events, h["stat_largest"]))
    return '<dl class="stats">\n' + "\n".join(items) + "\n</dl>"


def _flow(c: dict, arch_svg: str) -> str:
    f = c["flow"]
    steps = "\n".join(
        f"<li><strong>{e(s['name'])}</strong>{e(s['plain'])}"
        f'<span class="tools">{e(s["tools"])}</span></li>'
        for s in f["steps"]
    )
    return f"""<section id="flow" aria-labelledby="flow-h">
<div class="wrap">
<h2 id="flow-h">{e(f["title"])}</h2>
<p class="intro">{e(f["intro"])}</p>
<div class="flow">
<figure class="diagram">
{arch_svg}
</figure>
<div>
<ol class="steps">
{steps}
</ol>
<p class="note">{e(f["orchestrated"])}</p>
<div class="facts">
<div class="fact"><h3>{e(f["watched_title"])}</h3><p>{e(f["watched"])}</p></div>
<div class="fact"><h3>{e(f["partner_title"])}</h3><p>{e(f["partner"])}</p></div>
</div>
<p class="note">{e(f["delivery"])}</p>
</div>
</div>
</div>
</section>"""


def _run_card(title: str, note: str, v: RunView, c: dict) -> str:
    lt = c["latest"]
    rows = "\n".join(
        f'<tr><th scope="row">{d(label)}</th><td>{d(sec)}</td></tr>' for label, sec in v.states
    )
    cost = (
        f"{lt['cost_prefix']}{v.cost}" if v.cost.startswith("$") else v.cost[0].upper() + v.cost[1:]
    )
    link = ""
    if v.file_name is not None:
        link = f'<a class="link" href="{RUNS_URL}/{d(v.file_name)}">{e(lt["record_link"])}</a>'
    notes = [n for n in (note, lt["bulk_note"] if v.bulk else "") if n]
    note_html = "\n".join(f'<p class="note">{e(n)}</p>' for n in notes)
    return f"""<article class="card">
<h3>{e(title)}</h3>
<p class="when">{d(v.date)} <span class="pill">{d(v.status)}</span></p>
<dl class="big"><dt>{e(lt["events_label"])} {d(v.duration)}</dt><dd>{d(v.events)}</dd></dl>
<ul class="facts-list">
<li>{d(cost)}</li>
<li>{d(v.checks)}</li>
</ul>
<div class="scroll" tabindex="0" role="region" aria-label="{e(title)}: time per step">
<table>
<caption>{e(lt["table_caption"])}</caption>
<thead><tr>
<th scope="col">{e(lt["table_step"])}</th>
<th scope="col">{e(lt["table_seconds"])}</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
{link}
{note_html}
</article>"""


def _latest(c: dict, latest: RunView | None, largest: RunView | None) -> str:
    lt = c["latest"]
    if latest is None:
        body = f'<p class="placeholder">{e(lt["none"])}</p>'
    else:
        cards = [_run_card(lt["latest_title"], "", latest, c)]
        if largest is not None:
            cards.append(_run_card(lt["largest_title"], lt["largest_note"], largest, c))
        body = '<div class="cards">\n' + "\n".join(cards) + "\n</div>"
        body += f'\n<p class="note">{e(lt["estimate_note"])}</p>'
    return f"""<section id="latest" aria-labelledby="latest-h">
<div class="wrap">
<h2 id="latest-h">{e(lt["title"])}</h2>
<p class="intro">{e(lt["intro"])}</p>
{body}
</div>
</section>"""


def _scale(c: dict, charts: list[Chart]) -> str:
    s = c["scale"]
    if charts:
        items = "\n".join(
            f'<li><figure class="chart"><img src="{e(ch.src)}" width="{ch.width}" '
            f'height="{ch.height}" alt="{d(ch.alt)}">'
            + (f"<figcaption>{e(ch.caption)}</figcaption>" if ch.caption else "")
            + "</figure></li>"
            for ch in charts
        )
        body = (
            f'<ul class="charts">\n{items}\n</ul>\n'
            f'<p class="note"><a class="link" href="{SCALE_DOC}">{e(s["numbers_link"])}</a></p>'
        )
    else:
        body = f'<p class="placeholder">{e(s["placeholder"])}</p>'
    return f"""<section id="scale" aria-labelledby="scale-h">
<div class="wrap">
<h2 id="scale-h">{e(s["title"])}</h2>
<p class="intro">{e(s["intro"])}</p>
{body}
</div>
</section>"""


def _phase_item(p: Phase, sentence: str, c: dict) -> str:
    pr = c["progress"]
    status = STATUS_WORD[p.status]
    cls = p.status.replace(" ", "-")
    still = ""
    if p.status == "in progress" and p.open:
        still = f"<span>{e(pr['still_open'])}: {d(', '.join(p.open))}</span>"
    return f"""<li class="phase">
<div class="head">
<span class="num">Phase {p.number}</span>
<span class="name">{d(p.title)}</span>
<span class="badge {cls}">{status}</span>
</div>
<p class="what">{e(sentence)}</p>
<div class="meta">
<progress value="{len(p.done)}" max="{p.total}" aria-hidden="true"></progress>
<span>{len(p.done)} of {p.total} {e(pr["steps_done"])}</span>
{still}
</div>
</li>"""


def _progress(c: dict, phases: list[Phase]) -> str:
    pr = c["progress"]
    items = "\n".join(_phase_item(p, c["phases"][f"p{p.number}"], c) for p in phases)
    return f"""<section id="progress" aria-labelledby="progress-h">
<div class="wrap">
<h2 id="progress-h">{e(pr["title"])}</h2>
<p class="intro">{e(pr["intro"])}</p>
<ol class="phases">
{items}
</ol>
<p class="note"><a class="link" href="{PHASES_DOC}">{e(pr["checklist_link"])}</a></p>
</div>
</section>"""


def _live(c: dict) -> str:
    lv = c["live"]
    return f"""<section id="live" aria-labelledby="live-h">
<div class="wrap">
<h2 id="live-h">{e(lv["title"])}</h2>
<p class="intro">{e(lv["body"])}</p>
<p><a class="link" href="{ADR_0022}">{e(lv["link"])}</a></p>
</div>
</section>"""


def _terminal(c: dict) -> str:
    t = c["terminal"]
    link = ""
    if TERMINAL_HREF is not None:
        link = f'\n<p><a class="link" href="{e(TERMINAL_HREF)}">{e(t["link"])}</a></p>'
    return f"""<section id="terminal" aria-labelledby="terminal-h">
<div class="wrap">
<h2 id="terminal-h">{e(t["title"])}</h2>
<p class="intro">{e(t["body"])}</p>{link}
</div>
</section>"""


def render(
    c: dict,
    phases: list[Phase],
    latest: RunView | None,
    largest: RunView | None,
    n_records: int,
    n_ok: int,
    charts: list[Chart],
    arch_svg: str,
    css: str,
    favicon: str,
    build_id: str,
) -> str:
    nav = [("flow", c["flow"]["title"]), ("latest", c["latest"]["title"])]
    nav += [("scale", c["scale"]["title"]), ("progress", c["progress"]["title"])]
    nav += [("live", c["live"]["title"]), ("terminal", c["terminal"]["title"])]
    ft = c["footer"]
    links = [
        (GITHUB, ft["repo"]),
        (PAGES, ft["pages"]),
        (PAGES + "dbt/", ft["dbt"]),
        (PAGES + "lineage/", ft["lineage"]),
        (ADR_DIR, ft["adrs"]),
        (PHASES_DOC, ft["phases"]),
    ]
    h = c["hero"]
    return PAGE.substitute(
        title=e(c["site"]["title"]),
        description=e(c["site"]["description"]),
        build_id=e(build_id),
        favicon=e(favicon),
        css=e(css),
        nav="\n".join(f'<li><a href="#{i}">{e(t)}</a></li>' for i, t in nav),
        kicker=e(h["kicker"]),
        h1=e(h["title"]),
        lede=e(h["lede"]),
        cost=e(h["cost"]),
        stats=_stats(phases, latest, largest, n_records, n_ok, c),
        sections="\n".join(
            [
                _flow(c, arch_svg),
                _latest(c, latest, largest),
                _scale(c, charts),
                _progress(c, phases),
                _live(c),
                _terminal(c),
            ]
        ),
        footer_links="\n".join(f'<li><a href="{u}">{e(t)}</a></li>' for u, t in links),
        privacy=e(ft["privacy"]),
    )
