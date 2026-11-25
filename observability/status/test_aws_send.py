"""Tests for the AWS send path (PR D): fake AMP, STS and Step Functions clients.

No AWS and no network. botocore is needed only by the test that checks the real
SigV4 signature; it skips cleanly when botocore is not installed (CI installs
requirements-dev only). Run: pytest observability/status
"""

import ast
import copy
import inspect
import io
import json
import math
import textwrap
import urllib.error
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import aws_send
import publish
import pytest
import remote_write
import series

HERE = Path(__file__).parent
AT = "2026-11-20T12:00:00Z"
ENDPOINT = "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-fake/"
FAILED_RUN = "exercise-20261008T085728Z"
RECORD_END = series.epoch("2026-10-08T09:23:05.061000+00:00")


class Creds:
    access_key, secret_key, token = "AKIDFAKE", "secretfake", None

    def get_frozen_credentials(self):
        return self


class FakeAmp:
    def __init__(self, workspaces=None):
        self.calls = []
        self.workspaces = (
            [{"alias": "cerberus-platform", "workspaceId": "ws-fake"}]
            if workspaces is None
            else workspaces
        )

    def list_workspaces(self, **kwargs):
        self.calls.append(kwargs)
        return {"workspaces": self.workspaces}


class FakeSts:
    def get_caller_identity(self):
        return {"Account": "ACCT"}


class FakePaginator:
    def __init__(self, events):
        self.events = events
        self.arns = []

    def paginate(self, executionArn):
        self.arns.append(executionArn)
        yield {"events": self.events[:5]}  # two pages, as a long history returns
        yield {"events": self.events[5:]}


class FakeSfn:
    def __init__(self, described, events):
        self.described, self.paginator, self.arns = described, FakePaginator(events), []

    def describe_execution(self, executionArn):
        self.arns.append(executionArn)
        return self.described

    def get_paginator(self, name):
        assert name == "get_execution_history"
        return self.paginator


class FakeSession:
    def __init__(self, amp=None, sfn=None):
        self.amp, self.sfn, self.sts = amp or FakeAmp(), sfn, FakeSts()

    def client(self, name, config=None):
        self.configs = getattr(self, "configs", {}) | {name: config}
        return {"amp": self.amp, "sts": self.sts, "stepfunctions": self.sfn}[name]

    def get_credentials(self):
        return Creds()


class Reply:
    def __init__(self, status, body):
        self.status, self.body = status, body.encode() if isinstance(body, str) else body

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def vector(value):
    return json.dumps(
        {
            "status": "success",
            "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, str(value)]}]},
        }
    )


EMPTY = json.dumps({"status": "success", "data": {"resultType": "vector", "result": []}})


class Net:
    """urlopen stand-in. `write` and `queries` script the replies in order."""

    def __init__(self):
        self.write = [Reply(204, "")]
        self.guard = [Reply(200, EMPTY)]
        self.smoke = []
        self.seen = []  # (method, path, promql or None, request)

    def __call__(self, req, timeout=None):
        assert timeout == aws_send.TIMEOUT
        parts = urlsplit(req.full_url)
        promql = parse_qs(parts.query).get("query", [None])[0]
        self.seen.append((req.get_method(), parts.path, promql, req))
        if parts.path.endswith("/remote_write"):
            queue = self.write
        elif promql == aws_send.GUARD_QUERY:
            queue = self.guard
        else:
            queue = self.smoke
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        if item.status >= 400:
            raise urllib.error.HTTPError(req.full_url, item.status, "x", {}, io.BytesIO(item.body))
        return item

    def paths(self):
        return [(m, p.rsplit("/", 1)[-1]) for m, p, _, _ in self.seen]


@pytest.fixture
def net(monkeypatch):
    fake = Net()
    monkeypatch.setattr(aws_send.urllib.request, "urlopen", fake)
    monkeypatch.setattr(aws_send, "RETRY_PAUSE", 0)
    monkeypatch.setattr(aws_send, "SMOKE_PAUSE", 0)
    monkeypatch.setattr(aws_send, "SMOKE_POLLS", 2)
    # Unsigned stand-in so these tests do not need botocore.
    monkeypatch.setattr(
        aws_send.Target,
        "_request",
        lambda self, method, url, body, headers: aws_send.urllib.request.Request(
            url, data=body, headers=dict(headers or {}), method=method
        ),
    )
    return fake


