"""results_render.cost_read: the arithmetic, the $25 and $40 branches, separable days."""

import sys
from decimal import Decimal as D
from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCH))

import results_render as rr  # noqa: E402


def entry(kind, est, usd, date):
    return {"kind": kind, "estimate": D(est), "usd": D(usd), "gb": D(0), "date": date}


COST = {
    "month_total_usd": "30.25",
    "daily": [
        {"date": "2026-11-27", "service": "A", "usd": "1.2"},
        {"date": "2026-11-27", "service": "B", "usd": "2.0"},
        {"date": "2026-11-28", "service": "A", "usd": "4.0"},
    ],
}


def test_arithmetic_and_within_branches():
    ledger = {"r1": entry("session", "3", "2.5", "2026-11-27")}
    out = rr.cost_read(ledger, COST, D("12.5"))
    assert out["attributable"] == D("17.75")
    assert out["attributable_status"] == "within the $25 stop rule"
    assert out["account_total"] == D("30.25")
    assert out["account_status"] == "within the $40 ceiling"
    assert out["ledger_sum"] == D("2.5")  # shown beside, never added
    assert out["per_run"][0]["ce_day"] == D("3.2")
    assert out["per_run"][0]["estimate"] == D("3") and out["per_run"][0]["corrected"] == D("2.5")


def test_limits_are_inclusive_and_over_branches():
    at = rr.cost_read({}, {"month_total_usd": "37.5", "daily": []}, D("12.5"))
    assert at["attributable"] == D("25.0") and at["attributable_status"].startswith("within")
    over = rr.cost_read({}, {"month_total_usd": "40.01", "daily": []}, D("12.5"))
    assert over["attributable_status"] == "OVER the $25 stop rule"
    assert over["account_status"] == "OVER the $40 ceiling"
    at40 = rr.cost_read({}, {"month_total_usd": "40", "daily": []}, D("0"))
    assert at40["account_status"] == "within the $40 ceiling"


def test_non_separable_day_is_not_attributed():
    ledger = {
        "r1": entry("session", "3", "2.5", "2026-11-28"),
        "r2": entry("exercise", "4", "3.1", "2026-11-28"),
        "r3": entry("session", "1", "1", None),
    }
    out = {r["run_id"]: r for r in rr.cost_read(ledger, COST, D("12.5"))["per_run"]}
    assert out["r1"]["ce_day"] is None and "2 runs that day" in out["r1"]["ce_day_note"]
    assert out["r2"]["ce_day"] is None
    assert out["r3"]["ce_day"] is None and "no date" in out["r3"]["ce_day_note"]


def test_day_without_a_cost_explorer_row_is_not_zero():
    ledger = {"r1": entry("session", "3", "2.5", "2026-11-26")}
    out = rr.cost_read(ledger, {"month_total_usd": "20", "daily": []}, D("12.5"))
    assert out["per_run"][0]["ce_day"] is None
    assert out["per_run"][0]["ce_day_note"] == "no Cost Explorer row yet"


def test_no_cost_or_no_baseline_is_not_measured():
    ledger = {"r1": entry("session", "3", "2.5", "2026-11-27")}
    none = rr.cost_read(ledger, None, D("12.5"))
    assert none["attributable"] is None and none["attributable_status"] == rr.NM
    assert none["account_status"] == rr.NM
    assert none["per_run"][0]["ce_day"] is None and none["per_run"][0]["ce_day_note"] == rr.NM
    assert none["ledger_sum"] == D("2.5")
    nobase = rr.cost_read(ledger, COST, None)
    assert nobase["attributable"] is None and nobase["account_total"] == D("30.25")


