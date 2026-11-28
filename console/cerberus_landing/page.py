"""Renders index.html. A string.Template skeleton plus section builders.

Text from content.toml is author-controlled and goes through html.escape. Text
that came from the repo's data (run records, Phases.md) goes through
cerberus_console.sanitize and then html.escape. The only script is one deferred
file of this site (static/site.js). There is no inline script, no style element
or attribute and no event handler anywhere (the edge CSP forbids them).

"Follow the batch" holds every run and station in the HTML. Its buttons start
hidden: the script shows them and then hides all but one run and one station, so
a reader without JavaScript sees every panel and no dead button.
"""

import html
from dataclasses import dataclass
from string import Template

from cerberus_console.sanitize import clean_str
from cerberus_landing.journey import ANSWER, ARRIVE, CLEAN, MODEL, Run, Station
from cerberus_landing.phases import STATUS_WORD, Phase
from cerberus_landing.runs import RunView

GITHUB = "https://github.com/ChiragVenkateshaiah/cerberus-platform"
PAGES = "https://chiragvenkateshaiah.github.io/cerberus-platform/"
EXTERNAL_PREFIXES = (GITHUB, PAGES)


def is_allowed_external(url: str) -> bool:
    """Only this repo and its Pages site; a longer name such as ...-platformX is refused."""
    return any(url == p or url.startswith(p.rstrip("/") + "/") for p in EXTERNAL_PREFIXES)


# The 9.5 terminal page, published on its own by publish_terminal.sh. The sign-in
# there is for invited users only.
TERMINAL_HREF = "terminal/index.html"

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
<script src="$js" defer></script>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<header class="top">
<div class="wrap">
<p class="kicker">$kicker</p>
<h1>$h1</h1>
$stats
<nav aria-label="Sections">
<ul class="nav">
$nav
</ul>
</nav>
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

# A warning is an icon and the word "Warning", never a colour alone.
WARN_ICON = (
    '<svg class="icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" '
    'focusable="false"><path class="icon-shape" d="M8 1 15.5 15H.5Z"/>'
    '<path class="icon-mark" d="M7 5.5h2v5H7zM7 11.5h2v2H7z"/></svg>'
)
# journey total labels whose figure is a size in bytes, not a count
BYTE_TOTALS = ("Gold stored bytes",)


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


def format_seconds(seconds) -> str | None:
    return None if seconds is None else f"{seconds:,.1f} s"


def format_count(n) -> str | None:
    return None if n is None else f"{n:,}"


def format_bytes(n) -> str | None:
    """Decimal units, as docs/scale-metrics.md writes them (1 GB = 10^9 bytes)."""
    if n is None:
        return None
    if n < 1000:
        return f"{n} bytes"
    for unit, size in (("PB", 10**15), ("TB", 10**12), ("GB", 10**9), ("MB", 10**6)):
        if n >= size:
            return f"{n / size:,.1f} {unit}"
    return f"{n / 1000:,.1f} kB"


def format_usd(usd) -> str | None:
    return None if usd is None else f"${usd:,.4f}"


def _stat(cls: str, number: str, label: str) -> str:
    return f'<div class="stat {cls}"><dt>{e(label)}</dt><dd>{d(number)}</dd></div>'


def _record_link(file_name: str, text: str) -> str:
    return f'<a class="link" href="{RUNS_URL}/{d(file_name)}">{e(text)}</a>'


def _stats(run: Run, n_records: int, n_ok: int, c: dict) -> str:
    """The achievements strip: the featured run, then the count over all records."""
    h = c["hero"]
    missing = c["journey"]["not_recorded"]
    cost = format_usd(run.cost_usd_per_million_events)
    items = [
        _stat("stat-main", format_count(run.events) or missing, h["stat_events"]),
        _stat("", format_seconds(run.run_seconds) or missing, h["stat_seconds"]),
        _stat(
            "",
            cost or missing,
            h["stat_cost_estimated"] if cost and run.cost_estimated else h["stat_cost"],
        ),
        _stat("stat-last", h["runs_of"].format(ok=n_ok, total=n_records), h["stat_runs"]),
    ]
    note = [h["featured"].format(date=run.date)]
    if run.bulk:
        note.append(c["journey"]["bulk"])
    if cost is not None and run.cost_estimated:
        note.append(h["cost_excludes"])
    return (
        f'<dl class="stats" aria-label="{e(h["stats_label"])}">\n'
        + "\n".join(items)
        + f'\n</dl>\n<p class="note">{d(" ".join(note))}</p>\n'
        + f"<p>{_record_link(run.file_name, c['journey']['record_link'])}</p>"
    )


