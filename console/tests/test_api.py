import json
import logging

import fakes
import pytest

from cerberus_console import aws, commands, records
from cerberus_console.api import dispatch, lambda_handler
from cerberus_console.sources import Sources


@pytest.fixture
def runs(tmp_path):
    return fakes.materialize_runs(tmp_path / "runs")


def event(argv, b64=False, raw=None):
    import base64

    body = raw if raw is not None else json.dumps({"argv": argv})
    if b64:
        body = base64.b64encode(body.encode()).decode()
    return {"version": "2.0", "body": body, "isBase64Encoded": b64}


def call(ev, sources):
    out = lambda_handler(ev, None, sources=sources)
    return out, json.loads(out["body"])


@pytest.mark.parametrize("b64", [False, True])
def test_lambda_handler_ok(runs, b64):
    out, body = call(event(["runs"], b64), fakes.aws_sources(runs))
    assert out["statusCode"] == 200
    assert out["headers"]["cache-control"] == "no-store"
    assert body["ok"] is True and body["command"] == "runs"


def test_lambda_handler_refuses_and_not_found(runs):
    src = fakes.aws_sources(runs)
    out, body = call(event(["ls"]), src)
    assert out["statusCode"] == 400 and body["error"] == "refused"
    out, body = call(event(["run", "nope-1"]), src)
    assert out["statusCode"] == 404 and body["error"] == "not_found"
    out, body = call({"version": "2.0"}, src)
    assert out["statusCode"] == 400
    out, body = call("not a dict", src)
    assert out["statusCode"] == 400


def test_exception_fails_closed_without_leaking(runs, monkeypatch, caplog):
    leak = "arn:aws:states:us-east-1:" + fakes.FAKE_ACCOUNT + ":execution:x boom"

    def broken(ctx, args):
        raise fakes.Boom(leak)

    monkeypatch.setitem(commands.HANDLERS, "runs", broken)
    with caplog.at_level(logging.WARNING):
        resp = dispatch(["runs"], Sources(runs))
    assert resp.status == 503
    assert resp.body["error"] == "unavailable"
    wire = resp.to_json()
    assert "boom" not in wire and fakes.FAKE_ACCOUNT not in wire and "arn:" not in wire
    # logged by type name only
    assert "Boom" in caplog.text
    assert "boom" not in caplog.text.replace("Boom", "")
    assert fakes.FAKE_ACCOUNT not in caplog.text


def test_source_errors_stay_inside_their_section(runs):
    src = Sources(runs, lambda: fakes.ExplodingSfn(), lambda: fakes.ExplodingFresh())
    resp = dispatch(["status"], src)
    assert resp.status == 200
    assert "boom" not in resp.to_json()
    assert fakes.FAKE_ACCOUNT not in resp.to_json()


def test_malformed_record_file_is_skipped_and_counted(runs):
    (runs / "broken.json").write_text("{not json")
    (runs / "list.json").write_text("[1, 2]")
    (runs / "big.json").write_text(json.dumps({"execution": "big-1", "pad": "x" * 300000}))
    rs = records.load(runs)
    assert rs.skipped == 3
    assert len(rs.records) == 4
    resp = dispatch(["runs"], Sources(runs))
    assert resp.status == 200
    assert "3 record file(s) skipped" in resp.body["text"]


def test_hostile_record_is_sanitised_end_to_end(runs):
    src = fakes.aws_sources(runs)
    for argv in (
        ["runs"],
        ["run", "hostile-20990101T000000Z"],
        ["dq"],
        ["cost", "hostile-20990101T000000Z"],
    ):
        resp = dispatch(argv, src)
        assert resp.status == 200
        wire = resp.to_json()
        assert "\\u001b" not in wire and "\\u202e" not in wire and "\\u0000" not in wire
        assert fakes.FAKE_ACCOUNT not in wire
        assert all(ch == "\n" or " " <= ch <= "~" for ch in resp.body["text"])
        assert len(wire) <= 64 * 1024


def test_hostile_sfn_and_athena_values_are_sanitised(runs):
    src = fakes.aws_sources(
        runs, athena_client=fakes.FakeAthenaClient(rows="freshness_rows_hostile.json")
    )
    resp = dispatch(["status"], src)
    assert resp.status == 200
    assert all(ch == "\n" or " " <= ch <= "~" for ch in resp.body["text"])
    assert "\x1b" not in resp.to_json()
    resp = dispatch(["run", "exercise-20261008T085728Z"], src)
    assert "?[31m" in resp.body["text"]


def test_athena_timeout_stops_the_query_and_shows_unavailable(runs):
    clock = fakes.Clock()
    athena = fakes.FakeAthenaClient(polls=10_000)
    src = fakes.aws_sources(runs, athena_client=athena, clock=clock)
    resp = dispatch(["status"], src)
    assert resp.status == 200
    assert resp.body["data"]["gold"] == {"available": False}
    names = [c[0] for c in athena.calls]
    assert names.count("stop_query_execution") == 1
    assert "get_query_results" not in names
    assert clock.t >= 12


def test_athena_poll_error_stops_the_query_and_shows_unavailable(runs):
    class Boom(fakes.FakeAthenaClient):
        def get_query_execution(self, **kw):
            self.calls.append(("get_query_execution", kw))
            raise RuntimeError("poll failed")

    athena = Boom()
    src = fakes.aws_sources(runs, athena_client=athena)
    resp = dispatch(["status"], src)
    assert resp.status == 200
    assert resp.body["data"]["gold"] == {"available": False}
    assert [c[0] for c in athena.calls].count("stop_query_execution") == 1


def test_athena_failed_query_is_unavailable(runs):
    athena = fakes.FakeAthenaClient(polls=0, final="FAILED")
    resp = dispatch(["status"], fakes.aws_sources(runs, athena_client=athena))
    assert resp.body["data"]["gold"] == {"available": False}


def test_freshness_is_cached_and_query_is_the_fixed_constant(runs):
    from cerberus_console import config

    athena = fakes.FakeAthenaClient()
    clock = fakes.Clock()
    src = fakes.aws_sources(runs, athena_client=athena, clock=clock)
    dispatch(["status"], src)
    dispatch(["status"], src)
    starts = [c for c in athena.calls if c[0] == "start_query_execution"]
    assert len(starts) == 1
    assert starts[0][1] == {
        "QueryString": config.FRESHNESS_SQL,
        "QueryExecutionContext": {"Database": config.DATABASE},
        "WorkGroup": config.WORKGROUP,
    }
    clock.t += config.FRESHNESS_TTL + 1
    dispatch(["status"], src)
    assert len([c for c in athena.calls if c[0] == "start_query_execution"]) == 2


def test_sfn_calls_never_fetch_execution_data(runs):
    sfn = fakes.FakeSfnClient()
    src = fakes.aws_sources(runs, sfn_client=sfn)
    dispatch(["status"], src)
    dispatch(["run", "exercise-20261008T085728Z"], src)
    history = [kw for name, kw in sfn.calls if name == "get_execution_history"]
    assert history and all(kw["includeExecutionData"] is False for kw in history)
    assert not any(name == "describe_execution" for name, _ in sfn.calls)
    # list_executions is cached across the two commands
    assert len([1 for name, _ in sfn.calls if name == "list_executions"]) == 1


def test_aws_module_imports_without_boto3():
    assert aws.build_sources().sfn_factory is not None