def test_unit_costs_use_k6_bytes_then_planned_gb(tmp_path):
    fx = Path(__file__).resolve().parent / "fixtures" / "synthetic"
    runs = rr.load_runs(fx / "runs")
    entries = rr.load_ledger(fx / "ledger.jsonl")
    facts = rr.cost_facts(runs, entries, rr.read_json(fx / "extracts" / "cost.json"), D("12.5"))
    # k6 bytes_*: a, b, c, d and the probe, from the fixtures
    total = 805306368 + 134217728 + 70 + 6442450944 + 1200 + 4294967296 + 900 + 40000
    total += 2147483648 + 300
    assert facts["per_gb"] == D("17.75") / (D(total) / D(10**9))
    assert facts["per_gb_basis"] == "all attributable spend / k6 bytes (upper bound)"
    assert facts["per_million"] == D("3.10")  # 3.10 / 1,000,000 events x 1,000,000
    for run in runs.values():  # no counters: fall back to the planned GB, labelled
        for summary in [*run["results"].values(), *([run["probe"]] if run["probe"] else [])]:
            for key in ("bytes_build", "bytes_patch", "bytes_licence"):
                summary["metrics"].pop(key, None)
    fallback = rr.cost_facts(runs, entries, rr.read_json(fx / "extracts" / "cost.json"), D("12.5"))
    assert fallback["per_gb"] == D("17.75") / D("26.000")
    assert "planned GB" in fallback["per_gb_basis"]


def test_ledger_loader_keeps_kind_and_corrected_value():
    fx = Path(__file__).resolve().parent / "fixtures" / "synthetic"
    entries = rr.load_ledger(fx / "ledger.jsonl")
    assert entries["synthetic-exercise"]["kind"] == "exercise"
    assert entries["synthetic-exercise"]["usd"] == D("3.10")
    assert entries["synthetic-exercise"]["estimate"] == D("4.00")


class FakeCE:
    def __init__(self, pages_by_granularity=None):
        self.calls = []

    def get_cost_and_usage(self, **kw):
        self.calls.append(kw)
        if kw["Granularity"] == "MONTHLY":
            amount = "30.2500123456789"
            return {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": amount}}}]}
        if "NextPageToken" not in kw:
            return {
                "NextPageToken": "t",
                "ResultsByTime": [
                    {
                        "TimePeriod": {"Start": "2026-11-28"},
                        "Groups": [
                            {"Keys": ["Zed"], "Metrics": {"UnblendedCost": {"Amount": "1.23456"}}},
                            {"Keys": ["Zero"], "Metrics": {"UnblendedCost": {"Amount": "0.00001"}}},
                        ],
                    },
                ],
            }
        return {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-11-27"},
                    "Groups": [
                        {
                            "Keys": ["Amazon CloudFront"],
                            "Metrics": {"UnblendedCost": {"Amount": "2"}},
                        },
                    ],
                },
            ]
        }


def test_pull_cost_reads_usage_only_and_writes_sorted_json(tmp_path):
    import json

    import results_pull as rp

    ce = FakeCE()
    result = rp.pull_cost(ce, tmp_path)
    monthly, daily = ce.calls[0], ce.calls[1]
    assert monthly["Filter"] == {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}}
    assert monthly["TimePeriod"] == {"Start": "2026-11-01", "End": "2026-12-01"}
    assert daily["Granularity"] == "DAILY" and daily["GroupBy"][0]["Key"] == "SERVICE"
    assert daily["TimePeriod"] == {"Start": "2026-11-25", "End": "2026-12-01"}
    assert daily["Filter"] == monthly["Filter"]
    assert result["month_total_usd"] == "30.2500"
    assert [(d["date"], d["service"], d["usd"]) for d in result["daily"]] == [
        ("2026-11-27", "Amazon CloudFront", "2.0000"),
        ("2026-11-28", "Zed", "1.2346"),
    ]  # sorted, paged, and the rounded-to-zero row dropped
    assert json.loads((tmp_path / "cost.json").read_text()) == result


def test_pull_cost_main_refuses_a_12_digit_value(tmp_path, capsys):
    import results_pull as rp

    class Big(FakeCE):
        def get_cost_and_usage(self, **kw):
            return {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": "1" * 12}}}]}

    assert rp.main(["cost", "--out", str(tmp_path / "o")], ce=Big()) == 2
    assert not (tmp_path / "o").exists()
    assert "1" * 12 not in capsys.readouterr().err
