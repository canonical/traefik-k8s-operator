# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for the health tester.

Requests ingress with health-check params and runs a simple HTTP health endpoint
via pebble. Exposes a `set_health` method callable via the `rpc` action.
"""

import logging
import pathlib
import sys

import ops
from any_charm_base import AnyCharmBase
from ops.framework import StoredState
from ops.pebble import Layer

_src = pathlib.Path(__file__).parent
sys.path.insert(0, str(_src))

from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer  # noqa: E402

logger = logging.getLogger(__name__)

HEALTH_PORT = 8080


class AnyCharm(AnyCharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stored.set_default(healthy=True)
        self.unit.set_ports(HEALTH_PORT)
        self.ingress = IngressPerAppRequirer(
            self,
            port=HEALTH_PORT,
            relation_name="require-ingress",
            strip_prefix=True,
            healthcheck_params={
                "path": "/health",
                "port": HEALTH_PORT,
                "interval": "5s",
            },
        )
        self.framework.observe(self.on["any"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)

    def _on_start(self, event):
        container = self.unit.get_container("any")
        if not container.can_connect():
            event.defer()
            return
        self._configure_health_service(container)

    def _on_pebble_ready(self, event):
        self._configure_health_service(event.workload)

    def _configure_health_service(self, container):
        if not container.exists("/usr/bin/python3"):
            container.exec(["apt-get", "update", "-qq"]).wait()
            container.exec(["apt-get", "install", "-y", "-qq", "python3"]).wait()
        # Push the server script
        server_script = (_src / "health_server.py").read_text()
        container.push("/bin/health_server.py", server_script, make_dirs=True)
        self._start_health_service(container, healthy=bool(self._stored.healthy))

    def _start_health_service(self, container, healthy: bool):
        state = "up" if healthy else "down"
        layer = Layer({
            "summary": "health server layer",
            "services": {
                "health-server": {
                    "override": "replace",
                    "command": f"python3 /bin/health_server.py {state}",
                    "startup": "enabled",
                }
            },
        })
        container.add_layer("health-server", layer, combine=True)
        container.restart("health-server")
        self.unit.status = ops.ActiveStatus(f"Health server running (healthy={healthy})")

    def set_health(self, is_healthy: bool) -> str:
        """Set the health status for this unit. Callable via rpc action."""
        container = self.unit.get_container("any")
        if not container.can_connect():
            return "error: container not ready"
        self._stored.healthy = is_healthy
        self._start_health_service(container, healthy=is_healthy)
        return f"Health set to {is_healthy}"
