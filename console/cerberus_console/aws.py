"""The boto3 implementations of the source protocols. The only file that imports boto3.

boto3 and botocore are imported inside functions, so the tests
(which pass fake clients) need pytest only. Calls are bounded: short timeouts,
two attempts, and an in-process cache per reader (ListExecutions 30 s, the
freshness query 300 s plus a 60 s negative cache) so a flood of visitors costs
a handful of calls, not a bill.

The IAM role this runs as (cerberus-console-cli) can read Step Functions, run
the one workgroup's queries and write one results prefix. Nothing here relies on
that: the code only ever calls the read APIs named below.
"""

import contextlib
import json
import logging
import math
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlsplit

from cerberus_console import config, queries, sanitize
from cerberus_console.sources import Sources, Unavailable

log = logging.getLogger(__name__)


class TTLCache:
    """Caches successes for `ttl` seconds.

    With `negative_ttl` > 0 a failure is also remembered: the first call raises
    the original error, later calls raise Unavailable without calling the loader
    until `negative_ttl` seconds pass.
    """

    def __init__(self, ttl: float, clock=time.monotonic, negative_ttl: float = 0):
        self._ttl = ttl
        self._clock = clock
        self._negative_ttl = negative_ttl
        self._items: dict = {}
        self._failures: dict = {}

    def get_or_set(self, key, fn):
        hit = self._items.get(key)
        now = self._clock()
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        failed_at = self._failures.get(key)
        if failed_at is not None:
            if now - failed_at < self._negative_ttl:
                raise Unavailable
            del self._failures[key]
        try:
            value = fn()
        except Exception:
            if self._negative_ttl > 0:
                self._failures[key] = self._clock()
            raise
        self._items[key] = (now, value)
        return value


