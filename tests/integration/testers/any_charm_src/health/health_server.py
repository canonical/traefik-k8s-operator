# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Minimal HTTP server that serves a /health endpoint returning JSON status.

Accepts a CLI argument: 'up' (default) or 'down' to control health state.
"""

import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        hostname = socket.gethostname()
        if self.path == "/health":
            state = sys.argv[1] if len(sys.argv) > 1 else "up"
            if state == "up":
                self.send_json(200, {"host": hostname, "status": "up"})
            else:
                self.send_json(503, {"host": hostname, "status": "down"})
        else:
            self.send_json(404, {"host": hostname, "error": "Not Found"})

    def send_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
