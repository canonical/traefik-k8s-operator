#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer
from ops.charm import CharmBase
from ops.model import ActiveStatus


class RouteRequirerMock(CharmBase):
    def __init__(self, framework):
        """Initialize the mock charm."""
        super().__init__(framework)
        self.traefik_route = TraefikRouteRequirer(
            self, self.model.get_relation("traefik-route"), "traefik_route"
        )
        self.framework.observe(self.on.get_external_host_action, self._on_get_external_host_action)
        if self.traefik_route.is_ready():
            self.traefik_route.submit_to_traefik(
                config={"some": "config"},
                static={"entryPoints": {"test-port": {"address": ":4545"}}},
            )
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
