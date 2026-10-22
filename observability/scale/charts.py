"""Render the Phase 8 results charts (8.10) from the run records.

    python observability/scale/charts.py

Reads observability/scale/runs/*.json and writes three SVGs to
docs/img/scale/: run time per state, cost per million events (log scale),
and RunTransform input throughput against executors. Plain SVG with its
own light and dark styles, so GitHub renders it in either theme; the same
numbers are in tables in docs/scale-metrics.md (the charts' text view).

The palette is the categorical order blue, orange, aqua, yellow, validated
for adjacent-pair colour-blind separation in both modes. Aqua and yellow
sit below 3:1 on the light surface, so every chart carries direct labels.
No AWS calls; standard library only.
"""

# ruff: noqa: E501, E731 -- SVG markup in f-strings reads better on one line
# each, and each chart keeps its small scale functions as local lambdas.

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "observability" / "scale" / "runs"
OUT = ROOT / "docs" / "img" / "scale"

# The 8.10 ladder: the clean run at each step (docs/scale-metrics.md, 8.10).
LADDER = [
    ("1M", "exercise-20261015T145812Z"),
    ("10M", "exercise-20261009T074853Z"),
    ("100M", "exercise-20261013T055859Z"),
]
STATES = ["InvokeIngestion", "RunTransform", "RunDbt", "RunServingQuery"]

# Executors registered by the silver job, counted from each exercise's driver
# log ("Registered executor ... with ID n"; the logs are not in git). A count
# of registrations, so replacements after the Spot interruption count too.
THROUGHPUT_RUNS = [
    ("10M, 1 × 1 GB executor", "exercise-20261009T074853Z", 1),
    ("10M, 2 × 2 GB", "exercise-20261009T101830Z", 2),
    ("9M load test", "exercise-20261012T111304Z", 8),
    ("9M Spot interruption", "exercise-20261012T133620Z", 12),
    ("100M", "exercise-20261013T055859Z", 16),
    ("1M on 137M silver", "exercise-20261015T145812Z", 16),
]

STYLE = """
  .surface { fill: #fcfcfb; }
  .ink { fill: #0b0b0b; }
  .ink2 { fill: #52514e; }
  .muted { fill: #898781; }
  .grid { stroke: #e1e0d9; }
  .axis { stroke: #c3c2b7; }
  .s1 { fill: #2a78d6; } .s2 { fill: #eb6834; } .s3 { fill: #1baf7a; } .s4 { fill: #eda100; }
  .gap { stroke: #fcfcfb; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; }
    .ink { fill: #f0efec; }
    .ink2 { fill: #c3c2b7; }
    .grid { stroke: #2c2c2a; }
    .axis { stroke: #383835; }
    .s1 { fill: #3987e5; } .s2 { fill: #d95926; } .s3 { fill: #199e70; } .s4 { fill: #c98500; }
    .gap { stroke: #1a1a19; }
  }
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  .t { font-size: 15px; font-weight: 600; }
  .st { font-size: 12px; }
  .l { font-size: 12px; }
  .tick { font-size: 11px; font-variant-numeric: tabular-nums; }
"""


def load(execution):
    return json.loads((RUNS / f"{execution}.json").read_text())


def svg(width, height, title, subtitle, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">\n'
        f"<title>{esc(title)}</title>\n<style>{STYLE}</style>\n"
        f'<rect class="surface" fill="#fcfcfb" width="{width}" height="{height}" rx="8"/>\n'
        f'<text class="t ink" fill="#0b0b0b" x="20" y="28">{esc(title)}</text>\n'
        f'<text class="st ink2" fill="#52514e" x="20" y="47">{esc(subtitle)}</text>\n'
        f"{presentational(body)}</svg>\n"
    )


# Light-mode values as presentation attributes too: a renderer that ignores the
# <style> block still draws the light chart, and the CSS (which wins over
# presentation attributes) switches to dark.
LIGHT_FILL = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "s1": "#2a78d6",
    "s2": "#eb6834",
    "s3": "#1baf7a",
    "s4": "#eda100",
}
LIGHT_STROKE = {"grid": "#e1e0d9", "axis": "#c3c2b7", "gap": "#fcfcfb"}


