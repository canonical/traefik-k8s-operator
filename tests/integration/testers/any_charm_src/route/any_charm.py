# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a traefik-route requirer.

Submits dynamic + static config to Traefik and runs a UDP echo server
on port 9999 via pebble so that the static entrypoint test can reach it.
"""

import os
import pathlib
import sys

import ops
from any_charm_base import AnyCharmBase
from ops.pebble import Layer

sys.path.insert(0, os.path.dirname(__file__))

from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer  # noqa: E402

_src = pathlib.Path(os.path.dirname(__file__))
_UDP_PORT = 9999


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit.open_port("udp", _UDP_PORT)
        self.traefik_route = TraefikRouteRequirer(
            self,
            self.model.get_relation("require-traefik-route"),
            relation_name="require-traefik-route",
        )
        self.framework.observe(self.on["any"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.on["require-traefik-route"].relation_created, self._sync_config
        )
        self.framework.observe(
            self.on["require-traefik-route"].relation_changed, self._sync_config
        )
        self.unit.status = ops.ActiveStatus("ready")

    def _workload_server_address(self) -> str:
        return (
            f"{self.app.name}-0."
            f"{self.app.name}-endpoints."
            f"{self.model.name}.svc.cluster.local:{_UDP_PORT}"
        )

    def _on_pebble_ready(self, event):
        container = event.workload
        container.exec(["apt-get", "update", "-qq"]).wait()
        container.exec(["apt-get", "install", "-y", "-qq", "python3"]).wait()
        server_script = (_src / "udp_echo_server.py").read_text()
        container.push("/udp_echo_server.py", server_script, make_dirs=True)
        layer = Layer({
            "summary": "udp-echo layer",
            "services": {
                "udp-echo": {
                    "override": "replace",
                    "command": "python3 /udp_echo_server.py",
                    "startup": "enabled",
                }
            },
        })
        container.add_layer("udp-echo", layer, combine=True)
        container.replan()
        self._sync_config()
        self.unit.status = ops.ActiveStatus("ready")

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
