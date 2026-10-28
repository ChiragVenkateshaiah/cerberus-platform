"""9.2 VPC-origin spike: a stdlib-only HTTP responder.

GET /                      -> 200 "cerberus vpc-origin spike ok"
GET /ws + Upgrade: websocket -> 101, one text frame "hello", then close
anything else              -> 404

Never echoes request data. Python 3.9 compatible (AL2023's python3).
Usage: responder.py PORT
"""

import base64
import hashlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BODY = b"cerberus vpc-origin spike ok\n"
# Unmasked server frame: FIN + text opcode (0x81), payload length 5, "hello".
WS_HELLO_FRAME = b"\x81\x05hello"
# Close frame, status 1000 (normal closure).
WS_CLOSE_FRAME = b"\x88\x02\x03\xe8"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "spike"
    sys_version = ""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, BODY)
        elif path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
            self._upgrade()
        else:
            self._send(404, b"not found\n")

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _upgrade(self):
        key = self.headers.get("Sec-WebSocket-Key", "")
        digest = hashlib.sha1((key + WS_GUID).encode("ascii", "ignore")).digest()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", base64.b64encode(digest).decode("ascii"))
        self.end_headers()
        self.wfile.write(WS_HELLO_FRAME + WS_CLOSE_FRAME)
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, format, *args):
        # Request lines are not logged: nothing from a request is kept.
        return


def main():
    port = int(sys.argv[1])
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
