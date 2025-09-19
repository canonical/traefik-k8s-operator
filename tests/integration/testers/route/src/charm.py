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
        if self.traefik_route.is_ready():
            self.traefik_route.submit_to_traefik(
                config={"some": "config"},
                static={"entryPoints": {"test-port": {"address": ":4545"}}},
            )
        self.unit.status = ActiveStatus("ready")


if __name__ == "__main__":
    from ops.main import main

    main(RouteRequirerMock)
