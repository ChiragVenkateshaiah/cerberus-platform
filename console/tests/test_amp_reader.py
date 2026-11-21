"""The AMP reader (10.5a): parsing, limits, caches and failures. Fixtures and fakes only.

No live AMP call, no botocore: a fake opener replaces urlopen and a fake signer
replaces SigV4.
"""

import io
import json
import re
import urllib.error
import urllib.request

import fakes
import pytest

from cerberus_console import aws, config
from cerberus_console.sources import Unavailable

PRINTABLE = re.compile(r"[\x20-\x7e]*")


def parse(name):
    return aws.parse_vector(json.loads(fakes.amp_body(name)))


def one(name_or_body, query="latest_status", **kw):
    body = fakes.amp_body(name_or_body) if isinstance(name_or_body, str) else name_or_body
    return fakes.amp_reader(fakes.FakeOpener(body), **kw).query(query)


# --- parsing ---------------------------------------------------------------


def test_name_label_present_or_absent_gives_the_same_row():
    assert parse("vector_named") == [{"step": None, "execution": None, "value": 1.0}]
    assert parse("vector_unnamed") == [{"step": None, "execution": None, "value": 42.0}]


def test_only_step_and_execution_are_read():
    assert parse("vector_labels") == [
        {"step": "RunDbt", "execution": "exercise-20261013T055859Z", "value": 7.5}
    ]
    # `job`, `instance` and `__name__` of vector_named never reach the output.
    assert "cerberus_run_status" not in json.dumps(parse("vector_named"))


def test_nan_keeps_the_row_with_no_value():
    assert parse("vector_nan") == [{"step": "RunDbt", "execution": None, "value": None}]


def test_other_non_finite_empty_and_non_numeric_values_are_dropped():
    rows = parse("vector_bad_values")
    assert [r["step"] for r in rows] == ["good"]
    assert rows[0]["value"] == 2.0


def test_malformed_rows_are_dropped():
    assert [r["step"] for r in parse("vector_malformed_rows")] == ["kept"]


def test_empty_result_is_an_empty_list_not_an_error():
    assert parse("empty") == []


@pytest.mark.parametrize("name", ["matrix", "scalar", "error"])
def test_non_vector_and_error_replies_are_unavailable(name):
    with pytest.raises(Unavailable):
        parse(name)


@pytest.mark.parametrize(
    "reply",
    [None, [], "x", {}, {"status": "success"}, {"status": "success", "data": []},
     {"status": "success", "data": {"resultType": "vector", "result": "x"}}],
)  # fmt: skip
def test_odd_reply_shapes_are_unavailable(reply):
    with pytest.raises(Unavailable):
        aws.parse_vector(reply)


def test_hostile_labels_are_sanitised_and_capped():
    rows = parse("hostile_labels")
    assert len(rows) == 2
    for row in rows:
        for key in ("step", "execution"):
            assert PRINTABLE.fullmatch(row[key]), row[key][:40]
            assert len(row[key]) <= config.FIELD_CHARS
    assert "\n" not in rows[0]["step"] and "\x1b" not in rows[0]["step"]
    assert rows[1]["step"].endswith("...") and len(rows[1]["step"]) == config.FIELD_CHARS
    # Markup is not interpreted here: it stays plain text for the renderer to escape.
    assert rows[0]["execution"].startswith("<script>")


def test_a_non_string_label_becomes_none():
    reply = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {"step": 5, "execution": ["x"]}, "value": [1, "1"]}],
        },
    }
    assert aws.parse_vector(reply) == [{"step": None, "execution": None, "value": 1.0}]


def test_at_most_100_series_per_entry():
    rows = [{"metric": {"step": f"s{i}"}, "value": [1, "1"]} for i in range(500)]
    body = json.dumps(
        {"status": "success", "data": {"resultType": "vector", "result": rows}}
    ).encode()
    out = one(body)
    assert len(out) == config.AMP_MAX_SERIES == 100
    assert out[-1]["step"] == "s99"


# --- the request -----------------------------------------------------------


def test_the_url_is_the_signed_percent_encoded_instant_query():
    opener = fakes.FakeOpener(fakes.amp_body("vector_named"))
    fakes.amp_reader(opener).query("latest_status")
    url, timeout, headers = opener.calls[0]
    assert url.startswith(
        "https://aps-workspaces.example.invalid/workspaces/ws-test/api/v1/query?query="
    )
    assert "+" not in url and "%28" in url  # %20 style, never '+'
    assert "last_over_time" in url
    assert headers["Authorization"] == "fake"
    assert timeout == config.AMP_TIMEOUT_SECONDS == 4.0


