"""Post annotations to the console Grafana (step 10).

Stdlib only and Python 3.9 compatible. Run it on the console host while Grafana
listens on loopback:

    GRAFANA_ADMIN_PASSWORD=... python3 -I load.py annotations.json --wait 120

It refuses any URL whose host is not 127.0.0.1 or localhost, and it never
follows a redirect, so the credentials cannot leave the machine. The password
comes from the environment only (an argument would show up in `ps`) and is
never printed.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
DEFAULT_URL = "http://127.0.0.1:3000"


class RefusedURL(ValueError):
    """The URL is not plain http to a loopback host."""


def check_loopback(url):
    """Return the URL without a trailing slash, or raise RefusedURL."""
    parts = urlparse(url)
    try:
        port = parts.port
    except ValueError:
        raise RefusedURL("bad port") from None
    if parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS:
        raise RefusedURL("Grafana URL must be http://127.0.0.1 or http://localhost")
    if parts.username or parts.password or parts.path not in ("", "/") or parts.query:
        raise RefusedURL("Grafana URL must be a bare host and port")
    return f"http://{parts.hostname}" + (f":{port}" if port else "")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _opener():
    # No proxy handler either: a proxy variable must not capture loopback calls.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _request(base, path, user, password, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode()
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(base + path, data=data)
    req.add_header("Authorization", "Basic " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with _opener().open(req, timeout=timeout) as resp:
        return resp.status


def wait_healthy(base, seconds):
    """Poll /api/health (no auth needed) until it answers 200 or time is up."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            req = urllib.request.Request(base + "/api/health")
            with _opener().open(req, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def post_all(base, user, password, annotations):
    """POST each annotation. Returns the number accepted. Raises on a refusal."""
    done = 0
    for item in annotations:
        status = _request(base, "/api/annotations", user, password, item)
        if status != 200:
            raise RuntimeError(f"Grafana answered HTTP {status} for annotation {done + 1}")
        done += 1
    return done


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("annotations", help="annotations.json from build.py")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--user", default=os.environ.get("GRAFANA_ADMIN_USER", "admin"))
    parser.add_argument("--wait", type=int, default=0, help="seconds to wait for /api/health")
    args = parser.parse_args(argv)

    password = os.environ.get("GRAFANA_ADMIN_PASSWORD", "")
    if not password:
        print("load: GRAFANA_ADMIN_PASSWORD is not set", file=sys.stderr)
        return 2
    try:
        base = check_loopback(args.url)
    except RefusedURL as exc:
        print(f"load: refused: {exc}", file=sys.stderr)
        return 2
    with open(args.annotations, encoding="utf-8") as handle:
        annotations = json.load(handle)
    if args.wait and not wait_healthy(base, args.wait):
        print("load: Grafana did not become healthy in time", file=sys.stderr)
        return 1
    try:
        done = post_all(base, args.user, password, annotations)
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        # Show the reason, never the request: it carries the credentials.
        reason = getattr(exc, "reason", None) or getattr(exc, "code", None) or type(exc).__name__
        print(f"load: failed: {reason}", file=sys.stderr)
        return 1
    print(f"load: posted {done} annotations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
