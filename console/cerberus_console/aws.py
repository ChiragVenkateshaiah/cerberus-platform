"""The boto3 implementations of the source protocols. The only file that imports boto3.

boto3 is imported inside the two functions that build clients, so the tests
(which pass fake clients) need pytest only. Calls are bounded: short timeouts,
two attempts, and an in-process cache per reader (ListExecutions 30 s, the
freshness query 300 s plus a 60 s negative cache) so a flood of visitors costs
a handful of calls, not a bill.

The IAM role this runs as (cerberus-console-cli) can read Step Functions, run
the one workgroup's queries and write one results prefix. Nothing here relies on
that: the code only ever calls the read APIs named below.
"""

import contextlib
import logging
import time
from datetime import UTC, datetime

from cerberus_console import config
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


def build_sources(session=None, state_machine_arn: str | None = None) -> Sources:
    """Sources over a session. Readers (and their caches) are built once, on first use.

    `session` is a zero-argument callable returning a boto3 session, or None for
    the default credential chain (the Lambda's role). The state machine ARN comes
    from the caller (the Lambda's environment) or from the session's account.
    """
    built: dict = {}

    def clients():
        if not built:
            import boto3
            from botocore.config import Config

            cfg = Config(
                connect_timeout=3,
                read_timeout=8,
                retries={"max_attempts": 2, "mode": "standard"},
            )
            sess = session() if session else boto3.Session(region_name=config.REGION)
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
    )
