"""Parses Phases.md into one row per phase. Fails loudly: a heading or item it
does not understand raises PhasesError, so a format change breaks the build and
the PR check instead of silently dropping a phase from the public page.

Only the phase heading, the status word and the checkbox state are used. The
subtask titles are not parsed: their continuation lines mix titles with notes.
"""

import re
from dataclasses import dataclass, field

STATUS = {"✅": "complete", "🔨": "in progress", "⬜": "planned"}
STATUS_WORD = {"complete": "Complete", "in progress": "In progress", "planned": "Planned"}

_HEADING = re.compile(r"^## Phase (\d+) — (.+?)(?: 🎯)? (✅|🔨|⬜)$")
_ITEM = re.compile(r"^- \[( |x)\] (\d+)\.(\d+)(?: |$)")


class PhasesError(ValueError):
    pass


@dataclass
class Phase:
    number: int
    title: str
    status: str  # a value of STATUS
    done: list[str] = field(default_factory=list)  # "8.1"
    open: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.done) + len(self.open)


def parse(markdown: str) -> list[Phase]:
    phases: list[Phase] = []
    current: Phase | None = None
    for lineno, line in enumerate(markdown.split("\n"), start=1):
        if line.startswith("## Phase"):
            m = _HEADING.match(line)
            if not m:
                raise PhasesError(f"line {lineno}: unreadable phase heading: {line!r}")
            number = int(m.group(1))
            if number != len(phases):
                raise PhasesError(f"line {lineno}: phase {number} is out of order")
            current = Phase(number, m.group(2), STATUS[m.group(3)])
            phases.append(current)
        elif line.startswith("## "):
            current = None  # a section after the phases (or before them)
        elif line.lstrip().startswith("- ["):
            if line != line.lstrip():
                raise PhasesError(f"line {lineno}: indented subtask: {line!r}")
            m = _ITEM.match(line)
            if not m or current is None:
                raise PhasesError(f"line {lineno}: unreadable or stray subtask: {line!r}")
            if int(m.group(2)) != current.number:
                raise PhasesError(f"line {lineno}: subtask {m.group(2)}.{m.group(3)} not in phase")
            (current.done if m.group(1) == "x" else current.open).append(
                f"{m.group(2)}.{m.group(3)}"
            )
    for ph in phases:
        if ph.total == 0:
            raise PhasesError(f"phase {ph.number} has no subtasks")
        if ph.status == "complete" and ph.open:
            raise PhasesError(f"phase {ph.number} is marked complete with open subtasks")
    if not phases:
        raise PhasesError("no phases found")
    return phases
