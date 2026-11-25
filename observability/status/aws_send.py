"""AWS side of the status publisher (plan 10.2, PR D). The only module that may
use boto3 or botocore; both load inside functions, so the dry
run and the --url path never load them.

  - endpoint: the workspace is found by its alias at run time. No workspace ID
    and no account ID is written in the repo.
  - remote write and query: SigV4 for service `aps`, credentials from the
    default chain (the caller sets AWS_PROFILE). 5 s timeout, 2 attempts.
  - newest-run guard and smoke read-back: PromQL through the query API.
  - fallback record: built from Step Functions when the run record is missing.
    The state machine ARN uses the STS account ID read at run time.
"""

import json
import re
import time
import urllib.error
import urllib.request
from datetime import UTC
from urllib.parse import quote, urlencode

import remote_write

REGION = "us-east-1"
ALIAS = "cerberus-platform"
STATE_MACHINE = "cerberus-platform-orchestration"
TIMEOUT = 5  # seconds, per attempt
ATTEMPTS = 2
RETRY_PAUSE = 1.0  # seconds between attempts
READ_MAX = 1 << 20  # bytes of a reply kept; a query reply is small
GUARD_QUERY = "max(last_over_time(cerberus_execution_finished_timestamp_seconds[30d]))"
# The sample value is the publish time in seconds (timestamp() returns the query
# time, not the sample time, so it cannot prove the write).
SMOKE_QUERY = "last_over_time(cerberus_publisher_smoke[10m])"
SMOKE_POLLS = 6
SMOKE_PAUSE = 5.0  # seconds between read-back polls


class AwsError(Exception):
    """A failed AWS step; the message is safe to print (12-digit runs redacted)."""

    def __init__(self, message):
        super().__init__(re.sub(r"\b\d{12}\b", "<ACCOUNT_ID>", str(message)))


def make_session():
    import boto3  # lazy: only the --send paths reach here

    return boto3.Session(region_name=REGION)


def client(session, name):
    """A boto3 client with short timeouts and 2 attempts (as console/aws.py)."""
    try:
        from botocore.config import Config
    except ImportError:  # only a unit test with a fake session gets here
        return session.client(name)

    cfg = Config(connect_timeout=3, read_timeout=8, retries={"max_attempts": 2, "mode": "standard"})
    return session.client(name, config=cfg)


class Target:
    """One AMP workspace, found by alias, with a session to sign requests."""

    def __init__(self, session):
        self.session = session
        try:
            found = client(session, "amp").list_workspaces(alias=ALIAS)["workspaces"]
        except Exception as err:  # botocore errors; the message is the diagnosis
            raise AwsError(f"cannot list AMP workspaces: {err}") from err
        found = [w for w in found if w.get("alias") == ALIAS]
        if len(found) != 1:
            raise AwsError(f"expected 1 AMP workspace with alias {ALIAS!r}, found {len(found)}")
        # list_workspaces returns summaries without prometheusEndpoint (only
        # describe_workspace has it), so build the URL from the workspace id, as
        # observability/scale/collect_run_metrics.py does.
        self.base = (
            f"https://aps-workspaces.{REGION}.amazonaws.com/workspaces/{found[0]['workspaceId']}/"
        )

    def _request(self, method, url, body, headers):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        signed = AWSRequest(method=method, url=url, data=body, headers=dict(headers or {}))
        creds = self.session.get_credentials()
        if creds is None:
            raise AwsError("no AWS credentials found")
        SigV4Auth(creds.get_frozen_credentials(), "aps", REGION).add_auth(signed)
        return urllib.request.Request(url, data=body, headers=dict(signed.headers), method=method)

    def call(self, method, url, body=None, headers=None):
        """Signed request, 2 attempts. Returns (HTTP status, reply text)."""
        last = "no attempt"
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(RETRY_PAUSE)
            req = self._request(method, url, body, headers)  # signed again each time
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    return resp.status, resp.read(READ_MAX).decode("utf-8", "replace")
            except urllib.error.HTTPError as err:
                status, reply = err.code, err.read(READ_MAX).decode("utf-8", "replace")
                if status != 429 and status < 500:
                    return status, reply  # another 4xx will not change on a retry
                last = f"HTTP {status}: {reply[:200]}"
            except (OSError, ValueError) as err:  # URLError and timeouts are OSError
                last = str(err)
        raise AwsError(f"request failed after {ATTEMPTS} attempts: {last}")

    def write(self, body):
        """POST one remote-write body. Returns (HTTP status, first 200 chars)."""
        status, reply = self.call(
            "POST", self.base + "api/v1/remote_write", body, remote_write.HEADERS
        )
        return status, reply[:200]

    def query(self, promql):
        """Instant query. Returns the result list; raises AwsError on any failure."""
        # quote_via=quote: SigV4 signs %20, and urlencode's default '+' fails it.
        url = self.base + "api/v1/query?" + urlencode({"query": promql}, quote_via=quote)
        status, reply = self.call("GET", url)
        if not 200 <= status < 300:
            raise AwsError(f"query replied HTTP {status}: {reply[:200]}")
        try:
            data = json.loads(reply)
            if data["status"] != "success":
                raise AwsError(f"query status {data['status']!r}")
            return data["data"]["result"]
        except (ValueError, KeyError, TypeError) as err:
            raise AwsError(f"unreadable query reply: {err}") from err


