# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Minimal HTTP server that returns 200 for any GET request."""

import http.server
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK\n")

    def log_message(self, format, *args):  # noqa: A002
        pass  # suppress access logs


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as server:
        server.serve_forever()
