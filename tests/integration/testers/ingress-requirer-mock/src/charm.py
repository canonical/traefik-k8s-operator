#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import socket

from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.charm import CharmBase, CollectStatusEvent
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer, LayerDict, ServiceDict

PORT = 8080


class IPARequirerMock(CharmBase):
    """Charm a workload that accepts traffic on a port and supports all ingress types."""

    def __init__(self, framework):
        super().__init__(framework)
        self.unit.set_ports(PORT)

        self.ipa = IngressPerAppRequirer(self, port=PORT, relation_name="ingress")

        # Useful for manual testing of duplicated ingresses
        self.ipa2 = IngressPerAppRequirer(self, port=PORT, relation_name="ingress-2")

        self.ipu = IngressPerUnitRequirer(
            self,
            port=PORT,
            relation_name="ingress-per-unit",
            strip_prefix=True,
            scheme=lambda: "http",
        )

        self.traefik_route = TraefikRouteRequirer(
            self,
            self.model.get_relation("traefik-route"),
            "traefik_route",
            raw=False,  # TODO: could vary this by config
        )
        self.framework.observe(self.on["traefik_route"].relation_joined, self._on_traefik_route)

        self.framework.observe(self.on.echo_server_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)

        # The routes generated for us can overlap (if a user tries to browse to an ipu path
        # (path-prefix="/modelname-appname-0") and an ipa path (path-prefix="/modelname-appname") exists, the ipa path can
        # match and route the user.  This could generate a false positive, so as a protection we raise if more than one
        # ingress relation is present.  traefik-route is also included in this check, as it can define any route path
        # and similarly overlap the others.
        #
        # To test multiple ingress types, deploy multiple instances of this tester.
        if (
            int(
                len(self.model.relations["ingress"]) > 0
                or len(self.model.relations["ingress-2"]) > 0
            )
            + len(self.model.relations["ingress-per-unit"])
            + len(self.model.relations["traefik-route"])
        ) > 1:
            raise ValueError(
                "Tester only supports using a single type of ingress relation.  See tester code comments for why. "
                "Deploy multiple instances of this charm to test multiple ingress types."
            )

    def _on_pebble_ready(self, _):
        container = self.unit.get_container("echo-server")
        if not container.can_connect():
            return

        layer = Layer(
            LayerDict(
                summary="echo server layer",
                description="pebble config layer for echo server",
                services={
                    "echo-server": ServiceDict(
                        override="replace",
                        command="/bin/echo-server",
                        startup="enabled",
                    )
                },
            )
        )

        container.add_layer("echo-server", layer, combine=True)
        container.autostart()

    def _on_collect_status(self, event: CollectStatusEvent):

        if not self.unit.get_container("echo-server").can_connect():
            event.add_status(WaitingStatus("Waiting for echo server container to connect"))
            return

        if self.model.relations["traefik-route"]:
            event.add_status(ActiveStatus("Traefik route established"))
            return

        if self.model.relations["ingress"] or self.model.relations["ingress-2"]:
            if self.model.relations["ingress"] and self.model.relations["ingress-2"]:
                event.add_status(
                    ActiveStatus(
                        "Ingress per app established on 'ingress' and 'ingress-2' endpoints"
                    )
                )
                return
            if self.model.relations["ingress"]:
                event.add_status(ActiveStatus("Ingress per app established on 'ingress' endpoint"))
                return
            if self.model.relations["ingress-2"]:
                event.add_status(
                    ActiveStatus("Ingress per app established on 'ingress-2' endpoint")
                )
                return

        if self.model.relations["ingress-per-unit"]:
            event.add_status(ActiveStatus("Ingress per unit established"))
            return

        event.add_status(ActiveStatus("Echo server running (no ingresses established)"))

    def _on_traefik_route(self, _):
        """Handle the traefik route relation being joined."""
        # Submit the ingress configuration to Traefik
        self.traefik_route.submit_to_traefik(self._traefik_route_config())

    def _traefik_route_config(self) -> dict:
        """Build a raw ingress configuration for traefik-route."""
        # The path prefix must be different than the automatically generated one for ingress per app, otherwise we'll
        # overwrite each other in cases where the tester is used for both.
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
            f"{router_name}-tls": {
                "entryPoints": ["websecure"],
                "rule": rule,
                "middlewares": list(middlewares.keys()),
                "service": service_name,
                "tls": {},  # tls termination at the ingress
            },
        }

        services = {service_name: {"loadBalancer": {"servers": [{"url": self.internal_url}]}}}

        return {"http": {"routers": routers, "services": services, "middlewares": middlewares}}

    @property
    def internal_url(self) -> str:
        """Return workload's internal URL. Used for ingress."""
        return f"http://{socket.getfqdn()}:{PORT}"


if __name__ == "__main__":
    main(IPARequirerMock)
