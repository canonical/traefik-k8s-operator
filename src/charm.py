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
from charms.traefik_k8s.v0.ingress_unit import IngressUnitProvider
from lightkube import Client
from lightkube.resources.core_v1 import Service
from ops.charm import CharmBase, RelationEvent
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, Relation, WaitingStatus
from ops.pebble import PathError

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

    def __init__(self, *args):
        super().__init__(*args)

        self._port = 80
        self._diagnostics_port = 8082

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

        self.ingress_unit = IngressUnitProvider(self)

        self.framework.observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)
        self.framework.observe(self.ingress_unit.on.request, self._handle_ingress_unit_request)
        self.framework.observe(self.ingress_unit.on.failed, self._handle_ingress_unit_failure)
        self.framework.observe(self.ingress_unit.on.broken, self._handle_ingress_unit_broken)

    def _on_traefik_pebble_ready(self, _):
        # Ensure the required basic configurations and folders exist

        # TODO Handle case the relation events are deferred and this hook has not
        # run yet when the pebble event queueing triggers the previously deferred
        # events.
        if not self.traefik_container.can_connect():
            self.unit.status = WaitingStatus(
                f"container '{_TRAEFIK_CONTAINER_NAME}' not yet ready"
            )
            return

        # TODO Use the Traefik user and group?
        self.traefik_container.make_dir(path="/etc/traefik", make_parents=True)
        self.traefik_container.make_dir(
            path=_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY, make_parents=True
        )

        # Since pebble ready will also occur after a pod churn, but we store the
        # configuration files on a storage volume that survives the pod churn, before
        # we start traefik we clean up all Juju-generated config files to avoid spurious
        # routes.
        for ingress_relation_configuration_file in self.traefik_container.list_files(
            path=_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY, pattern="juju_*.yaml"
        ):
            self.traefik_container.remove_path(ingress_relation_configuration_file.path)
            logger.debug(
                f"Deleted orphaned ingress configuration file: {ingress_relation_configuration_file.path}"
            )

        # TODO Disable static config BS with telemetry and check new version
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

        self.traefik_container.push("/etc/traefik/traefik.yaml", basic_configurations)

        # After the container (re)starts, we need to loop over the relations to ensure all
        # the ingress configurations are there
        for ingress_relation in self.ingress_unit.relations:
            self._process_ingress_unit_relation(ingress_relation)

        self._restart_traefik()

        self.unit.status = ActiveStatus()

    def _handle_ingress_unit_request(self, event: RelationEvent):
        if not isinstance(self.unit.status, ActiveStatus):
            logger.debug("Charm not active yet, deferring event")
            event.defer()
            return

        self._process_ingress_unit_relation(event.relation)

    def _handle_ingress_unit_failure(self, event: RelationEvent):
        self.unit.status = self.ingress_unit.get_status(event.relation)

    def _process_ingress_unit_relation(self, relation: Relation):
        if not self.traefik_container.can_connect():
            self.unit.status = WaitingStatus(
                f"container '{_TRAEFIK_CONTAINER_NAME}' not yet ready"
            )
            return
        # There's a very small chance that we're processing a relation event
        # which was deferred until after the relation was broken.
        if not self.ingress_unit.is_ready(relation):
            return

        request = self.ingress_unit.get_request(relation)
        self.unit.status = MaintenanceStatus("updating ingress configurations")
        logger.debug(
            "Updating the ingress configurations for the "
            f"'{relation.name}:{relation.id}' relation"
        )

        # TODO We should cache this, it is very expensive
        gateway_address = self._get_gateway_address()

        ingress_relation_configuration = {
            "http": {
                "routers": {},
                "services": {},
            }
        }

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
            ingress_relation_configuration_path, yaml.dump(ingress_relation_configuration)
        )

        logger.debug(f"Updated ingress configuration file: {ingress_relation_configuration_path}")

        self.unit.status = ActiveStatus()

    def _handle_ingress_unit_broken(self, event: RelationEvent):
        if not isinstance(self.unit.status, ActiveStatus):
            logger.debug("Charm not active yet, deferring event")
            event.defer()
            return

        relation = event.relation

        if not self.traefik_container.can_connect():
            self.unit.status = WaitingStatus(
                f"container '{_TRAEFIK_CONTAINER_NAME}' not yet ready"
            )
            event.defer()
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")

        logger.debug(
            "Deleting the ingress configurations for the "
            f"'{relation.name}:{relation.id}' relation"
        )

        try:
            ingress_relation_configuration_path = f"{_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY}/{self._ingress_config_file_name(relation)}"

            self.traefik_container.remove_path(ingress_relation_configuration_path)
            logger.debug(
                f"Deleted orphaned {ingress_relation_configuration_path} ingress configuration file"
            )
        except PathError:
            logger.debug(
                "Trying to delete non-existent ingress configurations for the "
                f"'{relation.name}:{relation.id}' relation"
            )

        self.unit.status = ActiveStatus()

    def _ingress_config_file_name(self, relation: Relation):
        other_app = relation.app

        # Using both the relation it and the app name in the file to facilitate
        # the debugging experience somewhat when snooping into the container at runtime:
        # Apps not in the same model as Traefik (i.e., if `relation` is a CRM) will have
        # some `remote_...` as app name. Relation name and id are handy when one is
        # troubleshooting via `juju run 'relation_ids'...` and the like.`

        return f"juju_ingress_{relation.name}_{relation.id}_{other_app.name}.yaml"

    @cache
    def _get_gateway_address(self):
        """Determine the external address for the ingress gateway.

        It will prefer the `external-hostname` config if that is set, otherwise
        it will look up the load balancer address for the ingress gateway.

        If the gateway isn't available or doesn't have a load balancer address yet,
        returns None.
        """
        if "external_hostname" in self.model.config:
            return self.model.config["external_hostname"]

        namespace = self.model.name
        # This could also be used, but then needs to be mocked in the tests:
        #
        # with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
        #     namespace = f.read().strip()

        client = Client()
        traefik_service = client.get(Service, name=self.app.name, namespace=namespace)

        if status := traefik_service.status:
            if load_balancer_status := status.loadBalancer:
                if ingress_addresses := load_balancer_status.ingress:
                    ingress_address = ingress_addresses[0]
                    return ingress_address.hostname or ingress_address.ip

        return None

    def _restart_traefik(self):
        if not self.traefik_container.can_connect():
            self.unit.status = WaitingStatus(
                f"container '{_TRAEFIK_CONTAINER_NAME}' not yet ready"
            )
            return

        updated_pebble_layer = {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                _TRAEFIK_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Traefik",
                    "command": "/usr/local/bin/traefik",
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
            if is_restart := self.traefik_container.get_service(
                _TRAEFIK_SERVICE_NAME
            ).is_running():
                self.unit.status = MaintenanceStatus(
                    f"stopping the '{_TRAEFIK_SERVICE_NAME}' service to update the configurations"
                )

                self.traefik_container.stop(_TRAEFIK_SERVICE_NAME)
        except Exception:
            # We have not yet set up the pebble service, nevermind
            logger.exception(
                "The following error occurred while stopping the '%s' service, "
                "maybe it has not been created yet?",
                _TRAEFIK_SERVICE_NAME,
                exc_info=True,
            )

        maintenance_status_message = f"starting the '{_TRAEFIK_SERVICE_NAME}' service"
        if is_restart:
            maintenance_status_message = f"re{maintenance_status_message}"

        self.unit.status = MaintenanceStatus(maintenance_status_message)
        self.traefik_container.start(_TRAEFIK_SERVICE_NAME)

        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(TraefikIngressCharm)
