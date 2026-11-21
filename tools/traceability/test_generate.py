"""Tests for the traceability generator. Stdlib and pytest only; the git log is injected."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate as g  # noqa: E402

REAL_ROOT = Path(__file__).resolve().parents[2]
SEP, REC = "\x1f", "\x1e"


def merge(sha, stamp, subject, body=""):
    return f"{sha}{SEP}{stamp}{SEP}{subject}{SEP}{body}\n{REC}\n"


LOG = (
    # 23:30 at -05:00 is 04:30 UTC on the next day.
    merge(
        "a" * 40,
        "2026-11-21T23:30:00-05:00",
        "Merge pull request #5 from someone/secret-branch",
        "Add the thing\n",
    )
    + merge("b" * 40, "2026-11-21T10:00:00+00:00", "Merge remote-tracking branch 'o/main' into x")
    + merge(
        "c" * 40, "2026-11-20T09:00:00+00:00", "Merge pull request #4 from someone/other", "Older\n"
    )
    + merge(
        "d" * 40,
        "2026-11-19T09:00:00+00:00",
        "Merge pull request #3 from someone/leaky",
        "Key arn:aws:iam::1\n",
    )
    + merge(
        "e" * 40,
        "2026-11-18T09:00:00+00:00",
        "Merge pull request #2 from someone/mail",
        "Fix for bob@example.com\n",
    )
    + merge(
        "f" * 40,
        "2026-11-17T09:00:00+00:00",
        "Merge pull request #1 from someone/digits",
        "Acct 123456789012 note\n",
    )
)

PHASES = """# Phases

## Phase 1 — First ✅

- [x] 1.1 Old thing
- [x] 1.2 Old thing with notes
      ADR 0001 and docs/plans/2026-01-01-old.md, merged in #1
- [ ] 1.3 Not done yet, ADR 0099 is future

## Phase 2 — Second 🔨

- [x] 2.1 New thing linked
      Built in #5 (ADR 0002), docs/plans/2026-01-01-old.md; run `exercise-1`
- [x] 2.2 New thing with no PR
- [x] 2.3 New thing, PR still open
      #99
- [x] 2.4 New thing, ADR and plan missing
      #4 ADR 0050 docs/plans/nope.md