@pytest.fixture
def session(monkeypatch):
    sess = FakeSession()
    monkeypatch.setattr(aws_send, "make_session", lambda: sess)
    return sess


def run(capsys, *argv):
    code = publish.main(list(argv))
    out = capsys.readouterr()
    return code, out.out.splitlines(), out.err


def record_file(tmp_path, end="2026-10-08T09:23:05.061000+00:00"):
    record = json.loads((HERE.parent / "scale" / "runs" / f"{FAILED_RUN}.json").read_text())
    record["end"] = end
    path = tmp_path / "r.json"
    path.write_text(json.dumps(record))
    return str(path)


def headers(req):
    return {k.lower(): v for k, v in req.header_items()}


# --- the signed request --------------------------------------------------------


def test_signed_request_has_sigv4_for_aps(capsys, monkeypatch):
    pytest.importorskip("botocore")
    sess = FakeSession()
    monkeypatch.setattr(aws_send, "make_session", lambda: sess)
    fake = Net()
    monkeypatch.setattr(aws_send.urllib.request, "urlopen", fake)
    code, lines, err = run(capsys, "start", "--execution", "e1", "--at", AT, "--send")
    assert code == 0 and len(lines) == 2 and "HTTP 204" in err
    assert sess.amp.calls == [{"alias": "cerberus-platform"}]
    method, path, _, req = fake.seen[0]
    assert method == "POST" and req.full_url == ENDPOINT + "api/v1/remote_write"
    h = headers(req)
    assert "/us-east-1/aps/aws4_request" in h["authorization"]
    assert h["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDFAKE/")
    for name, value in remote_write.HEADERS.items():
        assert h[name.lower()] == value
    assert req.data  # the snappy body


def test_no_workspace_id_in_the_code():
    assert "ws-" not in (HERE / "aws_send.py").read_text()


@pytest.mark.parametrize("found", [0, 2])
def test_workspace_must_match_one_alias(capsys, net, monkeypatch, found):
    one = {"alias": "cerberus-platform", "workspaceId": "ws-fake"}
    sess = FakeSession(FakeAmp([one] * found))
    monkeypatch.setattr(aws_send, "make_session", lambda: sess)
    code, _, err = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 1 and "alias" in err and net.seen == []


# --- retries and failures ------------------------------------------------------


def test_non_2xx_exits_1_with_first_200_chars(capsys, net, session):
    net.write = [Reply(403, "denied " * 100)]
    code, _, err = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 1 and "HTTP 403" in err
    assert ("denied " * 100)[:200] in err and ("denied " * 100)[:201] not in err
    assert len(net.seen) == 1  # a 4xx is not retried


def test_429_is_retried_once_and_400_is_not(capsys, net, session):
    net.write = [Reply(429, "slow down"), Reply(204, "")]
    code, _, _ = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 0 and len(net.seen) == 2
    net.seen.clear()
    net.write = [Reply(400, "bad")]
    code, _, err = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 1 and "HTTP 400" in err and len(net.seen) == 1


def test_errors_redact_twelve_digit_runs():
    err = aws_send.AwsError("role arn:aws:iam::" + "1" * 12 + ":role/x and " + "2" * 13)
    assert "1" * 12 not in str(err) and "<ACCOUNT_ID>" in str(err)
    assert "2" * 13 in str(err)  # 13 digits is not an account ID


def test_clients_have_short_timeouts(session):
    pytest.importorskip("botocore")
    aws_send.client(session, "amp")
    cfg = session.configs["amp"]
    assert cfg.connect_timeout == 3 and cfg.read_timeout == 8
    assert cfg.retries["max_attempts"] == 2


