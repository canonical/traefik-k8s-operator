# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a traefik-route requirer.

Submits dynamic + static config to Traefik and runs a UDP echo server
on port 9999 as an init service so that the static entrypoint test can reach it.
"""

import pathlib
import socket
import subprocess
import sys
import time

import ops
from any_charm_base import AnyCharmBase

_src = pathlib.Path(__file__).parent
sys.path.insert(0, str(_src))

from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer  # noqa: E402

_UDP_PORT = 9999
_SERVICE_NAME = "traefik-route-udp"
_SERVICE_DIR = pathlib.Path("/var/lib/traefik-route")
_SERVICE_SCRIPT = _SERVICE_DIR / "udp_echo_server.py"
_INIT_SCRIPT = pathlib.Path(f"/etc/init.d/{_SERVICE_NAME}")
_PID_FILE = f"/run/{_SERVICE_NAME}.pid"

_INIT_SCRIPT_CONTENT = f"""#!/bin/sh
set -e

case "$1" in
    start)
        start-stop-daemon --start --quiet --background --make-pidfile \\
            --pidfile {_PID_FILE} --startas /usr/bin/python3 -- {_SERVICE_SCRIPT}
        ;;
    stop)
        start-stop-daemon --stop --quiet --retry TERM/5/KILL/5 --remove-pidfile \\
            --pidfile {_PID_FILE}
        ;;
    restart)
        "$0" stop
        "$0" start
        ;;
    status)
        start-stop-daemon --status --quiet --pidfile {_PID_FILE}
        ;;
    *)
        echo "Usage: $0 {{start|stop|restart|status}}" >&2
        exit 1
        ;;
esac
"""


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit.open_port("udp", _UDP_PORT)
        self.traefik_route = TraefikRouteRequirer(
            self,
            self.model.get_relation("require-traefik-route"),
            relation_name="require-traefik-route",
        )
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(
            self.on["require-traefik-route"].relation_created, self._sync_config
        )
        self.framework.observe(
            self.on["require-traefik-route"].relation_changed, self._sync_config
        )

    def _workload_server_address(self) -> str:
        address = self.model.get_binding("require-traefik-route").network.bind_address
        return f"{address}:{_UDP_PORT}"

    def _on_install(self, _event):
        _SERVICE_DIR.mkdir(parents=True, exist_ok=True)
        _SERVICE_SCRIPT.write_text(
            (_src / "udp_echo_server.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        _INIT_SCRIPT.write_text(_INIT_SCRIPT_CONTENT, encoding="utf-8")
        _INIT_SCRIPT.chmod(0o755)

    def _on_start(self, _event):
        subprocess.run(["service", _SERVICE_NAME, "start"], check=True)
        self._wait_for_udp_echo()
        self._sync_config()
        self.unit.status = ops.ActiveStatus("ready")

    @staticmethod
    def _wait_for_udp_echo():
        payload = b"ready"
        for _ in range(20):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
                    udp_sock.settimeout(0.5)
                    udp_sock.sendto(payload, ("127.0.0.1", _UDP_PORT))
                    response, _ = udp_sock.recvfrom(512)
                if response == payload:
                    return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("UDP echo service did not become ready")

    def _sync_config(self, _event=None):
        if not self.unit.is_leader() or not self.traefik_route.is_ready():
            return
        self.traefik_route.submit_to_traefik(
            config={
                "some": "config",
                "udp": {
                    "routers": {
                        "echo-router": {
                            "entryPoints": ["test-udp-port"],
                            "service": "echo-service",
                        }
                    },
                    "services": {
                        "echo-service": {
                            "loadBalancer": {
                                "servers": [{"address": self._workload_server_address()}]
                            }
                        }
                    },
                },
            },
            static={
                "entryPoints": {
                    "test-port": {"address": ":4545"},
                    "test-udp-port": {"address": ":4646/udp"},
                }
            },
        )

    def get_external_host(self):
        """Return the external host from traefik-route (callable via rpc action)."""
        return self.traefik_route.external_host