def _bar(share: float) -> str:
    """The share of the run: one mark on a neutral track, square at the baseline.

    The second rect covers the left half of the rounded one, so only the data end
    is round. The value is written as text next to the bar.
    """
    full = share * 100
    return (
        '<svg class="bar" width="100%" height="8" aria-hidden="true" focusable="false">'
        '<rect class="bar-track" width="100%" height="8"/>'
        f'<rect class="bar-mark" width="{full:.2f}%" height="8" rx="4"/>'
        f'<rect class="bar-mark" width="{full / 2:.2f}%" height="8"/></svg>'
    )


def _time(run: Run, s: Station, c: dict) -> str:
    j = c["journey"]
    value = format_seconds(s.seconds)
    out = [f'<p class="label">{e(j["time"])}</p>']
    share = ""
    if s.share is not None:
        text = j["share"].format(share=f"{s.share * 100:.1f}%", run=format_seconds(run.run_seconds))
        share = f" <span>{d(text)}</span>"
    out.append(f'<p class="time"><strong>{d(value or j["not_recorded"])}</strong>{share}</p>')
    if s.share is not None:
        out.append(_bar(s.share))
    notes = []
    if s.state == ARRIVE:
        notes.append(j["arrive_note"])
        if run.bulk:
            notes.append(j["arrive_bulk"])
    if s.queue_seconds:  # None and 0 both mean there is no queue time to show
        notes.append(j["queue"].format(seconds=format_seconds(s.queue_seconds)))
    if notes:
        out.append(f'<p class="note">{d(" ".join(notes))}</p>')
    return "\n".join(out)


def _fact(label: str, value: str) -> str:
    return f"<div><dt>{e(label)}</dt><dd>{d(value)}</dd></div>"


def _figures(s: Station, c: dict) -> str:
    j = c["journey"]
    label = j["read"] if s.bytes_source is None else j["read_source"].format(source=s.bytes_source)
    read = format_bytes(s.bytes_read) or j["not_recorded"]
    out = [f'<dl class="figures">\n{_fact(label, read)}\n</dl>']
    if s.totals:
        rows = []
        for t in s.totals:
            fmt = format_bytes if t.label in BYTE_TOTALS else format_count
            rows.append(_fact(t.label, fmt(t.value) or j["not_recorded"]))
        out.append(f'<p class="label">{e(j["totals"])}</p>')
        out.append('<dl class="figures">\n' + "\n".join(rows) + "\n</dl>")
    return "\n".join(out)


def _warning(text: str, c: dict) -> str:
    return (
        f'<p class="warn">{WARN_ICON}<span><strong>{e(c["journey"]["warning"])}</strong> '
        f"{e(text)}</span></p>"
    )


def _checks(s: Station, c: dict) -> str:
    j = c["journey"]
    titles = {
        ARRIVE: j["checks_arrive"],
        CLEAN: j["checks_clean"],
        MODEL: j["checks_model"],
        ANSWER: j["checks_answer"],
    }
    out = [f'<p class="label">{e(titles[s.state])}</p>']
    if s.checks_passed is None:
        out.append(f"<p>{e(j['checks_missing'])}</p>")
        return "\n".join(out)
    if not s.checks_passed and not s.checks_warned:
        out.append(f"<p>{e(j['checks_none'])}</p>")
    out += [_warning(words, c) for words in s.warnings]
    others = s.checks_warned - len(s.warnings)
    if others:
        text = j["warned_one"] if others == 1 else j["warned_many"]
        out.append(_warning(text.format(count=others), c))
    if s.checks_passed:
        n = len(s.checks_passed)
        title = (j["passed_one"] if n == 1 else j["passed_many"]).format(count=n)
        items = "\n".join(f"<li>{e(words)}</li>" for words in s.checks_passed)
        out.append(
            f'<details class="passed"><summary>{e(title)}</summary>\n'
            f"<ul>\n{items}\n</ul>\n</details>"
        )
    return "\n".join(out)


def _panel_id(run: Run, s: Station) -> str:
    return f"s-{run.size.lower()}-{s.name.lower()}"


