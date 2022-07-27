#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import socket

print("running tcp mock server")

HOST = ""


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind((HOST, 0))

    port = s.getsockname()[1]
    print(f"opened new tcp port at {port}")
    with open("./port.txt", "w") as f:
        f.write(str(port))
        print("tcp ready")

    while True:  # resist ctrl+c
        s.listen()
        conn, addr = s.accept()
        with conn:
            while True:
                data = conn.recv(1024)
                conn.sendall(data)
                print(data)
