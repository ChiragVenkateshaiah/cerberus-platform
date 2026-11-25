"""Fakes for the AWS clients and sources. No boto3, no network."""

import io
import json
import shutil
import urllib.error
from pathlib import Path

from cerberus_console import aws, queries
from cerberus_console.sources import Sources

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_ACCOUNT = "1" * 12  # built at runtime: no account-ID-shaped literal in the repo


def load(*parts):
    return json.loads(FIXTURES.joinpath(*parts).read_text())


def materialize_runs(dst: Path, src: Path = FIXTURES / "runs") -> Path:
    """Copy record fixtures, filling the @ACCT@ placeholder with a fake account ID."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.json"):
        dst.joinpath(f.name).write_text(f.read_text().replace("@ACCT@", FAKE_ACCOUNT))
    return dst


def copy_records(dst: Path, *names: str) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(FIXTURES / "runs" / f"{name}.json", dst / f"{name}.json")
    return dst


class FakeSfnClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def list_executions(self, **kw):
        self.calls.append(("list_executions", kw))
        if self.fail:
            raise self.fail
        return load("sfn", "list_executions.json")

    def get_execution_history(self, **kw):
        self.calls.append(("get_execution_history", kw))
        if self.fail:
            raise self.fail
        arn = kw["executionArn"]
        return load("sfn", "history_failed.json" if "20261008" in arn else "history_running.json")


class FakeAthenaClient:
    """Runs a query through `polls` RUNNING answers, then ends in `final`."""

    def __init__(self, rows="freshness_rows.json", polls=1, final="SUCCEEDED"):
        self.rows, self.polls, self.final = rows, polls, final
        self.calls = []

    def start_query_execution(self, **kw):
        self.calls.append(("start_query_execution", kw))
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, **kw):
        self.calls.append(("get_query_execution", kw))
        if self.polls > 0:
            self.polls -= 1
            state = "RUNNING"
        else:
            state = self.final
        return {
            "QueryExecution": {
                "Status": {"State": state},
                "Statistics": {"DataScannedInBytes": 24680},
            }
        }

    def get_query_results(self, **kw):
        self.calls.append(("get_query_results", kw))
        return load("athena", self.rows)

    def stop_query_execution(self, **kw):
        self.calls.append(("stop_query_execution", kw))
        return {}


class Clock:
    """A fake monotonic clock that advances when the code sleeps."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def aws_sources(runs_dir, sfn_client=None, athena_client=None, clock=None) -> Sources:
    clock = clock or Clock()
    sfn = aws.AwsStepFunctionsReader(sfn_client or FakeSfnClient(), "arn-not-used", clock)
    fresh = aws.AwsFreshnessReader(athena_client or FakeAthenaClient(), clock, clock.sleep)
    return Sources(runs_dir, lambda: sfn, lambda: fresh)


class Boom(Exception):
    pass


class ExplodingSfn:
    def list_executions(self):
        raise Boom("arn:aws:states:us-east-1:" + FAKE_ACCOUNT + ":execution:x boom")

    def current_state(self, arn):
        raise Boom("boom")

    def execution_detail(self, arn):
        raise Boom("boom")


class ExplodingFresh:
    def gold_freshness(self):
        raise Boom("boom")


def forbidden_factory():
    raise AssertionError("this command must not touch any source")


# ---- AMP -------------------------------------------------------------------

AMP_FIXTURES = FIXTURES / "amp"


def amp_body(name: str) -> bytes:
    return (AMP_FIXTURES / f"{name}.json").read_bytes()


class FakeResponse:
    """What urlopen returns: a context manager with `status` and a capped `read`."""

    def __init__(self, body: bytes, status: int = 200):
        self.body, self.status = body, status
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        self.read_sizes.append(n)
        return self.body if n < 0 else self.body[:n]


class FakeOpener:
    """Answers each call with the next item: bytes (HTTP 200), an int (an HTTP error code),
    or an exception to raise. The last item repeats. Records (url, timeout, headers)."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = []
        self.responses = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.full_url, timeout, dict(req.header_items())))
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            raise urllib.error.HTTPError(req.full_url, item, "err", {}, io.BytesIO(b"x"))
        resp = FakeResponse(item)
        self.responses.append(resp)
        return resp


def amp_reader(opener, clock=None, query_set=None):
    """An AwsAmpReader over a fake opener and a fake signer. No botocore, no network."""
    clock = clock or Clock()
    return aws.AwsAmpReader(
        lambda url: {"Authorization": "fake"},
        "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-test/",
        query_set if query_set is not None else queries.by_name(queries.load()),
        opener=opener,
        clock=clock,
        sleep=clock.sleep,
    )


def series(value, step=None, execution=None):
    return {"step": step, "execution": execution, "value": value}


class FakeAmp:
    """Reader fake: `results` maps a query name to its series list (default: no series)."""

    def __init__(self, results=None):
        self.results = results or {}
        self.asked = []

    def query(self, name):
        self.asked.append(name)
        return self.results.get(name, [])


class ExplodingAmp:
    def query(self, name):
        raise Boom("boom")