def _panel(run: Run, index: int, c: dict) -> str:
    j = c["journey"]
    s = run.stations[index]
    why = {
        ARRIVE: j["why_arrive"],
        CLEAN: j["why_clean"],
        MODEL: j["why_model"],
        ANSWER: j["why_answer"],
    }
    pid = _panel_id(run, s)
    partner = f'\n<p class="partner">{e(j["partner"])}</p>' if s.state == MODEL else ""
    last = index == len(run.stations) - 1
    target = run.stations[0 if last else index + 1]
    button = (j["restart"] if last else j["next"]).format(station=target.name)
    controls = _panel_id(run, target)
    return f"""<article class="panel" id="{pid}" tabindex="-1" aria-labelledby="{pid}-h">
<h4 id="{pid}-h">{index + 1}. {e(s.name)} <span>{e(s.label)}</span></h4>
<p class="why">{e(why[s.state])}</p>{partner}
<div class="cols">
<div>
{_time(run, s, c)}
{_figures(s, c)}
</div>
<div class="checks">
{_checks(s, c)}
</div>
</div>
<button type="button" class="btn next" data-next aria-controls="{controls}" \
hidden>{e(button)}</button>
</article>"""


def _run(run: Run, c: dict) -> str:
    j = c["journey"]
    rid = f"run-{run.size.lower()}"
    steps = "\n".join(
        f'<li><button type="button" class="btn" data-step aria-controls="{_panel_id(run, s)}" '
        f'aria-pressed="{"true" if i == 0 else "false"}"><span class="n">{i + 1}</span> '
        f"{e(s.name)}</button></li>"
        for i, s in enumerate(run.stations)
    )
    facts = "\n".join(
        [
            _fact(j["run_events"], format_count(run.events) or j["not_recorded"]),
            _fact(j["run_time"], format_seconds(run.run_seconds) or j["not_recorded"]),
            _fact(j["run_date"], run.date),
        ]
    )
    notes = []
    if run.bulk:
        notes.append(j["bulk"])
    if run.unknown_checks:
        notes.append(j["unknown"].format(count=run.unknown_checks))
    note = f'\n<p class="note">{d(" ".join(notes))}</p>' if notes else ""
    panels = "\n".join(_panel(run, i, c) for i in range(len(run.stations)))
    title = j["run_title"].format(size=run.size)
    return f"""<div class="run" id="{rid}" role="group" aria-labelledby="{rid}-h">
<h3 id="{rid}-h">{e(title)}</h3>
<dl class="figures run-facts">
{facts}
</dl>{note}
<p>{_record_link(run.file_name, j["record_link"])}</p>
<ol class="stepper" data-stepper aria-label="{e(j["stations"])}" hidden>
{steps}
</ol>
{panels}
</div>"""


def _journey(c: dict, featured_runs: tuple[Run, ...]) -> str:
    j = c["journey"]
    picks = "\n".join(
        f'<button type="button" class="btn" data-pick aria-controls="run-{r.size.lower()}" '
        f'aria-pressed="{"true" if r.featured else "false"}">{e(r.size)}</button>'
        for r in featured_runs
    )
    blocks = "\n".join(_run(r, c) for r in featured_runs)
    notes = "\n".join(
        f"<li>{e(t)}</li>" for t in (j["note_bytes"], j["note_checks"], j["note_runs"])
    )
    return f"""<section id="journey" aria-labelledby="journey-h">
<div class="wrap">
<h2 id="journey-h">{e(j["title"])}</h2>
<p class="intro">{e(j["intro"])}</p>
<div class="picker" data-picker role="group" aria-labelledby="pick-l" hidden>
<span id="pick-l">{e(j["pick"])}</span>
{picks}
</div>
{blocks}
<ul class="notes">
{notes}
</ul>
</div>
</section>"""


def _latest(c: dict, v: RunView) -> str:
    """One compact strip for the newest record, from the same view the console uses."""
    lt = c["latest"]
    cost = v.cost[0].upper() + v.cost[1:]
    rows = "\n".join(
        _fact(label, value)
        for label, value in (
            (lt["date"], v.date),
            (lt["status"], v.status),
            (lt["events"], v.events),
            (lt["duration"], v.duration),
            (lt["cost"], cost),
            (lt["checks"], v.checks),
        )
    )
    link = "" if v.file_name is None else f"\n<p>{_record_link(v.file_name, lt['record_link'])}</p>"
    notes = [lt["bulk_note"]] if v.bulk else []
    notes.append(lt["estimate_note"])
    return f"""<section id="latest" aria-labelledby="latest-h">
<div class="wrap">
<h2 id="latest-h">{e(lt["title"])}</h2>
<dl class="figures strip">
{rows}
</dl>
<p class="note">{e(" ".join(notes))}</p>{link}
</div>
</section>"""


