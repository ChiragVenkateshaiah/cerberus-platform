"""The launch scenarios as data: planned requests, exact bytes and the timeline.

One source for plan_bytes.py (bytes), the session script (schedule) and the
tests. Nothing here calls AWS or k6. Bytes are exact integers: chunk requests
times the chunk size (64 MiB) plus the licence response bodies. Headers, TLS
and the manifest (about 6 KB) are not counted; the 10% of the nftables budget
and the layer 4 limit cover them.

Scenario files: launch/scenarios/<name>.json. Each has "runs"; each run is one
k6 process. Workload kinds: "fetch" (clients each download a set; optional
ramp_minutes, chunks, manifest_from_edge), "licence" (total requests, vus,
rate_cap_per_s) and "sequence" (steps fetch:<set>, licence:403, wait:release,
licence:200). A run with "gate": "release" waits for T0 and one licence 200.

CLI: python3 launch/scenario.py schedule SCENARIO [--release-offset N]
prints key=value lines (the session script reads them).
"""

import json
import math
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIO_DIR = HERE / "scenarios"
CHOICES = {"a": ["a"], "b": ["b"], "c": ["c"], "d": ["d"], "bcd": ["b", "c", "d"], "p": ["p"]}
GB = Decimal(1_000_000_000)


# The terraform `minutes` variable allows 1 to 120.
MAX_MINUTES = 120


def load_sets(directory: Path | None = None) -> dict:
    return json.loads(((directory or SCENARIO_DIR) / "sets.json").read_text())


def load_scenario(name: str, directory: Path | None = None) -> dict:
    return json.loads(((directory or SCENARIO_DIR) / f"{name}.json").read_text())


def scenario_names(scenario: str) -> list[str]:
    if scenario not in CHOICES:
        raise ValueError(f"unknown scenario {scenario!r}; use one of {sorted(CHOICES)}")
    return CHOICES[scenario]


def gb(n_bytes: int) -> Decimal:
    """Decimal GB (1 GB = 10^9 bytes), three places, for display and the ledger."""
    return (Decimal(n_bytes) / GB).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


@dataclass
class Plan:
    """Planned requests and bytes of a workload, a run or a session."""

    requests: dict[str, int] = field(default_factory=dict)
    nbytes: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, requests: int, nbytes: int = 0) -> None:
        self.requests[kind] = self.requests.get(kind, 0) + requests
        self.nbytes[kind] = self.nbytes.get(kind, 0) + nbytes

    def merge(self, other: "Plan") -> None:
        for kind, n in other.requests.items():
            self.add(kind, n, other.nbytes.get(kind, 0))

    @property
    def total_requests(self) -> int:
        return sum(self.requests.values())

    @property
    def total_bytes(self) -> int:
        return sum(self.nbytes.values())


def _chunks(sets: dict, set_name: str, limit: int | None = None) -> int:
    n = sets["sets"][set_name]["chunks"]
    return n if limit is None else min(n, limit)


def workload_plan(sets: dict, w: dict) -> Plan:
    plan = Plan()
    chunk = sets["chunk_bytes"]
    lic = sets["licence_bytes"]
    if w["kind"] == "fetch":
        kind = sets["sets"][w["set"]]["prefix"]
        n = w["clients"] * _chunks(sets, w["set"], w.get("chunks"))
        plan.add(kind, n, n * chunk)
        if w.get("manifest_from_edge"):
            plan.add("manifest", 1)
    elif w["kind"] == "licence":
        plan.add("licence", w["total"], w["total"] * lic["200"])
    elif w["kind"] == "sequence":
        for step in w["steps"]:
            if step.startswith("fetch:"):
                set_name = step.split(":", 1)[1]
                kind = sets["sets"][set_name]["prefix"]
                n = _chunks(sets, set_name)
                plan.add(kind, n, n * chunk)
            elif step.startswith("licence:"):
                plan.add("licence", 1, lic[step.split(":", 1)[1]])
            elif step != "wait:release":
                raise ValueError(f"unknown step {step!r}")
    else:
        raise ValueError(f"unknown workload kind {w['kind']!r}")
    return plan


def run_plan(sets: dict, run: dict) -> Plan:
    plan = Plan()
    for w in run["workloads"]:
        plan.merge(workload_plan(sets, w))
    if run.get("gate") == "release":
        plan.add("licence", 1, sets["licence_bytes"]["200"])  # the one gate request
    return plan


def scenario_plan(sets: dict, scenario: dict) -> Plan:
    plan = Plan()
    for run in scenario["runs"]:
        plan.merge(run_plan(sets, run))
    return plan


def session_plan(scenario: str, directory: Path | None = None) -> Plan:
    """All instance runs of a SCENARIO choice (probe P is not included)."""
    sets = load_sets(directory)
    plan = Plan()
    for name in scenario_names(scenario):
        plan.merge(scenario_plan(sets, load_scenario(name, directory)))
    return plan


