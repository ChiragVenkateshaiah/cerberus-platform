"""The failed step of a real failed run (10.2e).

A real failed run ends with TaskStateEntered RunDbt, TaskFailed (three times),
TaskStateExited RunDbt, then FailStateEntered PipelineFailed. The Fail state also
carries stateEnteredEventDetails, so reading every entered state named
PipelineFailed as the failed step. The older synthetic fixture has no Fail state
and could not catch that.
"""

import json

import fakes

from cerberus_console import aws


class HistoryClient:
    def __init__(self, name):
        self._page = fakes.load("sfn", name)

    def get_execution_history(self, **kwargs):
        return self._page


def detail(name):
    reader = aws.AwsStepFunctionsReader(HistoryClient(name), "arn-not-used", lambda: 0.0)
    return reader.execution_detail("arn:fake")


def test_a_real_failed_run_names_the_task_not_the_fail_state():
    got = detail("history_failed_catch.json")
    assert got["failed_state"] == "RunDbt"
    assert got["error"] == "CerberusPipelineFailed"


def test_the_cause_text_is_never_returned():
    got = detail("history_failed_catch.json")
    assert "cause" not in json.dumps(got).lower()
    assert "dbt failed" not in json.dumps(got)


def test_step_timings_cover_only_exited_tasks():
    got = detail("history_failed_catch.json")
    assert [s["state"] for s in got["states"]] == ["InvokeIngestion", "RunTransform", "RunDbt"]


def test_the_synthetic_failed_fixture_still_names_run_dbt():
    assert detail("history_failed.json")["failed_state"] == "RunDbt"
