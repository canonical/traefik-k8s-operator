# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Minimal TCP echo server."""

import socketserver


class TCPEchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024).strip()
        self.request.sendall(data)


if __name__ == "__main__":
    host, port = "0.0.0.0", 9999
    with socketserver.TCPServer((host, port), TCPEchoHandler) as server:
        server.serve_forever()
