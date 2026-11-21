"""The scorer (plan 14.3): replay the cases through an answerer and score the claims.

Metrics (ADR 0025 decision 9):
- incidents found, x of the six, with the known gaps shown;
- false findings on clean runs (a claim a clean case does not expect or accept);
- cited-claim validity: every claim cites at least one id and every id is in the
  review's evidence;
- determinism: the whole run repeated, the bytes compared.
Also per-rule precision and recall. The labels come from the same records the rules
were tuned on, so the recall figures say "still as tuned", not "good" (plan 14.3 Risks).
"""

import hashlib
import json

from cerberus_console import config, records

from cerberus_agents import review as review_core

from .cases import load_cases, resolve_record

REPEATS = 3
BAR_INCIDENTS = 5  # of the six in ADR 0025
BAR_FALSE_FINDINGS = 1  # at most, over all clean runs


def _claims(answer):
    raw = answer.get("claims") if isinstance(answer, dict) else None
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


def claim_is_valid(claim, evidence_ids):
    ids = claim.get("evidence")
    return (
        isinstance(ids, list)
        and bool(ids)
        and all(isinstance(i, str) and i in evidence_ids for i in ids)
    )


def _cited_fields(claim, review_obj, rule):
    """The evidence items of this rule that the claim cites."""
    by_id = {e["id"]: e for e in review_obj["evidence"]}
    ids = claim.get("evidence") if isinstance(claim.get("evidence"), list) else []
    return [by_id[i] for i in ids if isinstance(i, str) and i in by_id and by_id[i]["rule"] == rule]


def score_case(case, review_obj, claims):
    """One case against the claims. Returns the case result (plain data, sorted lists)."""
    label = case["label"]
    expect = label.get("expect", [])
    accepted = set(label.get("accepted_extra", []))
    expected_rules = {item["rule"] for item in expect}
    claimed = {c.get("rule") for c in claims}

    missing = []
    for item in expect:
        hit = any(
            c.get("rule") == item["rule"] and ("step" not in item or c.get("step") == item["step"])
            for c in claims
        )
        if not hit:
            missing.append(item["rule"] + (f"@{item['step']}" if "step" in item else ""))
    for req in label.get("required_evidence", []):
        ok = any(
            all(e.get(k) == v for k, v in req["fields"].items())
            for c in claims
            if c.get("rule") == req["rule"]
            for e in _cited_fields(c, review_obj, req["rule"])
        )
        if not ok:
            missing.append(f"evidence:{req['rule']}")
    absent_hit = sorted(set(label.get("expect_absent", [])) & claimed)
    extras = sorted(
        c.get("rule") if isinstance(c.get("rule"), str) else "?"
        for c in claims
        if c.get("rule") not in expected_rules and c.get("rule") not in accepted
    )
    gap_case = label.get("expect_found", True) is False
    if gap_case:
        status = "gap"
    else:
        status = "ok" if not (missing or absent_hit or extras) else "fail"
    return {
        "case_id": case["case_id"],
        "group": case["group"],
        "status": status,
        "gap": case["gap"],
        "reason": label.get("reason"),
        "missing": sorted(missing),
        "absent_hit": absent_hit,
        "extras": extras,
        "claimed": sorted(c for c in claimed if isinstance(c, str)),
    }


def _rate(num, den):
    return round(num / den, 3) if den else None


def _evaluate(answerer, cases, runs_dir):
    baseline = records.load(runs_dir).records
    results, rule_counts = [], {r: {"tp": 0, "fp": 0, "fn": 0} for r in review_core.RULES}
    claims_total = claims_valid = 0
    for case in cases:
        review_obj = review_core.review(resolve_record(case, runs_dir), baseline)
        claims = _claims(answerer(review_obj, case))
        ids = {e["id"] for e in review_obj["evidence"]}
        claims_total += len(claims)
        claims_valid += sum(1 for c in claims if claim_is_valid(c, ids))
        results.append(score_case(case, review_obj, claims))

        expected = {i["rule"] for i in case["label"].get("expect", [])}
        accepted = set(case["label"].get("accepted_extra", []))
        claimed = {c.get("rule") for c in claims}
        for rule in review_core.RULES:
            if rule in expected and rule in claimed:
                rule_counts[rule]["tp"] += 1
            elif rule in expected:
                rule_counts[rule]["fn"] += 1
            elif rule in claimed and rule not in accepted:
                rule_counts[rule]["fp"] += 1

    rules = {}
    for rule, n in rule_counts.items():
        if n["tp"] or n["fp"] or n["fn"]:
            rules[rule] = {
                **n,
                "precision": _rate(n["tp"], n["tp"] + n["fp"]),
                "recall": _rate(n["tp"], n["tp"] + n["fn"]),
            }
    incidents = [r for r in results if r["group"] == "incident"]
    found = [r["case_id"] for r in incidents if r["status"] == "ok"]
    clean = [r for r in results if r["group"] == "clean"]
    return {
        "cases": results,
        "rules": rules,
        "incidents": {
            "found": len(found),
            "found_ids": found,
            "total": len(incidents),
            "bar": BAR_INCIDENTS,
            "gaps": sorted(
                r["case_id"] for r in incidents if r["status"] == "gap" or r["gap"] is not None
            ),
            "not_found": sorted(r["case_id"] for r in incidents if r["status"] != "ok"),
        },
        "clean": {
            "runs": len(clean),
            "false_findings": sum(len(r["extras"]) for r in clean),
            "bar": BAR_FALSE_FINDINGS,
        },
        "citations": {
            "claims": claims_total,
            "valid": claims_valid,
            "validity": round(claims_valid / claims_total, 3) if claims_total else 1.0,
        },
    }


