#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

# Define the content of our minimal health server
HEALTH_SERVER_CODE = """#!/usr/bin/env python3
import sys
import socket
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class HealthHandler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

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

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()
"""


class HealthMock(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.unit.set_ports(8080)
        self.ipa = IngressPerAppRequirer(
            self,
            port=8080,
            strip_prefix=True,
            healthcheck_params={
                "path": "/health",
                "port": 8080,
                "interval": "5s",
            },
        )
        # _local_health_status is None by default, meaning no per-unit override.
        self._local_health_status = None
        self.framework.observe(self.on.python_pebble_ready, self._on_pebble_ready)
        # Observe the new action for per-unit health override.
        self.framework.observe(self.on.set_health_action, self._on_set_health_action)

    def _on_pebble_ready(self, _):
        self._update_service_layer()

    def _on_set_health_action(self, event):
        # This action sets the health status for this unit only.
        health_value = event.params.get("is-healthy")
        if not isinstance(health_value, bool):
            event.fail("Invalid type for health parameter; expected boolean")
            return

        self._local_health_status = health_value
        self._update_service_layer()
        event.set_results({"message": f"Local health set to {health_value}"})

    def _update_service_layer(self):
        container = self.unit.get_container("python")
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        container.push("/bin/health_server.py", HEALTH_SERVER_CODE, make_dirs=True)

        health_status = (
            self._local_health_status if self._local_health_status is not None else True
        )
        if health_status:
            command = "python3 /bin/health_server.py up"
        else:
            command = "python3 /bin/health_server.py down"

        layer = Layer(
            {
                "summary": "health server layer",
                "description": "pebble config layer for health server",
                "services": {
                    "health-server": {
                        "override": "replace",
                        "command": command,
                        "startup": "enabled",
                    }
                },
            }
        )

        container.add_layer("health-server", layer, combine=True)
        container.restart("health-server")
        self.unit.status = ActiveStatus(f"Health server running (healthy={health_status})")


if __name__ == "__main__":
    main(HealthMock)
