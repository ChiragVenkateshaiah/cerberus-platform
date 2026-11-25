"""Cerberus 17.2 -- bulk synthetic `downloads` generator for the launch-day phase.

Writes about 100M download-lifecycle events into bronze as JSON Lines, per
ADR 0030 Decisions 7 and 10:

    s3a://<bronze>/downloads_bulk/run_id=<run_id>/dt=YYYY-MM-DD/part-*.json

The model is one title of 212 GB in 5 GB chunks, a 0.5 GB day-one patch, 24
synthetic regions (one per time zone) with 2 synthetic ISPs each, and a
release at 00:00 local per region. About 46% of clients pre-load; the rest
download the full title after release. One fixed ISP is under-provisioned, so
it congests at release and then a "traffic management" cap applies.

Deterministic on purpose (ADR 0018, ADR 0030 Decision 7): every random choice
is a SHA-256 hash of (run_id, client_id, a salt), `event_id` is a UUIDv7-shaped
hash (48-bit `occurred_at` in ms plus 74 hash bits), and "now" is an argument.
The same arguments give the same events. A different run_id gives different
event_ids, so the generator must not run twice under two ids for one dataset.

The core is pure Python (no Spark import at module level). Spark only
distributes the client index range, so the unit tests and `--local` run the
same code as the cluster. Congestion takes two passes: pass 1 adds up nominal
active clients per (ISP, minute), pass 2 regenerates each client with the
throughput that load allows. The active counts use nominal durations, not
the stretched ones, so there is no feedback loop.

The image runs Python 3.10, so this file avoids 3.11+ features. It is one
file with no pyFiles, like generate_bulk_payments.py.
"""

import argparse
import bisect
import calendar
import hashlib
import json
import math
import re
import time
from array import array
from collections import namedtuple

