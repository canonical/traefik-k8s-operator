#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Traefik."""

import enum
import ipaddress
import json
import logging
import re
import socket
import typing
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import yaml
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
    ServicePort,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tls_certificates_interface.v2.tls_certificates import (
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    CertificateInvalidatedEvent,
    TLSCertificatesRequiresV1,
    generate_csr,
    generate_private_key,
)
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
from lightkube.core.client import Client
from lightkube.resources.core_v1 import Service
from ops.charm import (
    ActionEvent,
    CharmBase,
    ConfigChangedEvent,
    PebbleReadyEvent,
    RelationBrokenEvent,
    RelationEvent,
    RelationJoinedEvent,
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
_DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"
_STATIC_CONFIG_DIR = "/etc/traefik"
_STATIC_CONFIG_PATH = _STATIC_CONFIG_DIR + "/traefik.yaml"
_DYNAMIC_CERTS_PATH = _DYNAMIC_CONFIG_DIR + "/certificates.yaml"
_CERTIFICATE_PATH = _DYNAMIC_CONFIG_DIR + "/certificate.cert"
_CERTIFICATE_KEY_PATH = _DYNAMIC_CONFIG_DIR + "/certificate.key"
BIN_PATH = "/usr/bin/traefik"


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
    _tls_port = 443
    _diagnostics_port = 8082  # Prometheus metrics, healthcheck/ping

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(  # pyright: reportGeneralTypeIssues=false
            current_external_host=None,
            current_routing_mode=None,
            tcp_entrypoints=None,
            private_key=None,
            csr=None,
            certificate=None,
            ca=None,
            chain=None,
        )

        self.container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        # FIXME: Do not move these lower. They must exist before `_tcp_ports` is called. The
        # better long-term solution is to allow dynamic modification of the object, and to try
        # to build the list first from tcp entrypoints on the filesystem, and append later.
        #
        # alternatively, a `Callable` could be passed into the KubernetesServicePatch, but the
        # service spec MUST have TCP/UCP ports listed if the loadbalancer is to send requests
        # to it.
        #
        # TODO
        # FIXME
        # stored.tcp_entrypoints would be used for this list instead, but it's never accessed.
        # intentional or can it be used so we don't need to worry about ordering?
        self.ingress_per_app = IngressPerAppProvider(charm=self)
        self.ingress_per_unit = IngressPerUnitProvider(charm=self)
        self.traefik_route = TraefikRouteProvider(charm=self, external_host=self.external_host)

        web = ServicePort(self._port, name=f"{self.app.name}")
        websecure = ServicePort(self._tls_port, name=f"{self.app.name}-tls")
        tcp_ports = [ServicePort(int(port), name=name) for name, port in self._tcp_ports.items()]
        self.service_patch = KubernetesServicePatch(
            charm=self,
            service_type="LoadBalancer",
            ports=[web, websecure] + tcp_ports,
            refresh_event=[
                self.ingress_per_app.on.data_provided,
                self.ingress_per_app.on.data_removed,
                self.ingress_per_unit.on.data_provided,
                self.ingress_per_unit.on.data_removed,
                self.traefik_route.on.ready,
                self.traefik_route.on.data_removed,
            ],
        )

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [{"targets": [f"*:{self._diagnostics_port}"]}],
                },
            ],
        )

        self.certificates = TLSCertificatesRequiresV1(self, "certificates")
        # TODO update init params once auto-renew is implemented
        # https://github.com/canonical/tls-certificates-interface/issues/24
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(
            self.on.certificates_relation_joined, self._on_certificates_relation_joined
        )
        self.framework.observe(
            self.certificates.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self.certificates.on.certificate_expiring, self._on_certificate_expiring
        )
        self.framework.observe(
            self.certificates.on.certificate_invalidated, self._on_certificate_invalidated
        )
        self.framework.observe(
            self.certificates.on.all_certificates_invalidated,
            self._on_all_certificates_invalidated,
        )

        observe = self.framework.observe
        observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)
        observe(self.on.start, self._on_start)
        observe(self.on.stop, self._on_stop)
        observe(self.on.update_status, self._on_update_status)
        observe(self.on.config_changed, self._on_config_changed)

        ipa_events = self.ingress_per_app.on
        observe(ipa_events.data_provided, self._handle_ingress_data_provided)
        observe(ipa_events.data_removed, self._handle_ingress_data_removed)

        ipu_events = self.ingress_per_unit.on
        observe(ipu_events.data_provided, self._handle_ingress_data_provided)
        observe(ipu_events.data_removed, self._handle_ingress_data_removed)

        route_events = self.traefik_route.on
        observe(route_events.ready, self._handle_traefik_route_ready)
        observe(route_events.data_removed, self._handle_ingress_data_removed)

        # Action handlers
        observe(self.on.show_proxied_endpoints_action, self._on_show_proxied_endpoints)

    def _on_install(self, event) -> None:
        # Generate key without a passphrase as traefik does not support it
        # https://github.com/traefik/traefik/pull/6518
        private_key = generate_private_key()
        self._stored.private_key = private_key.decode()

    def _on_certificates_relation_joined(self, event: RelationJoinedEvent) -> None:
        # Assuming there can be only one (metadata also has `limit: 1` on the relation).
        self.refresh_csr()

    def refresh_csr(self):
        """Refresh the CSR, overwriting any existing."""
        if not list(self.model.relations["certificates"]):
            # Relation "certificates" does not exist
            return

        private_key = self._stored.private_key
        if not (subject := self.cert_subject):
            logger.debug(
                "Cannot generate CSR: subject is invalid "
                "(hostname is '%s', which is probably invalid)",
                self.external_host,
            )
            # TODO set BlockedStatus here when compound_status is introduced
            #  https://github.com/canonical/operator/issues/665
            return

        csr = generate_csr(
            private_key=private_key.encode("utf-8"),
            subject=subject,
        )
        self._stored.csr = csr.decode()
        self.certificates.request_certificate_creation(certificate_signing_request=csr)
        logger.debug("CSR sent")

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent):
        # Assuming there can be only one cert (metadata also has `limit: 1` on the relation).
        # Assuming the `on-expiring` handle successfully takes care of renewal.
        # Keeping the cert on traefik's filesystem even if the cert does end up being invalidated.
        # Nothing to do here.
        pass

    def _on_all_certificates_invalidated(self, event: RelationBrokenEvent) -> None:
        if self.container.can_connect():
            self._stored.certificate = None
            self._stored.private_key = None
            self._stored.csr = None
            self.container.remove_path(_CERTIFICATE_PATH, recursive=True)
            self.container.remove_path(_CERTIFICATE_KEY_PATH, recursive=True)

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        self._stored.certificate = event.certificate
        self._stored.ca = event.ca
        self._stored.chain = event.chain
        # TODO: Store files in container and modify config file
        self.container.push(_CERTIFICATE_PATH, self._stored.certificate, make_dirs=True)
        self.container.push(_CERTIFICATE_KEY_PATH, self._stored.private_key, make_dirs=True)
        self._push_config()
        self._process_status_and_configurations()

    def _on_certificate_expiring(self, event: CertificateExpiringEvent) -> None:
        old_csr = self._stored.csr
        private_key = self._stored.private_key

        if not (subject := self.cert_subject):
            # TODO: use compound status
            logging.error(
                "Cannot generate CSR: invalid cert subject '%s' (is external hostname defined?)",
                subject,
            )
            event.defer()
            return

        new_csr = generate_csr(
            private_key=private_key.encode(),
            subject=subject,
        )
        self.certificates.request_certificate_renewal(
            old_certificate_signing_request=old_csr,
            new_certificate_signing_request=new_csr,
        )
        self._stored.csr = new_csr.decode()

    def _on_show_proxied_endpoints(self, event: ActionEvent):
        if not self.ready:
            return

        try:
            result = {}
            result.update(self.ingress_per_unit.proxied_endpoints)
            result.update(self.ingress_per_app.proxied_endpoints)

            event.set_results({"proxied-endpoints": json.dumps(result)})
        except Exception as e:
            logger.exception("Action 'show-proxied-endpoints' failed")
            event.fail(str(e))

    def _tcp_entrypoints(self):
        # for each unit related via IPU in tcp mode, we need to generate the tcp
        # entry points for traefik's static config.
        entrypoints = {}
        ipu = self.ingress_per_unit
        for relation in ipu.relations:
            for unit in relation.units:
                if unit._is_our_unit:
                    # is this necessary?
                    continue
                if not ipu.is_unit_ready(relation, unit):
                    logger.error(f"{relation} not ready: skipping...")
                    continue

                data = ipu.get_data(relation, unit)
                if data.get("mode", "http") == "tcp":
                    entrypoint_name = self._get_prefix(data)
                    entrypoints[entrypoint_name] = {"address": f":{data['port']}"}

        return entrypoints

    @property
    def _tcp_ports(self) -> Dict[str, str]:
        # For each unit related via IPU in tcp mode, we need to generate the tcp
        # ports for the servicepatch, so they can be bound on metallb.
        entrypoints = self._tcp_entrypoints()
        return {
            # Everything past a colon is assumed to be the port
            name: re.sub(r"^.*?:(.*)", r"\1", entry["address"])
            for name, entry in entrypoints.items()
        }

    def _clear_dynamic_configs(self):
        try:
            for file in self.container.list_files(path=_DYNAMIC_CONFIG_DIR, pattern="juju_*.yaml"):
                self.container.remove_path(file.path)
                logger.debug("Deleted orphaned ingress configuration file: %s", file.path)
        except (FileNotFoundError, APIError):
            pass

    def _push_config(self):
        # Ensure the required basic configurations and folders exist
        # TODO Use the Traefik user and group?

        # TODO Disable static config with telemetry and check new version

        # We always start the Prometheus endpoint for simplicity
        # TODO: Generate this file in the dynamic configuration folder when the
        #  metrics-endpoint relation is established?

        # we cache the tcp entrypoints, so we can detect changes and decide
        # whether we need a restart
        tcp_entrypoints = self._tcp_entrypoints()
        logger.debug(f"Statically configuring traefik with tcp entrypoints: {tcp_entrypoints}.")

        traefik_config = {
            "log": {
                "level": "DEBUG",
            },
            "entryPoints": {
                "diagnostics": {"address": f":{self._diagnostics_port}"},
                "web": {"address": f":{self._port}"},
                "websecure": {"address": f":{self._tls_port}"},
                **tcp_entrypoints,
            },
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
                    "directory": _DYNAMIC_CONFIG_DIR,
                    "watch": True,
                }
            },
        }
        self.container.push(_STATIC_CONFIG_PATH, yaml.dump(traefik_config), make_dirs=True)
        self.container.push(_DYNAMIC_CERTS_PATH, yaml.dump(self._get_tls_config()), make_dirs=True)

        self.container.make_dir(_DYNAMIC_CONFIG_DIR, make_parents=True)

    def _get_tls_config(self) -> dict:
        """Return dictionary with TLS traefik configuration if it exists."""
        if not self._stored.certificate:
            return {}
        return {
            "tls": {
                "certificates": [
                    {
                        "certFile": _CERTIFICATE_PATH,
                        "keyFile": _CERTIFICATE_KEY_PATH,
                    }
                ],
            }
        }

    def _on_traefik_pebble_ready(self, _: PebbleReadyEvent):
        # If the Traefik container comes up, e.g., after a pod churn, we
        # ignore the unit status and start fresh.
        self._clear_all_configs_and_restart_traefik()
        # push the (fresh new) configs.
        self._process_status_and_configurations()
        self._set_workload_version()

    def _clear_all_configs_and_restart_traefik(self):
        # Since pebble ready will also occur after a pod churn, but we store the
        # configuration files on a storage volume that survives the pod churn, before
        # we start traefik we clean up all Juju-generated config files to avoid spurious
        # routes.
        self._clear_dynamic_configs()
        # we push the static config
        self._push_config()
        # now we restart traefik
        self._restart_traefik()

    def _on_start(self, _: StartEvent):
        self._process_status_and_configurations()

    def _on_stop(self, _):
        # If obtaining the workload version after an upgrade fails, we do not want juju to display
        # the workload version from before the upgrade.
        self.unit.set_workload_version("")

    def _on_update_status(self, _: UpdateStatusEvent):
        self._process_status_and_configurations()
        self._set_workload_version()

    def _on_config_changed(self, _: ConfigChangedEvent):
        # If the external hostname is changed since we last processed it, we need to
        # reconsider all data sent over the relations and all configs
        new_external_host = self.external_host
        new_routing_mode = self.config["routing_mode"]

        if self._stored.current_external_host != new_external_host or not self._stored.csr:
            self.refresh_csr()

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

        hostname = self.external_host

        if not hostname:
            self.unit.status = MaintenanceStatus("resetting ingress relations")
            self._wipe_ingress_for_all_relations()
            self.unit.status = WaitingStatus("gateway address unavailable")
            return

        if hostname != urlparse(f"scheme://{hostname}").hostname:
            self.unit.status = MaintenanceStatus("resetting ingress relations")
            self._wipe_ingress_for_all_relations()
            self.unit.status = BlockedStatus(f"invalid hostname: {hostname}; see logs.")

            logger.error(
                "'%s' is not a valid hostname value; "
                "hostname must not include port or any other netloc components",
                hostname,
            )
            return

        if not self._traefik_service_running:
            self.unit.status = WaitingStatus(f"waiting for service: '{_TRAEFIK_SERVICE_NAME}'")
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")

        # if there are changes in the tcp configs, we'll need to restart
        # traefik as the tcp entrypoints are consumed as static configuration
        # and those can only be passed on init.
        if self._tcp_entrypoints_changed():
            logger.debug("change in tcp entrypoints detected. Rebooting traefik.")
            # fixme: this is kind of brutal;
            #  will kill in-flight requests and disrupt traffic.
            self._clear_all_configs_and_restart_traefik()
            # we do this BEFORE processing the relations.

        for ingress_relation in (
            self.ingress_per_app.relations
            + self.ingress_per_unit.relations
            + self.traefik_route.relations
        ):
            self._process_ingress_relation(ingress_relation)

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()
        else:
            logger.debug(
                "unit in {!r}: {}".format(self.unit.status.name, self.unit.status.message)
            )
            self.unit.status = BlockedStatus("setup of some ingress relation failed")
            logger.error("The setup of some ingress relation failed, see previous logs")

    def _pull_tcp_entrypoints_from_container(self):
        try:
            static_config_raw = self.container.pull(_STATIC_CONFIG_PATH).read()
        except PathError as e:
            logger.error(f"Could not fetch static config from container; {e}")
            return {}

        static_config = yaml.safe_load(static_config_raw)
        eps = static_config["entryPoints"]
        return {k: v for k, v in eps.items() if k not in {"diagnostics", "web", "websecure"}}

    def _tcp_entrypoints_changed(self):
        current = self._tcp_entrypoints()
        traefik_entrypoints = self._pull_tcp_entrypoints_from_container()
        return current != traefik_entrypoints

    @property
    def ready(self) -> bool:
        """Check whether we have an external host set, and traefik is running."""
        if not self.external_host:
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
        self._wipe_ingress_for_relation(
            event.relation, wipe_rel_data=not isinstance(event, RelationBrokenEvent)
        )

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
        if not self.ready:
            return

        provider = self._provider_from_relation(relation)
        if not provider.is_ready(relation):
            logger.debug(f"Provider {provider} not ready; resetting ingress configurations.")
            self._wipe_ingress_for_relation(relation)
            return

        rel = f"{relation.name}:{relation.id}"
        self.unit.status = MaintenanceStatus(f"updating ingress configuration for '{rel}'")
        logger.debug("Updating ingress for relation '%s'", rel)

        if provider is self.traefik_route:
            self._provide_routed_ingress(relation)
            return

        self._provide_ingress(relation, provider)

    def _provide_routed_ingress(self, relation: Relation):
        """Provide ingress to a unit related through TraefikRoute."""
        config = self.traefik_route.get_config(relation)
        config = yaml.safe_load(config)

        if "http" in config.keys():
            route_config = config["http"].get("routers", {})
            router_name = next(iter(route_config.keys()))
            route_rule = route_config.get(router_name, {}).get("rule", "")
            service_name = route_config.get(router_name, {}).get("service", "")

            if not all([router_name, route_rule, service_name]):
                logger.debug("Not enough information to generate a TLS config!")
            else:
                config["http"]["routers"].update(
                    self._generate_tls_block(router_name, route_rule, service_name)
                )

        self._push_configurations(relation, config)

    def _provide_ingress(
        self, relation: Relation, provider: Union[IngressPerAppProvider, IngressPerAppProvider]
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

    def _get_configs_per_unit(self, relation: Relation) -> dict:
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
                logger.error(
                    f"invalid data shared through {relation} by " f"{unit}... Error: {e}."
                )
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
            config_filename = f"{_DYNAMIC_CONFIG_DIR}/{self._relation_config_file(relation)}"
            self.container.push(config_filename, yaml_config, make_dirs=True)
            logger.debug("Updated ingress configuration file: %s", config_filename)
        else:
            self._wipe_ingress_for_relation(relation)

    @staticmethod
    def _get_prefix(data: Union["RequirerData_IPU", "RequirerData_IPA"]):
        name = data["name"].replace("/", "-")
        return f"{data['model']}-{name}"

    def _generate_middleware_config(
        self, data: Union["RequirerData_IPA", "RequirerData_IPU"], prefix: str
    ) -> dict:
        """Generate a stripPrefix middleware for path based routing."""
        if self._routing_mode is _RoutingMode.path and data.get("strip-prefix", False):
            return {
                f"juju-sidecar-noprefix-{prefix}": {
                    "stripPrefix": {"prefixes": [f"/{prefix}"], "forceSlash": False}
                }
            }

        return {}

    def _generate_per_unit_config(self, data: "RequirerData_IPU") -> Tuple[dict, str]:
        """Generate a config dict for a given unit for IngressPerUnit."""
        prefix = self._get_prefix(data)
        host = self.external_host
        if data["mode"] == "tcp":
            # TODO: is there a reason why SNI-based routing (from TLS certs) is per-unit only?
            # This is not a technical limitation in any way. It's meaningful/useful for
            # authenticating to individual TLS-based servers where it may be desirable to reach
            # one or more servers in a cluster (let's say Kafka), but limiting it to per-unit only
            # actively impedes the architectural design of any distributed/ring-buffered TLS-based
            # scale-out services which may only have frontends dedicated, but which do not "speak"
            # HTTP(S). Such as any of the "cloud-native" SQL implementations (TiDB, Cockroach, etc)
            port = data["port"]
            unit_url = f"{host}:{port}"
            config = {
                "tcp": {
                    "routers": {
                        f"juju-{prefix}-tcp-router": {
                            "rule": "HostSNI(`*`)",
                            "service": f"juju-{prefix}-tcp-service",
                            # or whatever entrypoint I defined in static config
                            "entryPoints": [prefix],
                        },
                    },
                    "services": {
                        f"juju-{prefix}-tcp-service": {
                            "loadBalancer": {"servers": [{"address": f"{data['host']}:{port}"}]}
                        }
                    },
                }
            }
            return config, unit_url

        else:
            lb_servers = [{"url": f"http://{data['host']}:{data['port']}"}]
            return self._generate_config_block(prefix, lb_servers, data)

    def _generate_config_block(
        self, prefix: str, lb_servers: List[Dict[str, str]], data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], str]:
        """Generate a configuration segment.

        Per-unit and per-app configuration blocks are mostly similar, with the principal
        difference being the list of servers to load balance across (where IPU is one server per
        unit and IPA may be more than one).
        """
        host = self.external_host

        if self._routing_mode is _RoutingMode.path:
            route_rule = f"PathPrefix(`/{prefix}`)"
            url = f"http://{host}:{self._port}/{prefix}"
        else:  # _RoutingMode.subdomain
            route_rule = f"Host(`{prefix}.{host}`)"
            url = f"http://{prefix}.{host}:{self._port}/"

        traefik_router_name = f"juju-{prefix}-router"
        traefik_service_name = f"juju-{prefix}-service"

        router_cfg = {
            traefik_router_name: {
                "rule": route_rule,
                "service": traefik_service_name,
                "entryPoints": ["web"],
            },
        }
        router_cfg.update(
            self._generate_tls_block(traefik_router_name, route_rule, traefik_service_name)
        )

        config = {
            "http": {
                "routers": router_cfg,
                "services": {traefik_service_name: {"loadBalancer": {"servers": lb_servers}}},
            }
        }

        middlewares = self._generate_middleware_config(data, prefix)

        if middlewares:
            config["http"]["middlewares"] = middlewares
            router_cfg[traefik_router_name]["middlewares"] = list(middlewares.keys())

        return config, url

    def _generate_tls_block(
        self,
        router_name: str,
        route_rule: str,
        service_name: str,
    ) -> Dict[str, Any]:
        """Generate a TLS configuration segment."""
        return {
            f"{router_name}-tls": {
                "rule": route_rule,
                "service": service_name,
                "entryPoints": ["websecure"],
                "tls": {
                    "domains": [
                        {
                            "main": self.external_host,
                            "sans": [f"*.{self.external_host}"],
                        },
                    ],
                },
            }
        }

    def _generate_per_app_config(self, data: "RequirerData_IPA") -> Tuple[dict, str]:
        prefix = self._get_prefix(data)

        lb_servers = [{"url": f"http://{data['host']}:{data['port']}"}]
        return self._generate_config_block(prefix, lb_servers, data)

    def _wipe_ingress_for_all_relations(self):
        for relation in self.model.relations["ingress"] + self.model.relations["ingress-per-unit"]:
            self._wipe_ingress_for_relation(relation)

    def _wipe_ingress_for_relation(self, relation: Relation, *, wipe_rel_data=True):
        logger.debug(f"Wiping the ingress setup for the '{relation.name}:{relation.id}' relation")

        # Delete configuration files for the relation. In case of Traefik pod
        # churns, and depending on the event ordering, we might be executing this
        # logic before pebble in the traefik container is up and running. If that
        # is the case, nevermind, we will wipe the dangling config files anyhow
        # during _on_traefik_pebble_ready .
        if self.container.can_connect():
            try:
                config_path = f"{_DYNAMIC_CONFIG_DIR}/{self._relation_config_file(relation)}"
                self.container.remove_path(config_path, recursive=True)
                logger.debug(f"Deleted orphaned {config_path} ingress configuration file")
            except (PathError, FileNotFoundError):
                logger.debug("Configurations for '%s:%s' not found", relation.name, relation.id)

        # Wipe URLs sent to the requesting apps and units, as they are based on a gateway
        # address that is no longer valid.
        # Skip this for traefik-route because it doesn't have a `wipe_ingress_data` method.
        provider = self._provider_from_relation(relation)
        if wipe_rel_data and self.unit.is_leader() and provider != self.traefik_route:
            provider.wipe_ingress_data(relation)

    def _relation_config_file(self, relation: Relation):
        # Using both the relation id and the app name in the file to facilitate
        # the debugging experience somewhat when snooping into the container at runtime:
        # Apps not in the same model as Traefik (i.e., if `relation` is a CRM) will have
        # some `remote_...` as app name. Relation name and id are handy when one is
        # troubleshooting via `juju run 'relation_ids'...` and the like.`
        assert relation.app, "no app in relation (shouldn't happen)"  # for type checker
        return f"juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"

    @property
    def _traefik_service_running(self):
        if not self.container.can_connect():
            return False
        return bool(self.container.get_services(_TRAEFIK_SERVICE_NAME))

    def _restart_traefik(self):
        layer = {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                _TRAEFIK_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Traefik",
                    "command": BIN_PATH,
                    "startup": "enabled",
                },
            },
        }

        current_services = self.container.get_plan().to_dict().get("services", {})

        if _TRAEFIK_SERVICE_NAME not in current_services:
            self.unit.status = MaintenanceStatus(f"creating the {_TRAEFIK_SERVICE_NAME!r} service")
            self.container.add_layer(_TRAEFIK_LAYER_NAME, layer, combine=True)
            logger.debug(f"replanning {_TRAEFIK_SERVICE_NAME!r} after a service update")
            self.container.replan()
        else:
            logger.debug(f"restarting {_TRAEFIK_SERVICE_NAME!r}")
            self.container.restart(_TRAEFIK_SERVICE_NAME)

    def _provider_from_relation(self, relation: Relation):
        """Returns the correct IngressProvider based on a relation."""
        relation_type = _get_relation_type(relation)
        if relation_type is _IngressRelationType.per_app:
            return self.ingress_per_app
        elif relation_type is _IngressRelationType.per_unit:
            return self.ingress_per_unit
        elif relation_type is _IngressRelationType.routed:
            return self.traefik_route
        else:
            raise RuntimeError("Invalid relation type (shouldn't happen)")

    @property
    def external_host(self):
        """Determine the external address for the ingress gateway.

        It will prefer the `external-hostname` config if that is set, otherwise
        it will look up the load balancer address for the ingress gateway.

        If the gateway isn't available or doesn't have a load balancer address yet,
        returns None.
        """
        if external_hostname := self.model.config.get("external_hostname"):
            return external_hostname

        return _get_loadbalancer_status(namespace=self.model.name, service_name=self.app.name)

    @property
    def _routing_mode(self) -> _RoutingMode:
        """Return the current routing mode for the ingress.

        The two modes are 'subdomain' and 'path', where 'path' is the default.
        """
        return _RoutingMode(self.config["routing_mode"])

    @property
    def version(self) -> Optional[str]:
        """Return the workload version."""
        if not self.container.can_connect():
            return None

        version_output, _ = self.container.exec([BIN_PATH, "version"]).wait_output()
        # Output looks like this:
        # Version:      2.9.6
        # Codename:     banon
        # Go version:   go1.18.9
        # Built:        2022-12-07_04:28:37PM
        # OS/Arch:      linux/amd64

        if result := re.search(r"Version:\s*(.+)", version_output):
            return result.group(1)
        return None

    def _set_workload_version(self):
        if version := self.version:
            self.unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get Traefik version."
            )

    @property
    def cert_subject(self) -> Optional[str]:
        """Provide certificate subject."""
        host_or_ip = self.external_host

        def is_hostname(st: Optional[str]) -> bool:
            try:
                ipaddress.ip_address(st)
                # No exception raised so this is an IP address.
                return False
            except ValueError:
                # This is not an IP address so assume it's a hostname.
                # Note: a ValueError will be raised if `st` is None, which is ok here.
                return st is not None

        if is_hostname(host_or_ip):
            return host_or_ip

        # This is an IP address. Try to look up the hostname.
        try:
            lookup = socket.gethostbyaddr(host_or_ip)[0]
            return lookup if is_hostname(lookup) else None
        except (OSError, TypeError):
            # We do not want to return `socket.getfqdn()` because the user's browser would
            # immediately complain about an invalid cert. If we can't resolve it via any method,
            # return None
            return None


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
    elif relation.name == "traefik-route":
        return _IngressRelationType.routed
    raise RuntimeError("Invalid relation name (shouldn't happen)")


if __name__ == "__main__":
    main(TraefikIngressCharm, use_juju_for_storage=True)
