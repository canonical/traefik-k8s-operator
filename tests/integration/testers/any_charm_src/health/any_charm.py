# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for the health tester.

Requests ingress with health-check params and runs an Apache health endpoint.
Exposes a `set_health` method callable via the `rpc` action.
"""

import json
import pathlib
import subprocess
import sys

import ops
from any_charm_base import AnyCharmBase
from charmlibs import apt
from ops.framework import StoredState

_src = pathlib.Path(__file__).parent
sys.path.insert(0, str(_src))

from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer  # noqa: E402

HEALTH_PORT = 80
HEALTH_PATH = pathlib.Path("/var/www/html/health")


class AnyCharm(AnyCharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stored.set_default(healthy=True)
        self.unit.open_port("tcp", HEALTH_PORT)
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
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)

    def _on_install(self, _event):
        self._ensure_apache_installed()
        self._write_health_response(bool(self._stored.healthy))

    def _on_start(self, _event):
        self._ensure_apache_installed()
        self._set_health(bool(self._stored.healthy))

    @staticmethod
    def _ensure_apache_installed():
        if not pathlib.Path("/usr/sbin/apache2").exists():
            apt.update()
            apt.add_package("apache2")

    def _write_health_response(self, healthy: bool):
        state = "up" if healthy else "down"
        HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_PATH.write_text(
            json.dumps({"host": self.unit.name.replace("/", "-"), "status": state}),
            encoding="utf-8",
        )

    def _set_health(self, healthy: bool):
        self._write_health_response(healthy)
        action = "start" if healthy else "stop"
        subprocess.run(["service", "apache2", action], check=True)
        self.unit.status = ops.ActiveStatus(f"Health server running (healthy={healthy})")

    def set_health(self, is_healthy: bool) -> str:
        """Set the health status for this unit. Callable via rpc action."""
        self._stored.healthy = is_healthy
        self._set_health(is_healthy)
        return f"Health set to {is_healthy}"
