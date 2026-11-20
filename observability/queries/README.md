# Named query set (pipeline status)

`status.json` is the one list of PromQL queries for pipeline status. The
Grafana dashboard (10.3), the alert rules (10.4), `make status` (10.5) and the
Phase 14 agents all read it. The decision is in
[ADR 0021](../../docs/adr/0021-pipeline-status-and-alerting.md), amendments of
2026-11-12 and 2026-11-20. The plan is
[2026-11-20-pipeline-status-exporter.md](../../docs/plans/2026-11-20-pipeline-status-exporter.md).

The file is JSON, so the Lambda, the console, the publisher and the Python 3.9
Grafana host read it with the standard library. JSON has no comments, so this
file explains the rules. A `"` inside PromQL is escaped (`{step=\"RunDbt\"}`).

## Format

```json
{"version": 1,
 "metrics": [{"name": "...", "labels": [], "scope": "latest", "meaning": "..."}],
 "queries": [{"name": "...", "expr": "...", "meaning": "..."}]}
```

- `metrics` is the catalogue of every series the publisher writes. Each has a
  `name`, its `labels`, a `scope` (`latest`, `detail` or `execution`) and a
  one-line `meaning`.
- `queries` are the named entries: a `name`, the PromQL `expr` and a one-line
  `meaning`.

## Lint rules (CI)

`console/cerberus_console/queries.py` (`lint`) checks the file. The tests are in
`console/tests/test_queries.py`.

- `version` is 1. Metric names start with `cerberus_` and are unique. Each
  `scope` is `latest`, `detail` or `execution`.
- Query names match `^[a-z][a-z0-9_]{2,63}$` and are unique.
- `meaning` is one line of 120 characters or less.
- No `$` and no `{{` in `expr` or `meaning`. There is no templating, because
  ADR 0025's tool takes names only.
- Every `cerberus_*` name in an `expr` is in `metrics`.
- Every catalogue selector sits directly inside `last_over_time(<selector>[30d])`.
  The one exception is `avg_over_time` or `count_over_time` with `[90d]`, kept
  for the 10.4 error budget. A bare selector, another window, another function
  or a subquery (`[30d:1m]`) fails. A catalogue name used as a label name, for
  example in `by (...)` or `without (...)`, is reported by this check as a
  false fail. Use a label name there, not a metric name.
- No `__name__` matcher and no `#` comment in an `expr` (PromQL comments are
  not allowed in a status query).
- An `expr` with a top-level operator (`==`, `+`, `and` and so on, outside
  parentheses) must be wrapped in parentheses. Example: `latest_failed_step` is
  `(last_over_time(cerberus_run_step_failed[30d]) == 1)`. The plan (section
  5.3) and the ADR amendment show it without parentheses. The wrapping is
  added so `2 * <entry>` means `2 * (X == 1)`, not `(2 * X) == 1`.

## How panels and rules use entries

Whitespace outside double-quoted strings does not count. `normalise` strips it
before any comparison.

- **Panels.** In every dashboard JSON under `observability/grafana/dashboards/`,
  each target `expr` that names a catalogue metric must equal an entry. This
  includes panels nested in rows. A panel needs no tag: an untagged panel is
  checked too. Copy the `expr` from the entry. Do not edit it in the panel.
  Templating variables and every other query field (`query`, `definition` and
  so on) may not read a status metric: only a panel target `expr` equal to an
  entry may. Only `title`, `description` and `content` may name one. A
  `__name__` matcher is rejected in a dashboard if it could select a catalogue
  metric; other dashboards (for example `spark-on-eks.json`) use it for
  non-status series, so it stays allowed when it provably misses the catalogue.
- **Rules.** An alert `expr` may wrap entries in more PromQL (`<entry> == 0`,
  or a join of two entries). It may not use a `__name__` matcher or a `#`
  comment. It must contain each entry verbatim. The check
  (`check_rule_expr`) removes every entry it finds and fails if a catalogue
  metric is left. 10.4 calls it on its rule files.

## How to add an entry

1. If the query reads a new series, add it to `metrics` first, with its labels
   and scope. The publisher's names must equal this catalogue (checked in PR B).
2. Add the entry to `queries`: a new unique `name`, the `expr` and a one-line
   `meaning`. Put each selector inside `last_over_time(<selector>[30d])`.
3. Run `cd console && uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest -q tests/test_queries.py`.
4. Use the entry by copying its `expr` into the panel, or by pasting it
   verbatim into the rule.
