#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import socketserver


class MyTCPHandler(socketserver.BaseRequestHandler):
    """The request handler class for our server.

    Source: https://docs.python.org/3/library/socketserver.html#socketserver-tcpserver-example
    """

    def handle(self):
        # self.request is the TCP socket connected to the client
        self.data = self.request.recv(1024).strip()
        print(f"{self.client_address[0]} wrote: {self.data}")
        # Send back the same data
        self.request.sendall(self.data)


if __name__ == "__main__":
    print("Running TCP echo server")
    HOST, PORT = "0.0.0.0", 9999

    with socketserver.TCPServer((HOST, PORT), MyTCPHandler) as server:
        # Activate the server; this will keep running until you
        # interrupt the program with Ctrl-C
        server.serve_forever()
