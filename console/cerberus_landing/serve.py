"""Local preview: python -m cerberus_landing.serve [--dir site-dist] [--port 8088]

Binds to 127.0.0.1 only. Sends the edge's Content-Security-Policy on every
response (terraform/modules/console_edge, #130) minus `upgrade-insecure-requests`,
which would break plain HTTP, and minus the Cognito host, which the page does not
use yet. A CSP violation shows in the browser DevTools console, as it would live.
"""

import argparse
import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "object-src 'none'"
)


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def make_server(directory: Path, port: int) -> ThreadingHTTPServer:
    handler = functools.partial(Handler, directory=str(directory))
    return ThreadingHTTPServer((HOST, port), handler)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cerberus_landing.serve")
    parser.add_argument("--dir", type=Path, default=Path("site-dist"))
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args(argv)
    if not (args.dir / "index.html").is_file():
        print(f"{args.dir}/index.html not found. Run `make console-site` first.", file=sys.stderr)
        return 1
    with make_server(args.dir, args.port) as server:
        print(f"http://{HOST}:{args.port}/  (Ctrl-C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
