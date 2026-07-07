# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Minimal httpbin-like server that echoes request headers as JSON."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        response = {
            "headers": dict(self.headers),
            "path": self.path,
            "method": "GET",
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence logs


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
