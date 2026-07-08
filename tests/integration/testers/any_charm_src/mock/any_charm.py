# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm-k8s src-overwrite for the ingress-requirer-mock.

Supports IPA, IPU, and traefik-route ingress modes (deploy multiple instances,
each related to a different endpoint). Runs a minimal HTTP server via pebble.
"""

import pathlib
import socket
import sys

import ops
from any_charm_base import AnyCharmBase
from ops.pebble import Layer

_src = pathlib.Path(__file__).parent
sys.path.insert(0, str(_src))

from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer  # noqa: E402
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer  # noqa: E402
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer  # noqa: E402

PORT = 8080


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit.set_ports(PORT)

        self.ipa = IngressPerAppRequirer(
            self, port=PORT, relation_name="require-ingress"
        )
        self.ipu = IngressPerUnitRequirer(
            self,
            port=PORT,
            relation_name="require-ingress-per-unit",
            strip_prefix=True,
            scheme=lambda: "http",
        )
        self.traefik_route = TraefikRouteRequirer(
            self,
            self.model.get_relation("require-traefik-route"),
            relation_name="require-traefik-route",
        )

        self.framework.observe(self.on["any"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.on["require-traefik-route"].relation_joined, self._on_traefik_route
        )
        self.unit.status = ops.ActiveStatus("ready")

    def _on_pebble_ready(self, event):
        container = event.workload
        container.exec(["apt-get", "update", "-qq"]).wait()
        container.exec(["apt-get", "install", "-y", "-qq", "python3"]).wait()
        server_script = (_src / "http_server.py").read_text()
        container.push("/http_server.py", server_script, make_dirs=True)
        layer = Layer({
            "summary": "http server layer",
            "services": {
                "http-server": {
                    "override": "replace",
                    "command": f"python3 /http_server.py {PORT}",
                    "startup": "enabled",
                }
            },
        })
        container.add_layer("http-server", layer, combine=True)
        container.replan()
        self._on_traefik_route(None)
        self.unit.status = ops.ActiveStatus("ready")

    def _on_traefik_route(self, _event):
        if not self.unit.is_leader() or not self.traefik_route.is_ready():
            return
        self.traefik_route.submit_to_traefik(self._traefik_route_config())

    def _traefik_route_config(self) -> dict:
        external_path = f"{self.model.name}-{self.model.app.name}-traefik-route"
        service_name = f"{external_path}-service"
        router_name = f"{external_path}-router"
        rule = f"PathPrefix(`/{external_path}`)"
        middlewares = {
            f"strip-prefix-{external_path}": {
                "stripPrefix": {"forceSlash": False, "prefixes": [f"/{external_path}"]},
            },
        }
        routers = {
            router_name: {
                "entryPoints": ["web"],
                "rule": rule,
                "middlewares": list(middlewares.keys()),
                "service": service_name,
            },
        }
        services = {
            service_name: {
                "loadBalancer": {"servers": [{"url": self._internal_url}]}
            }
        }
        return {"http": {"routers": routers, "services": services, "middlewares": middlewares}}

    @property
    def _internal_url(self) -> str:
        return f"http://{socket.getfqdn()}:{PORT}"
