#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Traefik."""
import contextlib
import enum
import functools
import ipaddress
import json
import logging
import re
import socket
import typing
from string import Template
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import yaml
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateAvailableEvent as CertificateTransferAvailableEvent,
)
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateRemovedEvent as CertificateTransferRemovedEvent,
)
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateTransferRequires,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.observability_libs.v0.cert_handler import CertHandler
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
    ServicePort,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_k8s.v0.charm_tracing import trace_charm
from charms.tempo_k8s.v0.tracing import TracingEndpointRequirer
from charms.tls_certificates_interface.v2.tls_certificates import (
    CertificateInvalidatedEvent,
)
from charms.traefik_k8s.v1.ingress import IngressPerAppProvider as IPAv1
from charms.traefik_k8s.v1.ingress import RequirerData as IPADatav1
from charms.traefik_k8s.v1.ingress_per_unit import DataValidationError, IngressPerUnitProvider
from charms.traefik_k8s.v1.ingress_per_unit import RequirerData as RequirerData_IPU
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider as IPAv2
from charms.traefik_k8s.v2.ingress import IngressRequirerData as IPADatav2
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
from ops.pebble import APIError, LayerDict, PathError

logger = logging.getLogger(__name__)

_TRAEFIK_CONTAINER_NAME = _TRAEFIK_LAYER_NAME = _TRAEFIK_SERVICE_NAME = "traefik"
# We watch the parent folder of where we store the configuration files,
# as that is usually safer for Traefik
_DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"
_STATIC_CONFIG_DIR = "/etc/traefik"
_STATIC_CONFIG_PATH = f"{_STATIC_CONFIG_DIR}/traefik.yaml"
_DYNAMIC_CERTS_PATH = f"{_DYNAMIC_CONFIG_DIR}/certificates.yaml"
_DYNAMIC_TRACING_PATH = f"{_DYNAMIC_CONFIG_DIR}/tracing.yaml"
_SERVER_CERT_PATH = f"{_DYNAMIC_CONFIG_DIR}/server.cert"
_SERVER_KEY_PATH = f"{_DYNAMIC_CONFIG_DIR}/server.key"
_CA_CERTS_PATH = "/usr/local/share/ca-certificates"
_CA_CERT_PATH = f"{_CA_CERTS_PATH}/traefik-ca.crt"
_RECV_CA_TEMPLATE = Template(f"{_CA_CERTS_PATH}/receive-ca-cert-$rel_id-ca.crt")

BIN_PATH = "/usr/bin/traefik"


def is_hostname(value: Optional[str]) -> bool:
    """Return False if input value is an IP address; True otherwise."""
    if value is None:
        return False

    try:
        ipaddress.ip_address(value)
        # No exception raised so this is an IP address.
        return False
    except ValueError:
        # This is not an IP address so assume it's a hostname.
        return bool(value)


class _RoutingMode(enum.Enum):
    path = "path"
    subdomain = "subdomain"


class _IngressRelationType(enum.Enum):
    per_app = "per_app"
    per_unit = "per_unit"
    routed = "routed"