def _scalar(result):
    """The one value of an instant-query result as a float, or None if empty."""
    return float(result[0]["value"][1]) if result else None


def newest_finished(target):
    """Newest stored run end (epoch seconds), or None when AMP holds no run."""
    return _scalar(target.query(GUARD_QUERY))


def read_back_smoke(target, ts_ms):
    """True when the smoke sample written at `ts_ms` is visible. Polls a few times."""
    for poll in range(SMOKE_POLLS):
        if poll:
            time.sleep(SMOKE_PAUSE)
        stored = _scalar(target.query(SMOKE_QUERY))
        if stored is not None and abs(stored - ts_ms / 1000) < 0.001:
            return True
    return False


def _iso(dt):
    return dt.astimezone(UTC).isoformat()


def record_from_history(session, execution):
    """A run record from Step Functions, for a run whose record file is missing.

    Events and data quality are unknown (None, so the series are NaN). Raises
    AwsError when the execution is unknown or still running.
    """
    try:
        account = client(session, "sts").get_caller_identity()["Account"]
        arn = f"arn:aws:states:{REGION}:{account}:execution:{STATE_MACHINE}:{execution}"
        sfn = client(session, "stepfunctions")
        described = sfn.describe_execution(executionArn=arn)
        pages = sfn.get_paginator("get_execution_history").paginate(executionArn=arn)
        events = [event for page in pages for event in page["events"]]
    except Exception as err:  # botocore errors
        raise AwsError(f"cannot read the execution from Step Functions: {err}") from err
    if "stopDate" not in described:
        raise AwsError(f"execution {execution} has not ended (status {described['status']})")
    return record_from_events(execution, described, events)


def failed_state(status, last_entered, exited):
    """The step a run ended in, or None. Same rule as the collector.

    FAILED names the last entered state (a Catch makes it exit; FailStateEntered
    is not a task). ABORTED and TIMED_OUT name it only if it never exited.
    """
    if status == "SUCCEEDED" or not last_entered:
        return None
    return last_entered if status == "FAILED" or last_entered not in exited else None


def record_from_events(execution, described, events):
    """Pure part of the fallback: describe_execution output and events -> record."""
    start, end = described["startDate"], described["stopDate"]
    status = described["status"]
    entered, exited, states, last_entered = {}, set(), [], None
    for event in events:
        if event["type"] == "TaskStateEntered":
            name = event["stateEnteredEventDetails"]["name"]
            entered[name] = event["timestamp"]
            last_entered = name
        elif event["type"] == "TaskStateExited":
            name = event["stateExitedEventDetails"]["name"]
            exited.add(name)
            if name in entered:
                seconds = (event["timestamp"] - entered[name]).total_seconds()
                states.append({"state": name, "seconds": round(seconds, 1)})
    return {
        "execution": execution,
        "status": status,
        "start": _iso(start),
        "end": _iso(end),
        "run_seconds": round((end - start).total_seconds(), 1),
        "states": states,
        "failed_state": failed_state(status, last_entered, exited),
        "events_processed": None,
        "data_quality": None,
    }