def _dt(v) -> datetime | None:
    """Always tz-aware UTC: boto3 returns local-tz datetimes; naive means UTC."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v.astimezone(UTC) if v.tzinfo else v.replace(tzinfo=UTC)
    return None


def _iso(v) -> str | None:
    d = _dt(v)
    return d.isoformat() if d else None


class AwsStepFunctionsReader:
    def __init__(self, client, state_machine_arn: str, clock=time.monotonic):
        self._client = client
        self._arn = state_machine_arn
        self._cache = TTLCache(config.LIST_EXECUTIONS_TTL, clock)

    def list_executions(self) -> list[dict]:
        return self._cache.get_or_set("list", self._list)

    def _list(self) -> list[dict]:
        out: list[dict] = []
        token = None
        for _ in range(config.SFN_LIST_PAGES):
            kwargs = {"stateMachineArn": self._arn, "maxResults": config.SFN_LIST_PAGE}
            if token:
                kwargs["nextToken"] = token
            page = self._client.list_executions(**kwargs)
            for ex in page.get("executions", []):
                out.append(
                    {
                        # The ARN is AWS's own answer, never built from visitor input.
                        "arn": ex.get("executionArn"),
                        "name": ex.get("name"),
                        "status": ex.get("status"),
                        "start": _iso(ex.get("startDate")),
                        "stop": _iso(ex.get("stopDate")),
                    }
                )
            token = page.get("nextToken")
            if not token:
                break
        out.sort(key=lambda e: e["start"] or "", reverse=True)
        return out

    def current_state(self, execution_arn: str) -> str | None:
        page = self._client.get_execution_history(
            executionArn=execution_arn,
            reverseOrder=True,
            maxResults=50,
            includeExecutionData=False,
        )
        for ev in page.get("events", []):
            name = (ev.get("stateEnteredEventDetails") or {}).get("name")
            if name:
                return name
        return None

    def execution_detail(self, execution_arn: str) -> dict:
        events: list[dict] = []
        token = None
        for _ in range(2):
            kwargs = {
                "executionArn": execution_arn,
                "maxResults": 500,
                "includeExecutionData": False,
            }
            if token:
                kwargs["nextToken"] = token
            page = self._client.get_execution_history(**kwargs)
            events.extend(page.get("events", []))
            token = page.get("nextToken")
            if not token:
                break
        entered: dict[str, datetime] = {}
        states: list[dict] = []
        last_state = None
        error = None
        failed_state = None
        for ev in events:
            when = _dt(ev.get("timestamp"))
            name = (ev.get("stateEnteredEventDetails") or {}).get("name")
            if name and when:
                entered[name] = when
                # A Fail state also carries stateEnteredEventDetails. Only a task
                # names the step a run failed in, so FailStateEntered is skipped.
                if ev.get("type") != "FailStateEntered":
                    last_state = name
            name = (ev.get("stateExitedEventDetails") or {}).get("name")
            if name and when and name in entered:
                states.append({"state": name, "seconds": (when - entered[name]).total_seconds()})
            failed = ev.get("executionFailedEventDetails")
            if failed is not None:
                # Only the error code. The cause text is never read or shown.
                error = str(failed.get("error") or "")[: config.ERROR_CODE_CHARS]
                failed_state = last_state
        return {"states": states, "failed_state": failed_state, "error": error}


class AwsFreshnessReader:
    """Runs the one fixed freshness query and reads its three rows."""

    def __init__(
        self,
        client,
        clock=time.monotonic,
        sleep=time.sleep,
        deadline: float = config.QUERY_DEADLINE_SECONDS,
    ):
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._deadline = deadline
        self._cache = TTLCache(
            config.FRESHNESS_TTL, clock, negative_ttl=config.FRESHNESS_NEGATIVE_TTL
        )

    def gold_freshness(self) -> dict:
        return self._cache.get_or_set("gold", self._query)

    def _query(self) -> dict:
        qid = self._client.start_query_execution(
            QueryString=config.FRESHNESS_SQL,
            QueryExecutionContext={"Database": config.DATABASE},
            WorkGroup=config.WORKGROUP,
            ResultReuseConfiguration={
                "ResultReuseByAgeConfiguration": {
                    "Enabled": True,
                    "MaxAgeInMinutes": config.RESULT_REUSE_MINUTES,
                }
            },
        )["QueryExecutionId"]
        stop_at = self._clock() + self._deadline
        delay = config.QUERY_POLL_SECONDS
        try:
            while True:
                execution = self._client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
                state = (execution.get("Status") or {}).get("State")
                if state == "SUCCEEDED":
                    break
                if state in ("FAILED", "CANCELLED"):
                    raise Unavailable
                if self._clock() >= stop_at:
                    self._client.stop_query_execution(QueryExecutionId=qid)
                    raise Unavailable
                self._sleep(delay)
                delay = min(delay * 1.5, 2.0)
        except Unavailable:
            raise
        except Exception:
            # best effort; the original error matters more
            with contextlib.suppress(Exception):
                self._client.stop_query_execution(QueryExecutionId=qid)
            raise
        scanned = (execution.get("Statistics") or {}).get("DataScannedInBytes")
        result = self._client.get_query_results(QueryExecutionId=qid)
        rows = result.get("ResultSet", {}).get("Rows", [])[1:]  # row 0 is the header
        tables = []
        for row in rows:
            cells = [c.get("VarCharValue") for c in row.get("Data", [])]
            if len(cells) == 2:
                tables.append({"table": cells[0], "last_commit": cells[1]})
        return {"tables": tables, "bytes_scanned": scanned}


def _label(v) -> str | None:
    """One label value: a cleaned, single-line, capped string, or None."""
    if not isinstance(v, str):
        return None
    return sanitize.clean_str(v.replace("\n", " "), config.FIELD_CHARS)


def _value(raw) -> tuple[bool, float | None]:
    """(keep, value). "NaN" keeps the row with None; any other non-finite value drops it."""
    if not isinstance(raw, str) or "_" in raw:
        return False, None
    try:
        v = float(raw)
    except ValueError:
        return False, None
    if math.isnan(v):
        return True, None
    return (True, v) if math.isfinite(v) else (False, None)


def parse_vector(reply) -> list[dict]:
    """A Prometheus instant-query reply -> [{step, execution, value}]. Raises Unavailable.

    Only `metric.step`, `metric.execution` and `value[1]` are read. `__name__`
    and every other label are ignored. A non-vector result type is refused, a
    malformed row is dropped, and at most AMP_MAX_SERIES rows are read.
    """
    if not isinstance(reply, dict) or reply.get("status") != "success":
        raise Unavailable
    data = reply.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise Unavailable
    result = data.get("result")
    if not isinstance(result, list):
        raise Unavailable
    out = []
    for row in result[: config.AMP_MAX_SERIES]:
        if not isinstance(row, dict):
            continue
        metric, value = row.get("metric"), row.get("value")
        if not isinstance(metric, dict) or not isinstance(value, list) or len(value) != 2:
            continue
        keep, number = _value(value[1])
        if keep:
            out.append(
                {
                    "step": _label(metric.get("step")),
                    "execution": _label(metric.get("execution")),
                    "value": number,
                }
            )
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx becomes an HTTPError: the SigV4 headers never leave the host


# No env proxy and no redirect: the signed headers go to the configured host only.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


_AMP_PATH = re.compile(r"^/workspaces/ws-[a-z0-9-]+/?$")


def _base_ok(base: str) -> bool:
    """True only for the AMP workspace URL of this region, checked before signing.

    https, host exactly aps-workspaces.<REGION>.amazonaws.com, no port, no
    userinfo, no query or fragment, path /workspaces/ws-<id>/.
    """
    # urlsplit drops tabs and newlines, so check the raw string too: what is
    # validated must be the string that is later requested.
    if not base.isascii() or re.search(r"[\x00-\x20\x7f]", base):
        return False
    try:
        parts = urlsplit(base)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.netloc == f"aps-workspaces.{config.REGION}.amazonaws.com"
        and port is None
        and parts.username is None
        and parts.password is None
        and not parts.query
        and not parts.fragment
        and bool(_AMP_PATH.fullmatch(parts.path))
    )


class AwsAmpReader:
    """Runs the named status queries against the AMP query API, one GET each.

    `query(name)` looks the `expr` up in the loaded query set; an unknown name
    raises KeyError. No visitor input reaches a query. A reply is cached 30 s,
    a failure 60 s. The queries share one deadline (a window that opens at the
    first fetch after the cache lapsed), so about 14 sequential queries cannot
    run past AMP_DEADLINE_SECONDS.

    `sign(url)` returns the signed request headers; `opener` replaces the default
    opener (no proxy, no redirect).
    """

    def __init__(
        self,
        sign,
        base_url: str,
        query_set: dict | None = None,
        opener=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self._sign = sign
        self._base = base_url
        self._set = query_set
        self._opener = opener or _OPENER.open
        self._clock = clock
        self._sleep = sleep
        self._window: float | None = None
        self._cache = TTLCache(config.AMP_TTL, clock, negative_ttl=config.AMP_NEGATIVE_TTL)

    def query(self, name: str) -> list[dict]:
        if self._set is None:
            self._set = queries.by_name(queries.load())
        expr = self._set[name]["expr"]  # KeyError for an unknown name
        return self._cache.get_or_set(name, lambda: self._fetch(expr))

    def _remaining(self) -> float:
        now = self._clock()
        if self._window is None or now - self._window > config.AMP_TTL:
            self._window = now
        return config.AMP_DEADLINE_SECONDS - (now - self._window)

    def _fetch(self, expr: str) -> list[dict]:
        if not _base_ok(self._base):
            raise Unavailable
        # quote_via=quote: SigV4 signs %20, and urlencode's default '+' fails it.
        query = urlencode({"query": expr}, quote_via=quote)
        url = self._base.rstrip("/") + "/api/v1/query?" + query
        for attempt in range(config.AMP_ATTEMPTS):
            if attempt:
                self._sleep(config.AMP_RETRY_PAUSE_SECONDS)
            left = self._remaining()
            if left <= 0:
                raise Unavailable
            # S310: a plain https URL (checked above), built from config and a fixed expr.
            req = urllib.request.Request(url, headers=self._sign(url), method="GET")  # noqa: S310
            try:
                with self._opener(req, timeout=min(config.AMP_TIMEOUT_SECONDS, left)) as resp:
                    if not 200 <= resp.status < 300:
                        raise Unavailable
                    body = resp.read(config.AMP_READ_MAX + 1)
            except urllib.error.HTTPError as err:
                if err.code != 429 and err.code < 500:
                    raise Unavailable from None  # another 4xx will not change on a retry
                continue
            except (OSError, ValueError):  # URLError and timeouts are OSError
                continue
            if len(body) > config.AMP_READ_MAX:
                raise Unavailable  # too big: fail closed, never parse a cut reply
            try:
                reply = json.loads(body)
            except ValueError:
                raise Unavailable from None
            return parse_vector(reply)
        raise Unavailable


def _amp_signer(sess):
    """Headers for one SigV4 GET (service aps) with the session's credentials."""

    def sign(url: str) -> dict:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        creds = sess.get_credentials()
        if creds is None:
            raise Unavailable
        signed = AWSRequest(method="GET", url=url)
        SigV4Auth(creds.get_frozen_credentials(), "aps", config.REGION).add_auth(signed)
        return dict(signed.headers)

    return sign