def test_an_unknown_name_raises_and_makes_no_call():
    opener = fakes.FakeOpener(fakes.amp_body("empty"))
    with pytest.raises(KeyError):
        fakes.amp_reader(opener).query("up; DROP")
    assert opener.calls == []


def test_a_base_url_that_is_not_https_makes_no_call():
    opener = fakes.FakeOpener(fakes.amp_body("empty"))
    reader = aws.AwsAmpReader(
        lambda u: {}, "http://x.invalid/", {"n": {"expr": "up"}}, opener=opener
    )
    with pytest.raises(Unavailable):
        reader.query("n")
    assert opener.calls == []


# --- failures --------------------------------------------------------------


@pytest.mark.parametrize("code", [500, 502, 503, 429])
def test_5xx_and_429_are_tried_twice_then_unavailable(code):
    opener = fakes.FakeOpener(code)
    with pytest.raises(Unavailable):
        fakes.amp_reader(opener).query("latest_status")
    assert len(opener.calls) == config.AMP_ATTEMPTS == 2


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_4xx_is_not_retried(code):
    opener = fakes.FakeOpener(code)
    with pytest.raises(Unavailable):
        fakes.amp_reader(opener).query("latest_status")
    assert len(opener.calls) == 1


def test_a_timeout_is_tried_twice_then_unavailable():
    opener = fakes.FakeOpener(TimeoutError("timed out"))
    with pytest.raises(Unavailable):
        fakes.amp_reader(opener).query("latest_status")
    assert len(opener.calls) == 2


def test_url_errors_are_retried_too():
    opener = fakes.FakeOpener(urllib.error.URLError("refused"))
    with pytest.raises(Unavailable):
        fakes.amp_reader(opener).query("latest_status")
    assert len(opener.calls) == 2


def test_the_second_attempt_can_succeed():
    opener = fakes.FakeOpener(503, fakes.amp_body("vector_named"))
    assert fakes.amp_reader(opener).query("latest_status")[0]["value"] == 1.0
    assert len(opener.calls) == 2


def test_unparseable_and_error_bodies_are_unavailable():
    for body in (b"{nope", b"", fakes.amp_body("error"), fakes.amp_body("matrix")):
        with pytest.raises(Unavailable):
            fakes.amp_reader(fakes.FakeOpener(body)).query("latest_status")


def test_a_2_mib_reply_is_cut_at_the_cap_and_fails_closed():
    body = b'{"status":"success","data":{"resultType":"vector","result":[' + b" " * (2 << 20)
    opener = fakes.FakeOpener(body + b"]}}")
    with pytest.raises(Unavailable):
        fakes.amp_reader(opener).query("latest_status")
    # It read at most cap + 1 bytes of each reply, never the whole 2 MiB.
    assert {n for r in opener.responses for n in r.read_sizes} == {config.AMP_READ_MAX + 1}
    assert config.AMP_READ_MAX == 256 * 1024


def test_a_reply_of_exactly_the_cap_is_read():
    head = b'{"status":"success","data":{"resultType":"vector","result":[]}}'
    body = head + b" " * (config.AMP_READ_MAX - len(head))
    assert len(body) == config.AMP_READ_MAX
    assert one(body) == []


# --- caches and the deadline ----------------------------------------------


def test_a_success_is_cached_for_30_s():
    opener = fakes.FakeOpener(fakes.amp_body("vector_named"))
    clock = fakes.Clock()
    reader = fakes.amp_reader(opener, clock)
    reader.query("latest_status")
    clock.t += 29
    reader.query("latest_status")
    assert len(opener.calls) == 1
    clock.t += 2
    reader.query("latest_status")
    assert len(opener.calls) == 2


def test_a_failure_is_remembered_for_60_s():
    opener = fakes.FakeOpener(500)
    clock = fakes.Clock()
    reader = fakes.amp_reader(opener, clock)
    with pytest.raises(Unavailable):
        reader.query("latest_status")
    calls = len(opener.calls)
    clock.t += 59
    with pytest.raises(Unavailable):
        reader.query("latest_status")
    assert len(opener.calls) == calls
    clock.t += 2
    with pytest.raises(Unavailable):
        reader.query("latest_status")
    assert len(opener.calls) > calls


