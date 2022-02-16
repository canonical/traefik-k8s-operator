#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm Traefik."""

import logging

import yaml
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
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


_TRAEFIK_CONTAINER_NAME = "traefik"
_TRAEFIK_LAYER_NAME = "traefik"
_TRAEFIK_SERVICE_NAME = "traefik"
# We watch the parent folder of where we store the configuration files,
# as that is usually safer for Traefik
_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY = "/opt/traefik/juju"


class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()
    _port = 80
    _diagnostics_port = 8082  # Prometheus metrics, healthcheck/ping

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(current_gateway_address=None)

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

        self.ingress_per_unit = IngressPerUnitProvider(charm=self)

        self.framework.observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.framework.observe(
            self.ingress_per_unit.on.request, self._handle_ingress_per_unit_request
        )
        self.framework.observe(
            self.ingress_per_unit.on.failed, self._handle_ingress_per_unit_failure
        )
        self.framework.observe(
            self.ingress_per_unit.on.broken, self._handle_ingress_per_unit_broken
        )

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
                path=_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY, pattern="juju_*.yaml"
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
                        "directory": _TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY,
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
        new_gateway_address = self._gateway_address

        if self._stored.current_gateway_address != new_gateway_address:
            self._stored.current_gateway_address = new_gateway_address
            self._process_status_and_configurations()

    def _process_status_and_configurations(self):
        if not self._gateway_address:
            self.unit.status = MaintenanceStatus(
                "resetting ingress-per-unit relations: gateway address not available"
            )

            for relation in self.model.relations["ingress-per-unit"]:
                self._wipe_ingress_for_relation(relation)

            self.unit.status = WaitingStatus("gateway address not available")

            return

        if not self._is_traefik_service_running():
            self.unit.status = WaitingStatus(f"service '{_TRAEFIK_CONTAINER_NAME}' not ready yet")
            return

        self.unit.status = MaintenanceStatus("updating the ingress configurations")

        for ingress_relation in self.ingress_per_unit.relations:
            self._process_ingress_per_unit_relation(ingress_relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("setup of some ingress relation failed")
            logger.error("The setup of some ingress relation failed, see previous logs")

    def _handle_ingress_per_unit_request(self, event: RelationEvent):
        if not self._gateway_address:
            self.unit.status = WaitingStatus("gateway address not available")
            event.defer()
            return

        if not self._is_traefik_service_running():
            self.unit.status = WaitingStatus(f"service '{_TRAEFIK_CONTAINER_NAME}' not ready yet")
            event.defer()
            return

        self._process_ingress_per_unit_relation(event.relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()

    def _process_ingress_per_unit_relation(self, relation: Relation):
        # There's a chance that we're processing a relation event
        # which was deferred until after the relation was broken.
        if not self.ingress_per_unit.is_ready(relation):
            return

        request = self.ingress_per_unit.get_request(relation)
        self.unit.status = MaintenanceStatus(
            "updating the ingress configurations for the "
            f"'{relation.name}:{relation.id}' relation"
        )
        logger.debug(
            "Updating the ingress configurations for the "
            f"'{relation.name}:{relation.id}' relation"
        )

        if self.unit.is_leader():
            if not (gateway_address := self._gateway_address):
                service = f"{self.app.name}.{self.model.name}.svc.cluster.local"

                for unit in request.units:
                    request.respond(unit, "")

                self.unit.status = WaitingStatus(
                    f"loadbalancer address not found on the '{service}' Kubernetes service"
                )
                return

        ingress_relation_configuration = {
            "http": {
                "routers": {},
                "services": {},
            }
        }

        # FIXME Ideally, follower units could instead watch for the data in the
        # ingress app data bag, but Juju does not allow non-leader units to read
        # the application data bag on their side of the relation, so we may start
        # routing for a remote unit before the leader unit of ingress has
        # communicated the url.
        for unit in request.units:
            unit_prefix = request.get_prefix(unit)
            unit_ingress_address = request.get_ip(unit)
            unit_port = request.port
            traefik_router_name = f"juju-{unit_prefix}-router"
            traefik_service_name = f"juju-{unit_prefix}-service"

            ingress_relation_configuration["http"]["routers"][traefik_router_name] = {
                "rule": f"PathPrefix(`/{unit_prefix}`)",
                "service": traefik_service_name,
                "entryPoints": ["web"],
            }

            ingress_relation_configuration["http"]["services"][traefik_service_name] = {
                "loadBalancer": {
                    "servers": [{"url": f"http://{unit_ingress_address}:{unit_port}"}]
                }
            }

            if self.unit.is_leader():
                request.respond(unit, f"http://{gateway_address}:{self._port}/{unit_prefix}")

        ingress_relation_configuration_path = f"{_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY}/{self._ingress_config_file_name(relation)}"
        self.traefik_container.push(
            ingress_relation_configuration_path,
            yaml.dump(ingress_relation_configuration),
            make_dirs=True,
        )

        logger.debug(f"Updated ingress configuration file: {ingress_relation_configuration_path}")

    def _handle_ingress_per_unit_failure(self, event: RelationEvent):
        self.unit.status = self.ingress_per_unit.get_status(event.relation)

    def _handle_ingress_per_unit_broken(self, event: RelationEvent):
        if not self._is_traefik_service_running():
            self.unit.status = WaitingStatus(f"service '{_TRAEFIK_CONTAINER_NAME}' not ready yet")
            event.defer()
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")

        self._wipe_ingress_for_relation(event.relation)

        self.unit.status = ActiveStatus()

    def _wipe_ingress_for_relation(self, relation: Relation):
        logger.debug(f"Wiping the ingress setup for the '{relation.name}:{relation.id}' relation")

        # Delete configuration files for the relation. In case of Traefik pod
        # churns, and depending on the event ordering, we might be executing this
        # logic before pebble in the traefik container is up and running. If that
        # is the case, nevermind, we will wipe the dangling config files anyhow
        # during _on_traefik_pebble_ready .
        if self.traefik_container.can_connect():
            try:
                ingress_relation_configuration_path = f"{_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY}/{self._ingress_config_file_name(relation)}"

                self.traefik_container.remove_path(ingress_relation_configuration_path)
                logger.debug(
                    f"Deleted orphaned {ingress_relation_configuration_path} ingress configuration file"
                )
            except PathError:
                logger.debug(
                    f"Ingress configurations for the '{relation.name}:{relation.id}' relation not found"
                )

        # Wipe URLs sent to the requesting units, as they are based on a gateway
        # address that is no longer valid.
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
    def _gateway_address(self):
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


def _get_loadbalancer_status(namespace: str, service_name: str):
    client = Client()
    traefik_service = client.get(Service, name=service_name, namespace=namespace)

    if status := traefik_service.status:
        if load_balancer_status := status.loadBalancer:
            if ingress_addresses := load_balancer_status.ingress:
                if ingress_address := ingress_addresses[0]:
                    return ingress_address.hostname or ingress_address.ip

    return None


if __name__ == "__main__":
    main(TraefikIngressCharm)
