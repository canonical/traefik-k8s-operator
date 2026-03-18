#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path

from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer
from ops.charm import CharmBase, PebbleReadyEvent
from ops.model import ActiveStatus, Container, WaitingStatus
from ops.pebble import Layer


class RouteRequirerMock(CharmBase):
    _udp_port = 9999

    def __init__(self, framework):
        """Initialize the mock charm."""
        super().__init__(framework)

        self.unit.open_port("udp", self._udp_port)

        self.traefik_route = TraefikRouteRequirer(
            self, self.model.get_relation("traefik-route"), "traefik_route"
        )
        self.framework.observe(self.on.get_external_host_action, self._on_get_external_host_action)

        self.framework.observe(self.on.udp_echo_server_pebble_ready, self._pebble_ready)
        self.framework.observe(self.on.traefik_route_relation_created, self._sync_traefik_route_config)
        self.framework.observe(self.on.traefik_route_relation_changed, self._sync_traefik_route_config)

        self._sync_traefik_route_config()
        self.unit.status = ActiveStatus("ready")

    def _workload_server_address(self) -> str:
        return (
            f"{self.app.name}-0."
            f"{self.app.name}-endpoints."
            f"{self.model.name}.svc.cluster.local:{self._udp_port}"
        )

    def _sync_traefik_route_config(self, _event=None):
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
            static={"entryPoints": {"test-port": {"address": ":4545"}, "test-udp-port": {"address": ":4646/udp"}}},
        )

    def _pebble_ready(self, event: PebbleReadyEvent):
        container: Container = event.workload
        if not container.can_connect():
            event.defer()
            self.unit.status = WaitingStatus(
                "Pending UDP echo restart; waiting for workload container"
            )
            return

        workload_file = Path(__file__).parent / "workload.py"
        with open(workload_file, "r") as workload_source:
            container.push("/workload.py", workload_source)

        new_layer = Layer(
            {
                "summary": "udp-echo layer",
                "description": "pebble config layer for udp echo workload",
                "services": {
                    "workload": {
                        "override": "replace",
                        "summary": "udp echo workload",
                        "command": "python3 /workload.py",
                        "startup": "enabled",
                    }
                },
            }
        )

        container.add_layer("udp-echo", new_layer, combine=True)
        container.replan()

        self._sync_traefik_route_config()
        self.unit.status = ActiveStatus("ready")

    def _on_get_external_host_action(self, event):
        """Handle get-external-host action."""
        try:
            external_host = self.traefik_route.external_host
            event.set_results({"external-host": external_host})
        except Exception as e:
            event.fail(f"Failed to get external host: {e}")


if __name__ == "__main__":
    from ops.main import main

    main(RouteRequirerMock)