@trace_charm(
    tracing_endpoint="charm_tracing_endpoint",
    server_cert="server_cert",
    extra_types=(
        IPAv2,
        IPAv1,
        IngressPerUnitProvider,
        TraefikRouteProvider,
        KubernetesServicePatch,
    ),
)
class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()
    _port = 80
    _tls_port = 443
    _log_path = "/var/log/traefik.log"
    _diagnostics_port = 8082  # Prometheus metrics, healthcheck/ping

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(
            current_external_host=None,
            current_routing_mode=None,
        )

        self.container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)
        sans = self.server_cert_sans_dns
        self.cert = CertHandler(
            self,
            key="trfk-server-cert",
            peer_relation_name="peers",
            # Route53 complains if CN is not a hostname
            cert_subject=sans[0] if len(sans) else None,
            extra_sans_dns=sans,
        )

        self.recv_ca_cert = CertificateTransferRequires(self, "receive-ca-cert")

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
        self.ingress_per_appv1 = ipa_v1 = IPAv1(charm=self)
        self.ingress_per_appv2 = ipa_v2 = IPAv2(charm=self)

        self.ingress_per_unit = IngressPerUnitProvider(charm=self)
        self.traefik_route = TraefikRouteProvider(
            charm=self, external_host=self.external_host, scheme=self._scheme  # type: ignore
        )

        web = ServicePort(self._port, name=f"{self.app.name}")
        websecure = ServicePort(self._tls_port, name=f"{self.app.name}-tls")
        tcp_ports = [ServicePort(int(port), name=name) for name, port in self._tcp_ports.items()]
        self.service_patch = KubernetesServicePatch(
            charm=self,
            service_type="LoadBalancer",
            ports=[web, websecure] + tcp_ports,
            refresh_event=[
                ipa_v1.on.data_provided,  # type: ignore
                ipa_v2.on.data_provided,  # type: ignore
                ipa_v1.on.data_removed,  # type: ignore
                ipa_v2.on.data_removed,  # type: ignore
                self.ingress_per_unit.on.data_provided,  # type: ignore
                self.ingress_per_unit.on.data_removed,  # type: ignore
                self.traefik_route.on.ready,  # type: ignore
                self.traefik_route.on.data_removed,  # type: ignore
                self.on.traefik_pebble_ready,  # type: ignore
            ],
        )

        # Observability integrations
        # tracing integration
        self._tracing = TracingEndpointRequirer(self)

        # Provide grafana dashboards over a relation interface
        # dashboard to use: https://grafana.com/grafana/dashboards/4475-traefik/
        # TODO wishlist: I would like for the p60, p70, p80, p90, p99, min, max, and avg for
        #  http_request_duration to be plotted as a graph. You should have access to a
        #  http_request_duration_bucket, which should make this fairly straight
        #  forward to do using histogram_quantiles
        self._grafana_dashboards = GrafanaDashboardProvider(
            self, relation_name="grafana-dashboard"
        )
        # Enable log forwarding for Loki and other charms that implement loki_push_api
        self._logging = LogProxyConsumer(self, relation_name="logging", log_files=[self._log_path])
        self.metrics_endpoint = MetricsEndpointProvider(
            charm=self,
            jobs=self._scrape_jobs,
            refresh_event=[
                self.on.traefik_pebble_ready,  # type: ignore
                self.on.update_status,  # type: ignore
            ],
        )
        observe = self.framework.observe

        # TODO update init params once auto-renew is implemented
        # https://github.com/canonical/tls-certificates-interface/issues/24
        observe(
            self._tracing.on.endpoint_changed,  # type: ignore
            self._on_tracing_endpoint_changed,
        )
        observe(
            self._tracing.on.endpoint_removed,  # type: ignore
            self._on_tracing_endpoint_removed,
        )

        observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)  # type: ignore
        observe(self.on.start, self._on_start)
        observe(self.on.stop, self._on_stop)
        observe(self.on.update_status, self._on_update_status)
        observe(self.on.config_changed, self._on_config_changed)
        observe(
            self.cert.on.cert_changed,  # pyright: ignore
            self._on_cert_changed,
        )
        observe(
            self.recv_ca_cert.on.certificate_available,  # pyright: ignore
            self._on_recv_ca_cert_available,
        )
        observe(
            # Need to observe a managed relation event because a custom wrapper is not available
            # https://github.com/canonical/mutual-tls-interface/issues/5
            self.recv_ca_cert.on.certificate_removed,  # pyright: ignore
            self._on_recv_ca_cert_removed,
        )

        # observe data_provided and data_removed events for all types of ingress we offer:
        for ingress in (self.ingress_per_unit, self.ingress_per_appv1, self.ingress_per_appv2):
            observe(ingress.on.data_provided, self._handle_ingress_data_provided)  # type: ignore
            observe(ingress.on.data_removed, self._handle_ingress_data_removed)  # type: ignore

        route_events = self.traefik_route.on
        observe(route_events.ready, self._handle_traefik_route_ready)  # type: ignore
        observe(route_events.data_removed, self._handle_ingress_data_removed)  # type: ignore

        # Action handlers
        observe(self.on.show_proxied_endpoints_action, self._on_show_proxied_endpoints)  # type: ignore

    def _on_recv_ca_cert_available(self, event: CertificateTransferAvailableEvent):
        # Assuming only one cert per relation (this is in line with the original lib design).
        if not self.container.can_connect():
            return
        self._update_received_ca_certs(event)

    def _update_received_ca_certs(self, event: Optional[CertificateTransferAvailableEvent] = None):
        """Push the cert attached to the event, if it is given; otherwise push all certs.

        This function is needed because relation events are not emitted on upgrade, and because we
        do not have (nor do we want) persistent storage for certs.
        Calling this function from upgrade-charm might be too early though. Pebble-ready is
        preferred.
        """
        if event:
            self.container.push(
                _RECV_CA_TEMPLATE.substitute(rel_id=event.relation_id), event.ca, make_dirs=True
            )
        else:
            for relation in self.model.relations.get(self.recv_ca_cert.relationship_name, []):
                # For some reason, relation.units includes our unit and app. Need to exclude them.
                for unit in set(relation.units).difference([self.app, self.unit]):
                    # Note: this nested loop handles the case of multi-unit CA, each unit providing
                    # a different ca cert, but that is not currently supported by the lib itself.
                    cert_path = _RECV_CA_TEMPLATE.substitute(rel_id=relation.id)
                    if cert := relation.data[unit].get("ca"):
                        self.container.push(cert_path, cert, make_dirs=True)

        self._update_system_certs()

    def _on_recv_ca_cert_removed(self, event: CertificateTransferRemovedEvent):
        # Assuming only one cert per relation (this is in line with the original lib design).
        target = _RECV_CA_TEMPLATE.substitute(rel_id=event.relation_id)
        self.container.remove_path(target, recursive=True)
        self._update_system_certs()

    @property
    def charm_tracing_endpoint(self) -> Optional[str]:
        """Otlp grpc endpoint for charm instrumentation."""
        return self._tracing.otlp_grpc_endpoint()

    @property
    def server_cert(self) -> Optional[str]:
        """Server certificate for tls tracing."""
        return self.cert.cert

    def _on_certificate_invalidated(self, event: CertificateInvalidatedEvent):
        # Assuming there can be only one cert (metadata also has `limit: 1` on the relation).
        # Assuming the `on-expiring` handle successfully takes care of renewal.
        # Keeping the cert on traefik's filesystem even if the cert does end up being invalidated.
        # Nothing to do here.
        pass

    def _on_all_certificates_invalidated(self, event: RelationBrokenEvent) -> None:
        if not self.container.can_connect():
            event.defer()
            return

        self.container.remove_path(_SERVER_CERT_PATH, recursive=True)
        self.container.remove_path(_SERVER_KEY_PATH, recursive=True)

    def _is_tls_enabled(self) -> bool:
        """Return True if TLS is enabled."""
        return self.cert.enabled

    def _is_tracing_enabled(self) -> bool:
        """Return True if tracing is enabled."""
        if not self._tracing.is_ready():
            return False
        return True

    def _on_tracing_endpoint_removed(self, event) -> None:
        if not self.container.can_connect():
            # this probably means we're being torn down, so we don't really need to
            # clear anything up. We could defer, but again, we're being torn down and the unit db
            # will
            return
        self._clear_tracing_config()

    def _on_tracing_endpoint_changed(self, event) -> None:
        # On slow machines, this event may come up before pebble is ready
        if not self.container.can_connect():
            event.defer()
            return

        if not self._tracing.is_ready():
            self._clear_tracing_config()

        self._push_tracing_config()

    def _on_cert_changed(self, event) -> None:
        # On slow machines, this event may come up before pebble is ready
        if not self.container.can_connect():
            event.defer()
            return
        self._update_cert_configs()
        self._push_config()
        self._process_status_and_configurations()

    def _update_cert_configs(self):
        cert_handler = self.cert
        if cert_handler.cert:
            self.container.push(_SERVER_CERT_PATH, cert_handler.cert, make_dirs=True)
        else:
            self.container.remove_path(_SERVER_CERT_PATH, recursive=True)

        if cert_handler.key:
            self.container.push(_SERVER_KEY_PATH, cert_handler.key, make_dirs=True)
        else:
            self.container.remove_path(_SERVER_KEY_PATH, recursive=True)

        if cert_handler.ca:
            self.container.push(_CA_CERT_PATH, cert_handler.ca, make_dirs=True)
        else:
            self.container.remove_path(_CA_CERT_PATH, recursive=True)

        self._update_system_certs()

    def _update_system_certs(self):
        self.container.exec(["update-ca-certificates", "--fresh"]).wait()

        # Must restart traefik after refreshing certs, otherwise:
        # - newly added certs will not be loaded and traefik will keep erroring-out with "signed by
        #   unknown authority".
        # - old certs will be kept active.
        self._restart_traefik()

    def _on_show_proxied_endpoints(self, event: ActionEvent):
        if not self.ready:
            return
        result = {}

        for provider in (self.ingress_per_unit, self.ingress_per_appv1, self.ingress_per_appv2):
            try:
                result.update(provider.proxied_endpoints)
            except Exception as e:
                msg = f"failed to fetch proxied endpoints from provider {provider} with error {e}."
                event.log(msg)

        event.set_results({"proxied-endpoints": json.dumps(result)})

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
                    entrypoint_name = self._get_prefix(data)  # type: ignore
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
        self.container.make_dir(_DYNAMIC_CONFIG_DIR, make_parents=True)

        tls_config = self._get_tls_config()
        if tls_config:
            self.container.push(_DYNAMIC_CERTS_PATH, yaml.dump(tls_config), make_dirs=True)

        self._push_tracing_config()

    def _push_tracing_config(self):
        tracing_config = self._get_tracing_config()
        if tracing_config:
            self.container.push(_DYNAMIC_TRACING_PATH, yaml.dump(tracing_config), make_dirs=True)

    def _get_tls_config(self) -> dict:
        """Return dictionary with TLS traefik configuration if it exists."""
        if not self._is_tls_enabled():
            return {}
        return {
            "tls": {
                "certificates": [
                    {
                        "certFile": _SERVER_CERT_PATH,
                        "keyFile": _SERVER_KEY_PATH,
                    }
                ],
                "stores": {
                    "default": {
                        # When the external hostname is a bare IP, traefik cannot match a domain,
                        # so we must set the default cert for the TLS handshake to succeed.
                        "defaultCertificate": {
                            "certFile": _SERVER_CERT_PATH,
                            "keyFile": _SERVER_KEY_PATH,
                        },
                    },
                },
            }
        }

    def _get_tracing_config(self) -> dict:
        """Return dictionary with opentelemetry configuration if available."""
        # wokeignore:rule=master
        # ref: https://doc.traefik.io/traefik/master/observability/tracing/opentelemetry/
        if not self._is_tracing_enabled():
            logger.info("tracing not enabled: skipping tracing config")
            return {}

        # traefik supports http and grpc
        if addr := self._tracing.otlp_grpc_endpoint():
            grpc = True
        elif addr := self._tracing.otlp_http_endpoint():
            grpc = False
        else:
            logger.error(
                "tracing integration is active but none of the "
                "protocols traefik supports is available."
            )
            return {}

        otlp_cfg: Dict[str, Any] = {"address": addr}
        if self._is_tls_enabled():
            # todo: we have an option to use CA or to use CERT+KEY (available with mtls) authentication.
            #  when we have mTLS, consider this again.
            otlp_cfg["ca"] = _CA_CERT_PATH
        else:
            otlp_cfg["insecure"] = True

        if grpc:
            otlp_cfg["grpc"] = {}
        logger.debug(f"dumping {otlp_cfg} to {_DYNAMIC_TRACING_PATH}")
        return {"tracing": {"openTelemetry": otlp_cfg}}

    def _on_traefik_pebble_ready(self, _: PebbleReadyEvent):
        # If the Traefik container comes up, e.g., after a pod churn, we
        # ignore the unit status and start fresh.
        self._clear_all_configs_and_restart_traefik()
        # push the (fresh new) configs.
        self._process_status_and_configurations()
        self._update_received_ca_certs()
        self._set_workload_version()

    def _clear_all_configs_and_restart_traefik(self):
        # Since pebble ready will also occur after a pod churn, but we store the
        # configuration files on a storage volume that survives the pod churn, before
        # we start traefik we clean up all Juju-generated config files to avoid spurious
        # routes.
        self._clear_tracing_config()
        self._clear_dynamic_configs()
        # we push the static config
        self._push_config()
        # now we restart traefik
        self._restart_traefik()

    def _clear_tracing_config(self):
        """If tracing config is present, clear it up."""
        with contextlib.suppress(PathError):
            self.container.remove_path(_DYNAMIC_TRACING_PATH)

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
        # TODO set BlockedStatus here when compound_status is introduced
        #  https://github.com/canonical/operator/issues/665

        if (
            self._stored.current_external_host != new_external_host  # type: ignore
            or self._stored.current_routing_mode != new_routing_mode  # type: ignore
        ):
            self._stored.current_external_host = new_external_host  # type: ignore
            self._stored.current_routing_mode = new_routing_mode  # type: ignore
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
            self.ingress_per_appv1.relations
            + self.ingress_per_appv2.relations
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

        # Without the following line, _STATIC_CONFIG_PATH is updated with TCP endpoints only on
        # update-status.
        self._process_status_and_configurations()

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus()

    def _handle_ingress_data_removed(self, event: RelationEvent):
        """A unit has removed the data we need to provide ingress."""
        self._wipe_ingress_for_relation(
            event.relation, wipe_rel_data=not isinstance(event, RelationBrokenEvent)
        )

        # FIXME? on relation broken, data is still there so cannot simply call
        #  self._process_status_and_configurations(). For this reason, the static config in
        #  _STATIC_CONFIG_PATH will be updated only on update-status.
        #  https://github.com/canonical/operator/issues/888

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
            logger.warning("not ready: early exit")
            return

        provider = self._provider_from_relation(relation)
        logger.warning(f"provider: {provider}")

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

        self._provide_ingress(relation, provider)  # type: ignore

    def _provide_routed_ingress(self, relation: Relation):
        """Provide ingress to a unit related through TraefikRoute."""
        config = self.traefik_route.get_config(relation)
        if not config:
            logger.warning(
                f"traefik route config could not be accessed: "
                f"traefik_route.get_config({relation}) returned None"
            )
            return

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
        self,
        relation: Relation,
        provider: Union[IPAv1, IPAv2, IngressPerUnitProvider],
    ):
        # to avoid long-gone units from lingering in the databag, we wipe it
        if self.unit.is_leader():
            provider.wipe_ingress_data(relation)

        # generate configs based on ingress type
        # this will also populate our databags with the urls
        if provider is self.ingress_per_unit:
            config_getter = self._get_configs_per_unit
        elif provider is self.ingress_per_appv2:
            config_getter = self._get_configs_per_app
        elif provider is self.ingress_per_appv1:
            logger.warning(
                "providing ingress over ingress v1: " "handling it as ingress per leader (legacy)"
            )
            config_getter = self._get_configs_per_leader
        else:
            raise ValueError(f"unknown provider: {provider}")

        configs = config_getter(relation)
        self._push_configurations(relation, configs)

    def _get_configs_per_leader(self, relation: Relation) -> Dict[str, Any]:
        """Generates ingress per leader config."""
        # this happens to be the same behaviour as ingress v1 (legacy) provided.
        ipa = self.ingress_per_appv1

        try:
            data = ipa.get_data(relation)
        except DataValidationError as e:
            logger.error(f"invalid data shared through {relation}... Error: {e}.")
            return {}

        prefix = self._get_prefix(data)  # type: ignore
        config = self._generate_per_leader_config(prefix, data)  # type: ignore
        if self.unit.is_leader():
            ipa.publish_url(relation, self._get_external_url(prefix))

        return config

    def _get_configs_per_app(self, relation: Relation) -> Dict[str, Any]:
        ipa = self.ingress_per_appv2
        if not relation.app:
            logger.error(f"no app on relation {relation}")
            return {}

        try:
            data = ipa.get_data(relation)
        except DataValidationError as e:
            logger.error(f"invalid data shared through {relation}... Error: {e}.")
            return {}

        prefix = self._get_prefix(data.app.dict(by_alias=True))
        config = self._generate_per_app_config(prefix, data)
        if self.unit.is_leader():
            external_url = self._get_external_url(prefix)
            logger.debug(f"publishing external url for {relation.app.name}: {external_url}")

            ipa.publish_url(relation, external_url)

        return config

    def _get_configs_per_unit(self, relation: Relation) -> Dict[str, Any]:
        # FIXME Ideally, follower units could instead watch for the data in the
        # ingress app data bag, but Juju does not allow non-leader units to read
        # the application data bag on their side of the relation, so we may start
        # routing for a remote unit before the leader unit of ingress has
        # communicated the url.
        ipu = self.ingress_per_unit

        config = {}
        for unit in relation.units:
            if not ipu.is_unit_ready(relation, unit):
                continue
            # if the unit is ready, it's implied that the data is there.
            # but we should still ensure it's valid, hence...
            try:
                data = ipu.get_data(relation, unit)
            except DataValidationError as e:
                # is_unit_ready should guard against no data being there yet,
                # but if the data is invalid...
                logger.error(
                    f"invalid data shared through {relation} by " f"{unit}... Error: {e}."
                )
                continue

            prefix = self._get_prefix(data)  # type: ignore
            if data.get("mode", "http") == "tcp":
                unit_config = self._generate_per_unit_tcp_config(prefix, data)  # type: ignore
                if self.unit.is_leader():
                    host = self.external_host
                    ipu.publish_url(relation, data["name"], f"{host}:{data['port']}")
            else:  # "http"
                unit_config = self._generate_per_unit_http_config(prefix, data)  # type: ignore
                if self.unit.is_leader():
                    ipu.publish_url(relation, data["name"], self._get_external_url(prefix))

            always_merger.merge(config, unit_config)

        # Note: We might be pushing an empty configuration if, for example,
        # none of the units has yet written their part of the data into the
        # relation. Traefik is fine with it :-)
        return config

    def _push_configurations(self, relation: Relation, config: Union[Dict[str, Any], str]):
        if config:
            yaml_config = yaml.dump(config) if not isinstance(config, str) else config
            config_filename = f"{_DYNAMIC_CONFIG_DIR}/{self._relation_config_file(relation)}"
            self.container.push(config_filename, yaml_config, make_dirs=True)
            logger.debug("Updated ingress configuration file: %s", config_filename)
        else:
            self._wipe_ingress_for_relation(relation)

    @staticmethod
    def _get_prefix(data: Dict[str, Any]):
        name = data["name"].replace("/", "-")
        return f"{data['model']}-{name}"

    def _generate_middleware_config(
        self,
        data: Dict[str, Any],
        prefix: str,
    ) -> dict:
        """Generate a middleware config.

        We need to generate a different section per middleware type, otherwise traefik complains:
          "cannot create middleware: multi-types middleware not supported, consider declaring two
          different pieces of middleware instead"
        """
        no_prefix_middleware = {}  # type: Dict[str, Dict[str, Any]]
        if self._routing_mode is _RoutingMode.path:
            if data.get("strip-prefix", False):
                no_prefix_middleware[f"juju-sidecar-noprefix-{prefix}"] = {
                    "stripPrefix": {"prefixes": [f"/{prefix}"], "forceSlash": False}
                }

        # Condition rendering the https-redirect middleware on the scheme, otherwise we'd get a 404
        # when attempting to reach an http endpoint.
        redir_scheme_middleware = {}
        if data.get("redirect-https", False) and data.get("scheme") == "https":
            redir_scheme_middleware[f"juju-sidecar-redir-https-{prefix}"] = {
                "redirectScheme": {"scheme": "https", "port": 443, "permanent": True}
            }

        return {**no_prefix_middleware, **redir_scheme_middleware}

    def _generate_per_unit_tcp_config(self, prefix: str, data: RequirerData_IPU) -> dict:
        """Generate a config dict for a given unit for IngressPerUnit in tcp mode."""
        # TODO: is there a reason why SNI-based routing (from TLS certs) is per-unit only?
        # This is not a technical limitation in any way. It's meaningful/useful for
        # authenticating to individual TLS-based servers where it may be desirable to reach
        # one or more servers in a cluster (let's say Kafka), but limiting it to per-unit only
        # actively impedes the architectural design of any distributed/ring-buffered TLS-based
        # scale-out services which may only have frontends dedicated, but which do not "speak"
        # HTTP(S). Such as any of the "cloud-native" SQL implementations (TiDB, Cockroach, etc)
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
                        "loadBalancer": {
                            "servers": [{"address": f"{data['host']}:{data['port']}"}]
                        }
                    },
                },
            }
        }
        return config

    def _generate_per_unit_http_config(self, prefix: str, data: RequirerData_IPU) -> dict:
        """Generate a config dict for a given unit for IngressPerUnit."""
        lb_servers = [{"url": f"{data.get('scheme', 'http')}://{data['host']}:{data['port']}"}]
        return self._generate_config_block(prefix, lb_servers, data)  # type: ignore

    def _generate_config_block(
        self,
        prefix: str,
        lb_servers: List[Dict[str, str]],
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate a configuration segment.

        Per-unit and per-app configuration blocks are mostly similar, with the principal
        difference being the list of servers to load balance across (where IPU is one server per
        unit and IPA may be more than one).
        """
        host = self.external_host
        if self._routing_mode is _RoutingMode.path:
            route_rule = f"PathPrefix(`/{prefix}`)"
        else:  # _RoutingMode.subdomain
            route_rule = f"Host(`{prefix}.{host}`)"

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

        # Add the "rootsCAs" section only if TLS is enabled. If the rootCA section
        # is empty or the file does not exist, HTTP requests will fail with
        # "404 page not found".
        # Note: we're assuming here that the CA that signed traefik's own CSR is
        # the same CA that signed the service's servers CSRs.
        external_tls = self._is_tls_enabled()

        # REVERSE TERMINATION: we are providing ingress for a unit who is itself behind https,
        # but traefik is not.
        internal_tls = data.get("scheme") == "https"

        is_reverse_termination = not external_tls and internal_tls
        is_termination = external_tls and not internal_tls
        is_end_to_end = external_tls and internal_tls

        lb_def: Dict[str, Any] = {"servers": lb_servers}
        service_def = {
            "loadBalancer": lb_def,
        }

        if is_reverse_termination:
            # i.e. traefik itself is not related to tls certificates, but the ingress requirer is
            transport_name = "reverseTerminationTransport"
            lb_def["serversTransport"] = transport_name
            transports = {transport_name: {"insecureSkipVerify": False}}

        elif is_termination:
            # i.e. traefik itself is related to tls certificates, but the ingress requirer is not
            transports = {}

        elif is_end_to_end:
            # We cannot assume traefik's CA is the same CA that signed the proxied apps.
            # Since we use the update_ca_certificates machinery, we don't need to specify the
            # "rootCAs" entry.
            # Keeping the serverTransports section anyway because it is informative ("endToEndTLS"
            # vs "reverseTerminationTransport") when inspecting the config file in production.
            transport_name = "endToEndTLS"
            lb_def["serversTransport"] = transport_name
            transports = {transport_name: {"insecureSkipVerify": False}}

        else:
            transports = {}

        config = {
            "http": {
                "routers": router_cfg,
                "services": {traefik_service_name: service_def},
            },
        }
        # Traefik does not accept an empty serversTransports. Add it only if it's non-empty.
        if transports:
            config["http"].update({"serversTransports": transports})

        middlewares = self._generate_middleware_config(data, prefix)

        if middlewares:
            config["http"]["middlewares"] = middlewares
            router_cfg[traefik_router_name]["middlewares"] = list(middlewares.keys())

            if f"{traefik_router_name}-tls" in router_cfg:
                router_cfg[f"{traefik_router_name}-tls"]["middlewares"] = list(middlewares.keys())

        return config

    def _generate_tls_block(
        self,
        router_name: str,
        route_rule: str,
        service_name: str,
    ) -> Dict[str, Any]:
        """Generate a TLS configuration segment."""
        tls_entry = (
            {
                "domains": [
                    {
                        "main": self.external_host,
                        "sans": [f"*.{self.external_host}"],
                    },
                ],
            }
            if is_hostname(self.external_host)
            else {}  # When the external host is a bare IP, we do not need the 'domains' entry.
        )

        return {
            f"{router_name}-tls": {
                "rule": route_rule,
                "service": service_name,
                "entryPoints": ["websecure"],
                "tls": tls_entry,
            }
        }

    def _generate_per_app_config(
        self,
        prefix: str,
        data: "IPADatav2",
    ) -> dict:
        # todo: IPA>=v2 uses pydantic models, the other providers use raw dicts.
        #  eventually switch all over to pydantic and handle this uniformly
        app_dict = data.app.dict(by_alias=True)
        lb_servers = [
            {"url": f"{data.app.scheme}://{unit_data.host}:{data.app.port}"}
            for unit_data in data.units
        ]
        return self._generate_config_block(prefix, lb_servers, app_dict)

    def _generate_per_leader_config(
        self,
        prefix: str,
        data: "IPADatav1",
    ) -> dict:
        lb_servers = [{"url": f"http://{data['host']}:{data['port']}"}]
        return self._generate_config_block(prefix, lb_servers, data)  # type: ignore

    @property
    def _scheme(self):
        return "https" if self.cert.enabled else "http"

    def _get_external_url(self, prefix):
        if self._routing_mode is _RoutingMode.path:
            url = f"{self._scheme}://{self.external_host}/{prefix}"
        else:  # _RoutingMode.subdomain
            url = f"{self._scheme}://{prefix}.{self.external_host}/"
        return url

    def _wipe_ingress_for_all_relations(self):
        for relation in self.model.relations["ingress"] + self.model.relations["ingress-per-unit"]:
            self._wipe_ingress_for_relation(relation)

    def _wipe_ingress_for_relation(self, relation: Relation, *, wipe_rel_data=True):
        logger.debug(f"Wiping ingress for the '{relation.name}:{relation.id}' relation")

        # Delete configuration files for the relation. In case of Traefik pod
        # churns, and depending on the event ordering, we might be executing this
        # logic before pebble in the traefik container is up and running. If that
        # is the case, nevermind, we will wipe the dangling config files anyhow
        # during _on_traefik_pebble_ready .
        if self.container.can_connect() and relation.app:
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
            provider.wipe_ingress_data(relation)  # type: ignore  # this is an ingress-type relation

    @staticmethod
    def _relation_config_file(relation: Relation):
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
                    # trick to drop the logs to a file but also keep them available in the pod logs
                    "command": '/bin/sh -c "{} | tee {}"'.format(BIN_PATH, self._log_path),
                    "startup": "enabled",
                },
            },
        }

        current_services = self.container.get_plan().to_dict().get("services", {})

        if _TRAEFIK_SERVICE_NAME not in current_services:
            self.unit.status = MaintenanceStatus(f"creating the {_TRAEFIK_SERVICE_NAME!r} service")
            self.container.add_layer(
                _TRAEFIK_LAYER_NAME, typing.cast(LayerDict, layer), combine=True
            )
            logger.debug(f"replanning {_TRAEFIK_SERVICE_NAME!r} after a service update")
            self.container.replan()
        else:
            logger.debug(f"restarting {_TRAEFIK_SERVICE_NAME!r}")
            self.container.restart(_TRAEFIK_SERVICE_NAME)

    def _provider_from_relation(self, relation: Relation):
        """Returns the correct IngressProvider based on a relation."""
        relation_type = _get_relation_type(relation)
        if relation_type is _IngressRelationType.per_app:
            # first try to tell if remote is speaking v2
            if self.ingress_per_appv2.is_ready(relation):
                return self.ingress_per_appv2
            # if not: are we speaking v1?
            if self.ingress_per_appv1.is_ready(relation):
                # todo: only warn once per relation
                logger.warning(
                    f"{relation} is using a deprecated ingress v1 protocol to talk to Traefik. "
                    f"Please inform the maintainers of "
                    f"{getattr(relation.app, 'name', '<unknown remote>')!r} that they "
                    f"should bump to v2."
                )
            # if neither ingress v1 nor v2 are ready, the relation is simply still empty and we
            # don't know yet what protocol we're speaking
            return self.ingress_per_appv1
        if relation_type is _IngressRelationType.per_unit:
            return self.ingress_per_unit
        if relation_type is _IngressRelationType.routed:
            return self.traefik_route
        raise RuntimeError(f"Invalid relation type: {relation_type} ({relation.name})")

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
    def server_cert_sans_dns(self) -> List[str]:
        """Provide certificate SANs DNS."""
        target = self.external_host

        if is_hostname(target):
            assert isinstance(target, str)  # for type checker
            return [target]

        # This is an IP address. Try to look up the hostname.
        with contextlib.suppress(OSError, TypeError):
            name, _, _ = socket.gethostbyaddr(target)  # type: ignore
            # Do not return "hostname" like '10-43-8-149.kubernetes.default.svc.cluster.local'
            if is_hostname(name) and not name.endswith(".svc.cluster.local"):
                return [name]

        # If all else fails, we'd rather use the bare IP
        return [target] if target else []

    @property
    def _hostname(self) -> str:
        return socket.getfqdn()

    @property
    def _scrape_jobs(self) -> list:
        return [
            {
                "static_configs": [{"targets": [f"{self._hostname}:{self._diagnostics_port}"]}],
            }
        ]


@functools.lru_cache
def _get_loadbalancer_status(namespace: str, service_name: str):
    client = Client()  # type: ignore
    traefik_service = client.get(Service, name=service_name, namespace=namespace)

    if status := traefik_service.status:  # type: ignore
        if load_balancer_status := status.loadBalancer:
            if ingress_addresses := load_balancer_status.ingress:
                if ingress_address := ingress_addresses[0]:
                    return ingress_address.hostname or ingress_address.ip

    return None


def _get_relation_type(relation: Relation) -> _IngressRelationType:
    if relation.name == "ingress":
        return _IngressRelationType.per_app
    if relation.name == "ingress-per-unit":
        return _IngressRelationType.per_unit
    if relation.name == "traefik-route":
        return _IngressRelationType.routed
    raise RuntimeError("Invalid relation name (shouldn't happen)")


if __name__ == "__main__":
    main(TraefikIngressCharm, use_juju_for_storage=True)