def test_one_failing_name_does_not_poison_the_others():
    opener = fakes.FakeOpener(500, 500, fakes.amp_body("vector_named"))
    reader = fakes.amp_reader(opener)
    with pytest.raises(Unavailable):
        reader.query("latest_status")
    assert reader.query("latest_events")[0]["value"] == 1.0


def test_all_queries_share_one_5_s_deadline():
    clock = fakes.Clock()
    inner = fakes.FakeOpener(fakes.amp_body("vector_named"))

    def slow(req, timeout=None):
        clock.t += 3  # each answer takes 3 s
        return inner(req, timeout)

    reader = fakes.amp_reader(slow, clock)
    reader.query("latest_status")
    reader.query("latest_started")
    assert len(inner.calls) == 2
    with pytest.raises(Unavailable):
        reader.query("latest_finished")  # the window is spent: no third call
    assert len(inner.calls) == 2
    assert {c[1] for c in inner.calls} <= {4.0, 2.0}


def test_the_timeout_never_passes_the_time_left():
    clock = fakes.Clock()
    inner = fakes.FakeOpener(fakes.amp_body("vector_named"))

    def slow(req, timeout=None):
        clock.t += 3
        return inner(req, timeout)

    reader = fakes.amp_reader(slow, clock)
    reader.query("latest_status")
    reader.query("latest_started")
    assert [c[1] for c in inner.calls] == [4.0, 2.0]


# --- wiring ----------------------------------------------------------------


def test_build_sources_without_a_url_has_an_unavailable_amp(tmp_path):
    src = aws.build_sources(session=lambda: object(), amp_query_url="")
    with pytest.raises(Unavailable):
        src.amp()


def test_build_sources_with_a_url_builds_the_reader_lazily():
    built = []
    src = aws.build_sources(
        session=lambda: built.append(1) or object(), amp_query_url="https://x.invalid/"
    )
    assert built == []  # nothing built yet
    reader = src.amp()
    assert isinstance(reader, aws.AwsAmpReader) and src.amp() is reader
    assert built == [1]


# --- redirects, proxy and the base URL --------------------------------------


class Redirecting:
    """Answers every call with a 302 and a Location header, as a hostile server would."""

    def __init__(self):
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        hdrs = {"Location": "https://evil.example.invalid/"}
        raise urllib.error.HTTPError(req.full_url, 302, "Found", hdrs, io.BytesIO(b"x"))


def test_a_redirect_is_never_followed_and_fails_closed():
    opener = Redirecting()
    with pytest.raises(Unavailable):
        fakes.amp_reader(opener).query("latest_status")
    assert opener.calls == 1  # no retry, no second request


def test_the_default_opener_has_no_proxy_and_no_redirect():
    handlers = aws._OPENER.handlers
    # An empty ProxyHandler adds no method, so build_opener keeps none: no env proxy at all.
    assert not [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert not any(k.endswith("_open") and "proxy" in k for k in vars(aws._OPENER))
    redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert [type(h) for h in redirects] == [aws._NoRedirect]
    assert redirects[0].redirect_request(None, None, 302, "Found", {}, "https://x/") is None


@pytest.mark.parametrize(
    "base",
    [
        "https://user@evil.example.invalid/",
        "https://user:pw@evil.example.invalid/",
        "https://aps.example.invalid/ws/?a=b",
        "https://aps.example.invalid/ws/#frag",
        "https:///workspaces/ws-test/",
        "http://aps.example.invalid/ws/",
        "aps.example.invalid/ws/",
        "",
    ],
)
def test_a_bad_base_url_raises_and_makes_no_call(base):
    opener = fakes.FakeOpener(fakes.amp_body("vector_named"))
    reader = aws.AwsAmpReader(
        lambda url: {"Authorization": "fake"},
        base,
        {"q": {"expr": "up"}},
        opener=opener,
    )
    with pytest.raises(Unavailable):
        reader.query("q")
    assert opener.calls == []


# --- output hygiene ---------------------------------------------------------


@pytest.mark.parametrize("name", sorted(p.stem for p in fakes.AMP_FIXTURES.glob("*.json")))
def test_parse_vector_never_returns_a_control_character(name):
    try:
        rows = parse(name)
    except Unavailable:
        return
    for row in rows:
        for text in (row["step"], row["execution"], json.dumps(row)):
            assert text is None or not re.search(r"[\x00-\x1f\x7f-\x9f]", text)
