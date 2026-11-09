"""TTLCache negative caching and the freshness reader's Athena calls. Fake clock, fake client."""

import fakes
import pytest

from cerberus_console import aws
from cerberus_console.sources import Unavailable


class Boom(Exception):
    pass


def make(client, clock):
    return aws.AwsFreshnessReader(client, clock=clock, sleep=clock.sleep)


def test_failing_query_is_started_once_within_60s_and_again_after_61s():
    athena = fakes.FakeAthenaClient(polls=0, final="FAILED")
    clock = fakes.Clock()
    reader = make(athena, clock)

    def starts():
        return len([c for c in athena.calls if c[0] == "start_query_execution"])

    with pytest.raises(Unavailable):
        reader.gold_freshness()
    clock.t += 59
    with pytest.raises(Unavailable):
        reader.gold_freshness()
    assert starts() == 1
    clock.t += 2  # 61 s after the failure
    with pytest.raises(Unavailable):
        reader.gold_freshness()
    assert starts() == 2


def test_timed_out_query_is_remembered_from_failure_time_not_start_time():
    athena = fakes.FakeAthenaClient(polls=10_000)
    clock = fakes.Clock()
    reader = make(athena, clock)

    def starts():
        return len([c for c in athena.calls if c[0] == "start_query_execution"])

    with pytest.raises(Unavailable):
        reader.gold_freshness()
    assert clock.t >= 12  # the 12 s deadline passed before the failure
    failed_at = clock.t
    clock.t = failed_at + 59
    with pytest.raises(Unavailable):
        reader.gold_freshness()
    assert starts() == 1
    clock.t = failed_at + 61
    with pytest.raises(Unavailable):
        reader.gold_freshness()
    assert starts() == 2


def test_original_exception_is_raised_on_first_failure_only():
    cache = aws.TTLCache(300, fakes.Clock(), negative_ttl=60)
    calls = []

    def fn():
        calls.append(1)
        raise Boom

    with pytest.raises(Boom):
        cache.get_or_set("k", fn)
    with pytest.raises(Unavailable):
        cache.get_or_set("k", fn)
    assert len(calls) == 1


def test_no_negative_cache_by_default():
    cache = aws.TTLCache(300, fakes.Clock())
    calls = []

    def fn():
        calls.append(1)
        raise Boom

    for _ in range(2):
        with pytest.raises(Boom):
            cache.get_or_set("k", fn)
    assert len(calls) == 2


def test_success_is_cached_300s():
    athena = fakes.FakeAthenaClient()
    clock = fakes.Clock()
    reader = make(athena, clock)
    reader.gold_freshness()
    clock.t += 299
    reader.gold_freshness()
    starts = [c for c in athena.calls if c[0] == "start_query_execution"]
    assert len(starts) == 1
    clock.t += 2
    reader.gold_freshness()
    assert len([c for c in athena.calls if c[0] == "start_query_execution"]) == 2


def test_start_query_asks_athena_to_reuse_results_for_5_minutes():
    athena = fakes.FakeAthenaClient()
    make(athena, fakes.Clock()).gold_freshness()
    kw = next(c[1] for c in athena.calls if c[0] == "start_query_execution")
    reuse = kw["ResultReuseConfiguration"]["ResultReuseByAgeConfiguration"]
    assert reuse == {"Enabled": True, "MaxAgeInMinutes": 5}