def run_files(scenario: str, directory: Path | None = None) -> list[str]:
    """The k6 summary names of a session, one per run: <scenario>-<index>."""
    names = []
    for name in scenario_names(scenario):
        names += [f"{name}-{i}" for i in range(len(load_scenario(name, directory)["runs"]))]
    return names


# --- timeline (planning estimates; see sets.json timing_unverified) ---


def _t(sets: dict, key: str):
    return sets["timing_unverified"][key]


def _fetch_minutes(sets: dict, set_name: str, chunks: int | None = None) -> float:
    n_bytes = _chunks(sets, set_name, chunks) * sets["chunk_bytes"]
    return n_bytes * 8 / (_t(sets, "client_mbit_per_s") * 1e6) / 60


def run_minutes(sets: dict, run: dict) -> tuple[float, float]:
    """(minutes before the release wait, minutes after it) of one run.

    A run without a wait step has all its time in the second number. The
    estimate is the longest workload (ramp plus one client's own download, or
    the licence flood at its rate cap), but at least the whole run's bytes over
    the link, plus one drain minute.
    """
    pre = post = 0.0
    for w in run["workloads"]:
        if w["kind"] == "sequence":
            waited = False
            for step in w["steps"]:
                if step == "wait:release":
                    waited = True
                    continue
                m = (
                    _fetch_minutes(sets, step.split(":", 1)[1])
                    if step.startswith("fetch:")
                    else 0.0
                )
                if waited:
                    post += m
                else:
                    pre += m
        elif w["kind"] == "fetch":
            m = w.get("ramp_minutes", 0) + _fetch_minutes(sets, w["set"], w.get("chunks"))
            post = max(post, m)
        else:
            post = max(post, w["total"] / w["rate_cap_per_s"] / 60)
    link = run_plan(sets, run).total_bytes * 8 / (_t(sets, "link_gbit_per_s") * 1e9) / 60
    post = max(post, link) + _t(sets, "drain_minutes")
    return pre, post


def _has_wait(run: dict) -> bool:
    return any("wait:release" in w.get("steps", []) for w in run["workloads"])


def schedule(
    scenario: str, release_offset: int | None = None, directory: Path | None = None
) -> dict:
    """Derive the seed list, T0, the end and the MINUTES limits from the scenario data.

    Times are minutes from the start of the instance apply. T0 (release_at)
    falls after every run before the first gated run ends, plus the margin.
    """
    sets = load_sets(directory)
    names = scenario_names(scenario)
    runs = [(n, r) for n in names for r in load_scenario(n, directory)["runs"]]
    used = {"build"}  # the probe P reads the build in every live session
    for _, r in runs:
        for w in r["workloads"]:
            if "set" in w:
                used.add(w["set"])
            for step in w.get("steps", []):
                if step.startswith("fetch:"):
                    used.add(step.split(":", 1)[1])
    seed_sets = [s for s in sets["sets"] if s in used]
    seed_bytes = sum(sets["sets"][s]["chunks"] for s in seed_sets) * sets["chunk_bytes"]
    seed_minutes = math.ceil(seed_bytes / (_t(sets, "seed_mb_per_s") * 1e6) / 60)
    lead = _t(sets, "boot_minutes") + seed_minutes

    margin = _t(sets, "release_margin_minutes")
    t = float(lead)
    t0 = None
    for _, r in runs:
        pre, post = run_minutes(sets, r)
        gated = r.get("gate") == "release" or _has_wait(r)
        if gated and t0 is None:
            t0 = t + pre + margin
        if gated:
            t = max(t + pre, t0) + post
        else:
            t += pre + post
    if t0 is None:
        t0 = t + margin  # no gated run: release_at still falls after the last run
    derived = math.ceil(t0)
    if release_offset is not None and release_offset < derived:
        raise ValueError(
            f"release offset {release_offset} min is below the derived {derived} min "
            "(the release would fall before the runs before it end)"
        )
    shift = 0 if release_offset is None else release_offset - derived
    end = math.ceil(t) + shift
    min_minutes = _t(sets, "prep_minutes") + end + _t(sets, "slack_minutes")
    if min_minutes > MAX_MINUTES:
        raise ValueError(f"needs {min_minutes} minutes; the limit is {MAX_MINUTES}")
    return {
        "seed_sets": seed_sets,
        "seed_minutes": seed_minutes,
        "release_offset_minutes": derived + shift,
        "end_minutes": end,
        "min_minutes": min_minutes,
        "max_minutes": MAX_MINUTES,
        "order": names,
        "run_files": run_files(scenario, directory),
    }


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "schedule":
        offset = None
        if "--release-offset" in argv:
            offset = int(argv[argv.index("--release-offset") + 1])
        try:
            s = schedule(argv[1], offset)
        except Exception as err:
            print(f"ERROR: {err}", file=sys.stderr)
            return 3
        for key, value in s.items():
            print(f"{key}={' '.join(value) if isinstance(value, list) else value}")
        return 0
    print(__doc__.split("CLI:")[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
