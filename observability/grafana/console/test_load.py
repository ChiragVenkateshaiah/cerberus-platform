"""load.py: the loopback guard, no redirects, no secret in output."""

import http.server
import json
import threading

import load
import pytest


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:3000",
        "http://10.0.0.5:3000",
        "https://127.0.0.1:3000",
        "http://127.0.0.1.evil.com:3000",
        "http://127.0.0.1:3000@evil.com",
        "http://user:pw@127.0.0.1:3000",
        "http://[::1]:3000",
        "http://0.0.0.0:3000",
        "ftp://127.0.0.1",
        "http://127.0.0.1:3000/x",
        "http://127.0.0.1:99999999",
        "",
    ],
)
def test_refuses_non_loopback(url):
    with pytest.raises(load.RefusedURL):
        load.check_loopback(url)


def test_accepts_loopback():
    assert load.check_loopback("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
    assert load.check_loopback("http://localhost:3000/") == "http://localhost:3000"


def test_main_refuses_and_never_connects(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "s3cret-value")
    f = tmp_path / "a.json"
    f.write_text("[]")
    assert load.main([str(f), "--url", "http://example.com:3000"]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "s3cret-value" not in err


def test_main_needs_password(monkeypatch, tmp_path):
    monkeypatch.delenv("GRAFANA_ADMIN_PASSWORD", raising=False)
    f = tmp_path / "a.json"
    f.write_text("[]")
    assert load.main([str(f)]) == 2


class _Handler(http.server.BaseHTTPRequestHandler):
    seen = []
    mode = "ok"

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen.append((self.headers["Authorization"], json.loads(body)))
        if type(self).mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "/followed")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_GET(self):  # noqa: N802
        type(self).seen.append(("GET " + self.path, None))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    _Handler.seen = []
    _Handler.mode = "ok"
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_posts_with_basic_auth_and_hides_password(server, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "s3cret-value")
    f = tmp_path / "a.json"
    f.write_text(json.dumps([{"text": "a", "time": 1, "tags": ["x"]}] * 3))
    url = f"http://127.0.0.1:{server.server_port}"
    assert load.main([str(f), "--url", url]) == 0
    assert len(_Handler.seen) == 3
    assert _Handler.seen[0][0].startswith("Basic ")
    out = capsys.readouterr()
    assert "s3cret-value" not in out.out + out.err


def test_redirect_is_not_followed(server, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "s3cret-value")
    _Handler.mode = "redirect"
    f = tmp_path / "a.json"
    f.write_text(json.dumps([{"text": "a", "time": 1, "tags": []}]))
    assert load.main([str(f), "--url", f"http://127.0.0.1:{server.server_port}"]) == 1
    assert len(_Handler.seen) == 1
    assert not [s for s in _Handler.seen if str(s[0]).startswith("GET")]
    assert "s3cret-value" not in capsys.readouterr().err