def _chart(ch: Chart, s: dict) -> str:
    """The image keeps its width, so a narrow screen scrolls it; the box takes focus."""
    label = s["scroll_label"].format(title=ch.alt)
    caption = f"<figcaption>{e(ch.caption)}</figcaption>" if ch.caption else ""
    return (
        f'<li><figure class="chart"><div class="scroll" role="group" tabindex="0" '
        f'aria-label="{d(label)}"><img src="{e(ch.src)}" width="{ch.width}" '
        f'height="{ch.height}" alt="{d(ch.alt)}"></div>{caption}</figure></li>'
    )


def _scale(c: dict, charts: list[Chart]) -> str:
    s = c["scale"]
    if charts:
        items = "\n".join(_chart(ch, s) for ch in charts)
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
    pr = c["folds"]
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


def _folds(c: dict, phases: list[Phase], arch_svg: str) -> str:
    """The architecture and the phase status, closed until the reader opens them."""
    f = c["folds"]
    items = "\n".join(_phase_item(p, c["phases"][f"p{p.number}"], c) for p in phases)
    done = sum(1 for p in phases if p.status == "complete")
    progress = f["progress"].format(done=done, total=len(phases))
    return f"""<section id="more" aria-label="{e(f["label"])}">
<div class="wrap">
<details class="fold" id="architecture">
<summary>{e(f["architecture"])}</summary>
<p class="note">{e(f["architecture_note"])}</p>
<figure class="diagram">
{arch_svg}
</figure>
</details>
<details class="fold" id="progress">
<summary>{e(progress)}</summary>
<ol class="phases">
{items}
</ol>
<p><a class="link" href="{PHASES_DOC}">{e(f["checklist_link"])}</a></p>
</details>
</div>
</section>"""


def _closer(c: dict, run: Run) -> str:
    """The live dashboard, the terminal and one recorded Prometheus figure."""
    lv, t, rc = c["live"], c["terminal"], c["recorded"]
    peak = format_count(run.peak_series) or c["journey"]["not_recorded"]
    return f"""<section id="live" aria-labelledby="live-h">
<div class="wrap">
<h2 id="live-h">{e(lv["title"])}</h2>
<div class="cards">
<div class="card">
<h3>{e(lv["dashboard"])}</h3>
<p>{e(lv["body"])}</p>
<p><a class="link" id="live-link" hidden>{e(lv["open"])}</a></p>
<p><a class="link" href="{ADR_0022}">{e(lv["link"])}</a></p>
</div>
<div class="card" id="terminal">
<h3>{e(t["title"])}</h3>
<p>{e(t["body"])}</p>
<p><a class="link" href="{e(TERMINAL_HREF)}">{e(t["link"])}</a></p>
</div>
<div class="card" id="recorded">
<h3>{e(rc["title"])}</h3>
<p class="time"><strong>{d(peak)}</strong></p>
<p>{d(rc["label"].format(date=run.date))}</p>
<p class="note">{e(rc["note"])}</p>
</div>
</div>
</div>
</section>"""


def render(
    c: dict,
    phases: list[Phase],
    featured_runs: tuple[Run, ...],
    latest: RunView,
    n_records: int,
    n_ok: int,
    charts: list[Chart],
    arch_svg: str,
    css: str,
    js: str,
    favicon: str,
    build_id: str,
) -> str:
    nav = [("journey", c["journey"]["title"]), ("latest", c["latest"]["title"])]
    nav += [("scale", c["scale"]["title"]), ("live", c["live"]["title"])]
    ft = c["footer"]
    links = [
        (GITHUB, ft["repo"]),
        (PAGES, ft["pages"]),
        (PAGES + "dbt/", ft["dbt"]),
        (PAGES + "lineage/", ft["lineage"]),
        (ADR_DIR, ft["adrs"]),
        (PHASES_DOC, ft["phases"]),
    ]
    featured = next(r for r in featured_runs if r.featured)
    h = c["hero"]
    return PAGE.substitute(
        title=e(c["site"]["title"]),
        description=e(c["site"]["description"]),
        build_id=e(build_id),
        favicon=e(favicon),
        css=e(css),
        js=e(js),
        nav="\n".join(f'<li><a href="#{i}">{e(t)}</a></li>' for i, t in nav),
        kicker=e(h["kicker"]),
        h1=e(h["title"]),
        stats=_stats(featured, n_records, n_ok, c),
        sections="\n".join(
            [
                _journey(c, featured_runs),
                _latest(c, latest),
                _scale(c, charts),
                _closer(c, featured),
                _folds(c, phases, arch_svg),
            ]
        ),
        footer_links="\n".join(f'<li><a href="{u}">{e(t)}</a></li>' for u, t in links),
        privacy=e(ft["privacy"]),
    )
