# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a traefik-route requirer."""

import os
import pathlib
import sys

_src = pathlib.Path(os.path.dirname(__file__))
_lib_dir = _src / "charms" / "traefik_k8s" / "v0"
_lib_dir.mkdir(parents=True, exist_ok=True)
(_src / "charms" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "traefik_k8s" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "traefik_k8s" / "v0" / "__init__.py").touch(exist_ok=True)
_lib_src = _src / "_lib_traefik_route_v0.py"
_lib_dst = _lib_dir / "traefik_route.py"
if _lib_src.exists() and not _lib_dst.exists():
    _lib_dst.write_text(_lib_src.read_text())

sys.path.insert(0, str(_src))

from any_charm_base import AnyCharmBase  # noqa: E402
from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer  # noqa: E402


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.traefik_route = TraefikRouteRequirer(
            self, self.model.get_relation("require-traefik-route"), "traefik_route"
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
