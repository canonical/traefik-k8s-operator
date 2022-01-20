#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm Traefik."""

import logging

import yaml
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from lightkube import Client
from lightkube.resources.core_v1 import Service
from ops.charm import CharmBase, RelationEvent
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, Relation, WaitingStatus
from ops.pebble import PathError

logger = logging.getLogger(__name__)


_TRAEFIK_CONTAINER_NAME = "traefik"
_TRAEFIK_LAYER_NAME = "traefik"
_TRAEFIK_SERVICE_NAME = "traefik"
# We watch the parent folder of where we store the configuration files,
# as that is usually safer for Traefik
_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY = f"/opt/traefik/juju"


class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)

        self._port = 80
        self._ping_port = 8082

        self.service_patch = KubernetesServicePatch(
            charm=self,
            service_type="LoadBalancer",
            ports=[(f"{self.app.name}", self._port)],
        )

        self.framework.observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)

        # TODO Need to ensure K8s service has LoadBalancer IP before processing proxy requests?

        self.framework.observe(self.on["ingress"].relation_created, self._handle_ingress_change)
        self.framework.observe(self.on["ingress"].relation_joined, self._handle_ingress_change)
        self.framework.observe(self.on["ingress"].relation_changed, self._handle_ingress_change)
        self.framework.observe(self.on["ingress"].relation_departed, self._handle_ingress_change)
        self.framework.observe(self.on["ingress"].relation_broken, self._handle_ingress_broken)

    def _on_traefik_pebble_ready(self, event):
        # Ensure the required basic configurations and folders exist
        container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        # TODO Handle case the relation events are deferred and this hook has not
        # run yet when the pebble event queueing triggers the previously deferred
        # events.
        if not container.can_connect():
            self.unit.status = WaitingStatus(
                f"container '{_TRAEFIK_CONTAINER_NAME}' not yet ready"
            )
            return

        # TODO Use the Traefik user and group?
        container.make_dir(path="/etc/traefik", make_parents=True)
        container.make_dir(path=_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY, make_parents=True)

        # Since pebble ready will also occur after a pod churn, but we store the
        # configuration files on a storage volume that survives the pod churn, before
        # we start traefik we clean up all Juju-generated config files to avoid spurious
        # routes.
        for ingress_relation_configuration_file in container.list_files(
            path=_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY,
            pattern="juju_*.yaml"
        ):
            container.remove_path(ingress_relation_configuration_file.path)
            logger.debug(f"Deleted orphaned ingress configuration file: {ingress_relation_configuration_file.path}")

        # TODO Disable static config BS with telemetry and check new version
        basic_configurations = yaml.dump(
            {
                "log": {
                    "level": "DEBUG",
                },
                "entryPoints": {
                    "ping": {
                        "address": f":{self._ping_port}"
                    },
                    "web": {
                        "address": f":{self._port}"
                    }
                },
                "ping": {
                    "entryPoint": "ping"
                },
                "providers": {
                    "file": {
                        "directory": _TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY,
                        "watch": True,
                    }
                }
            }
        )

        container.push("/etc/traefik/traefik.yaml", basic_configurations)

        # After the container (re)starts, we need to loop over the relations to ensure all
        # the ingress configurations are there
        for ingress_relation in self.model.relations["ingress"]:
            self._process_ingress_relation(ingress_relation)

        self._restart_traefik()

        self.unit.status = ActiveStatus()

    def _handle_ingress_change(self, event: RelationEvent):
        if not isinstance(self.unit.status, ActiveStatus):
            logger.debug("Charm not active yet, deferring event")
            event.defer()
            return

        self._process_ingress_relation(event.relation)

    def _process_ingress_relation(self, relation: Relation):
        container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        if not container.can_connect():
            self.unit.status = WaitingStatus(
                f"container '{_TRAEFIK_CONTAINER_NAME}' not yet ready"
            )
            return

        other_app_name = relation.app.name

        # Version negotiation

        if self.unit.is_leader():
            supported_versions_raw = relation.data[relation.app]["_supported_versions"]

            supported_versions = yaml.safe_load(supported_versions_raw)

            if "v3" not in supported_versions:
                logger.error(
                    f"The {other_app_name} application does not support the ingress relation v3 "
                    f"(found: '{supported_versions}'); aborting data negotiation"
                )
                # TODO Put the charm in Blocked status?
                return

            logger.debug(f"Remote app of the '{relation.name}:{relation.id}' relation supports v3")

            if not "_supported_versions" in relation.data[self.app]:
                relation.data[self.app]["_supported_versions"] = "[v3]"
                logger.debug(f"Version v3 negotiated over the '{relation.name}:{relation.id}' relation")
                self.unit.status = ActiveStatus()
                return

        if not "data" in relation.data[relation.app]:
            if self.unit.is_leader():
                logger.debug(
                    f"Databag 'data' not found in the '{relation.name}:{relation.id}' "
                    "relation; aborting data negotiation"
                )
                # TODO Put the charm in Blocked status?
            else:
                logger.debug(
                    "Leader unit has not yet completed version negotiation for the "
                    f"'{relation.name}:{relation.id}' relation; skipping further event processing"
                )
            self.unit.status = ActiveStatus()
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")
        logger.debug(
            "Updating the ingress configurations for the "
            f"'{relation.name}:{relation.id}' relation"
        )

        other_app_data = yaml.safe_load(relation.data[relation.app]["data"])

        if not "namespace" in other_app_data:
            logger.debug(
                f"Namespace data not found in the '{relation.name}:{relation.id}' relation; aborting data negotiation"
            )
            # TODO Put the charm in Blocked status?
            self.unit.status = ActiveStatus()
            return

        if not "port" in other_app_data:
            logger.debug(
                f"Port data not found in the '{relation.name}:{relation.id}' relation; aborting data negotiation"
            )
            # TODO Put the charm in Blocked status?
            self.unit.status = ActiveStatus()
            return

        # We are relying on the fact that the model has the same name as the namespace
        namespace = other_app_data["namespace"]
        # namespace = relation.data["namespace"]
        # service = relation.data["service"]
        # prefix = relation.data["prefix"]
        # rewrite = relation.data["rewrite"]
        port = other_app_data["port"]

        if other_app_data["per_unit_routes"] is not True:
            # TODO Implement "normal" ingress routing over the K8s service
            logger.warning(
                f"The application '{relation.app.name}' is not requesting per_unit routing "
                f"over the '{relation.name}:{relation.id}' relation; aborting data negotiation"
            )
            return

        ingress_relation_configuration = {
            "http": {
                "routers": {},
                "services": {},
            }
        }

        unit_urls = {}
        # We should cache this, it is very expensive
        gateway_address = self._get_gateway_address()

        for unit in relation.units:
            if unit.app is self.app:
                logger.debug(f"Skipping unit {unit}")
                continue

            unit_id = unit.name[len(other_app_name) + 1:]

            # This does not work in CMRs if the application IS NOT ON THE SAME CLUSTER.
            # We probably could just look up the IP on `relation_joined` using the Kube
            # API and getting the pod ip.
            unit_ingress_address = f"{other_app_name}-{unit_id}.{other_app_name}-endpoints.{namespace}.svc.cluster.local"
            
            traefik_router_name = f"juju-{namespace}-{other_app_name}-{unit_id}-router"
            traefik_service_name = f"juju-{namespace}-{other_app_name}-{unit_id}-service"

            route_prefix = f"{namespace}-{other_app_name}-{unit_id}"
            ingress_relation_configuration["http"]["routers"][traefik_router_name] = {
                "rule": f"PathPrefix(`/{route_prefix}`)",
                "service": traefik_service_name,
                "entryPoints": ["web"],
            }

            ingress_relation_configuration["http"]["services"][traefik_service_name] = {
                "loadBalancer": {"servers": [{"url": f"http://{unit_ingress_address}:{port}"}]}
            }

            unit_urls[unit.name] = f"http://{gateway_address}:{self._port}/{route_prefix}"

        ingress_relation_configuration_path = f"{_TRAEFIK_INGRESS_CONFIGURATIONS_DIRECTORY}/{self._ingress_config_file_name(relation)}"
        container.push(ingress_relation_configuration_path, yaml.dump(ingress_relation_configuration))

        logger.debug(f"Updated ingress configuration file: {ingress_relation_configuration_path}")

        if self.unit.is_leader():
            # TODO remove this when the SDI library is updated
            relation.data[self.app]["data"] = yaml.dump({"url": f"http://{gateway_address}:{self._port}/nope", "unit_urls": unit_urls})

        self.unit.status = ActiveStatus()

    def _handle_ingress_broken(self, event: RelationEvent):
        if not isinstance(self.unit.status, ActiveStatus):
            logger.debug("Charm not active yet, deferring event")
            event.defer()
            return

        relation = event.relation

        container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        if not container.can_connect():
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

            container.remove_path(ingress_relation_configuration_path)
            logger.debug(f"Deleted orphaned {ingress_relation_configuration_path} ingress configuration file")
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
        # This could also be used
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
        container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        if not container.can_connect():
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
                    "command": f"/usr/local/bin/traefik",
                },
            },
        }

        current_pebble_layer = container.get_plan().to_dict()

        if current_pebble_layer != updated_pebble_layer:
            self.unit.status = MaintenanceStatus(f"updating the '{_TRAEFIK_SERVICE_NAME}' service")

            container.add_layer(_TRAEFIK_LAYER_NAME, updated_pebble_layer, combine=True)

            try:
                if is_restart := container.get_service(_TRAEFIK_SERVICE_NAME).is_running():
                    self.unit.status = MaintenanceStatus(
                        f"stopping the '{_TRAEFIK_SERVICE_NAME}' service to update the configurations"
                    )

                    container.stop(_TRAEFIK_SERVICE_NAME)
            except:
                # We have not yet set up the pebble service, nevermind
                logger.exception(
                    "The following error occurred while stopping the '%s' service, "
                    "maybe it has not been created yet?",
                    _TRAEFIK_SERVICE_NAME,
                    exc_info=True,
                )

            self.unit.status = MaintenanceStatus(f"starting the '{_TRAEFIK_SERVICE_NAME}' service")

            container.start(_TRAEFIK_SERVICE_NAME)

            if is_restart:
                logger.info(f"'{_TRAEFIK_SERVICE_NAME}' service restarted")
            else:
                logger.info(f"'{_TRAEFIK_SERVICE_NAME}' service started")
        else:
            logger.debug(
                "No differences found in the Pebble plan for the "
                f"'{_TRAEFIK_SERVICE_NAME}' service, no restart needed"
            )

        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(TraefikIngressCharm)
