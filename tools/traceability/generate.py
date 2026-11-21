"""Platform-development traceability generator (ADR 0029, step 16.2).

Builds two files from git, Phases.md, the ADRs, the plans and the run records:

    observability/showcase/history.json   (the data, schema_version 1)
    docs/traceability.md                  (the human table)

and checks that they are current and that no link dangles. Standard library
only. No AWS, no network, no GitHub API: the PR number and title come from the
GitHub merge commits ("Merge pull request #N from ...", title in the body).

    python tools/traceability/generate.py [--check] [--write-baseline]

Design note on staleness (see README.md): only PRs that Phases.md references
by number are written to the outputs; a number with no merge yet is "pending".
A PR that merges later, and that no
note mentions yet, changes nothing, so a merge never makes the committed
files stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORY = "observability/showcase/history.json"
BASELINE = "observability/showcase/traceability-baseline.json"
TABLE = "docs/traceability.md"
ADR_0029 = "docs/adr/0029-platform-traceability.md"
LEGACY_TEXT = "none (before traceability)"
# SHA-256 of the committed baseline file. A later edit to the baseline then shows
# up as a change to this constant in review. Update it only with a reason.
BASELINE_SHA256 = "0b3e0054c4e3f313a9c29be218e9f57fe22ea5936044e3a6ec90302bece2f4c4"
TITLE_MAX = 140

# Redaction gate (the ADR 0027 idea, self-contained): a title with any of these
# is not published; the item shows as "PR #N" only.
_REDACT = re.compile(r"arn:|s3://|amazonaws\.com|cloudfront\.net|@|\d{12}", re.IGNORECASE)

_PHASE_RE = re.compile(r"^## Phase (\d+) — (.+?)\s*(✅|🔨|⬜)?\s*$")
_SUBTASK_RE = re.compile(r"^- \[( |x)\] (\d+\.\d+[a-z]?) (.*)$")
_PR_RE = re.compile(r"(?<![\w/&])#(\d{1,5})\b")
_ADR_LIST_RE = re.compile(r"\bADRs? ((?:\d{4}(?:\s*(?:,|and|/|&)\s*)?)+)")
_ADR_PATH_RE = re.compile(r"docs/adr/(\d{4})-")
_PLAN_RE = re.compile(r"docs/plans/[\w.-]+\.md")
_PLAN_REL_RE = re.compile(r"\.\./plans/([\w.-]+\.md)")
_THE_PLAN_RE = re.compile(r"\[the\s+plan\]\(\.\./plans/([\w.-]+\.md)\)", re.IGNORECASE)
_MERGE_SUBJECT_RE = re.compile(r"^Merge pull request #(\d+) from ")
# A line that starts a note, not the subtask title: a bullet, "ADR 0023 Accepted",
# "Done ...", "Progress: ...", "Plan ...", a leading date, or "(#".
_NOTE_START_RE = re.compile(
    r"^(?:- |\(#|\d{4}-\d{2}-\d{2}|[A-Z][\w-]*(?: \d+)? (?:Accepted|Done|Progress|Plan)\b"
    r"|[A-Z][\w-]*(?: \d+)? \d{4}-\d{2}-\d{2})"
)
_SENTENCE_END_RE = re.compile(r"\.(?:\s|$)")
_STATUS_WORDS = ("Accepted", "Proposed", "Superseded", "Rejected", "Deprecated")
_PHASE_STATUS = {"✅": "complete", "🔨": "in progress", "⬜": "planned"}


def safe_title(title: str, fallback: str, dropped: list[str]) -> str:
    """Return the title, or the fallback (and record the drop) if it fails the gate."""
    title = " ".join(title.split())
    if not title or _REDACT.search(title):
        dropped.append(fallback)
        return fallback
    return title


def _utc(stamp: str) -> str:
    """An ISO-8601 commit timestamp (%cI) as UTC, `YYYY-MM-DDTHH:MM:SSZ`."""
    return datetime.fromisoformat(stamp).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_merge_log(log: str) -> dict[int, dict]:
    """Parse `git log --merges --format='%H%x1f%cI%x1f%s%x1f%b%x1e'` output.

    Only GitHub PR merges are kept. Only number, title, date and the short
    merge hash leave this function: never the owner or the branch name.
    """
    prs: dict[int, dict] = {}
    for record in log.split("\x1e"):
        fields = record.strip("\n").split("\x1f")
        if len(fields) < 4:
            continue
        sha, stamp, subject, body = fields[0].strip(), fields[1], fields[2], fields[3]
        match = _MERGE_SUBJECT_RE.match(subject)
        if not match:
            continue
        number = int(match.group(1))
        title = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        # The log is newest first; keep the newest record of a number.
        when = _utc(stamp)
        prs.setdefault(
            number,
            {"number": number, "title": title, "date": when[:10], "ts": when, "merge": sha[:7]},
        )
    return prs


def parse_phases(text: str) -> tuple[list[dict], list[dict]]:
    """Return (phases, subtasks) from Phases.md. A subtask owns its indented notes."""
    phases: list[dict] = []
    subtasks: list[dict] = []
    current: dict | None = None
    phase_no = None
    for line in text.splitlines():
        m = _PHASE_RE.match(line)
        if m:
            current = None
            phase_no = int(m.group(1))
            title = re.sub(r"\s*🎯\s*", " ", m.group(2)).strip()
            status = _PHASE_STATUS.get(m.group(3), "planned")
            phases.append({"number": phase_no, "title": title, "status": status})
            continue
        if line.startswith("## "):
            current = None
            phase_no = None
            continue
        m = _SUBTASK_RE.match(line)
        if m and phase_no is not None:
            current = {
                "id": m.group(2),
                "phase": phase_no,
                "checked": m.group(1) == "x",
                "title": m.group(3).strip(),
                "text": m.group(3).strip(),
                "title_open": True,
            }
            subtasks.append(current)
            continue
        if current is not None and line.startswith(" ") and line.strip():
            piece = line.strip()
            if current["title_open"]:
                if _SENTENCE_END_RE.search(current["title"]) or _NOTE_START_RE.match(piece):
                    current["title_open"] = False
                else:
                    current["title"] += " " + piece
            current["text"] += " " + piece
        elif current is not None and not line.startswith(" "):
            current = None
    for st in subtasks:
        st["title"] = _short_title(st["title"])
        del st["title_open"]
    return phases, subtasks


def _short_title(title: str) -> str:
    """Cut at the first sentence end, then cap at TITLE_MAX at a word boundary."""
    m = _SENTENCE_END_RE.search(title)
    if m:
        title = title[: m.start() + 1]
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return title


def extract_refs(text: str, run_names: list[str]) -> dict:
    """Pull PR numbers, ADR numbers, plan paths and run names out of one subtask's text."""
    adrs: set[str] = set(_ADR_PATH_RE.findall(text))
    for group in _ADR_LIST_RE.findall(text):
        adrs.update(re.findall(r"\d{4}", group))
    return {
        "pr": sorted({int(n) for n in _PR_RE.findall(text)}),
        "adr": sorted(adrs),
        "plan": sorted(set(_PLAN_RE.findall(text))),
        "runs": sorted(r for r in run_names if r in text),
    }


