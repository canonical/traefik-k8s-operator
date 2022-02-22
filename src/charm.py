#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm Traefik."""

import enum
import logging
from typing import Optional, Tuple

import yaml
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v0.ingress import IngressPerAppProvider
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitProvider
from lightkube import Client
from lightkube.resources.core_v1 import Service
from ops.charm import (
    CharmBase,
    ConfigChangedEvent,
    PebbleReadyEvent,
    RelationEvent,
    StartEvent,
    UpdateStatusEvent,
)
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    Relation,
    WaitingStatus,
)
from ops.pebble import APIError, PathError

try:
    # introduced in 3.9
    from functools import cache
except ImportError:
    from functools import lru_cache

    cache = lru_cache(maxsize=None)

logger = logging.getLogger(__name__)


_TRAEFIK_CONTAINER_NAME = _TRAEFIK_LAYER_NAME = _TRAEFIK_SERVICE_NAME = "traefik"
# We watch the parent folder of where we store the configuration files,
# as that is usually safer for Traefik
_CONFIG_DIRECTORY = "/opt/traefik/juju"


class _RoutingMode(enum.Enum):
    path = "path"
    subdomain = "subdomain"


class _IngressRelationType(enum.Enum):
    per_app = "per_app"
    per_unit = "per_unit"


