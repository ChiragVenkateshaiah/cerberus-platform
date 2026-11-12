"""Local preview: python -m cerberus_terminal.serve [--dir terminal-dist] [--port 8089]

Binds to 127.0.0.1 only. Sends the edge's Content-Security-Policy on every response
(terraform/modules/console_edge/main.tf) minus `upgrade-insecure-requests`, which
would break plain HTTP. The Cognito host is a wildcard here, because the real host
comes from config.json at publish time. A CSP violation shows in the browser
DevTools console, as it would live.

The build does not write config.json (the publish script does). Without one the
page shows the "not configured" message. To test more, place your own config.json
in DIR/terminal/; never commit one. A local origin is not a registered callback
URL, so a real sign-in does not work from the preview.
"""

import argparse
import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
COGNITO = "https://*.auth.us-east-1.amazoncognito.com"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    f"connect-src 'self' {COGNITO}; form-action 'self' {COGNITO}; frame-ancestors 'none'; "
    "base-uri 'none'; object-src 'none'"
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
    parser = argparse.ArgumentParser(prog="cerberus_terminal.serve")
    parser.add_argument("--dir", type=Path, default=Path("terminal-dist"))
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args(argv)
    if not (args.dir / "terminal" / "index.html").is_file():
        print(
            f"{args.dir}/terminal/index.html not found. Run `make console-terminal` first.",
            file=sys.stderr,
        )
        return 1
    with make_server(args.dir, args.port) as server:
        print(f"http://{HOST}:{args.port}/terminal/index.html  (Ctrl-C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