def _plan_links(text: str) -> list[str]:
    """Plan paths (`docs/plans/x.md`) linked in the text, in document order."""
    found = [(m.start(), m.group(0)) for m in _PLAN_RE.finditer(text)]
    found += [(m.start(), f"docs/plans/{m.group(1)}") for m in _PLAN_REL_RE.finditer(text)]
    return [path for _, path in sorted(found)]


def _ordered_plans(text: str) -> list[str]:
    """The ADR's plan links by priority.

    1. the target of a link whose text is "the plan";
    2. the plan links inside the `## Status` section;
    3. every plan link in document order.
    The first existing one is the ADR's plan (plan_for_adr).
    """
    ordered = [f"docs/plans/{p}" for p in _THE_PLAN_RE.findall(text)]
    status = re.search(r"^## Status\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if status:
        ordered += _plan_links(status.group(1))
    ordered += _plan_links(text)
    return list(dict.fromkeys(ordered))


def parse_adr(path: Path) -> dict:
    """Number, title, status and accepted date from one ADR file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = re.sub(r"^#\s*\d+\.\s*", "", lines[0]).strip() if lines else path.name
    status_line = ""
    for i, line in enumerate(lines):
        if line.strip() == "## Status":
            status_line = next((ln for ln in lines[i + 1 :] if ln.strip()), "")
            break
    status = next((w for w in _STATUS_WORDS if status_line.startswith(w)), "Unknown")
    date = re.match(r"Accepted \((\d{4}-\d{2}-\d{2})\)", status_line)
    return {
        "number": path.name[:4],
        "file": path.name,
        "title": title,
        "status": status,
        "accepted": date.group(1) if date else None,
        "own_plans": _ordered_plans(text),
    }


def plan_for_adr(adr: dict, plan_texts: dict[str, str]) -> str | None:
    """Only the ADR's own plan link counts. A plan that merely mentions the ADR does not."""
    own = [p for p in adr["own_plans"] if p in plan_texts]
    return own[0] if own else None


def build(
    phases_text: str,
    adr_files: dict[str, Path],
    plan_texts: dict[str, str],
    run_names: list[str],
    merge_log: str,
    baseline: dict,
    pending_hint: frozenset[int] = frozenset(),
) -> dict:
    """Pure core.

    A PR number that Phases.md names but that has no merge commit is pending:
    written as {"number": N, "pending": true}, never an error. `pending_hint`
    holds numbers that the committed history.json still has as pending; they stay
    pending even if merged now, so a later merge never makes the files stale.
    Returns {"history": dict, "errors": [str], "notes": [str], "stats": dict}.
    """
    merges = parse_merge_log(merge_log)
    phases, raw_subtasks = parse_phases(phases_text)
    dropped: list[str] = []
    errors: list[str] = []
    notes: list[str] = []  # report only, never fail
    base_checked = set(baseline.get("checked_subtasks", []))
    base_adrs = set(baseline.get("accepted_adrs", []))

    adrs_parsed = {n: parse_adr(p) for n, p in sorted(adr_files.items())}
    used_prs: dict[int, dict] = {}
    pending: set[int] = set()
    subtasks = []
    for st in raw_subtasks:
        refs = extract_refs(st["text"], run_names)
        legacy = st["checked"] and st["id"] in base_checked
        strict = st["checked"] and not legacy
        pr_numbers = []
        for number in refs["pr"]:
            merge = None if number in pending_hint else merges.get(number)
            if merge is None:
                pending.add(number)
            else:
                used_prs[number] = merge
            pr_numbers.append(number)
        adr_links = []
        for n in refs["adr"]:
            if n in adrs_parsed:
                adr_links.append(n)
            elif strict:
                errors.append(f"subtask {st['id']}: ADR {n} has no file in docs/adr")
        plan_links = []
        for p in refs["plan"]:
            if p in plan_texts:
                plan_links.append(p)
            elif strict:
                errors.append(f"subtask {st['id']}: plan {p} does not exist")
        if strict and not refs["pr"]:
            errors.append(f"subtask {st['id']}: checked after the baseline with no PR reference")
        subtasks.append(
            {
                "id": st["id"],
                "phase": st["phase"],
                "title": safe_title(st["title"], f"Subtask {st['id']}", dropped),
                "checked": st["checked"],
                "links": {
                    "adr": adr_links,
                    "plan": plan_links,
                    "pr": pr_numbers,
                    "runs": refs["runs"],
                },
                "legacy": legacy,
            }
        )

    pr_rows = {}
    for number, m in sorted(used_prs.items()):
        title = safe_title(m["title"], f"PR #{number}", dropped)
        pr_rows[number] = {"number": number, "title": title, "date": m["date"], "merge": m["merge"]}
    for st in subtasks:
        st["links"]["pr"] = [
            pr_rows[n] if n in pr_rows else {"number": n, "pending": True}
            for n in st["links"]["pr"]
        ]
    highest = max(merges, default=0)
    behind = sorted(n for n in pending if n < highest)
    if behind:
        listed = ", ".join(f"#{n}" for n in behind)
        notes.append(f"pending PRs below the newest merged PR (#{highest}): {listed}")

    adr_rows = []
    for n, a in adrs_parsed.items():
        plan = plan_for_adr(a, plan_texts)
        legacy = a["status"] == "Accepted" and n in base_adrs
        if a["status"] == "Accepted" and not legacy and plan is None:
            errors.append(f"ADR {n}: accepted after the baseline with no plan link")
        adr_rows.append(
            {
                "number": n,
                "file": a["file"],
                "title": safe_title(a["title"], f"ADR {n}", dropped),
                "status": a["status"],
                "accepted": a["accepted"],
                "plan": plan,
                "legacy": legacy,
            }
        )

    referenced = " ".join(st["text"] for st in raw_subtasks)
    unreferenced = [r for r in run_names if r not in referenced]
    if unreferenced:
        notes.append(
            f"{len(unreferenced)} of {len(run_names)} run records are not named in Phases.md"
        )

    history = {
        "schema_version": 1,
        "generated_at": max((used_prs[n]["ts"] for n in pr_rows), default=None),
        "phases": phases,
        "subtasks": subtasks,
        "adrs": adr_rows,
        "prs": list(pr_rows.values()),
    }
    stats = {
        "phases": len(phases),
        "subtasks": len(subtasks),
        "checked": sum(1 for s in subtasks if s["checked"]),
        "legacy": sum(1 for s in subtasks if s["legacy"]),
        "adrs": len(adr_rows),
        "prs": len(pr_rows),
        "pending": len(pending),
        "dropped_titles": len(dropped),
    }
    return {"history": history, "errors": errors, "notes": notes, "stats": stats}


def render_history(history: dict) -> str:
    return json.dumps(history, indent=2, ensure_ascii=False) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_table(history: dict, cutoff: str) -> str:
    adrs = {a["number"]: a for a in history["adrs"]}
    phase_titles = {p["number"]: p["title"] for p in history["phases"]}

    def col(values: list[str], legacy: bool) -> str:
        if values:
            return "<br>".join(values)
        return LEGACY_TEXT if legacy else "-"

    out = [
        "# Platform-development traceability",
        "",
        "_Generated by `tools/traceability/generate.py` (ADR 0029). Do not edit by hand:",
        "run `make traceability`. The same data, as JSON, is in",
        "`observability/showcase/history.json`._",
        "",
        "This page shows, for each step of the build, the decision, the plan, the pull",
        "request and the run record behind it, so a reader can follow how the platform was made.",
        "",
        "Each row is one subtask of [Phases.md](../Phases.md), with the ADR, plan, PR and",
        "run record that the notes of that subtask name. `#N (pending)` is a PR that is named",
        "but not merged yet; `make traceability` fills in its title and date after the merge.",
        "",
        f"**Legend.** Done: `x` checked, blank not yet. A link marked `{LEGACY_TEXT}` means the",
        "subtask was checked before this record began and its notes name no such link.",
        "`-` means none is named.",
        "",
        "**Cut-off.** The CI check for dangling links applies only to subtasks checked, and",
        f"ADRs accepted, on or after {cutoff} (the date ADR 0029 was accepted). Items already",
        "done then are listed in `observability/showcase/traceability-baseline.json` and",
        "never fail the check. Only PRs named in Phases.md appear here.",
        "",
    ]
    last_phase = None
    for st in history["subtasks"]:
        if st["phase"] != last_phase:
            last_phase = st["phase"]
            out += [
                f"## Phase {last_phase} — {_cell(phase_titles.get(last_phase, ''))}",
                "",
                "| Subtask | Done | ADR | Plan | PR | Runs |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        legacy = st["legacy"]
        adr_cells = [
            f"[{n}](adr/{adrs[n]['file']}) {_cell(adrs[n]['title'])}" for n in st["links"]["adr"]
        ]
        plan_cells = [f"[{Path(p).name}](plans/{Path(p).name})" for p in st["links"]["plan"]]
        pr_cells = [
            f"#{p['number']} (pending)"
            if p.get("pending")
            else f"#{p['number']} {_cell(p['title'])} ({p['date']})"
            for p in st["links"]["pr"]
        ]
        out.append(
            "| {id} {title} | {done} | {adr} | {plan} | {pr} | {runs} |".format(
                id=st["id"],
                title=_cell(st["title"]),
                done="x" if st["checked"] else "",
                adr=col(adr_cells, legacy),
                plan=col(plan_cells, legacy),
                pr=col(pr_cells, legacy),
                runs=col([f"`{r}`" for r in st["links"]["runs"]], legacy),
            )
        )
        if st["id"] == _last_in_phase(history, last_phase):
            out.append("")
    out += ["## ADRs", "", "| ADR | Status | Accepted | Plan |", "| --- | --- | --- | --- |"]
    for a in history["adrs"]:
        if a["plan"]:
            plan = f"[{Path(a['plan']).name}](plans/{Path(a['plan']).name})"
        else:
            plan = LEGACY_TEXT if a["legacy"] else "-"
        link = f"[{a['number']}](adr/{a['file']}) {_cell(a['title'])}"
        out.append(f"| {link} | {a['status']} | {a['accepted'] or '-'} | {plan} |")
    return "\n".join(out) + "\n"


def _last_in_phase(history: dict, phase: int) -> str:
    return [s["id"] for s in history["subtasks"] if s["phase"] == phase][-1]


def git_merge_log(root: Path) -> str:
    return subprocess.run(
        ["git", "log", "--merges", "--format=%H%x1f%cI%x1f%s%x1f%b%x1e"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def cutoff_date(root: Path) -> str:
    text = (root / ADR_0029).read_text(encoding="utf-8")
    m = re.search(r"^Accepted \((\d{4}-\d{2}-\d{2})\)", text, re.MULTILINE)
    if not m:
        raise SystemExit(f"cannot read the acceptance date from {ADR_0029}")
    return m.group(1)


def committed_pending(root: Path) -> frozenset[int]:
    """PR numbers that the committed history.json still has as pending."""
    path = root / HISTORY
    if not path.exists():
        return frozenset()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return frozenset(
            p["number"] for st in data["subtasks"] for p in st["links"]["pr"] if p.get("pending")
        )
    except (ValueError, KeyError, TypeError):
        return frozenset()


def load(
    root: Path, merge_log: str, baseline: dict, pending_hint: frozenset[int] = frozenset()
) -> dict:
    adr_dir = root / "docs/adr"
    adr_files = {p.name[:4]: p for p in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))}
    plan_texts = {
        f"docs/plans/{p.name}": p.read_text(encoding="utf-8")
        for p in sorted((root / "docs/plans").glob("*.md"))
    }
    run_names = []
    for p in sorted((root / "observability/scale/runs").glob("*.json")):
        run_names.append(json.loads(p.read_text(encoding="utf-8")).get("execution") or p.stem)
    phases_text = (root / "Phases.md").read_text(encoding="utf-8")
    result = build(phases_text, adr_files, plan_texts, run_names, merge_log, baseline, pending_hint)
    result["cutoff"] = cutoff_date(root)
    return result


def baseline_from(result: dict) -> dict:
    h = result["history"]
    return {
        "schema_version": 1,
        "cutoff": result["cutoff"],
        "note": "Subtasks checked and ADRs accepted at the cut-off. Newer ones need links.",
        "checked_subtasks": sorted(s["id"] for s in h["subtasks"] if s["checked"]),
        "accepted_adrs": sorted(a["number"] for a in h["adrs"] if a["status"] == "Accepted"),
    }


def main(
    argv: list[str] | None = None,
    root: Path = ROOT,
    merge_log: str | None = None,
    baseline_sha256: str | None = BASELINE_SHA256,
) -> int:
    """`baseline_sha256=None` skips the pin (synthetic repos in tests only)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail on stale outputs or dangling links")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="write the baseline once; refuses to overwrite",
    )
    args = ap.parse_args(argv)
    log = git_merge_log(root) if merge_log is None else merge_log

    if args.write_baseline:
        if (root / BASELINE).exists():
            print(f"refusing: {BASELINE} exists; the baseline is written once", file=sys.stderr)
            return 1
        base = baseline_from(load(root, log, {}))
        (root / BASELINE).parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(base, indent=2) + "\n"
        (root / BASELINE).write_text(data, encoding="utf-8")
        print(
            f"wrote {BASELINE}: {len(base['checked_subtasks'])} subtasks, "
            f"{len(base['accepted_adrs'])} ADRs; sha256 {hashlib.sha256(data.encode()).hexdigest()}"
        )
        return 0

    base_path = root / BASELINE
    if not base_path.exists():
        print(f"missing {BASELINE}: run with --write-baseline once", file=sys.stderr)
        return 1
    raw = base_path.read_bytes()
    if baseline_sha256 is not None and hashlib.sha256(raw).hexdigest() != baseline_sha256:
        print(
            f"FAIL: {BASELINE} does not match BASELINE_SHA256 in generate.py; "
            "the baseline must not change",
            file=sys.stderr,
        )
        return 1
    baseline = json.loads(raw)
    if baseline.get("cutoff") != cutoff_date(root):
        print(f"FAIL: {BASELINE} cutoff differs from the ADR 0029 acceptance date", file=sys.stderr)
        return 1
    # --check keeps the PRs that the committed file has as pending still pending, so a
    # merge after the file was written never makes it stale. A plain run refreshes them.
    hint = committed_pending(root) if args.check else frozenset()
    result = load(root, log, baseline, hint)
    outputs = (
        (HISTORY, render_history(result["history"])),
        (TABLE, render_table(result["history"], result["cutoff"])),
    )
    s = result["stats"]
    print(
        f"subtasks {s['subtasks']} ({s['checked']} checked, {s['legacy']} before traceability), "
        f"ADRs {s['adrs']}, PRs {s['prs']} merged + {s['pending']} pending, phases {s['phases']}, "
        f"titles dropped {s['dropped_titles']}"
    )
    for note in result["notes"]:
        print(f"note: {note}")

    problems = list(result["errors"])
    if args.check:
        for rel, text in outputs:
            p = root / rel
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                problems.append(f"{rel} is stale: run `make traceability` and commit it")
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1 if problems else 0

    for rel, text in outputs:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
        print(f"wrote {rel}")
    for problem in problems:
        print(f"WARN: {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
