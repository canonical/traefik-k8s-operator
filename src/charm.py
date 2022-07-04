#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Traefik."""

import enum
import json
import logging
import typing
from typing import Tuple, Union, Callable, Dict

import yaml
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v1.ingress import IngressPerAppProvider
from charms.traefik_k8s.v1.ingress_per_unit import (
    DataValidationError,
    IngressPerUnitProvider,
)
from charms.traefik_route_k8s.v0.traefik_route import (
    TraefikRouteProvider,
    TraefikRouteRequirerReadyEvent,
)
from deepmerge import always_merger
from lightkube import Client
from lightkube.resources.core_v1 import Service
from ops.charm import (
    ActionEvent,
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
    Relation,
    WaitingStatus,
)
from ops.pebble import APIError, PathError

if typing.TYPE_CHECKING:
    from charms.traefik_k8s.v1.ingress import RequirerData as RequirerData_IPA
    from charms.traefik_k8s.v1.ingress_per_unit import RequirerData as RequirerData_IPU

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
    routed = "routed"


class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()
    _port = 80
    _diagnostics_port = 8082  # Prometheus metrics, healthcheck/ping

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(current_external_host=None, current_routing_mode=None)

        self.container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

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
        self.traefik_route = TraefikRouteProvider(charm=self)

        observe = self.framework.observe
        observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)
        observe(self.on.start, self._on_start)
        observe(self.on.update_status, self._on_update_status)
        observe(self.on.config_changed, self._on_config_changed)

        ipa_events = self.ingress_per_app.on
        observe(ipa_events.data_provided, self._handle_ingress_data_provided)
        observe(ipa_events.data_removed, self._handle_ingress_data_removed)

        ipu_events = self.ingress_per_unit.on
        observe(ipu_events.data_provided, self._handle_ingress_data_provided)
        observe(ipu_events.data_removed, self._handle_ingress_data_removed)

        observe(self.traefik_route.on.ready, self._handle_traefik_route_ready)

        # Action handlers
        observe(self.on.show_proxied_endpoints_action, self._on_show_proxied_endpoints)

    def _on_show_proxied_endpoints(self, event: ActionEvent):
        try:
            result = {}
            result.update(self.ingress_per_unit.proxied_endpoints)
            result.update(self.ingress_per_app.proxied_endpoints)

            event.set_results({"proxied-endpoints": json.dumps(result)})
        except Exception as e:
            logger.exception("Action 'show-proxied-endpoints' failed")
            event.fail(str(e))

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
            for file in self.container.list_files(path=_CONFIG_DIRECTORY, pattern="juju_*.yaml"):
                self.container.remove_path(file.path)
                logger.debug("Deleted orphaned ingress configuration file: %s", file.path)
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

        self.container.push("/etc/traefik/traefik.yaml", basic_configurations, make_dirs=True)
        self.container.make_dir(_CONFIG_DIRECTORY, make_parents=True)
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
            self.unit.status = MaintenanceStatus("resetting ingress relations")
            self._wipe_ingress_for_all_relations()
            self.unit.status = BlockedStatus(f"invalid routing mode: {routing_mode}; see logs.")

            logger.error(
                "'%s' is not a valid routing_mode value; valid values are: %s",
                routing_mode,
                [e.value for e in _RoutingMode],
            )
            return

        if not self._external_host:
            self.unit.status = MaintenanceStatus("resetting ingress relations")
            self._wipe_ingress_for_all_relations()
            self.unit.status = WaitingStatus("gateway address unavailable")
            return

        if not self._traefik_service_running:
            self.unit.status = WaitingStatus(f"waiting for service: '{_TRAEFIK_SERVICE_NAME}'")
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")

        for ingress_relation in self.ingress_per_app.relations + self.ingress_per_unit.relations:
            self._process_ingress_relation(ingress_relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("setup of some ingress relation failed")
            logger.error("The setup of some ingress relation failed, see previous logs")

    @property
    def ready(self) -> bool:
        """Check whether we have an external host set, and traefik is running."""
        if not self._external_host:
            self._wipe_ingress_for_all_relations()  # fixme: no side-effects in prop
            self.unit.status = WaitingStatus("gateway address unavailable")
            return False
        if not self._traefik_service_running:
            self.unit.status = WaitingStatus(f"waiting for service: '{_TRAEFIK_SERVICE_NAME}'")
            return False
        return True

    def _handle_ingress_data_provided(self, event: RelationEvent):
        """A unit has provided data requesting ipu."""
        if not self.ready:
            event.defer()
            return
        self._process_ingress_relation(event.relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()

    def _handle_ingress_data_removed(self, event: RelationEvent):
        """A unit has removed the data we need to provide ingress."""
        self._wipe_ingress_for_relation(event.relation)

    def _handle_traefik_route_ready(self, event: TraefikRouteRequirerReadyEvent):
        """A traefik_route charm has published some ingress data."""
        self._process_ingress_relation(event.relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()

    def _process_ingress_relation(self, relation: Relation):
        # There's a chance that we're processing a relation event which was deferred until after
        # the relation was broken. Select the right per_app/per_unit provider and check it is ready
        # before continuing. However, the provider will NOT be ready if there are no units on the
        # other side, which is the case for the RelationDeparted for the last unit (i.e., the
        # proxied application scales to zero).
        gateway_address = self._external_host
        assert gateway_address, "No gateway address available"

        provider = self._provider_from_relation(relation)
        if not provider.is_ready(relation):
            # TODO Cleanup: the provider for ingress_per_unit will NOT be ready
            #  if there are no units on the other side, which is the case for
            #  the RelationDeparted for the last unit (i.e., the proxied
            #  application scales to zero).

            if provider == self.ingress_per_unit and not relation.units:
                logger.debug(
                    "No units found in the ingress-per-unit relation; resetting ingress configurations"
                )
                self._wipe_ingress_for_relation(relation)

        rel = f"{relation.name}:{relation.id}"
        self.unit.status = MaintenanceStatus(f"updating ingress configuration for '{rel}'")
        logger.debug("Updating ingress for relation '%s'", rel)

        if provider is self.traefik_route:
            return self._provide_routed_ingress(relation)

        self._provide_ingress(relation, provider)

    def _provide_routed_ingress(self, relation: Relation):
        """Provide ingress to a unit related through TraefikRoute."""
        if not self.traefik_route.is_ready(relation):
            logger.info("traefik-route not ready on %s", relation)
            return
        config = self.traefik_route.get_config(relation)
        self._push_configurations(relation, config)

    def _provide_ingress(
        self, relation: Relation,
            provider: Union[IngressPerAppProvider, IngressPerAppProvider]
    ):
        # to avoid long-gone units from lingering in the databag, we wipe it
        if self.unit.is_leader():
            provider.wipe_ingress_data(relation)

        # generate configs based on ingress type
        # this will also populate our databags with the urls
        # fixme no side-effects in _get_ method.
        if provider is self.ingress_per_unit:
            config_getter = self._get_configs_per_unit
        else:  # self.ingress_per_app
            config_getter = self._get_configs_per_app

        configs = config_getter(relation)
        self._push_configurations(relation, configs)

    def _get_configs_per_app(self, relation: Relation):
        provider = self.ingress_per_app

        try:
            data: "RequirerData_IPA" = provider.get_data(relation)
        except DataValidationError as e:
            logger.error(f"invalid data shared through {relation}... Error: {e}.")
            return

        config, app_url = self._generate_per_app_config(data)
        if self.unit.is_leader():
            provider.publish_url(relation, app_url)

        return config

    def _get_configs_per_unit(self, relation: Relation):
        # FIXME Ideally, follower units could instead watch for the data in the
        # ingress app data bag, but Juju does not allow non-leader units to read
        # the application data bag on their side of the relation, so we may start
        # routing for a remote unit before the leader unit of ingress has
        # communicated the url.
        provider = self.ingress_per_unit

        config = {}
        for unit in relation.units:
            if not provider.is_unit_ready(relation, unit):
                continue
            # if the unit is ready, it's implied that the data is there.
            # but we should still ensure it's valid, hence...
            try:
                data: "RequirerData_IPU" = provider.get_data(relation, unit)
            except DataValidationError as e:
                # is_unit_ready should guard against no data being there yet,
                # but if the data is invalid...
                logger.error(f"invalid data shared through {relation} by "
                             f"{unit}... Error: {e}.")
                continue

            unit_config, unit_url = self._generate_per_unit_config(data)
            if self.unit.is_leader():
                provider.publish_url(relation, data["name"], unit_url)
            always_merger.merge(config, unit_config)

        # Note: We might be pushing an empty configuration if, for example,
        # none of the units has yet written their part of the data into the
        # relation. Traefik is fine with it :-)
        return config

    def _push_configurations(self, relation: Relation, config: Union[dict, str]):
        if config:
            yaml_config = yaml.dump(config) if not isinstance(config, str) else config
            config_filename = f"{_CONFIG_DIRECTORY}/{self._relation_config_file(relation)}"
            self.container.push(config_filename, yaml_config, make_dirs=True)
            logger.debug("Updated ingress configuration file: %s", config_filename)
        else:
            self._wipe_ingress_for_relation(relation)

    def _generate_per_unit_config(self, data: "RequirerData_IPU") -> Tuple[dict, str]:
        """Generate a config dict for a given unit for IngressPerUnit."""
        config = {"http": {"routers": {}, "services": {}}}
        name = data["name"].replace("/", "-")
        prefix = f"{data['model']}-{name}"

        host = self._external_host
        if self._routing_mode is _RoutingMode.path:
            route_rule = f"PathPrefix(`/{prefix}`)"
            unit_url = f"http://{host}:{self._port}/{prefix}"
        else:  # _RoutingMode.subdomain
            route_rule = f"Host(`{prefix}.{host}`)"
            unit_url = f"http://{prefix}.{host}:{self._port}/"

        traefik_router_name = f"juju-{prefix}-router"
        traefik_service_name = f"juju-{prefix}-service"

        config["http"]["routers"][traefik_router_name] = {
            "rule": route_rule,
            "service": traefik_service_name,
            "entryPoints": ["web"],
        }
        config["http"]["services"][traefik_service_name] = {
            "loadBalancer": {"servers": [{"url": f"http://{data['host']}:{data['port']}"}]}
        }
        return config, unit_url

    def _generate_per_app_config(self, data: "RequirerData_IPA") -> Tuple[dict, str]:
        host = self._external_host
        port = self._port
        prefix = f"{data['model']}-{data['name']}"

        if self._routing_mode == _RoutingMode.path:
            route_rule = f"PathPrefix(`/{prefix}`)"
            app_url = f"http://{host}:{port}/{prefix}"
        else:  # _RoutingMode.subdomain
            route_rule = f"Host(`{prefix}.{host}`)"
            app_url = f"http://{prefix}.{host}:{port}/"

        traefik_router_name = f"juju-{prefix}-router"
        traefik_service_name = f"juju-{prefix}-service"

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
                            "servers": [{"url": f"http://{data['host']}:{data['port']}"}]
                        }
                    }
                },
            }
        }

        return config, app_url

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
        if self.container.can_connect():
            try:
                config_path = f"{_CONFIG_DIRECTORY}/{self._relation_config_file(relation)}"
                self.container.remove_path(config_path, recursive=True)
                logger.debug(f"Deleted orphaned {config_path} ingress configuration file")
            except (PathError, FileNotFoundError):
                logger.debug("Configurations for '%s:%s' not found", relation.name, relation.id)

        # Wipe URLs sent to the requesting apps and units, as they are based on a gateway
        # address that is no longer valid.
        if self.unit.is_leader():
            provider = self._provider_from_relation(relation)
            provider.wipe_ingress_data(relation)

    def _relation_config_file(self, relation: Relation):
        # Using both the relation id and the app name in the file to facilitate
        # the debugging experience somewhat when snooping into the container at runtime:
        # Apps not in the same model as Traefik (i.e., if `relation` is a CRM) will have
        # some `remote_...` as app name. Relation name and id are handy when one is
        # troubleshooting via `juju run 'relation_ids'...` and the like.`
        return f"juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"

    @property
    def _traefik_service_running(self):
        if not self.container.can_connect():
            return False
        return bool(self.container.get_services(_TRAEFIK_SERVICE_NAME))

    def _restart_traefik(self):
        updated_pebble_layer = {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                _TRAEFIK_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Traefik",
                    "command": "/usr/bin/traefik",
                    "startup": "enabled",
                },
            },
        }

        current_pebble_layer = self.container.get_plan().to_dict()

        if _TRAEFIK_SERVICE_NAME not in current_pebble_layer.get("services", {}):
            self.unit.status = MaintenanceStatus(f"creating the '{_TRAEFIK_SERVICE_NAME}' service")
            self.container.add_layer(_TRAEFIK_LAYER_NAME, updated_pebble_layer, combine=True)

        self.container.replan()

    def _provider_from_relation(self, relation: Relation):
        """Returns the correct IngressProvider based on a relation."""
        if _get_relation_type(relation) == _IngressRelationType.per_app:
            return self.ingress_per_app
        elif _get_relation_type(relation) == _IngressRelationType.per_unit:
            return self.ingress_per_unit
        else:
            return self.traefik_route

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
    if relation.name == "ingress":
        return _IngressRelationType.per_app
    elif relation.name == "ingress-per-unit":
        return _IngressRelationType.per_unit
    else:  # traefik-route
        return _IngressRelationType.routed


if __name__ == "__main__":
    main(TraefikIngressCharm)
