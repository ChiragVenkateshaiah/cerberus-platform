#!/usr/bin/env python3
"""Cerberus 6.4d — render captured OpenLineage events into a static page.

Reads the OpenLineage RunEvents the 6.4b collector wrote to S3 (synced to a
local directory by the dbt-docs workflow) and produces one self-contained
HTML page: a Mermaid graph of every dataset and job actually observed at
runtime, a column-lineage table per output dataset, and a summary of the
runs seen. It is the runtime cross-check against the hand-maintained graph
in docs/lineage.md -- if the two disagree, one of them is stale.

Pure stdlib: the workflow runs `aws s3 sync` (AWS CLI, preinstalled on the
runner) to fetch the events, so this script only ever reads local files.
"""

import argparse
import html
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"


def load_events(events_dir):
    """Every parseable *.json under events_dir except the malformed/ prefix."""
    events = []
    for path in sorted(Path(events_dir).rglob("*.json")):
        if "malformed" in path.parts:
            continue
        try:
            events.append(json.loads(path.read_text()))
        except (ValueError, OSError):
            continue
    return events


def short(name):
    """awsdatacatalog.cerberus_platform.payments_events -> payments_events."""
    return name.rsplit(".", 1)[-1] if name else name


def job_label(name):
    """Last three dotted segments -- for dbt that's <model>.build.<run|test>,
    for Spark the app name. The full leading catalog/schema path is noise."""
    if not name:
        return name
    return ".".join(name.split(".")[-3:])


def node_id(prefix, name):
    safe = "".join(c if c.isalnum() else "_" for c in name)
    return f"{prefix}_{safe}"


class Graph:
    def __init__(self):
        self.datasets = set()  # (namespace, name)
        self.jobs = set()  # (namespace, name)
        self.job_inputs = defaultdict(set)  # job name -> {dataset name}
        self.job_outputs = defaultdict(set)
        # output dataset name -> {output field -> sorted [ "ds.field", ... ]}
        self.column_lineage = defaultdict(lambda: defaultdict(set))
        self.dataset_fields = defaultdict(set)  # dataset name -> {field}
        self.namespaces = set()
        self.producers = set()
        self.newest_event = None

    def transform_jobs(self):
        """Jobs that produce a dataset -- the actual lineage edges. A job with
        inputs but no outputs is a dbt test (consumes a table, asserts on it)
        and is counted separately, not drawn."""
        return {j for j, outs in self.job_outputs.items() if any(outs)}

    def test_job_count(self):
        producing = self.transform_jobs()
        return sum(1 for j, ins in self.job_inputs.items() if j not in producing and any(ins))

    def ingest(self, ev):
        job = ev.get("job") or {}
        jname = job.get("name")
        if job.get("namespace"):
            self.namespaces.add(job["namespace"])
        if jname:
            self.jobs.add((job.get("namespace", ""), jname))
        if ev.get("producer"):
            self.producers.add(ev["producer"])

        et = ev.get("eventTime")
        if et and (self.newest_event is None or et > self.newest_event):
            self.newest_event = et

        for ds in ev.get("inputs") or []:
            self._dataset(ds)
            if jname:
                self.job_inputs[jname].add(ds.get("name"))
        for ds in ev.get("outputs") or []:
            self._dataset(ds)
            if jname:
                self.job_outputs[jname].add(ds.get("name"))
            self._column_lineage(ds)

    def _dataset(self, ds):
        name = ds.get("name")
        if not name:
            return
        self.datasets.add((ds.get("namespace", ""), name))
        schema = (ds.get("facets") or {}).get("schema") or {}
        for field in schema.get("fields") or []:
            if field.get("name"):
                self.dataset_fields[name].add(field["name"])

    def _column_lineage(self, ds):
        out_name = ds.get("name")
        cl = (ds.get("facets") or {}).get("columnLineage") or {}
        for out_field, spec in (cl.get("fields") or {}).items():
            for inp in spec.get("inputFields") or []:
                ref = f"{short(inp.get('name', '?'))}.{inp.get('field', '?')}"
                self.column_lineage[out_name][out_field].add(ref)


def mermaid(graph):
    jobs = graph.transform_jobs()
    # datasets that any drawn job touches, plus any that appear standalone
    touched = set()
    for j in jobs:
        touched |= {d for d in graph.job_inputs.get(j, ()) if d}
        touched |= {d for d in graph.job_outputs.get(j, ()) if d}
    datasets = sorted({n for _ns, n in graph.datasets} | touched)

    lines = ["flowchart LR"]
    for name in datasets:
        lines.append(f'    {node_id("d", name)}[("{html.escape(short(name))}")]')
    for job in sorted(jobs):
        lines.append(f'    {node_id("j", job)}["{html.escape(job_label(job))}"]')
    for job in sorted(jobs):
        for ds in sorted(d for d in graph.job_inputs.get(job, ()) if d):
            lines.append(f"    {node_id('d', ds)} --> {node_id('j', job)}")
        for ds in sorted(d for d in graph.job_outputs.get(job, ()) if d):
            lines.append(f"    {node_id('j', job)} --> {node_id('d', ds)}")
    lines.append("    classDef ds fill:#dbeafe,stroke:#1e3a8a,color:#1e3a8a;")
    lines.append("    classDef job fill:#dcfce7,stroke:#14532d,color:#14532d;")
    if datasets:
        lines.append("    class " + ",".join(node_id("d", n) for n in datasets) + " ds;")
    if jobs:
        lines.append("    class " + ",".join(node_id("j", j) for j in sorted(jobs)) + " job;")
    return "\n".join(lines)