"""

# The same file with every failure fixed.
GOOD = PHASES.replace("2.2 New thing with no PR", "2.2 New thing with no PR #4").replace(
    "#4 ADR 0050 docs/plans/nope.md", "#4 ADR 0002"
)

BASELINE = {
    "cutoff": "2026-11-20",
    "checked_subtasks": ["1.1", "1.2"],
    "accepted_adrs": ["0001", "0029"],
}


def make_repo(tmp_path, phases=PHASES, adr2_status="Accepted (2026-11-21)", plan_links_adr2=True):
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "observability/scale/runs").mkdir(parents=True)
    (tmp_path / "observability/showcase").mkdir(parents=True)
    (tmp_path / "Phases.md").write_text(phases, encoding="utf-8")
    (tmp_path / "docs/adr/0001-first.md").write_text(
        "# 1. First\n\nDate: 2026-01-01\n\n## Status\n\nAccepted\n", encoding="utf-8"
    )
    own = "[the plan](../plans/2026-01-01-old.md)" if plan_links_adr2 else ""
    (tmp_path / "docs/adr/0002-second.md").write_text(
        f"# 2. Second\n\n## Status\n\n{adr2_status}\n{own}\n", encoding="utf-8"
    )
    (tmp_path / "docs/adr/0029-platform-traceability.md").write_text(
        "# 29. T\n\n## Status\n\nAccepted (2026-11-20). x\n", encoding="utf-8"
    )
    # The plan only mentions ADR 0002; the ADR links the plan itself or does not.
    text = "see docs/adr/0002-second.md and ADR 0002"
    (tmp_path / "docs/plans/2026-01-01-old.md").write_text(f"# plan\n{text}\n", encoding="utf-8")
    (tmp_path / "observability/scale/runs/exercise-1.json").write_text(
        json.dumps({"execution": "exercise-1"}), encoding="utf-8"
    )
    (tmp_path / g.BASELINE).write_text(json.dumps(BASELINE), encoding="utf-8")
    return tmp_path


def run(root, *args, log=LOG, sha=None):
    return g.main(list(args), root=root, merge_log=log, baseline_sha256=sha)


def result(root, hint=frozenset()):
    base = json.loads((root / g.BASELINE).read_text(encoding="utf-8"))
    return g.load(root, LOG, base, hint)


def test_merge_log_keeps_number_title_date_only():
    prs = g.parse_merge_log(LOG)
    assert sorted(prs) == [1, 2, 3, 4, 5]
    assert prs[5] == {
        "number": 5,
        "title": "Add the thing",
        "date": "2026-11-22",
        "ts": "2026-11-22T04:30:00Z",
        "merge": "aaaaaaa",
    }
    assert "secret-branch" not in json.dumps(prs) and "someone" not in json.dumps(prs)


def test_pr_checkout_merge_subject_is_ignored():
    subject = f"Merge {'1' * 40} into {'2' * 40}"
    assert g.parse_merge_log(merge("c" * 40, "2026-11-21T10:00:00+00:00", subject)) == {}


def test_phases_and_subtasks_parse():
    phases, subs = g.parse_phases(PHASES)
    assert [(p["number"], p["status"]) for p in phases] == [(1, "complete"), (2, "in progress")]
    assert [s["id"] for s in subs] == ["1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "2.4"]
    assert [s["checked"] for s in subs][:3] == [True, True, False]
    refs = g.extract_refs(subs[3]["text"], ["exercise-1", "exercise-2"])
    assert refs == {
        "pr": [5],
        "adr": ["0002"],
        "plan": ["docs/plans/2026-01-01-old.md"],
        "runs": ["exercise-1"],
    }
    assert g.extract_refs("ADRs 0021 and 0022, plan.md#phase-10", [])["adr"] == ["0021", "0022"]
    assert g.extract_refs("see plan.md#phase-10", [])["pr"] == []


def test_title_joins_wrapped_lines_and_stops_at_notes():
    text = (
        "## Phase 3 — X\n\n"
        "- [x] 3.1 A long title that wraps onto\n"
        "      a second line, then ends here. More text\n"
        "- [x] 3.2 Well-Architected pass + ADR\n"
        "      ADR 0023 Accepted 2026-10-27\n"
        "- [x] 3.3 Done thing\n"
        "      2026-11-01 built (#12)\n"
        "- [ ] 3.4 " + "word " * 60 + "\n"
    )
    _, subs = g.parse_phases(text)
    assert subs[0]["title"] == "A long title that wraps onto a second line, then ends here."
    assert subs[1]["title"] == "Well-Architected pass + ADR"
    assert subs[2]["title"] == "Done thing"
    assert len(subs[3]["title"]) <= g.TITLE_MAX and subs[3]["title"].endswith("word…")
    # The notes still count for link extraction.
    assert "#12" in subs[2]["text"]


def test_baseline_old_items_never_fail_new_ones_do(tmp_path):
    root = make_repo(tmp_path)
    errors = result(root)["errors"]
    assert not [e for e in errors if "1.1" in e or "1.2" in e]
    assert "subtask 2.2: checked after the baseline with no PR reference" in errors
    assert "subtask 2.4: ADR 0050 has no file in docs/adr" in errors
    assert "subtask 2.4: plan docs/plans/nope.md does not exist" in errors
    assert not [e for e in errors if "2.1" in e or "2.3" in e]
    legacy = {s["id"]: s["legacy"] for s in result(root)["history"]["subtasks"]}
    assert legacy["1.1"] and legacy["1.2"] and not legacy["2.1"] and not legacy["1.3"]


def test_legacy_dangling_reference_does_not_fail(tmp_path):
    phases = PHASES.replace("merged in #1", "merged in #777 ADR 0088 docs/plans/gone.md")
    root = make_repo(tmp_path, phases=phases)
    assert not [e for e in result(root)["errors"] if "1.2" in e]


def test_unchecked_subtask_never_fails(tmp_path):
    root = make_repo(tmp_path)
    assert not [e for e in result(root)["errors"] if "1.3" in e]


def test_adr_accepted_after_baseline_needs_its_own_plan_link(tmp_path):
    linked = make_repo(tmp_path / "a")
    assert not [e for e in result(linked)["errors"] if e.startswith("ADR")]
    # A plan that only mentions the ADR does not count.
    mention = make_repo(tmp_path / "b", plan_links_adr2=False)
    assert "ADR 0002: accepted after the baseline with no plan link" in result(mention)["errors"]
    adrs = {a["number"]: a for a in result(mention)["history"]["adrs"]}
    assert adrs["0002"]["plan"] is None
    proposed = make_repo(tmp_path / "c", adr2_status="Proposed", plan_links_adr2=False)
    assert not [e for e in result(proposed)["errors"] if e.startswith("ADR")]


def test_redaction_gate_shows_pr_number_only():
    bad_parts = ("arn:aws:s3", "s3://bucket/x", "x.amazonaws.com", "d1.cloudfront.net", "a@b.c")
    for bad in (*bad_parts, "123456789012"):
        dropped = []
        assert g.safe_title(f"title {bad}", "PR #9", dropped) == "PR #9"
        assert dropped == ["PR #9"]
    assert g.safe_title("12345678901 is eleven", "PR #9", []) != "PR #9"


def test_redacted_titles_in_history(tmp_path):
    phases = PHASES + "- [ ] 2.5 Future\n      #1 #2 #3\n"
    root = make_repo(tmp_path, phases=phases)
    res = result(root)
    titles = {p["number"]: p["title"] for p in res["history"]["prs"]}
    assert titles[1] == "PR #1" and titles[2] == "PR #2" and titles[3] == "PR #3"
    assert titles[5] == "Add the thing"
    assert res["stats"]["dropped_titles"] == 3
    text = g.render_history(res["history"]) + g.render_table(res["history"], "2026-11-20")
    for secret in ("bob@example.com", "123456789012", "arn:aws", "secret-branch", "someone"):
        assert secret not in text


def test_only_referenced_merged_prs_are_written_and_generated_at_is_utc(tmp_path):
    res = result(make_repo(tmp_path))
    assert [p["number"] for p in res["history"]["prs"]] == [1, 4, 5]
    # Newest merged row, in UTC (the commit was 23:30 at -05:00).
    assert res["history"]["generated_at"] == "2026-11-22T04:30:00Z"


def test_deterministic(tmp_path):
    root = make_repo(tmp_path)
    first = result(root)["history"]
    second = result(root)["history"]
    assert g.render_history(first) == g.render_history(second)
    assert g.render_table(first, "d") == g.render_table(second, "d")


def test_check_flow_and_a_new_merge_does_not_make_it_stale(tmp_path):
    root = make_repo(tmp_path)
    # Dangling links fail the check even when the outputs are fresh.
    assert run(root) == 0
    assert run(root, "--check") == 1
    (root / "Phases.md").write_text(GOOD, encoding="utf-8")
    assert run(root) == 0
    assert run(root, "--check") == 0
    # A new PR merges and no note names it: the committed files stay current.
    newer = merge("9" * 40, "2026-11-30T09:00:00+00:00", "Merge pull request #6 from x/y", "U\n")
    assert run(root, "--check", log=newer + LOG) == 0
    # Editing Phases.md makes the table stale.
    (root / "Phases.md").write_text(GOOD + "- [ ] 2.9 Later\n", encoding="utf-8")
    assert run(root, "--check") == 1


def test_pending_pr_passes_then_merge_does_not_make_files_stale(tmp_path):
    phases = GOOD.replace("Built in #5", "Built in #50")
    root = make_repo(tmp_path, phases=phases)
    # #50 is checked but unmerged: pending, not an error.
    assert run(root) == 0
    hist = json.loads((root / g.HISTORY).read_text(encoding="utf-8"))
    row = next(s for s in hist["subtasks"] if s["id"] == "2.1")
    assert {"number": 50, "pending": True} in row["links"]["pr"]
    assert 50 not in [p["number"] for p in hist["prs"]]
    assert run(root, "--check") == 0
    # The merge commit for #50 arrives. The OLD files still pass --check.
    merged = merge(
        "7" * 40, "2026-12-01T09:00:00+00:00", "Merge pull request #50 from x/y", "Fifty\n"
    )
    assert run(root, "--check", log=merged + LOG) == 0
    # A plain run refreshes the row with its title and date.
    assert run(root, log=merged + LOG) == 0
    hist = json.loads((root / g.HISTORY).read_text(encoding="utf-8"))
    row = next(s for s in hist["subtasks"] if s["id"] == "2.1")
    pr50 = next(p for p in row["links"]["pr"] if p["number"] == 50)
    assert pr50["title"] == "Fifty" and pr50["date"] == "2026-12-01"
    assert hist["generated_at"] == "2026-12-01T09:00:00Z"
    assert run(root, "--check", log=merged + LOG) == 0


def test_pending_below_newest_merged_pr_is_a_note(tmp_path):
    root = make_repo(tmp_path, phases=GOOD)
    # #99 is above the newest merged PR (#5): no note. #4 forced pending is below it: a note.
    assert not any("pending PRs below" in n for n in result(root)["notes"])
    notes = result(root, hint=frozenset({4}))["notes"]
    assert any("pending PRs below" in n and "#4" in n for n in notes)
    assert result(root, hint=frozenset({4}))["errors"] == []


def test_stacked_open_pr_note_passes(tmp_path):
    phases = GOOD + "- [x] 2.6 Stacked\n      built in #7 (open, stacked on #5)\n"
    root = make_repo(tmp_path, phases=phases)
    assert result(root)["errors"] == []
    behind = merge("8" * 40, "2026-11-25T09:00:00+00:00", "Merge pull request #8 from x/y", "E\n")
    base = json.loads((root / g.BASELINE).read_text(encoding="utf-8"))
    res = g.load(root, behind + LOG, base)
    assert any("#7" in n for n in res["notes"])


def test_missing_baseline_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / g.BASELINE).unlink()
    assert run(root, "--check") == 1


def test_write_baseline_once_only(tmp_path):
    root = make_repo(tmp_path)
    (root / g.BASELINE).unlink()
    assert run(root, "--write-baseline") == 0
    base = json.loads((root / g.BASELINE).read_text(encoding="utf-8"))
    assert base["checked_subtasks"] == ["1.1", "1.2", "2.1", "2.2", "2.3", "2.4"]
    assert base["accepted_adrs"] == ["0001", "0002", "0029"]
    assert base["cutoff"] == "2026-11-20"
    # A second write refuses and leaves the file as it was.
    before = (root / g.BASELINE).read_bytes()
    assert run(root, "--write-baseline") == 1
    assert (root / g.BASELINE).read_bytes() == before


def test_baseline_pin_and_cutoff_guard(tmp_path):
    root = make_repo(tmp_path)
    (root / "Phases.md").write_text(GOOD, encoding="utf-8")
    assert run(root) == 0
    right = hashlib.sha256((root / g.BASELINE).read_bytes()).hexdigest()
    assert run(root, "--check", sha=right) == 0
    assert run(root, "--check", sha="0" * 64) == 1
    # A baseline whose cutoff differs from the ADR 0029 date fails.
    bad = {**BASELINE, "cutoff": "2026-01-01"}
    (root / g.BASELINE).write_text(json.dumps(bad), encoding="utf-8")
    assert run(root, "--check") == 1


def test_real_baseline_matches_the_pin():
    data = (REAL_ROOT / g.BASELINE).read_bytes()
    assert hashlib.sha256(data).hexdigest() == g.BASELINE_SHA256


@pytest.mark.skipif(not (REAL_ROOT / ".git").exists(), reason="needs a git checkout")
def test_real_repo_smoke():
    """Runs against the real tree and merge log; skips if the checkout has no PR merges."""
    try:
        log = g.git_merge_log(REAL_ROOT)
    except Exception:  # noqa: BLE001
        pytest.skip("git log not available")
    if not g.parse_merge_log(log):
        pytest.skip("no PR merges in this checkout (shallow clone)")
    base = json.loads((REAL_ROOT / g.BASELINE).read_text(encoding="utf-8"))
    res = g.load(REAL_ROOT, log, base)
    assert res["errors"] == []
    assert res["history"]["schema_version"] == 1
    assert res["stats"]["subtasks"] > 0


def _adr_plan(tmp_path, body):
    tmp_path.mkdir(parents=True)
    path = tmp_path / "0050-fake.md"
    path.write_text(body, encoding="utf-8")
    plans = {f"docs/plans/{n}.md": "" for n in ("older", "status-one", "the-one", "body-only")}
    return g.plan_for_adr(g.parse_adr(path), plans)


def test_adr_plan_priority(tmp_path):
    older = "see [old](../plans/older.md)"
    # 1. "[the plan]" in Status beats an older plan cited earlier in the Context.
    head = f"# 50. X\n\n## Context\n\n{older}\n\n## Status\n\n"
    body = head + "Accepted. [The\nplan](../plans/the-one.md)\n"
    assert _adr_plan(tmp_path / "a", body) == "docs/plans/the-one.md"
    # 2. No "[the plan]": the first plan link in Status beats one cited earlier in the body.
    body = head + "Accepted, see [x](../plans/status-one.md).\n"
    assert _adr_plan(tmp_path / "b", body) == "docs/plans/status-one.md"
    # 3. No Status link: the first plan link in document order.
    body = (
        f"# 50. X\n\n## Status\n\nAccepted.\n\n## Context\n\n[b](../plans/body-only.md) {older}\n"
    )
    assert _adr_plan(tmp_path / "c", body) == "docs/plans/body-only.md"
    # A plan that is not a file does not count.
    body = "# 50. X\n\n## Status\n\nAccepted. [the plan](../plans/missing.md)\n"
    assert _adr_plan(tmp_path / "d", body) is None