def presentational(markup):
    def add(match):
        tag, classes = match.group(1), match.group(2).split()
        attrs = ""
        for c in classes:
            if c in LIGHT_FILL and "fill=" not in match.group(0):
                attrs += f' fill="{LIGHT_FILL[c]}"'
            if c in LIGHT_STROKE:
                attrs += f' stroke="{LIGHT_STROKE[c]}"'
        return f'<{tag} class="{match.group(2)}"{attrs}'

    return re.sub(r'<(\w+) class="([^"]*)"', add, markup)


def esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar(x, y, w, h, cls, round_end):
    """A horizontal bar segment; only the run's last segment gets the 4px end."""
    if not round_end or w <= 4:
        return f'<rect class="{cls}" x="{x:.1f}" y="{y}" width="{max(w, 0.5):.1f}" height="{h}"/>'
    r = 4
    return (
        f'<path class="{cls}" d="M{x:.1f},{y} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} '
        f'v{h - 2 * r} a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z"/>'
    )


def run_time_chart():
    width, left, right, top = 760, 175, 30, 110
    row, thick = 62, 24
    scale_max = 800
    plot_w = width - left - right
    height = top + row * len(LADDER) + 50
    xs = lambda s: left + s / scale_max * plot_w  # noqa: E731
    out = []
    # legend, one row above the plot
    lx = left
    for i, state in enumerate(STATES):
        out.append(f'<rect class="s{i + 1}" x="{lx}" y="66" width="12" height="12" rx="2"/>')
        out.append(f'<text class="l ink2" x="{lx + 17}" y="76">{state}</text>')
        lx += 17 + len(state) * 7 + 22
    for s in range(0, scale_max + 1, 100):
        x = xs(s)
        out.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" '
            f'y2="{top + row * len(LADDER) - 16}" stroke-width="1"/>'
        )
        out.append(
            f'<text class="tick muted" x="{x:.1f}" y="{top + row * len(LADDER) + 2}" '
            f'text-anchor="middle">{s}</text>'
        )
    out.append(
        f'<text class="tick muted" x="{left + plot_w}" y="{top + row * len(LADDER) + 20}" '
        f'text-anchor="end">seconds</text>'
    )
    for r, (step, execution) in enumerate(LADDER):
        rec = load(execution)
        seconds = {s["state"]: s["seconds"] for s in rec["states"]}
        y = top + r * row
        out.append(f'<text class="l ink" x="20" y="{y + 11}">{step} new events</text>')
        out.append(f'<text class="tick muted" x="20" y="{y + 26}">{execution[9:]}</text>')
        x = left
        for i, state in enumerate(STATES):
            w = xs(seconds[state]) - left
            out.append(bar(x, y, w, thick, f"s{i + 1}", i == len(STATES) - 1))
            if state == "RunDbt":
                dbt_x = x
            if i:  # 2px surface gap between touching segments
                out.append(
                    f'<line class="gap" x1="{x:.1f}" y1="{y}" x2="{x:.1f}" '
                    f'y2="{y + thick}" stroke-width="2"/>'
                )
            if w > 60:
                out.append(
                    f'<text class="tick" x="{x + w / 2:.1f}" y="{y + 16}" '
                    f'text-anchor="middle" fill="#0b0b0b">{seconds[state]:.0f}</text>'
                )
            x += w
        out.append(
            f'<text class="l ink" x="{x + 8:.1f}" y="{y + 16}">{rec["run_seconds"]:.0f} s</text>'
        )
        if step == "1M":
            queue = next(s for s in rec["states"] if s["state"] == "RunDbt")["athena"][
                "queue_seconds"
            ]
            out.append(
                f'<text class="tick ink2" x="{dbt_x:.1f}" y="{y + thick + 14}">'
                f"↑ RunDbt includes {queue:.0f} s of Athena queue time</text>"
            )
    return svg(
        width,
        height,
        "Run time per state",
        "The clean run at each step of the ladder. Each run starts on a larger silver table: "
        "1.1M, 37.1M, 137.1M events.",
        "\n".join(out) + "\n",
    )