def column_tables(graph):
    blocks = []
    for out_name in sorted(graph.column_lineage):
        rows = "".join(
            f"<tr><td><code>{html.escape(out_field)}</code></td>"
            f"<td>{', '.join(f'<code>{html.escape(r)}</code>' for r in sorted(refs))}</td></tr>"
            for out_field, refs in sorted(graph.column_lineage[out_name].items())
        )
        blocks.append(
            f"<details><summary>{html.escape(short(out_name))} "
            f"&mdash; {len(graph.column_lineage[out_name])} columns</summary>"
            f"<table><thead><tr><th>column</th><th>derived from</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details>"
        )
    return "\n".join(blocks)


def render(graph, generated_at):
    has_data = bool(graph.datasets or graph.jobs)
    if has_data:
        body = f"""
    <p class="meta">
      {len(graph.datasets)} datasets &middot; {len(graph.transform_jobs())} transform jobs
      &middot; {graph.test_job_count()} test executions &middot;
      newest event {html.escape(graph.newest_event or "?")}
    </p>
    <pre class="mermaid">
{mermaid(graph)}
    </pre>
    <h2>Column lineage</h2>
    <p class="sub">From each output dataset's <code>columnLineage</code> facet.
    dbt's SQL parser resolves references to the model's own CTEs / refs
    (e.g. <code>ranked.*</code> is <code>fct_transactions.sql</code>'s window
    CTE), not transitively to the source columns.</p>
    {column_tables(graph) or "<p>No column-level facets in the captured events yet.</p>"}
    <h2>Producers seen</h2>
    <ul>{"".join(f"<li><code>{html.escape(p)}</code></li>" for p in sorted(graph.producers))}</ul>
"""
    else:
        body = """
    <p class="empty">
      No OpenLineage events captured yet. This page fills in after the next
      orchestrated pipeline run &mdash; the Spark transform (on EKS) and
      <code>dbt-ol build</code> both POST events to the collector as they run.
    </p>
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cerberus-platform &mdash; runtime lineage</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fafafa; --fg:#1a1a1a; --muted:#5a5a5a;
           --card:#fff; --border:#e2e2e2; --accent:#7c3aed; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14141a; --fg:#e8e8ea; --muted:#9a9aa2; --card:#1e1e26;
             --border:#2e2e38; --accent:#a78bfa; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:3rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
          font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
  main {{ max-width: 60rem; margin: 0 auto; }}
  h1 {{ font-size: 1.7rem; margin: 0 0 .25rem; }}
  h2 {{ font-size: 1.15rem; margin: 2.5rem 0 .75rem; }}
  a {{ color: var(--accent); }}
  .sub, .meta {{ color: var(--muted); }}
  .meta {{ font-size: .9rem; margin: 0 0 1.5rem; }}
  .empty {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
            padding:1.25rem; color:var(--muted); }}
  pre.mermaid {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
                 padding:1rem; overflow-x:auto; }}
  details {{ background:var(--card); border:1px solid var(--border); border-radius:8px;
             padding:.5rem .9rem; margin:.5rem 0; }}
  summary {{ cursor:pointer; font-weight:600; }}
  table {{ border-collapse:collapse; width:100%; margin:.75rem 0; font-size:.92rem; }}
  th, td {{ text-align:left; padding:.4rem .6rem; border-bottom:1px solid var(--border); }}
  code {{ font-size:.85em; }}
  footer {{ margin-top:3rem; color:var(--muted); font-size:.85rem; }}
</style>
</head>
<body>
<main>
  <h1>Runtime lineage</h1>
  <p class="sub">
    Assembled from the OpenLineage events the Spark and dbt steps emitted as
    they ran (6.4b/6.4c) &mdash; the observed cross-check against the curated
    <a href="https://github.com/ChiragVenkateshaiah/cerberus-platform/blob/main/docs/lineage.md">docs/lineage.md</a>.
    <a href="../">&larr; back</a> &middot; <a href="../dbt/">dbt model DAG &rarr;</a>
  </p>
  {body}
  <footer>generated {html.escape(generated_at)} by
    <code>lineage/render/render_graph.py</code> (6.4d)</footer>
</main>
<script type="module">
  import mermaid from "{MERMAID_CDN}";
  mermaid.initialize({{ startOnLoad: true, theme:
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "default" }});
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events-dir", required=True, help="directory of OpenLineage event JSON files")
    ap.add_argument("--out", required=True, help="HTML file to write")
    args = ap.parse_args()

    graph = Graph()
    events = load_events(args.events_dir)
    for ev in events:
        graph.ingest(ev)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out.write_text(render(graph, generated_at))
    print(
        f"rendered {out} from {len(events)} events "
        f"({len(graph.datasets)} datasets, {len(graph.transform_jobs())} transform jobs, "
        f"{graph.test_job_count()} test executions)"
    )


if __name__ == "__main__":
    main()