def run(answerer, cases=None, runs_dir=None, repeats=REPEATS):
    """Replay all cases `repeats` times. Returns the report (plain, json-ready data)."""
    runs_dir = config.RUNS_DIR if runs_dir is None else runs_dir
    cases = load_cases(runs_dir=runs_dir) if cases is None else cases
    digests, first = [], None
    for _ in range(repeats):
        out = _evaluate(answerer, cases, runs_dir)
        blob = json.dumps(out, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        digests.append(hashlib.sha256(blob.encode("ascii")).hexdigest())
        first = first or out
    first["determinism"] = {
        "repeats": repeats,
        "distinct_outputs": len(set(digests)),
        "same_bytes": len(set(digests)) == 1,
        "digest": digests[0][:12],
    }
    first["bar"] = _bar(first)
    return first


def _bar(report):
    inc, clean, cit, det = (
        report["incidents"],
        report["clean"],
        report["citations"],
        report["determinism"],
    )
    checks = {
        "incidents": inc["found"] >= inc["bar"],
        "false_findings": clean["false_findings"] <= clean["bar"],
        "cited_claims": cit["claims"] > 0 and cit["valid"] == cit["claims"],
        "determinism": det["same_bytes"],
    }
    return {**checks, "passed": all(checks.values())}


def dumps(report):
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _pct(value):
    return "n/a" if value is None else f"{value:.0%}"


def markdown(report, answerer_name="echo"):
    inc, clean, cit, det, bar = (
        report["incidents"],
        report["clean"],
        report["citations"],
        report["determinism"],
        report["bar"],
    )
    word = {True: "PASS", False: "FAIL"}
    gaps = [r for r in report["cases"] if r["status"] == "gap"]
    lines = [
        f"# Replay report (answerer: {answerer_name})",
        "",
        f"Result: **{word[bar['passed']]}** (ADR 0025 decision 9 bar)",
        "",
        "| Metric | Value | Bar | |",
        "| --- | --- | --- | --- |",
        f"| Incidents found | {inc['found']} of {inc['total']} | at least {inc['bar']} "
        f"| {word[bar['incidents']]} |",
        f"| False findings on clean runs | {clean['false_findings']} over {clean['runs']} runs "
        f"| at most {clean['bar']} | {word[bar['false_findings']]} |",
        f"| Cited-claim validity | {cit['valid']} of {cit['claims']} ({_pct(cit['validity'])}) "
        f"| 100% | {word[bar['cited_claims']]} |",
        f"| Determinism | {det['distinct_outputs']} distinct output in {det['repeats']} repeats "
        f"| 1 | {word[bar['determinism']]} |",
        "",
        "## Incidents",
        "",
    ]
    for r in report["cases"]:
        if r["group"] != "incident":
            continue
        note = ""
        if r["status"] == "gap":
            note = f" (known gap: {r['reason']}; not counted as found)"
        elif r["gap"]:
            note = f" (documented gap: {r['gap']})"
        lines.append(f"- {r['case_id']}: {r['status']}{note}")
    lines += [
        "",
        "## Per-rule precision and recall",
        "",
        "| Rule | TP | FP | FN | Precision | Recall |",
    ]
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for rule, n in sorted(report["rules"].items()):
        lines.append(
            f"| {rule} | {n['tp']} | {n['fp']} | {n['fn']} "
            f"| {_pct(n['precision'])} | {_pct(n['recall'])} |"
        )
    other = [r for r in report["cases"] if r["group"] != "incident" and r["status"] != "ok"]
    lines += ["", "## Other cases not ok", ""]
    lines += [f"- {r['case_id']}: {r['status']} {r['missing']} {r['extras']}" for r in other] or [
        "- none"
    ]
    lines += [
        "",
        f"Known gaps: {len(gaps)} (the record cannot show the incident).",
        "The labels come from the same records the rules were tuned on, so these",
        "figures show the rules still behave as tuned. They are not a recall estimate.",
        "",
    ]
    return "\n".join(lines)
