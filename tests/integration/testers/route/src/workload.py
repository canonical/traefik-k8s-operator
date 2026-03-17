#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import socketserver


class UDPEchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        sock.sendto(data, self.client_address)


if __name__ == "__main__":
    host, port = "0.0.0.0", 9999
    with socketserver.UDPServer((host, port), UDPEchoHandler) as server:
        server.serve_forever()