def test_5xx_is_tried_twice(capsys, net, session):
    net.write = [Reply(503, "busy")]
    code, _, err = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 1 and "2 attempts" in err and "busy" in err
    assert len(net.seen) == 2


def test_timeout_then_success_is_two_attempts(capsys, net, session):
    net.write = [TimeoutError("timed out"), Reply(204, "")]
    code, _, err = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 0 and len(net.seen) == 2 and "HTTP 204" in err


# --- newest-run guard ----------------------------------------------------------


def test_guard_refuses_an_older_run(capsys, net, session, tmp_path):
    net.guard = [Reply(200, vector(RECORD_END + 1000))]
    path = record_file(tmp_path)
    code, _, err = run(capsys, "end", "--execution", FAILED_RUN, "--record", path, "--send")
    assert code == 2 and "--force" in err and len(err.strip().splitlines()) == 1
    assert net.paths() == [("GET", "query")]  # no write
    assert net.seen[0][2] == aws_send.GUARD_QUERY


def test_guard_passes_when_stored_is_older(capsys, net, session, tmp_path):
    net.guard = [Reply(200, vector(RECORD_END - 1000))]
    code, _, err = run(
        capsys, "end", "--execution", FAILED_RUN, "--record", record_file(tmp_path), "--send"
    )
    assert code == 0 and net.paths() == [("GET", "query"), ("POST", "remote_write")]


def test_guard_passes_when_amp_has_no_run(capsys, net, session, tmp_path):
    code, _, _ = run(
        capsys, "end", "--execution", FAILED_RUN, "--record", record_file(tmp_path), "--send"
    )
    assert code == 0 and net.paths() == [("GET", "query"), ("POST", "remote_write")]


def test_force_skips_the_guard(capsys, net, session, tmp_path):
    net.guard = [Reply(200, vector(RECORD_END + 1000))]
    code, _, _ = run(
        capsys,
        "end",
        "--execution",
        FAILED_RUN,
        "--record",
        record_file(tmp_path),
        "--send",
        "--force",
    )
    assert code == 0 and net.paths() == [("POST", "remote_write")]


def test_guard_failure_warns_and_continues(capsys, net, session, tmp_path):
    net.guard = [Reply(403, "no aps:QueryMetrics")]
    code, _, err = run(
        capsys, "end", "--execution", FAILED_RUN, "--record", record_file(tmp_path), "--send"
    )
    assert code == 0 and "warning" in err and "guard skipped" in err
    assert net.paths() == [("GET", "query"), ("POST", "remote_write")]


def test_guard_garbage_reply_warns_and_continues(capsys, net, session, tmp_path):
    net.guard = [Reply(200, "not json")]
    code, _, err = run(
        capsys, "end", "--execution", FAILED_RUN, "--record", record_file(tmp_path), "--send"
    )
    assert code == 0 and "guard skipped" in err


def test_start_has_no_guard(capsys, net, session):
    code, _, _ = run(capsys, "start", "--execution", "e1", "--send")
    assert code == 0 and net.paths() == [("POST", "remote_write")]


# --- Step Functions fallback ---------------------------------------------------


def load_history(name="history_failed_catch.json"):
    data = json.loads((HERE / "fixtures" / name).read_text())
    stamp = datetime.fromisoformat
    execution = {
        **data["execution"],
        "startDate": stamp(data["execution"]["startDate"]),
        "stopDate": stamp(data["execution"]["stopDate"]),
    }
    events = [{**e, "timestamp": stamp(e["timestamp"])} for e in data["events"]]
    return execution, events


def test_fixture_has_the_real_event_order():
    _, events = load_history()
    assert [e["type"] for e in events] == [
        "ExecutionStarted",
        "TaskStateEntered", "TaskStateExited",
        "TaskStateEntered", "TaskStateExited",
        "TaskStateEntered", "TaskFailed", "TaskFailed", "TaskFailed", "TaskStateExited",
        "FailStateEntered", "ExecutionFailed",
    ]  # fmt: skip