def assumed_session():
    """A boto3 session as cerberus-console-cli, for the local CLI (ADR 0024 rule 7).

    The caller's own credentials only assume the role; every read below uses the
    role's short-lived keys, which this module never prints.
    """
    import boto3

    sts = boto3.client("sts", region_name=config.REGION)
    account = sts.get_caller_identity()["Account"]
    creds = sts.assume_role(
        RoleArn=f"arn:aws:iam::{account}:role/{config.ROLE_NAME}",
        RoleSessionName="cerberus-console-local",
        DurationSeconds=900,
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=config.REGION,
    )


def build_sources(
    session=None, state_machine_arn: str | None = None, amp_query_url: str | None = None
) -> Sources:
    """Sources over a session. Readers (and their caches) are built once, on first use.

    `session` is a zero-argument callable returning a boto3 session, or None for
    the default credential chain (the Lambda's role). The state machine ARN comes
    from the caller (the Lambda's environment) or from the session's account. The
    AMP query URL comes from the caller or from CERBERUS_AMP_QUERY_URL; without
    one the AMP reader is unavailable.
    """
    built: dict = {}
    amp_url = config.AMP_QUERY_URL if amp_query_url is None else amp_query_url

    def boto_session():
        if "session" not in built:
            if session:
                built["session"] = session()
            else:
                import boto3

                built["session"] = boto3.Session(region_name=config.REGION)
        return built["session"]

    def amp():
        if "amp" not in built:
            if not amp_url:
                raise Unavailable
            built["amp"] = AwsAmpReader(_amp_signer(boto_session()), amp_url)
        return built["amp"]

    def clients():
        if "sfn" not in built:
            from botocore.config import Config

            cfg = Config(
                connect_timeout=3,
                read_timeout=8,
                retries={"max_attempts": 2, "mode": "standard"},
            )
            sess = boto_session()
            arn = state_machine_arn
            if not arn:
                account = sess.client("sts", config=cfg).get_caller_identity()["Account"]
                arn = (
                    f"arn:aws:states:{config.REGION}:{account}:stateMachine:"
                    f"{config.STATE_MACHINE_NAME}"
                )
            built["sfn"] = AwsStepFunctionsReader(sess.client("stepfunctions", config=cfg), arn)
            built["fresh"] = AwsFreshnessReader(sess.client("athena", config=cfg))
        return built

    return Sources(
        runs_dir=config.RUNS_DIR,
        sfn_factory=lambda: clients()["sfn"],
        freshness_factory=lambda: clients()["fresh"],
        amp_factory=amp,
    )
