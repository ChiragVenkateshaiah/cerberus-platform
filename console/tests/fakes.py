"""Fakes for the AWS clients and sources. No boto3, no network."""

import json
import shutil
from pathlib import Path

from cerberus_console import aws
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