def test_fallback_record_from_a_failed_catch_history():
    described, events = load_history()
    sess = FakeSession(sfn=FakeSfn(described, events))
    record = aws_send.record_from_history(sess, "exec-1")
    assert sess.sfn.arns == [
        "arn:aws:states:us-east-1:ACCT:execution:cerberus-platform-orchestration:exec-1"
    ]
    assert record["failed_state"] == "RunDbt"  # not PipelineFailed
    assert record["status"] == "FAILED" and record["run_seconds"] == 571.9
    assert [s["state"] for s in record["states"]] == ["InvokeIngestion", "RunTransform", "RunDbt"]
    assert [s["seconds"] for s in record["states"]] == [3.6, 226.7, 341.3]
    assert record["events_processed"] is None and record["data_quality"] is None
    assert record["start"].startswith("2026-10-08T09:13:33") and record["end"].endswith("+00:00")
    rows = {(n, tuple(lab.items())): v for n, lab, v in series.end_series(record)}
    assert rows[("cerberus_run_step_failed", (("step", "RunDbt"),))] == 1
    assert math.isnan(rows[("cerberus_run_events_processed", ())])
    assert math.isnan(rows[("cerberus_dq_errors", ())])


def events_upto(last_id):
    described, events = load_history()
    return described, [e for e in events if e["id"] <= last_id]


def test_aborted_during_a_state_names_it():
    described, events = events_upto(6)  # RunDbt entered, never exited
    record = aws_send.record_from_events("e", {**described, "status": "ABORTED"}, events)
    assert record["failed_state"] == "RunDbt"
    assert [s["state"] for s in record["states"]] == ["InvokeIngestion", "RunTransform"]


def test_aborted_between_states_names_none():
    described, events = events_upto(5)  # RunTransform exited, next state not entered
    record = aws_send.record_from_events("e", {**described, "status": "ABORTED"}, events)
    assert record["failed_state"] is None
    assert series.failed_step(record) is None  # ABORTED never uses the states[] fallback


def test_timed_out_follows_the_same_rule():
    described, events = events_upto(6)
    record = aws_send.record_from_events("e", {**described, "status": "TIMED_OUT"}, events)
    assert record["failed_state"] == "RunDbt"


def test_aborted_before_any_state_names_none():
    described, events = events_upto(1)
    record = aws_send.record_from_events("e", {**described, "status": "ABORTED"}, events)
    assert record["failed_state"] is None


def test_succeeded_history_has_no_failed_state():
    described, events = load_history()
    record = aws_send.record_from_events("e", {**described, "status": "SUCCEEDED"}, events)
    assert record["failed_state"] is None


def test_running_execution_is_refused():
    described, events = load_history()
    del described["stopDate"]
    described["status"] = "RUNNING"
    with pytest.raises(aws_send.AwsError, match="has not ended"):
        aws_send.record_from_history(FakeSession(sfn=FakeSfn(described, events)), "e")


def test_end_send_falls_back_when_the_record_is_missing(capsys, net, monkeypatch, tmp_path):
    described, events = load_history()
    sess = FakeSession(sfn=FakeSfn(copy.deepcopy(described), events))
    monkeypatch.setattr(aws_send, "make_session", lambda: sess)
    monkeypatch.setattr(publish, "RUNS", tmp_path)  # no record file here
    code, lines, err = run(capsys, "end", "--execution", "exec-1", "--at", AT, "--send")
    assert code == 0 and net.paths() == [("GET", "query"), ("POST", "remote_write")]
    assert 'cerberus_run_step_failed{step="RunDbt"} 1 ' in "\n".join(lines)
    assert any(line.startswith("cerberus_dq_errors NaN") for line in lines)
    assert "ACCT" not in err and "ACCT" not in "\n".join(lines)  # the account is never printed


