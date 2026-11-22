"""Scale classes, peer sets and the fixed thresholds of the review rules.

Every threshold is a proposal. The 14.3 eval scores them (plan 14.2).
"""

import math
from statistics import median

# Scale class by `events_processed`. Upper bounds are exclusive; they sit between
# the record clusters in observability/scale/runs (about 6k-45k, 1M, 9M-10M, 100M).
SCALE_CLASSES = (("6k", 100_000), ("1m", 5_000_000), ("9m", 50_000_000), ("100m", None))
UNKNOWN_CLASS = "unknown"

MIN_PEERS = 3  # step_slow and cost_outlier are skipped below this
STEP_SLOW_FACTOR = 1.5
COST_OUTLIER_FACTOR = 2.0
# Longest Athena queue wait of a step before it is a finding. A proposal with no
# source in the repo (records show 0 to 5.4 s, plus one at 230.5 s); 14.3 scores it.
ATHENA_QUEUE_LIMIT_SECONDS = 60.0

# ADR 0023 cutoffs. NOT used by a rule: a record holds the bytes summed over all
# queries of a step (RunDbt of demo-100m sums 26 GiB over 33 queries and
# succeeded), not the largest query, so a headroom rule cannot be checked.
DBT_CUTOFF_BYTES = 25 * 2**30
DQ_CUTOFF_BYTES = 20 * 2**30


def number(value):
    """A finite int or float, else None. A bool is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def scale_class(record):
    events = number(record.get("events_processed"))
    if events is None:
        return UNKNOWN_CLASS
    for name, upper in SCALE_CLASSES:
        if upper is None or events < upper:
            return name
    return UNKNOWN_CLASS


def peers(record, records):
    """Other SUCCEEDED records of the same known scale class."""
    cls = scale_class(record)
    if cls == UNKNOWN_CLASS:
        return []
    return [
        r
        for r in records
        if isinstance(r, dict)
        and r.get("execution") != record.get("execution")
        and r.get("status") == "SUCCEEDED"
        and scale_class(r) == cls
    ]


def peer_median(values):
    """Median of the finite numbers, or None when fewer than MIN_PEERS."""
    nums = [v for v in (number(x) for x in values) if v is not None]
    return median(nums) if len(nums) >= MIN_PEERS else None