def cost_chart():
    width, left, right, top = 760, 175, 40, 80
    row = 52
    lo, hi = 0.001, 1.0
    plot_w = width - left - right
    height = top + row * len(LADDER) + 40
    xs = lambda v: (
        left + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * plot_w
    )  # noqa: E731
    out = []
    bottom = top + row * len(LADDER) - 14
    for v, label in [(0.001, "$0.001"), (0.01, "$0.01"), (0.1, "$0.10"), (1.0, "$1")]:
        x = xs(v)
        out.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top - 10}" x2="{x:.1f}" y2="{bottom}" stroke-width="1"/>'
        )
        out.append(
            f'<text class="tick muted" x="{x:.1f}" y="{bottom + 16}" text-anchor="middle">{label}</text>'
        )
    out.append(
        f'<text class="tick muted" x="{left + plot_w}" y="{bottom + 32}" text-anchor="end">'
        "per million events, log scale</text>"
    )
    for r, (step, execution) in enumerate(LADDER):
        rec = load(execution)
        cost = rec["cost"]
        y = top + r * row
        x = xs(cost["usd_per_million_events"])
        out.append(f'<text class="l ink" x="20" y="{y + 4}">{step} new events</text>')
        out.append(
            f'<line class="axis" x1="{left}" y1="{y}" x2="{x:.1f}" y2="{y}" stroke-width="2"/>'
        )
        out.append(f'<circle class="s1" cx="{x:.1f}" cy="{y}" r="6"/>')
        out.append(
            f'<circle cx="{x:.1f}" cy="{y}" r="6" fill="none" class="gap" stroke-width="2"/>'
        )
        out.append(
            f'<text class="l ink" x="{x:.1f}" y="{y - 11}" text-anchor="end">'
            f"${cost['usd_per_million_events']:.4f} per M · run ${cost['run_usd']:.2f}</text>"
        )
    return svg(
        width,
        height,
        "Cost per million events, orchestrated run",
        "The run costs $0.10–0.37 at every step, so the cost per event falls about 80 times "
        "from 1M to 100M.",
        "\n".join(out) + "\n",
    )


def throughput_chart():
    width, left, right, top = 760, 70, 200, 84
    plot_h = 260
    x_max, y_max = 18, 120
    plot_w = width - left - right
    height = top + plot_h + 50
    xs = lambda v: left + v / x_max * plot_w  # noqa: E731
    ys = lambda v: top + plot_h - v / y_max * plot_h  # noqa: E731
    out = []
    for v in range(0, y_max + 1, 20):
        out.append(
            f'<line class="grid" x1="{left}" y1="{ys(v):.1f}" x2="{left + plot_w}" y2="{ys(v):.1f}" stroke-width="1"/>'
        )
        out.append(
            f'<text class="tick muted" x="{left - 8}" y="{ys(v) + 4:.1f}" text-anchor="end">{v}</text>'
        )
    for v in range(0, x_max + 1, 2):
        out.append(
            f'<text class="tick muted" x="{xs(v):.1f}" y="{top + plot_h + 18}" text-anchor="middle">{v}</text>'
        )
    out.append(
        f'<line class="axis" x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke-width="1"/>'
    )
    out.append(
        f'<text class="tick muted" x="{left + plot_w}" y="{top + plot_h + 36}" text-anchor="end">'
        "executors registered by the silver job</text>"
    )
    out.append(
        f'<text class="tick muted" x="{left - 8}" y="{top - 12}" text-anchor="end">MB/s</text>'
    )
    offsets = {"9M Spot interruption": 18, "1M on 137M silver": -12, "10M, 2 × 2 GB": -8}
    for label, execution, executors in THROUGHPUT_RUNS:
        rec = load(execution)
        state = next(s for s in rec["states"] if s["state"] == "RunTransform")
        input_bytes = rec["prometheus"]["spark"]["cerberus-promote-payments"]["spark_input_bytes"]
        mbps = input_bytes / 1e6 / state["seconds"]
        x, y = xs(executors), ys(mbps)
        out.append(f'<circle class="s1" cx="{x:.1f}" cy="{y:.1f}" r="5"/>')
        out.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="none" class="gap" stroke-width="2"/>'
        )
        out.append(
            f'<text class="tick ink2" x="{x + 10:.1f}" y="{y + 4 + offsets.get(label, 0):.1f}">'
            f"{esc(label)} · {mbps:.0f} MB/s</text>"
        )
    return svg(
        width,
        height,
        "RunTransform input throughput against executors",
        "Spark input bytes per second of the step. Throughput follows the input size "
        "more than the executor count.",
        "\n".join(out) + "\n",
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, render in [
        ("run-time-per-state.svg", run_time_chart),
        ("cost-per-million-events.svg", cost_chart),
        ("transform-throughput.svg", throughput_chart),
    ]:
        (OUT / name).write_text(render())
        print(f"wrote {(OUT / name).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