SOURCE = "generate_bulk_downloads.py"
HEAD_FIELDS = ["event_id", "event_family", "event_type", "occurred_at", "ingested_at"]
BULK_PREFIX = "downloads_bulk/"
# Row layout: the Spark schema and rows() both read these, so they cannot drift apart.
ENVELOPE_FIELDS = HEAD_FIELDS + ["schema_version", "payload"]
PAYLOAD_FIELDS = [
    ("client_id", "string"),
    ("platform", "string"),
    ("region", "string"),
    ("isp", "string"),
    ("bytes", "long"),
    ("duration_ms", "long"),
    ("throughput_mbps", "double"),
    ("http_status", "int"),
]
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# --- Model constants (launch plan section 4, ADR 0030) -----------------------
TITLE_BYTES = 212 * 10**9
CHUNK_BYTES = 5 * 10**9
PATCH_BYTES = 5 * 10**8
# 42 chunks of 5 GB and one of 2 GB: 43 chunk_completed events per full download.
CHUNKS = [CHUNK_BYTES] * (TITLE_BYTES // CHUNK_BYTES) + [TITLE_BYTES % CHUNK_BYTES]
# Pre-loader: 50 events. Non-pre-loader: 48. Plus the stalls and retries.
# Measured on the 10k sample by a test (mean must stay within 48-54).
EVENTS_PER_CLIENT = 50
# Spark's JSON writer, a little over the ~330 bytes a line holds: only sizes files.
BYTES_PER_EVENT = 450

REGIONS = 24
WINDOW_START_MS = calendar.timegm((2026, 11, 10, 0, 0, 0)) * 1000
WINDOW_END_MS = calendar.timegm((2026, 11, 22, 0, 0, 0)) * 1000
RELEASE_UTC_MS = calendar.timegm((2026, 11, 19, 0, 0, 0)) * 1000
DAYS = (WINDOW_END_MS - WINDOW_START_MS) // 86_400_000
MINUTES = (WINDOW_END_MS - WINDOW_START_MS) // 60_000
LAST_EVENING_DAY = 8  # local 2026-11-18, the evening before release

PRELOAD_SHARE = 0.46
ISP_A_SHARE = 0.60
EARLY_ASK_SHARE = 0.03
ABANDON_SHARE = 0.03
MBPS_RANGE = (150.0, 600.0)  # a client's nominal throughput
LICENSE_JITTER_MS = 5 * 60_000
INSTALL_DELAY_MS = (30_000, 300_000)
LATE_DELAY_MEAN_MS = 20 * 60_000  # non-pre-loaders start this long after the grant
STALL_BASE = 0.02
STALL_PER_UTIL = 0.25  # added per unit of utilisation above STALL_KNEE
STALL_KNEE = 0.8
STALL_MAX = 0.6
HEADROOM = 1.25  # capacity = headroom x peak nominal demand
WEAK_HEADROOM = 0.55
WEAK_ISP = "isp_17_a"
TM_CAP_MBPS = 50.0  # "traffic management" cap
TM_MINUTES = 180

TYPES = (
    "preload_started chunk_completed stalled retried preload_completed license_requested "
    "license_granted patch_started patch_completed install_completed abandoned"
).split()

Plan = namedtuple("Plan", "client_id region isp platform preloads early pre_start release mbps")


# --- Hash randomness ---------------------------------------------------------
def u(run_id: str, client_id: str, salt: str) -> float:
    """A deterministic value in [0, 1): the top 53 bits of SHA-256, over 2^53."""
    digest = hashlib.sha256(f"{run_id}|{client_id}|{salt}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) / (1 << 53)


def client_id_of(run_id: str, index: int) -> str:
    return "cl_" + hashlib.sha256(f"{run_id}|client|{index}".encode()).hexdigest()[:12]


def event_id(run_id: str, client_id: str, event_type: str, sequence: int, ms: int) -> str:
    """UUIDv7 layout: 48-bit ms, 0111, 12 hash bits, 10, 62 hash bits. Not random."""
    h = int.from_bytes(
        hashlib.sha256(f"{run_id}|{client_id}|{event_type}|{sequence}".encode()).digest()[:10],
        "big",
    )  # the top 74 of these 80 bits
    top = h >> 6
    value = (ms << 80) | (0x7 << 76) | ((top >> 62) << 64) | (0x2 << 62) | (top & ((1 << 62) - 1))
    s = f"{value:032x}"
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"


# --- Names and calendar ------------------------------------------------------
def region_name(n: int) -> str:
    return f"region_{n:02d}"


def isp_name(n: int, b: bool) -> str:
    return f"isp_{n:02d}_{'b' if b else 'a'}"


ISP_NAMES = [isp_name(n, b) for n in range(1, REGIONS + 1) for b in (False, True)]
WEAK_INDEX = ISP_NAMES.index(WEAK_ISP)


def offset_hours(region_n: int) -> int:
    return region_n - 12  # region_01..24 are UTC-11..UTC+12


def release_ms(region_n: int) -> int:
    """00:00 local on the release day, in UTC ms."""
    return RELEASE_UTC_MS - offset_hours(region_n) * 3_600_000


def iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + f".{ms % 1000:03d}Z"


def parse_ms(text: str) -> int:
    ms = int(text[20:23]) if len(text) > 20 else 0
    return calendar.timegm(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")) * 1000 + ms


def parse_now(text: str) -> int:
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")) * 1000


# --- Pre-load start: inverse CDF over hourly bins per region ----------------
def _preload_cdf(region_n: int) -> list:
    """Cumulative weights over the hours from window start to local release.

    An opening spike decays from day 0, a diurnal term lifts local hours
    18-23, and the local evening of 11-18 gets an extra bump.
    """
    off = offset_hours(region_n)
    hours = (release_ms(region_n) - WINDOW_START_MS) // 3_600_000
    total, cum = 0.0, []
    for h in range(hours):
        local = h + off
        evening = 18 <= local % 24 <= 23
        w = 1.0 + 8.0 * math.exp(-h / 4.0)
        if evening:
            w += 1.5
            if local // 24 == LAST_EVENING_DAY:
                w += 4.0
        total += w
        cum.append(total)
    return cum


PRELOAD_CDF = [None] + [_preload_cdf(n) for n in range(1, REGIONS + 1)]


def preload_start(run_id: str, cid: str, region_n: int) -> int:
    cum = PRELOAD_CDF[region_n]
    hour = bisect.bisect_right(cum, u(run_id, cid, "pre_bin") * cum[-1])
    hour = min(hour, len(cum) - 1)
    return WINDOW_START_MS + hour * 3_600_000 + int(u(run_id, cid, "pre_off") * 3_600_000)


# --- Client plan and nominal schedule ----------------------------------------
def plan_client(run_id: str, cid: str) -> Plan:
    region_n = 1 + int(u(run_id, cid, "region") * REGIONS)
    b = u(run_id, cid, "isp") >= ISP_A_SHARE
    preloads = u(run_id, cid, "preload") < PRELOAD_SHARE
    lo, hi = MBPS_RANGE
    return Plan(
        client_id=cid,
        region=region_n,
        isp=(region_n - 1) * 2 + (1 if b else 0),
        platform="console_a" if u(run_id, cid, "platform") < 0.5 else "console_b",
        preloads=preloads,
        early=preloads and u(run_id, cid, "early") < EARLY_ASK_SHARE,
        pre_start=preload_start(run_id, cid, region_n) if preloads else 0,
        release=release_ms(region_n),
        mbps=round(lo + (hi - lo) * u(run_id, cid, "mbps"), 1),
    )


def _ms_for(nbytes: int, mbps: float) -> int:
    return int(nbytes * 8 / (mbps * 1e6) * 1000)


def nominal_intervals(run_id: str, p: Plan) -> list:
    """(start_ms, duration_ms) of each download at the client's nominal speed."""
    cid = p.client_id
    jit = int(u(run_id, cid, "jitter") * LICENSE_JITTER_MS)
    title, patch = _ms_for(TITLE_BYTES, p.mbps), _ms_for(PATCH_BYTES, p.mbps)
    if p.preloads:
        grant = max(p.release, p.pre_start + title + 1000) + jit
        return [(p.pre_start, title), (grant, patch)]
    grant = p.release + jit
    start = grant + int(-math.log(1.0 - u(run_id, cid, "delay")) * LATE_DELAY_MEAN_MS)
    return [(start, title), (start + title, patch)]


# --- Congestion --------------------------------------------------------------
class Congestion:
    """Active nominal clients per (ISP, minute), a capacity per ISP, and the cap window."""

    def __init__(self, active: list):
        self.active = active
        self.capacity, self.tm_start = [], []
        for i, row in enumerate(active):
            cap = (WEAK_HEADROOM if i == WEAK_INDEX else HEADROOM) * max(row)
            self.capacity.append(cap)
            self.tm_start.append(next((m for m, a in enumerate(row) if a > cap), -1))

    def util(self, isp: int, ms: int) -> float:
        cap = self.capacity[isp]
        if cap <= 0:
            return 0.0
        minute = min(max((ms - WINDOW_START_MS) // 60_000, 0), MINUTES - 1)
        return self.active[isp][minute] / cap

    def throughput(self, isp: int, ms: int, mbps: float) -> float:
        thr = mbps / max(1.0, self.util(isp, ms))
        start = self.tm_start[isp]
        if start >= 0 and start <= (ms - WINDOW_START_MS) // 60_000 < start + TM_MINUTES:
            thr = min(thr, TM_CAP_MBPS)
        return round(thr, 1)

    def stall_prob(self, isp: int, ms: int) -> float:
        extra = max(0.0, self.util(isp, ms) - STALL_KNEE) * STALL_PER_UTIL
        return min(STALL_MAX, STALL_BASE + extra)


def new_diffs() -> list:
    return [array("i", bytes(4 * (MINUTES + 1))) for _ in ISP_NAMES]


def add_client(diffs: list, run_id: str, p: Plan) -> list:
    for start, dur in nominal_intervals(run_id, p):
        a = (start - WINDOW_START_MS) // 60_000
        b = (start + dur - WINDOW_START_MS) // 60_000 + 1
        if a >= MINUTES or b <= 0:
            continue
        d = diffs[p.isp]
        d[max(a, 0)] += 1
        d[min(b, MINUTES)] -= 1
    return diffs


def merge_diffs(x: list, y: list) -> list:
    for dx, dy in zip(x, y, strict=True):
        for m in range(MINUTES + 1):
            dx[m] += dy[m]
    return x


def congestion_from_diffs(diffs: list) -> Congestion:
    active = []
    for d in diffs:
        run, row = 0, array("i")
        for m in range(MINUTES):
            run += d[m]
            row.append(run)
        active.append(row)
    return Congestion(active)


def curve_congestion(clients: int) -> Congestion:
    """The fallback: active counts from a closed-form curve, with no pass 1."""
    active = []
    for i in range(len(ISP_NAMES)):
        region_n = i // 2 + 1
        share = (ISP_A_SHARE if i % 2 == 0 else 1.0 - ISP_A_SHARE) / REGIONS
        n = clients * share
        off = offset_hours(region_n)
        rel_min = (release_ms(region_n) - WINDOW_START_MS) // 60_000
        row = array("i")
        for m in range(MINUTES):
            d = m - rel_min
            if d >= 0:
                f = 0.9 * (1.0 - math.exp(-d / 20.0)) * math.exp(-d / 90.0)
            else:
                evening = 18 <= (m // 60 + off) % 24 <= 23
                f = PRELOAD_SHARE * (0.02 + 0.05 * evening + 0.3 * math.exp(-m / 240.0))
            row.append(int(n * f))
        active.append(row)
    return Congestion(active)


# --- Events ------------------------------------------------------------------
def _download(run_id, p, cong, t, tag, out):
    """Append the stalls and chunk_completed events of one full download; return the end time."""
    cid = p.client_id
    for i, size in enumerate(CHUNKS):
        if cong is not None and u(run_id, cid, f"{tag}stall{i}") < cong.stall_prob(p.isp, t):
            part = int(u(run_id, cid, f"{tag}part{i}") * size)
            stall_ms = 5000 + int(u(run_id, cid, f"{tag}stallms{i}") * 55_000)
            out.append((t, "stalled", part, stall_ms, 0.0, 0))
            t += stall_ms
            if u(run_id, cid, f"{tag}retry{i}") < 0.5:
                out.append((t, "retried", 0, 0, 0.0, 503))
                t += 1000
        thr = cong.throughput(p.isp, t, p.mbps) if cong is not None else p.mbps
        dur = _ms_for(size, thr)
        t += dur
        out.append((t, "chunk_completed", size, dur, thr, 200))
    return t


def _patch(run_id, p, cong, t, out):
    thr = cong.throughput(p.isp, t, p.mbps) if cong is not None else p.mbps
    out.append((t, "patch_started", 0, 0, 0.0, 200))
    dur = _ms_for(PATCH_BYTES, thr)
    t += dur
    out.append((t, "patch_completed", PATCH_BYTES, dur, thr, 200))
    delay = INSTALL_DELAY_MS[0] + int(
        u(run_id, p.client_id, "install") * (INSTALL_DELAY_MS[1] - INSTALL_DELAY_MS[0])
    )
    out.append((t + delay, "install_completed", 0, 0, 0.0, 0))


def raw_events(run_id: str, p: Plan, cong) -> list:
    """The client's (ms, type, bytes, duration_ms, mbps, http_status), in time order."""
    cid = p.client_id
    out = []
    jit = int(u(run_id, cid, "jitter") * LICENSE_JITTER_MS)
    grant_ms = 200 + int(u(run_id, cid, "grant") * 1800)
    if p.preloads:
        out.append((p.pre_start, "preload_started", 0, 0, 0.0, 200))
        t = _download(run_id, p, cong, p.pre_start, "p", out)
        span = t - p.pre_start
        out.append((t, "preload_completed", TITLE_BYTES, span, round(_rate(span), 1), 200))
        early = p.release - 60_000 * (1 + int(u(run_id, cid, "early_min") * 30))
        if p.early and early > t:
            out.append((early, "license_requested", 0, 0, 0.0, 403))
            out.append((early + 1500, "retried", 0, 0, 0.0, 403))
        ask = max(p.release, t + 1000) + jit
        out.append((ask, "license_requested", 0, 0, 0.0, 200))
        out.append((ask + grant_ms, "license_granted", 0, 0, 0.0, 200))
        _patch(run_id, p, cong, ask + grant_ms + 1000, out)
    else:
        ask = p.release + jit
        out.append((ask, "license_requested", 0, 0, 0.0, 200))
        out.append((ask + grant_ms, "license_granted", 0, 0, 0.0, 200))
        late = int(-math.log(1.0 - u(run_id, cid, "delay")) * LATE_DELAY_MEAN_MS)
        t = _download(run_id, p, cong, ask + grant_ms + late, "f", out)
        _patch(run_id, p, cong, t + 1000, out)
    if u(run_id, cid, "abandon") < ABANDON_SHARE:
        keep = 1 + int(u(run_id, cid, "abandon_at") * (len(out) - 1))
        out = out[:keep]
        gap = 1000 + int(u(run_id, cid, "abandon_gap") * 60_000)
        out.append((out[-1][0] + gap, "abandoned", 0, 0, 0.0, 0))
    return out


def _rate(span_ms: int) -> float:
    return TITLE_BYTES * 8 / (span_ms / 1000) / 1e6


def client_events(run_id: str, now: str, p: Plan, cong) -> list:
    """The client's events as dicts, ids and sequence set, cut at the window end."""
    out, last = [], -1
    for seq, (ms, etype, nbytes, dur, thr, http) in enumerate(raw_events(run_id, p, cong)):
        ms = max(ms, last + 1)  # strictly increasing ms keeps the order stable
        last = ms
        if ms >= WINDOW_END_MS:
            break  # time order makes this a suffix cut, so the lifecycle stays valid
        out.append(
            {
                "event_id": event_id(run_id, p.client_id, etype, seq, ms),
                "event_family": "downloads",
                "event_type": etype,
                "occurred_at": iso(ms),
                "ingested_at": now,
                "schema_version": 1,
                "payload": {
                    "client_id": p.client_id,
                    "platform": p.platform,
                    "region": region_name(p.region),
                    "isp": ISP_NAMES[p.isp],
                    "bytes": nbytes,
                    "duration_ms": dur,
                    "throughput_mbps": thr,
                    "http_status": http,
                },
            }
        )
    return out


def validate_lifecycle(events: list) -> list:
    """Check one client's time-ordered events; return the problems (empty is valid)."""
    errors, seen, chunk_sum, last, abandoned = [], set(), 0, -1, False
    for e in events:
        etype, pl, ms = e["event_type"], e["payload"], parse_ms(e["occurred_at"])
        region_n = int(pl["region"].split("_")[1])
        if abandoned:
            errors.append("event after abandoned")
        if not WINDOW_START_MS <= ms < WINDOW_END_MS:
            errors.append(f"{etype} outside the window")
        if ms <= last:
            errors.append(f"{etype} not after the previous event")
        last = ms
        if not 0 <= pl["bytes"] <= TITLE_BYTES:
            errors.append(f"{etype} bytes out of range")
        if etype == "license_granted" and ms < release_ms(region_n):
            errors.append("license_granted before local release")
        if etype == "install_completed":
            if "license_granted" not in seen:
                errors.append("install_completed without license_granted")
            if "patch_completed" not in seen:
                errors.append("install_completed before the patch")
        if etype == "chunk_completed":
            chunk_sum += pl["bytes"]
        if etype == "abandoned":
            abandoned = True
        seen.add(etype)
    if chunk_sum > TITLE_BYTES:
        errors.append("chunk bytes above the title size")
    if "install_completed" in seen and chunk_sum != TITLE_BYTES:
        errors.append("installed but chunk bytes differ from the title size")
    return errors


# --- Run (shared by --local and Spark) ---------------------------------------
def check_run_id(run_id: str) -> str:
    """Return run_id if it is safe in a path (no dots, slashes or '|'); else raise ValueError."""
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("--run-id must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    return run_id


def check_output(output: str) -> str:
    """Return output if it ends in /downloads_bulk (a trailing slash is fine); else raise."""
    if not output.rstrip("/").endswith("/" + BULK_PREFIX.rstrip("/")):
        raise ValueError(f"--output must end in /{BULK_PREFIX.rstrip('/')}")
    return output


def run_dir_of(output: str, run_id: str) -> str:
    """The one directory a run owns, rebuilt from the validated parts."""
    return f"{check_output(output).rstrip('/')}/run_id={check_run_id(run_id)}"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True, help="names the run_id= partition")
    parser.add_argument("--events", type=int, required=True, help="target event count")
    parser.add_argument(
        "--now",
        required=True,
        help="fixed 'now' as YYYY-MM-DDTHH:MM:SSZ; the ingested_at of every event",
    )
    parser.add_argument("--congestion", choices=["two-pass", "curve"], default="two-pass")
    parser.add_argument("--clients", type=int, help="override the client count")
    parser.add_argument("--target-file-mb", type=int, default=128)
    parser.add_argument("--output", help="output root, s3a://<bronze>/downloads_bulk/")
    parser.add_argument("--local", metavar="PATH", help="pure-Python run, no Spark; .gz is gzipped")
    args = parser.parse_args()
    try:
        check_run_id(args.run_id)
        if not args.local and args.output:
            check_output(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    for name in ("events", "clients"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            parser.error(f"--{name} must be greater than 0")
    if parse_now(args.now) < WINDOW_END_MS:
        parser.error("--now must be at or after the window end (2026-11-22T00:00:00Z)")
    if not args.local and not args.output:
        parser.error("--output is required unless --local is set")
    return args


def client_count(args) -> int:
    return args.clients or math.ceil(args.events / EVENTS_PER_CLIENT)


def local_congestion(run_id: str, clients: int, mode: str) -> Congestion:
    if mode == "curve":
        return curve_congestion(clients)
    diffs = new_diffs()
    for i in range(clients):
        add_client(diffs, run_id, plan_client(run_id, client_id_of(run_id, i)))
    return congestion_from_diffs(diffs)


def local_events(run_id: str, now: str, clients: int, cong):
    for i in range(clients):
        p = plan_client(run_id, client_id_of(run_id, i))
        yield from client_events(run_id, now, p, cong)


def dumps(event: dict) -> str:
    return json.dumps(event, separators=(",", ":"))


def write_local(path: str, lines) -> int:
    import gzip

    count = 0
    if path.endswith(".gz"):
        with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as fh:
            for line in lines:
                fh.write(line.encode() + b"\n")
                count += 1
    else:
        with open(path, "w") as fh:
            for line in lines:
                fh.write(line + "\n")
                count += 1
    return count


def main():
    args = parse_args()
    clients = client_count(args)
    if args.local:
        cong = local_congestion(args.run_id, clients, args.congestion)
        lines = (dumps(e) for e in local_events(args.run_id, args.now, clients, cong))
        print(f"[generate] local events={write_local(args.local, lines)} clients={clients}")
        return
    run_spark(args, clients)


def run_spark(args, clients: int):
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    run_id, now = args.run_id, args.now
    target_bytes = args.target_file_mb * 1024 * 1024
    files_per_dt = max(1, math.ceil(args.events * BYTES_PER_EVENT / DAYS / target_bytes))
    spark = (
        SparkSession.builder.appName("cerberus-generate-bulk-downloads")
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "com.amazonaws.auth.WebIdentityTokenCredentialsProvider",
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.files.maxRecordsPerFile", str(target_bytes // BYTES_PER_EVENT))
        .getOrCreate()
    )
    sc = spark.sparkContext
    print(f"[generate] run_id={run_id} clients={clients} files_per_dt={files_per_dt}")
    ids = spark.range(0, clients, 1, max(1, math.ceil(clients / 20000))).rdd.map(lambda r: r[0])

    def plans(it):
        return (plan_client(run_id, client_id_of(run_id, i)) for i in it)

    if args.congestion == "curve":
        cong = curve_congestion(clients)
    else:
        diffs = ids.mapPartitions(plans).treeAggregate(
            new_diffs(), lambda acc, p: add_client(acc, run_id, p), merge_diffs
        )
        cong = congestion_from_diffs(diffs)  # about 3.3 MB, not a collect of tuples
    # Broadcast plain arrays: a __main__ class would not unpickle in the worker.
    bc = sc.broadcast(cong.active)

    def rows(it):
        cg = Congestion(bc.value)  # once per partition
        for p in plans(it):
            for e in client_events(run_id, now, p, cg):
                head = tuple(e[k] for k in HEAD_FIELDS)
                payload = tuple(e["payload"][k] for k, _ in PAYLOAD_FIELDS)
                yield (*head, e["schema_version"], payload)

    types = {
        "string": T.StringType(),
        "long": T.LongType(),
        "double": T.DoubleType(),
        "int": T.IntegerType(),
    }
    payload_type = T.StructType([T.StructField(k, types[t]) for k, t in PAYLOAD_FIELDS])
    envelope = {k: types["string"] for k in HEAD_FIELDS}
    envelope.update(schema_version=types["int"], payload=payload_type)
    schema = T.StructType([T.StructField(k, envelope[k]) for k in ENVELOPE_FIELDS])
    df = (
        spark.createDataFrame(ids.mapPartitions(rows), schema)
        .withColumn("dt", F.substring("occurred_at", 1, 10))
        .withColumn("run_id", F.lit(run_id))
        .withColumn("_bucket", F.pmod(F.xxhash64("event_id"), F.lit(files_per_dt)))
    )
    manifest_path = delete_manifest(spark, args.output, run_id)
    clear_run_dir(spark, args.output, run_id)  # no stale dt= left from a bigger earlier run
    started = time.time()
    to_write = df.repartition(DAYS * files_per_dt, "dt", "_bucket").drop("_bucket")
    to_write.write.mode("overwrite").partitionBy("run_id", "dt").json(args.output)
    elapsed = time.time() - started
    run_dir = run_dir_of(args.output, run_id)
    counts = (
        spark.read.text(run_dir)
        .groupBy(F.col("dt").cast("string").alias("dt"))
        .count()
        .orderBy("dt")
        .collect()
    )
    write_manifest(spark, args, run_id, clients, counts, manifest_path)
    total = sum(r["count"] for r in counts)
    print(f"[generate] done events={total} write_seconds={elapsed:.1f} eps={total / elapsed:.0f}")
    spark.stop()


def delete_manifest(spark, output: str, run_id: str) -> str:
    """Delete any old manifest first, so a re-run that fails is not marked complete."""
    jvm = spark.sparkContext._jvm
    run_dir = jvm.org.apache.hadoop.fs.Path(run_dir_of(output, run_id))
    path = jvm.org.apache.hadoop.fs.Path(run_dir, "_manifest.json")
    fs = run_dir.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    if fs.exists(path):
        fs.delete(path, False)
    return str(path)


def clear_run_dir(spark, output: str, run_id: str):
    """Delete only <output>/run_id=<id>, rebuilt from the validated parts."""
    jvm = spark.sparkContext._jvm
    run_dir = jvm.org.apache.hadoop.fs.Path(run_dir_of(output, run_id))
    fs = run_dir.getFileSystem(spark.sparkContext._jsc.hadoopConfiguration())
    if fs.exists(run_dir):
        fs.delete(run_dir, True)


def write_manifest(spark, args, run_id: str, clients: int, counts, manifest_path: str):
    """Write run_id=<id>/_manifest.json last, from the Hadoop FS (copied from payments)."""
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    run_dir = jvm.org.apache.hadoop.fs.Path(run_dir_of(args.output, run_id))
    fs = run_dir.getFileSystem(conf)
    per_dt = {}
    for row in counts:
        files = [
            f
            for f in fs.listStatus(jvm.org.apache.hadoop.fs.Path(run_dir, f"dt={row['dt']}"))
            if f.getPath().getName().startswith("part-")
        ]
        per_dt[row["dt"]] = {
            "events": row["count"],
            "objects": len(files),
            "bytes": sum(f.getLen() for f in files),
        }
    body = {
        "run_id": run_id,
        "now": args.now,
        "events": sum(v["events"] for v in per_dt.values()),
        "clients": clients,
        "congestion": args.congestion,
        "per_dt": per_dt,
        "source": SOURCE,
    }
    data = bytearray(json.dumps(body, sort_keys=True).encode("utf-8"))  # before create
    stream = fs.create(jvm.org.apache.hadoop.fs.Path(manifest_path), True)
    stream.write(data)
    stream.close()
    print(f"[generate] manifest {manifest_path}")


if __name__ == "__main__":
    main()