def test_missing_record_without_send_stays_an_error(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(aws_send, "make_session", lambda: pytest.fail("no AWS in a dry run"))
    monkeypatch.setattr(publish, "RUNS", tmp_path)
    code, lines, err = run(capsys, "end", "--execution", "exec-1")
    assert code == 2 and lines == [] and "cannot read" in err


def test_explicit_missing_record_does_not_fall_back(capsys, session, net, tmp_path):
    code, _, err = run(
        capsys, "end", "--execution", "e", "--send", "--record", str(tmp_path / "none.json")
    )
    assert code == 2 and "cannot read" in err and net.seen == []


# --- dry run, --url, smoke -----------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["start", "--execution", "e1", "--at", AT],
        ["end", "--execution", FAILED_RUN, "--at", AT],
        ["smoke", "--at", AT],
    ],
)
def test_dry_run_makes_no_aws_call(capsys, monkeypatch, argv):
    monkeypatch.setattr(aws_send, "make_session", lambda: pytest.fail("AWS session built"))
    monkeypatch.setattr(aws_send, "Target", lambda *a: pytest.fail("AMP target built"))
    monkeypatch.setattr(aws_send.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    code, lines, err = run(capsys, *argv)
    assert code == 0 and lines and "not sent" in err


@pytest.mark.parametrize("command", ["start", "end"])
def test_send_and_url_together_exit_2(capsys, monkeypatch, command):
    monkeypatch.setattr(aws_send, "make_session", lambda: pytest.fail("AWS session built"))
    monkeypatch.setattr(publish, "send", lambda *a: pytest.fail("must not send"))
    code, lines, err = run(
        capsys, command, "--execution", "e1", "--send", "--url", "http://127.0.0.1:1/w"
    )
    assert code == 2 and lines == [] and "cannot be used together" in err


def test_smoke_dry_run_prints_one_sample(capsys):
    code, lines, err = run(capsys, "smoke", "--at", AT)
    assert code == 0 and "not sent" in err
    ms = publish.publish_ms(AT)
    # The execution label is the UTC stamp of the publish time (AT is 12:00:00Z).
    assert lines == [
        'cerberus_publisher_smoke{execution="smoke-20261120T120000Z"} '
        f"{publish.fmt_value(ms / 1000)} {ms}"
    ]


def test_smoke_value_is_the_publish_time_and_query_is_not_timestamp():
    assert "timestamp(" not in aws_send.SMOKE_QUERY
    assert series.epoch(AT) == publish.publish_ms(AT) / 1000


def test_smoke_url_is_loopback_only(capsys):
    code, lines, err = run(capsys, "smoke", "--url", "http://example.com/w")
    assert code == 2 and lines == [] and "--url must be http" in err


def test_smoke_send_writes_then_reads_back(capsys, net, session):
    net.smoke = [Reply(200, vector(publish.publish_ms(AT) / 1000))]
    code, lines, err = run(capsys, "smoke", "--at", AT, "--send")
    assert code == 0 and len(lines) == 1 and "read back" in err
    assert net.paths() == [("POST", "remote_write"), ("GET", "query")]
    assert net.seen[1][2] == aws_send.SMOKE_QUERY


def test_smoke_not_visible_exits_1(capsys, net, session):
    net.smoke = [Reply(200, EMPTY)]
    code, _, err = run(capsys, "smoke", "--at", AT, "--send")
    assert code == 1 and "not visible" in err
    assert net.paths() == [("POST", "remote_write"), ("GET", "query"), ("GET", "query")]


def test_smoke_sample_from_an_older_write_is_not_a_read_back(capsys, net, session):
    net.smoke = [Reply(200, vector(publish.publish_ms(AT) / 1000 - 60))]
    code, _, err = run(capsys, "smoke", "--at", AT, "--send")
    assert code == 1 and "not visible" in err


def _rule_body(source, name):
    """The AST of a function body without its docstring."""
    func = next(
        n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    return ast.dump(ast.Module(body=func.body[1:], type_ignores=[]))


def test_failed_state_rule_matches_the_collector():
    # The rule is written twice (the collector imports boto3 and has no CI job).
    # This keeps the two copies from drifting apart.
    collector = (HERE.parent / "scale" / "collect_run_metrics.py").read_text()
    mine = textwrap.dedent(inspect.getsource(aws_send.failed_state))
    assert _rule_body(collector, "last_state") == _rule_body(mine, "failed_state")
