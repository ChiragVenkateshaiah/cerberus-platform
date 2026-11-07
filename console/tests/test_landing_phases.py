"""Phases.md parsing: the real file parses, and a changed format fails loudly."""

import tomllib

import pytest
from landing_helpers import PHASES_MD

from cerberus_landing import phases
from cerberus_landing.build import PKG

GOOD = """# Phases

## Cross-cutting (not phases)

- **IaC** is not a subtask.

## Phase 0 — Foundation ✅

- [x] 0.1 One
- [x] 0.2 Two

## Phase 1 — MVP: lakehouse 🎯 ✅

- [x] 1.1 One

## Phase 2 — Doing 🔨

- [x] 2.1 One
      a continuation line
- [ ] 2.2 Two

## Phase 3 — Later & more ⬜

- [ ] 3.1 One
"""


def test_synthetic_file_parses_with_counts():
    got = phases.parse(GOOD)
    assert [p.number for p in got] == [0, 1, 2, 3]
    assert [p.title for p in got] == ["Foundation", "MVP: lakehouse", "Doing", "Later & more"]
    assert [p.status for p in got] == ["complete", "complete", "in progress", "planned"]
    assert got[2].done == ["2.1"] and got[2].open == ["2.2"] and got[2].total == 2


def test_real_phases_md_parses_to_phases_0_to_13():
    got = phases.parse(PHASES_MD.read_text(encoding="utf-8"))
    assert [p.number for p in got] == list(range(14))
    for p in got:
        assert p.status in phases.STATUS.values()
        assert p.total > 0
        if p.status == "complete":
            assert p.open == [], p.number


def test_content_has_exactly_one_sentence_per_phase():
    got = phases.parse(PHASES_MD.read_text(encoding="utf-8"))
    content = tomllib.loads((PKG / "content.toml").read_text(encoding="utf-8"))["phases"]
    assert sorted(content) == sorted(f"p{p.number}" for p in got)
    for key, sentence in content.items():
        assert sentence.endswith("."), key
        assert sentence.count(". ") == 0 and sentence.count(".") == 1, key


BAD = {
    "unreadable heading": "## Phase 0 -- Foundation ✅\n- [x] 0.1 a\n",
    "no status": "## Phase 0 — Foundation\n- [x] 0.1 a\n",
    "unknown status": "## Phase 0 — Foundation ❌\n- [x] 0.1 a\n",
    "out of order": "## Phase 1 — Foundation ✅\n- [x] 1.1 a\n",
    "skipped phase": "## Phase 0 — A ✅\n- [x] 0.1 a\n## Phase 2 — B ⬜\n- [ ] 2.1 a\n",
    "stray item": "- [x] 0.1 a\n",
    "item in wrong phase": "## Phase 0 — A ✅\n- [x] 1.1 a\n",
    "unreadable item": "## Phase 0 — A ⬜\n- [x]0.1 a\n",
    "bad checkbox": "## Phase 0 — A ⬜\n- [?] 0.1 a\n",
    "complete with open item": "## Phase 0 — A ✅\n- [x] 0.1 a\n- [ ] 0.2 b\n",
    "phase without items": "## Phase 0 — A ✅\n\n## Phase 1 — B ⬜\n- [ ] 1.1 a\n",
    "indented subtask": "## Phase 0 — A ⬜\n  - [ ] 0.1 a\n",
    "empty file": "# Phases\n",
}


@pytest.mark.parametrize("name", BAD)
def test_bad_input_raises(name):
    with pytest.raises(phases.PhasesError):
        phases.parse(BAD[name])
