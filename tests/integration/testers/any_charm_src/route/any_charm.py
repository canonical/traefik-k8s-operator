# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a traefik-route requirer."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from any_charm_base import AnyCharmBase  # noqa: E402
from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer  # noqa: E402


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.traefik_route = TraefikRouteRequirer(
            self,
            self.model.get_relation("require-traefik-route"),
            relation_name="require-traefik-route",
        )
        self.framework.observe(
            self.on["require-traefik-route"].relation_created, self._sync_config
        )
        self.framework.observe(
            self.on["require-traefik-route"].relation_changed, self._sync_config
        )

    def _sync_config(self, _event=None):
        if not self.unit.is_leader() or not self.traefik_route.is_ready():
            return
        self.traefik_route.submit_to_traefik(
            config={
                "http": {
                    "routers": {
                        "test-router": {
                            "entryPoints": ["web"],
                            "rule": "PathPrefix(`/test-route`)",
                            "service": "test-service",
                        }
                    },
                    "services": {
                        "test-service": {
                            "loadBalancer": {
                                "servers": [{"url": "http://localhost:8080"}]
                            }
                        }
                    },
                }
            },
        )

    def get_external_host(self):
        """Return the external host from traefik-route (callable via rpc action)."""
        return self.traefik_route.external_host