class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()
    _port = 80
    _diagnostics_port = 8082  # Prometheus metrics, healthcheck/ping

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(current_external_host=None, current_routing_mode=None)

        self.traefik_container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        self.service_patch = KubernetesServicePatch(
            charm=self,
            service_type="LoadBalancer",
            ports=[(f"{self.app.name}", self._port)],
        )

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [{"targets": [f"*:{self._diagnostics_port}"]}],
                },
            ],
        )

        self.ingress_per_app = IngressPerAppProvider(charm=self)
        self.ingress_per_unit = IngressPerUnitProvider(charm=self)

        self.framework.observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.framework.observe(self.ingress_per_app.on.request, self._handle_ingress_request)
        self.framework.observe(self.ingress_per_app.on.failed, self._handle_ingress_failure)
        self.framework.observe(self.ingress_per_app.on.broken, self._handle_ingress_broken)

        self.framework.observe(self.ingress_per_unit.on.request, self._handle_ingress_request)
        self.framework.observe(self.ingress_per_unit.on.failed, self._handle_ingress_failure)
        self.framework.observe(self.ingress_per_unit.on.broken, self._handle_ingress_broken)

    def _on_traefik_pebble_ready(self, _: PebbleReadyEvent):
        # The the Traefik container comes up, e.g., after a pod churn, we
        # ignore the unit status and start fresh.

        # Ensure the required basic configurations and folders exist
        # TODO Use the Traefik user and group?

        # Since pebble ready will also occur after a pod churn, but we store the
        # configuration files on a storage volume that survives the pod churn, before
        # we start traefik we clean up all Juju-generated config files to avoid spurious
        # routes.
        try:
            for ingress_relation_configuration_file in self.traefik_container.list_files(
                path=_CONFIG_DIRECTORY, pattern="juju_*.yaml"
            ):
                self.traefik_container.remove_path(ingress_relation_configuration_file.path)
                logger.debug(
                    f"Deleted orphaned ingress configuration file: {ingress_relation_configuration_file.path}"
                )
        except (FileNotFoundError, APIError):
            pass

        # TODO Disable static config with telemetry and check new version
        basic_configurations = yaml.dump(
            {
                "log": {
                    "level": "DEBUG",
                },
                "entryPoints": {
                    "diagnostics": {"address": f":{self._diagnostics_port}"},
                    "web": {"address": f":{self._port}"},
                },
                # We always start the Prometheus endpoint for simplicity
                # TODO: Generate this file in the dynamic configuration folder when the
                # metrics-endpoint relation is established?
                "metrics": {
                    "prometheus": {
                        "addRoutersLabels": True,
                        "addServicesLabels": True,
                        "entryPoint": "diagnostics",
                    }
                },
                "ping": {"entryPoint": "diagnostics"},
                "providers": {
                    "file": {
                        "directory": _CONFIG_DIRECTORY,
                        "watch": True,
                    }
                },
            }
        )

        self.traefik_container.push(
            "/etc/traefik/traefik.yaml", basic_configurations, make_dirs=True
        )

        self._restart_traefik()
        self._process_status_and_configurations()

    def _on_start(self, _: StartEvent):
        self._process_status_and_configurations()

    def _on_update_status(self, _: UpdateStatusEvent):
        self._process_status_and_configurations()

    def _on_config_changed(self, _: ConfigChangedEvent):
        # If the external hostname is changed since we last processed it, we need to
        # to reconsider all data sent over the relations and all configs
        new_external_host = self._external_host
        new_routing_mode = self.config["routing_mode"]

        if (
            self._stored.current_external_host != new_external_host
            or self._stored.current_routing_mode != new_routing_mode
        ):
            self._stored.current_external_host = new_external_host
            self._stored.current_routing_mode = new_routing_mode
            self._process_status_and_configurations()

    def _process_status_and_configurations(self):
        routing_mode = self.config["routing_mode"]
        try:
            _RoutingMode(routing_mode)
        except ValueError:
            self.unit.status = MaintenanceStatus(
                "resetting ingress relations: invalid routing_mode"
            )

            self._wipe_ingress_for_all_relations()

            self.unit.status = BlockedStatus(
                f"'{routing_mode}' is not a valid routing_mode value; see debug logs for more information"
            )
            logger.error(
                "'%s' is not a valid routing_mode value; valid values are: %s",
                routing_mode,
                [e.value for e in _RoutingMode],
            )
            return

        if not self._external_host:
            self.unit.status = MaintenanceStatus(
                "resetting ingress relations: gateway address not available"
            )

            self._wipe_ingress_for_all_relations()

            self.unit.status = WaitingStatus("gateway address not available")
            return

        if not self._is_traefik_service_running():
            self.unit.status = WaitingStatus(f"service '{_TRAEFIK_CONTAINER_NAME}' not ready yet")
            return

        self.unit.status = MaintenanceStatus("updating the ingress configurations")

        for ingress_relation in self.ingress_per_app.relations + self.ingress_per_unit.relations:
            self._process_ingress_relation(ingress_relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("setup of some ingress relation failed")
            logger.error("The setup of some ingress relation failed, see previous logs")

    def _handle_ingress_request(self, event: RelationEvent):
        if not self._external_host:
            self.unit.status = WaitingStatus("gateway address not available")
            event.defer()
            return

        if not self._is_traefik_service_running():
            self.unit.status = WaitingStatus(f"service '{_TRAEFIK_CONTAINER_NAME}' not ready yet")
            event.defer()
            return

        self._process_ingress_relation(event.relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()

    def _process_ingress_relation(self, rel: Relation):
        # There's a chance that we're processing a relation event
        # which was deferred until after the relation was broken.
        per_app = _get_relation_type(rel) == _IngressRelationType.per_app

        if per_app and not self.ingress_per_app.is_ready(rel):
            return
        if not per_app and not self.ingress_per_unit.is_ready(rel):
            return

        msg = f"updating the ingress configurations for the '{rel.name}:{rel.id}' relation"
        self.unit.status = MaintenanceStatus(msg)
        logger.debug(msg)

        request = (
            self.ingress_per_app.get_request(rel)
            if per_app
            else self.ingress_per_unit.get_request(rel)
        )

        if not (gateway_address := self._check_gateway_address(per_app, request)):
            return

        if per_app:
            config, app_url = self._generate_per_app_config(request, gateway_address)
            if self.unit.is_leader():
                request.respond(app_url)
        else:
            # FIXME Ideally, follower units could instead watch for the data in the
            # ingress app data bag, but Juju does not allow non-leader units to read
            # the application data bag on their side of the relation, so we may start
            # routing for a remote unit before the leader unit of ingress has
            # communicated the url.
            for unit in request.units:
                config, unit_url = self._generate_per_unit_config(request, gateway_address, unit)
                if self.unit.is_leader():
                    request.respond(unit, unit_url)

        config_filename = f"{_CONFIG_DIRECTORY}/{self._ingress_config_file_name(rel)}"

        self.traefik_container.push(config_filename, yaml.dump(config), make_dirs=True)

        logger.debug(f"Updated ingress configuration file: {config_filename}")

    def _check_gateway_address(self, per_app: bool, request) -> Optional[str]:
        if self.unit.is_leader():
            if not (gateway_address := self._external_host):
                service = f"{self.app.name}.{self.model.name}.svc.cluster.local"

                if per_app:
                    request.respond("")
                else:
                    for unit in request.units:
                        request.respond(unit, "")

                msg = f"loadbalancer address not found on the '{service}' Kubernetes service"
                self.unit.status = WaitingStatus(msg)
                return None
            return gateway_address

    def _generate_per_unit_config(self, request, gateway_address, unit) -> Tuple[dict, str]:
        """Generate a config dict for a given unit for IngressPerUnit."""
        # Base config
        config = {"http": {"routers": {}, "services": {}}}

        unit_name = request.get_unit_name(unit).replace("/", "-")
        prefix = f"{request.model}-{unit_name}"

        if self._routing_mode == _RoutingMode.path:
            route_rule = f"PathPrefix(`/{prefix}`)"
            unit_url = f"http://{gateway_address}:{self._port}/{prefix}"
        elif self._routing_mode == _RoutingMode.subdomain:
            route_rule = f"Host(`{prefix}.{self._external_host}`)"
            unit_url = f"http://{prefix}.{gateway_address}:{self._port}/"

        traefik_router_name = f"juju-{prefix}-router"
        traefik_service_name = f"juju-{prefix}-service"

        config["http"]["routers"][traefik_router_name] = {
            "rule": route_rule,
            "service": traefik_service_name,
            "entryPoints": ["web"],
        }

        config["http"]["services"][traefik_service_name] = {
            "loadBalancer": {
                "servers": [{"url": f"http://{request.get_host(unit)}:{request.port}"}]
            }
        }

        return config, unit_url

    def _generate_per_app_config(self, request, gateway_address) -> Tuple[dict, str]:
        id = f"{request.model}-{request.app_name}"

        if self._routing_mode == _RoutingMode.path:
            route_rule = f"PathPrefix(`/{id}`)"
            app_url = f"http://{gateway_address}:{self._port}/{id}"
        elif self._routing_mode == _RoutingMode.subdomain:
            route_rule = f"Host(`{id}.{self.external_host}`)"
            app_url = f"http://{id}.{gateway_address}:{self._port}/"

        traefik_router_name = f"juju-{id}-router"
        traefik_service_name = f"juju-{id}-service"

        config = {
            "http": {
                "routers": {
                    traefik_router_name: {
                        "rule": route_rule,
                        "service": traefik_service_name,
                        "entryPoints": ["web"],
                    }
                },
                "services": {
                    traefik_service_name: {
                        "loadBalancer": {
                            "servers": [{"url": f"http://{request.host}:{request.port}"}]
                        }
                    }
                },
            }
        }

        return config, app_url

    def _handle_ingress_failure(self, event: RelationEvent):
        self.unit.status = (
            self.ingress_per_app.get_status(event.relation)
            if _get_relation_type(event.relation) == _IngressRelationType.per_app
            else self.ingress_per_unit.get_status(event.relation)
        )

    def _handle_ingress_broken(self, event: RelationEvent):
        if not self._is_traefik_service_running():
            self.unit.status = WaitingStatus(f"service '{_TRAEFIK_CONTAINER_NAME}' not ready yet")
            event.defer()
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")

        self._wipe_ingress_for_relation(event.relation)

        self.unit.status = ActiveStatus()

    def _wipe_ingress_for_all_relations(self):
        for relation in self.model.relations["ingress"] + self.model.relations["ingress-per-unit"]:
            self._wipe_ingress_for_relation(relation)

    def _wipe_ingress_for_relation(self, relation: Relation):
        logger.debug(f"Wiping the ingress setup for the '{relation.name}:{relation.id}' relation")

        # Delete configuration files for the relation. In case of Traefik pod
        # churns, and depending on the event ordering, we might be executing this
        # logic before pebble in the traefik container is up and running. If that
        # is the case, nevermind, we will wipe the dangling config files anyhow
        # during _on_traefik_pebble_ready .
        if self.traefik_container.can_connect():
            try:
                ingress_relation_configuration_path = (
                    f"{_CONFIG_DIRECTORY}/{self._ingress_config_file_name(relation)}"
                )

                self.traefik_container.remove_path(ingress_relation_configuration_path)
                logger.debug(
                    f"Deleted orphaned {ingress_relation_configuration_path} ingress configuration file"
                )
            except PathError:
                logger.debug(
                    f"Ingress configurations for the '{relation.name}:{relation.id}' relation not found"
                )

        # Wipe URLs sent to the requesting apps and units, as they are based on a gateway
        # address that is no longer valid.
        if self.ingress_per_app.is_ready():
            if request := self.ingress_per_app.get_request(relation):
                request.respond("")

        if self.ingress_per_unit.is_ready():
            for unit in relation.units:
                if unit.app != self.app:
                    if request := self.ingress_per_unit.get_request(relation):
                        request.respond(unit, "")

    def _ingress_config_file_name(self, relation: Relation):
        # Using both the relation it and the app name in the file to facilitate
        # the debugging experience somewhat when snooping into the container at runtime:
        # Apps not in the same model as Traefik (i.e., if `relation` is a CRM) will have
        # some `remote_...` as app name. Relation name and id are handy when one is
        # troubleshooting via `juju run 'relation_ids'...` and the like.`

        return f"juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"

    def _is_traefik_service_running(self):
        if not self.traefik_container.can_connect():
            return False

        try:
            # FIXME We cannot check by looking got the _TRAEFIK_SERVICE_NAME in
            # `self.traefik_container.get_services()` because it would wrongly fail
            # in the test Harness, see https://github.com/canonical/operator/issues/694
            return self.traefik_container.get_service(_TRAEFIK_SERVICE_NAME).is_running()
        except ModelError:
            return False

    def _restart_traefik(self):
        updated_pebble_layer = {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                _TRAEFIK_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Traefik",
                    "command": "/usr/bin/traefik",
                },
            },
        }

        current_pebble_layer = self.traefik_container.get_plan().to_dict()

        if (
            not current_pebble_layer
            or _TRAEFIK_SERVICE_NAME not in current_pebble_layer["services"]
        ):
            self.unit.status = MaintenanceStatus(f"creating the '{_TRAEFIK_SERVICE_NAME}' service")
            self.traefik_container.add_layer(
                _TRAEFIK_LAYER_NAME, updated_pebble_layer, combine=True
            )

        try:
            if self.traefik_container.get_service(_TRAEFIK_SERVICE_NAME).is_running():
                self.traefik_container.stop(_TRAEFIK_SERVICE_NAME)
        except Exception:
            # We have not yet set up the pebble service, nevermind
            logger.exception(
                "The following error occurred while stopping the '%s' service, "
                "maybe it has not been created yet?",
                _TRAEFIK_SERVICE_NAME,
                exc_info=True,
            )

        self.traefik_container.start(_TRAEFIK_SERVICE_NAME)

    @property
    def _external_host(self):
        """Determine the external address for the ingress gateway.

        It will prefer the `external-hostname` config if that is set, otherwise
        it will look up the load balancer address for the ingress gateway.

        If the gateway isn't available or doesn't have a load balancer address yet,
        returns None.
        """
        if "external_hostname" in self.model.config:
            if external_hostname := self.model.config["external_hostname"]:
                return external_hostname

        return _get_loadbalancer_status(namespace=self.model.name, service_name=self.app.name)

    @property
    def _routing_mode(self) -> _RoutingMode:
        """Return the current routing mode for the ingress.

        The two modes are 'subdomain' and 'path', where 'path' is the default.
        """
        return _RoutingMode(self.config["routing_mode"])


def _get_loadbalancer_status(namespace: str, service_name: str):
    client = Client()
    traefik_service = client.get(Service, name=service_name, namespace=namespace)

    if status := traefik_service.status:
        if load_balancer_status := status.loadBalancer:
            if ingress_addresses := load_balancer_status.ingress:
                if ingress_address := ingress_addresses[0]:
                    return ingress_address.hostname or ingress_address.ip

    return None


def _get_relation_type(relation: Relation) -> _IngressRelationType:
    return (
        _IngressRelationType.per_app
        if relation.name == "ingress"
        else _IngressRelationType.per_unit
    )


if __name__ == "__main__":
    main(TraefikIngressCharm)
