#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed traefik operator."""
import contextlib
import enum
import itertools
import json
import logging
import re
import socket
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse

import pydantic
import yaml
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateAvailableEvent as CertificateTransferAvailableEventV0,
)
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateRemovedEvent as CertificateTransferRemovedEventV0,
)
from charms.certificate_transfer_interface.v0.certificate_transfer import (
    CertificateTransferRequires as CertificateTransferRequiresV0,
)
from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificatesAvailableEvent as CertificateTransferAvailableEventV1,
)
from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificatesRemovedEvent as CertificateTransferRemovedEventV1,
)
from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires as CertificateTransferRequiresV1,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LokiPushApiConsumer
from charms.oathkeeper.v0.forward_auth import (
    AuthConfigChangedEvent,
    AuthConfigRemovedEvent,
    ForwardAuthRequirer,
    ForwardAuthRequirerConfig,
)
from charms.observability_libs.v1.cert_handler import CertHandler
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer, charm_tracing_config
from charms.traefik_k8s.v0.traefik_route import (
    TraefikRouteProvider,
    TraefikRouteRequirerReadyEvent,
)
from charms.traefik_k8s.v1.ingress import IngressPerAppProvider as IPAv1
from charms.traefik_k8s.v1.ingress_per_unit import (
    DataValidationError,
    IngressPerUnitProvider,
)
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider as IPAv2
from cosl import JujuTopology
from deepmerge import always_merger
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from lightkube_extensions.batch import KubernetesResourceManager, create_charm_default_labels
from ops import main
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
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    WaitingStatus,
)
from ops.pebble import PathError

from traefik import (
    CA,
    SERVER_CERT_PATH,
    RoutingMode,
    StaticConfigMergeConflictError,
    Traefik,
)
from utils import is_hostname

# To keep a tidy debug-log, we suppress some DEBUG/INFO logs from some imported libs,
# even when charm logging is set to a lower level.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_TRAEFIK_CONTAINER_NAME = "traefik"
_RECV_CA_CERT_RELATION_NAME = "receive-ca-cert"


# Regex for Kubernetes annotation values:
# - Allows alphanumeric characters, dots (.), dashes (-), and underscores (_)
# - Matches the entire string
# - Does not allow empty strings
# - Example valid: "value1", "my-value", "value.name", "value_name"
# - Example invalid: "value@", "value#", "value space"
ANNOTATION_VALUE_PATTERN = re.compile(r"^[\w.\-_]+$")

# Based on https://github.com/kubernetes/apimachinery/blob/v0.31.3/pkg/util/validation/validation.go#L204
# Regex for DNS1123 subdomains:
# - Starts with a lowercase letter or number ([a-z0-9])
# - May contain dashes (-), but not consecutively, and must not start or end with them
# - Segments can be separated by dots (.)
# - Example valid: "example.com", "my-app.io", "sub.domain"
# - Example invalid: "-example.com", "example..com", "example-.com"
DNS1123_SUBDOMAIN_PATTERN = re.compile(
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
)

# Based on https://github.com/kubernetes/apimachinery/blob/v0.31.3/pkg/util/validation/validation.go#L32
# Regex for Kubernetes qualified names:
# - Starts with an alphanumeric character ([A-Za-z0-9])
# - Can include dashes (-), underscores (_), dots (.), or alphanumeric characters in the middle
# - Ends with an alphanumeric character
# - Must not be empty
# - Example valid: "annotation", "my.annotation", "annotation-name"
# - Example invalid: ".annotation", "annotation.", "-annotation", "annotation@key"
QUALIFIED_NAME_PATTERN = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")

LB_LABEL = "traefik-loadbalancer"

PYDANTIC_IS_V1 = int(pydantic.version.VERSION.split(".")[0]) < 2


class _IngressRelationType(enum.Enum):
    per_app = "per_app"
    per_unit = "per_unit"
    routed = "routed"


class IngressSetupError(Exception):
    """Error setting up ingress for some requirer."""


class ExternalHostNotReadyError(Exception):
    """Raised when the ingress hostname is not ready but is assumed to be."""


@trace_charm(
    tracing_endpoint="charm_tracing_endpoint",
    server_cert="server_cert",
    extra_types=(
        IPAv2,
        IPAv1,
        IngressPerUnitProvider,
        TraefikRouteProvider,
    ),
)
class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        # Before doing anything, validate the charm config.  If configuration is invalid, warn the user.
        # FIXME: Invalid configuration here SHOULD halt the charm's operation until resolution, or at least make a
        #  persistent BlockedStatus, but this charm handles events atomically rather than holistically.
        #  This means that skipping events will result in unexpected issues, so if we halt the charm here we must
        #  ensure the charm processes all backlogged events on resumption in the original order.  Rather than do that
        #  and risk losing an event, we simply warn the user and continue functioning as best as possible.  The charm
        #  will operate correctly except that it will not publish ingress urls to related applications, instead
        #  leaving the ingress relation data empty and logging an error.
        #  If we refactor this charm to handle events holistically (and thus we can skip events without issue), we
        #  should refactor this validation truly halt the charm.
        #  If we refactor this charm to use collect_unit_status, we could raise a persistent BlockedStatus message when
        #  this configuration is invalid.
        self._validate_config()

        self._stored.set_default(
            config_hash=None,
        )

        self.container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        self._lightkube_client = None
        self._lightkube_field_manager: str = self.app.name
        self._lb_name: str = f"{self.app.name}-lb"
        sans = self.server_cert_sans_dns
        self.cert = CertHandler(
            self,
            key="trfk-server-cert",
            # Route53 complains if CN is not a hostname
            cert_subject=sans[0] if sans else None,
            sans=sans,
        )

        self.recv_ca_cert_v0 = CertificateTransferRequiresV0(self, _RECV_CA_CERT_RELATION_NAME)
        self.recv_ca_cert_v1 = CertificateTransferRequiresV1(self, _RECV_CA_CERT_RELATION_NAME)

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
        self.ingress_per_appv1 = IPAv1(charm=self)
        self.ingress_per_appv2 = IPAv2(charm=self)

        self.ingress_per_unit = IngressPerUnitProvider(charm=self)

        self.traefik_route = TraefikRouteProvider(
            charm=self, external_host=self._external_host, scheme=self._scheme  # type: ignore
        )

        self._topology = JujuTopology.from_charm(self)

        # tracing integration
        self._charm_tracing = TracingEndpointRequirer(
            self, relation_name="charm-tracing", protocols=["otlp_http"]
        )
        self._workload_tracing = TracingEndpointRequirer(
            self, relation_name="workload-tracing", protocols=["jaeger_thrift_http"]
        )

        self.charm_tracing_endpoint, self.server_cert = charm_tracing_config(
            self._charm_tracing, SERVER_CERT_PATH
        )

        self.traefik = Traefik(
            container=self.container,
            routing_mode=self._routing_mode,
            tcp_entrypoints=self._tcp_entrypoints(),
            tls_enabled=self._is_tls_enabled(),
            experimental_forward_auth_enabled=self._is_forward_auth_enabled,
            traefik_route_static_configs=self._traefik_route_static_configs(),
            basic_auth_user=self._basic_auth_user,
            topology=self._topology,
            tracing_endpoint=(
                self._workload_tracing.get_endpoint("jaeger_thrift_http")
                if self._is_workload_tracing_ready()
                else None
            ),
        )

        # Observability integrations

        # Provide grafana dashboards over a relation interface
        # dashboard to use: https://grafana.com/grafana/dashboards/4475-traefik/
        # TODO wishlist: I would like for the p60, p70, p80, p90, p99, min, max, and avg for
        #  http_request_duration to be plotted as a graph. You should have access to a
        #  http_request_duration_bucket, which should make this fairly straight
        #  forward to do using histogram_quantiles
        self._grafana_dashboards = GrafanaDashboardProvider(
            self, relation_name="grafana-dashboard"
        )
        # Enable logging relation for Loki and other charms that implement loki_push_api
        self._logging = LokiPushApiConsumer(self)
        self.metrics_endpoint = MetricsEndpointProvider(
            charm=self,
            jobs=self.traefik.scrape_jobs,
            refresh_event=[
                self.on.traefik_pebble_ready,  # type: ignore
                self.on.update_status,  # type: ignore
            ],
        )

        self.forward_auth = ForwardAuthRequirer(self, relation_name="experimental-forward-auth")

        observe = self.framework.observe

        # TODO update init params once auto-renew is implemented
        # https://github.com/canonical/tls-certificates-interface/issues/24
        observe(
            self._workload_tracing.on.endpoint_changed,  # type: ignore
            self._on_workload_tracing_endpoint_changed,
        )
        observe(
            self._workload_tracing.on.endpoint_removed,  # type: ignore
            self._on_workload_tracing_endpoint_removed,
        )

        observe(self.on.traefik_pebble_ready, self._on_traefik_pebble_ready)  # type: ignore
        observe(self.on.start, self._on_start)
        observe(self.on.stop, self._on_stop)
        observe(self.on.remove, self._on_remove)
        observe(self.on.update_status, self._on_update_status)
        observe(self.on.config_changed, self._on_config_changed)
        observe(
            self.cert.on.cert_changed,  # pyright: ignore
            self._on_cert_changed,
        )
        observe(
            self.recv_ca_cert_v0.on.certificate_available,  # pyright: ignore
            self._on_recv_ca_cert_available,
        )
        observe(
            # Need to observe a managed relation event because a custom wrapper is not available
            # https://github.com/canonical/mutual-tls-interface/issues/5
            self.recv_ca_cert_v0.on.certificate_removed,  # pyright: ignore
            self._on_recv_ca_cert_removed,
        )

        observe(
            self.recv_ca_cert_v1.on.certificate_set_updated,  # pyright: ignore
            self._on_recv_ca_cert_available,
        )
        observe(
            self.recv_ca_cert_v1.on.certificates_removed,  # pyright: ignore
            self._on_recv_ca_cert_removed,
        )

        observe(self.forward_auth.on.auth_config_changed, self._on_forward_auth_config_changed)
        observe(self.forward_auth.on.auth_config_removed, self._on_forward_auth_config_removed)

        # observe data_provided and data_removed events for all types of ingress we offer:
        for ingress in (self.ingress_per_unit, self.ingress_per_appv1, self.ingress_per_appv2):
            observe(ingress.on.data_provided, self._handle_ingress_data_provided)  # type: ignore
            observe(ingress.on.data_removed, self._handle_ingress_data_removed)  # type: ignore

        route_events = self.traefik_route.on
        observe(route_events.ready, self._handle_traefik_route_ready)  # type: ignore
        observe(route_events.data_removed, self._handle_ingress_data_removed)  # type: ignore

        # Action handlers
        observe(self.on.show_proxied_endpoints_action, self._on_show_proxied_endpoints)  # type: ignore

    @property
    def _service_ports(self) -> List[ServicePort]:
        """Kubernetes service ports to be opened for this workload.

        We cannot use ops unit.open_port here because Juju will provision a ClusterIP
        but for traefik we need LoadBalancer.
        """
        traefik = self.traefik
        service_name = traefik.service_name
        web = ServicePort(traefik.port, name=f"{service_name}")
        websecure = ServicePort(traefik.tls_port, name=f"{service_name}-tls")
        return [web, websecure] + [
            ServicePort(int(port), name=name) for name, port in self._tcp_entrypoints().items()
        ]

    @property
    def _forward_auth_config(self) -> ForwardAuthRequirerConfig:
        ingress_app_names = [
            rel.app.name  # type: ignore
            for rel in itertools.chain(
                self.ingress_per_appv1.relations,
                self.ingress_per_appv2.relations,
                self.ingress_per_unit.relations,
                self.traefik_route.relations,
            )
        ]
        return ForwardAuthRequirerConfig(ingress_app_names)

    @property
    def _is_forward_auth_enabled(self) -> bool:
        if self.config["enable_experimental_forward_auth"]:
            return True
        return False

    @property
    def _basic_auth_user(self) -> Optional[str]:
        """A single user for the global basic auth configuration.

        As we can't reject it, we assume it's correctly formatted.
        """
        return cast(Optional[str], self.config.get("basic_auth_user", None))

    @property
    def _loadbalancer_annotations(self) -> Optional[Dict[str, str]]:
        """Parses and returns annotations to apply to the LoadBalancer service.

        The annotations are expected as a string in the configuration,
        formatted as: "key1=value1,key2=value2,key3=value3". This string is
        parsed into a dictionary where each key-value pair corresponds to an annotation.

        Returns:
            Optional[Dict[str, str]]: A dictionary of annotations if provided in the Juju config and valid, otherwise None.
        """
        lb_annotations = cast(Optional[str], self.config.get("loadbalancer_annotations", None))
        return parse_annotations(lb_annotations)

    @property
    def lightkube_client(self):
        """Returns a lightkube client configured for this charm."""
        if self._lightkube_client is None:
            self._lightkube_client = Client(
                namespace=self.model.name, field_manager=self._lightkube_field_manager
            )
        return self._lightkube_client

    def _get_lb_resource_manager(self):
        return KubernetesResourceManager(
            labels=create_charm_default_labels(self.app.name, self.model.name, scope=LB_LABEL),
            resource_types={Service},
            lightkube_client=self.lightkube_client,
            logger=logger,
        )

    def _construct_lb(self) -> Service:
        return Service(
            metadata=ObjectMeta(
                name=f"{self.app.name}-lb",
                namespace=self.model.name,
                labels={"app.kubernetes.io/name": self.app.name},
                annotations=self._loadbalancer_annotations,
            ),
            spec=ServiceSpec(
                ports=self._service_ports,
                selector={"app.kubernetes.io/name": self.app.name},
                type="LoadBalancer",
            ),
        )

    def _reconcile_lb(self):
        """Reconcile the LoadBalancer's state."""
        klm = self._get_lb_resource_manager()

        resources_list = []
        if self._annotations_valid:
            resources_list.append(self._construct_lb())
        klm.reconcile(resources_list)

    @property
    def _get_loadbalancer_status(self) -> Optional[str]:
        try:
            traefik_service = self.lightkube_client.get(
                Service, name=self._lb_name, namespace=self.model.name
            )
        except ApiError as e:
            logger.error(f"Failed to fetch LoadBalancer {self._lb_name}: {e}")
            return None

        if not (status := getattr(traefik_service, "status", None)):
            return None
        if not (load_balancer_status := getattr(status, "loadBalancer", None)):
            return None
        if not (ingress_addresses := getattr(load_balancer_status, "ingress", None)):
            return None
        if not (ingress_address := ingress_addresses[0]):
            return None

        return ingress_address.hostname or ingress_address.ip

    @property
    def _annotations_valid(self) -> bool:
        """Check if the annotations are valid.

        :return: True if the annotations are valid, False otherwise.
        """
        if self._loadbalancer_annotations is None:
            logger.error("Annotations are invalid or could not be parsed.")
            return False
        return True

    def _on_forward_auth_config_changed(self, event: AuthConfigChangedEvent):
        if self._is_forward_auth_enabled:
            if self.forward_auth.is_ready():
                self._process_status_and_configurations()
        else:
            logger.info(
                "The `enable_experimental_forward_auth` config option is not enabled. Forward-auth relation will not be processed"
            )

    def _on_forward_auth_config_removed(self, event: AuthConfigRemovedEvent):
        self._process_status_and_configurations()

    def _on_recv_ca_cert_available(
        self,
        event: Union[CertificateTransferAvailableEventV0, CertificateTransferAvailableEventV1],
    ):
        # Assuming only one cert per relation (this is in line with the original lib design).
        if not self.container.can_connect():
            return
        self._update_received_ca_certs(event)
        self._reconcile_lb()

    def _update_received_ca_certs(
        self,
        event: Optional[
            Union[CertificateTransferAvailableEventV0, CertificateTransferAvailableEventV1]
        ] = None,
    ):
        """Push the cert attached to the event, if it is given; otherwise push all certs.

        This function is needed because relation events are not emitted on upgrade, and because we
        do not have (nor do we want) persistent storage for certs.
        Calling this function from upgrade-charm might be too early though. Pebble-ready is
        preferred.
        """
        cas = []
        if event and isinstance(event, CertificateTransferAvailableEventV0):
            cas.append(CA(event.ca, uid=f"{event.relation_id}-0"))
        else:
            for relation in self.model.relations.get(_RECV_CA_CERT_RELATION_NAME, []):
                recv_ca_cert_requirer = self._recv_ca_cert_requirer_from_relation(relation)
                relation_certificates = []
                if recv_ca_cert_requirer is self.recv_ca_cert_v0:
                    # For some reason, relation.units includes our unit and app. Need to exclude them.
                    for unit in set(relation.units).difference([self.app, self.unit]):
                        # Note: this nested loop handles the case of multi-unit CA, each unit providing
                        # a different ca cert, but that is not currently supported by the lib itself.
                        if ca := relation.data[unit].get("ca"):
                            relation_certificates.append(ca)
                elif recv_ca_cert_requirer is self.recv_ca_cert_v1:
                    # add index to relation id to avoid conflicts in case of multiple CAs per relation
                    relation_certificates.extend(
                        self.recv_ca_cert_v1.get_all_certificates(relation.id)
                    )
                else:
                    raise ValueError(
                        f"unknown cert transfer relation type: {recv_ca_cert_requirer}"
                    )
                cas.extend(
                    CA(ca, uid=f"{relation.id}-{i}") for i, ca in enumerate(relation_certificates)
                )
        self.traefik.add_cas(cas)

    def _on_recv_ca_cert_removed(
        self, event: Union[CertificateTransferRemovedEventV0, CertificateTransferRemovedEventV1]
    ):
        self.traefik.remove_cas([event.relation_id])
        self._reconcile_lb()

    def _is_tls_enabled(self) -> bool:
        """Return True if TLS is enabled."""
        if self.cert.enabled:
            return True
        if (
            self.config.get("tls-ca", None)
            and self.config.get("tls-cert", None)
            and self.config.get("tls-key", None)
        ):
            return True
        return False

    def _on_workload_tracing_endpoint_removed(self, _) -> None:
        self._update_config_if_changed()

    def _on_workload_tracing_endpoint_changed(self, _) -> None:
        self._update_config_if_changed()

    def _is_workload_tracing_ready(self) -> bool:
        """Return True if workload tracing is enabled and ready."""
        if not self._workload_tracing.is_ready():
            return False
        return True

    def _on_cert_changed(self, event) -> None:
        # On slow machines, this event may come up before pebble is ready
        if not self.container.can_connect():
            event.defer()
            return

        self._update_cert_configs()
        self._configure_traefik()
        self._process_status_and_configurations()

    def _update_cert_configs(self):
        self.traefik.update_cert_configuration(*self._get_certs())

    def _get_certs(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        cert_handler = self.cert
        if not self._is_tls_enabled():
            return None, None, None
        if (
            self.config.get("tls-ca", None)
            and self.config.get("tls-cert", None)
            and self.config.get("tls-key", None)
        ):
            return (
                cast(str, self.config["tls-cert"]),
                cast(str, self.config["tls-key"]),
                cast(str, self.config["tls-ca"]),
            )
        return cert_handler.chain, cert_handler.private_key, cert_handler.ca_cert

    def _on_show_proxied_endpoints(self, event: ActionEvent):
        if not self.ready:
            return
        result = {}

        traefik_endpoint = {self.app.name: {"url": f"{self._scheme}://{self.external_host}"}}
        result.update(traefik_endpoint)

        for provider in (self.ingress_per_unit, self.ingress_per_appv1, self.ingress_per_appv2):
            try:
                result.update(provider.proxied_endpoints)
            except Exception as e:
                remote_app_names = [
                    # relation.app could be None
                    (relation.app.name if relation.app else "<unknown-remote>")
                    for relation in provider.relations
                ]
                msg = (
                    f"failed to fetch proxied endpoints from (at least one of) the "
                    f"remote apps {remote_app_names!r} with error {e}."
                )
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
                    entrypoints[entrypoint_name] = data["port"]

        # for each static config sent via traefik_route add provided entryPoints to open a ServicePort
        static_configs = self._traefik_route_static_configs()
        for config in static_configs:
            if "entryPoints" in config:
                provided_entrypoints = config["entryPoints"]
                for entrypoint_name, value in provided_entrypoints.items():
                    # TODO names can be only lower-case alphanumeric with dashes. Should we validate and replace?
                    # ref https://kubernetes.io/docs/concepts/overview/working-with-objects/names/#dns-label-names
                    if "address" in value:
                        entrypoints[entrypoint_name] = value["address"].replace(":", "")

        return entrypoints

    def _configure_traefik(self):
        self.traefik.configure()

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
        self.traefik.delete_dynamic_configs()

        # we push the static config
        self._configure_traefik()
        # now we restart traefik
        self._restart_traefik()

    def _on_start(self, _: StartEvent):
        self._process_status_and_configurations()

    def _on_stop(self, _):
        # If obtaining the workload version after an upgrade fails, we do not want juju to display
        # the workload version from before the upgrade.
        self.unit.set_workload_version("")

    def _on_remove(self, _):
        klm = self._get_lb_resource_manager()
        klm.delete()

    def _on_update_status(self, _: UpdateStatusEvent):
        self._process_status_and_configurations()
        self._set_workload_version()

    @property
    def _config_hash(self) -> int:
        """A hash of the config of this application.

        Only include here the config options that, should they change, should trigger a recalculation of
        the traefik config files.
        The main goal of this logic is to avoid recalculating status and configs on each event,
        since it can be quite expensive.
        """
        return hash(
            (
                self._external_host,
                self.config["routing_mode"],
                self._is_forward_auth_enabled,
                self._basic_auth_user,
                self._is_tls_enabled(),
            )
        )

    def _on_config_changed(self, _: ConfigChangedEvent):
        """Handle the ops.ConfigChanged event."""
        self._update_config_if_changed()

    def _update_config_if_changed(self):
        # that we're processing a config-changed event, doesn't necessarily mean that our config has changed (duh!)
        # If the config hash has changed since we last calculated it, we need to
        # recompute our state from scratch, based on all data sent over the relations and all configs
        self._reconcile_lb()
        new_config_hash = self._config_hash
        if self._stored.config_hash != new_config_hash:
            self._stored.config_hash = new_config_hash

            if self._is_tls_enabled():
                # we keep this nested under the hash-check because, unless the tls config has
                # changed, we don't need to redo this.
                self._update_cert_configs()
                self._configure_traefik()

            self._process_status_and_configurations()

    def _process_status_and_configurations(self):
        self._reconcile_lb()
        if (
            self.config.get("tls-ca", None)
            or self.config.get("tls-cert", None)
            or self.config.get("tls-key", None)
        ):
            if not (
                self.config.get("tls-ca", None)
                and self.config.get("tls-cert", None)
                and self.config.get("tls-key", None)
            ):
                self.unit.status = BlockedStatus("Please set tls-cert, tls-key, and tls-ca")
                return

        routing_mode = self.config["routing_mode"]
        try:
            RoutingMode(routing_mode)
        except ValueError:
            self._wipe_ingress_for_all_relations()
            self.unit.status = BlockedStatus(f"invalid routing mode: {routing_mode}; see logs.")

            logger.error(
                "'%s' is not a valid routing_mode value; valid values are: %s",
                routing_mode,
                [e.value for e in RoutingMode],
            )
            return

        hostname = self._external_host

        if not hostname:
            self._wipe_ingress_for_all_relations()
            self.unit.status = BlockedStatus(
                "Traefik load balancer is unable to obtain an IP or hostname from the cluster."
            )
            return

        if hostname != urlparse(f"scheme://{hostname}").hostname:
            self._wipe_ingress_for_all_relations()
            self.unit.status = BlockedStatus(f"invalid hostname: {hostname}; see logs.")

            logger.error(
                "'%s' is not a valid hostname value; "
                "hostname must not include port or any other netloc components",
                hostname,
            )
            return

        if not self.traefik.is_ready:
            self.unit.status = WaitingStatus(f"waiting for service: '{self.traefik.service_name}'")
            return

        self.unit.status = MaintenanceStatus("updating ingress configurations")
        self._update_ingress_configurations()

    def _update_ingress_configurations(self):
        # step 1: determine whether the STATIC config should be changed and traefik restarted.

        # if there was a static config changed requested through a traefik route interface,
        # we need to restart traefik.
        # if there are changes in the tcp configs, we'll need to restart
        # traefik as the tcp entrypoints are consumed as static configuration
        # and those can only be passed on init.

        if self._static_config_changed:
            logger.debug("Static config needs to be updated. Rebooting traefik.")
            # fixme: this is kind of brutal;
            #  will kill in-flight requests and disrupt traffic.
            self._clear_all_configs_and_restart_traefik()
            # we do this BEFORE processing the relations.

        # step 2:
        # update the dynamic configs.

        errors = False

        if self._is_forward_auth_enabled:
            self.forward_auth.update_requirer_relation_data(self._forward_auth_config)

        for ingress_relation in (
            self.ingress_per_appv1.relations
            + self.ingress_per_appv2.relations
            + self.ingress_per_unit.relations
            + self.traefik_route.relations
        ):
            try:
                self._process_ingress_relation(ingress_relation)
            except IngressSetupError as e:
                err_msg = e.args[0]
                logger.error(
                    f"failed processing the ingress relation {ingress_relation}: {err_msg!r}"
                )
                errors = True

        if errors:
            logger.debug(
                "unit in {!r}: {}".format(self.unit.status.name, self.unit.status.message)
            )
            self.unit.status = BlockedStatus("setup of some ingress relation failed")
            logger.error("The setup of some ingress relation failed, see previous logs")

        else:
            self.unit.status = ActiveStatus(f"Serving at {self._external_host}")

    @property
    def _static_config_changed(self):
        current = self.traefik.generate_static_config()
        traefik_static_config = self.traefik.pull_static_config()
        return current != traefik_static_config

    @property
    def ready(self) -> bool:
        """Check whether we have an external host set, and traefik is running."""
        if not self._external_host:
            self._wipe_ingress_for_all_relations()  # fixme: no side-effects in prop
            self.unit.status = BlockedStatus(
                "Traefik load balancer is unable to obtain an IP or hostname from the cluster."
            )
            return False
        if not self.traefik.is_ready:
            self.unit.status = WaitingStatus(f"waiting for service: '{self.traefik.service_name}'")
            return False
        return True

    def _handle_ingress_data_provided(self, event: RelationEvent):
        """A unit has provided data requesting ipu."""
        if not self.ready:
            event.defer()
            return
        self._process_ingress_relation(event.relation)

        # Without the following line, traefik.STATIC_CONFIG_PATH is updated with TCP endpoints only on
        # update-status.
        self._process_status_and_configurations()

        if isinstance(self.unit.status, MaintenanceStatus):
            self.unit.status = ActiveStatus(f"Serving at {self._external_host}")

    def _handle_ingress_data_removed(self, event: RelationEvent):
        """A unit has removed the data we need to provide ingress."""
        self._wipe_ingress_for_relation(
            event.relation, wipe_rel_data=not isinstance(event, RelationBrokenEvent)
        )

        # FIXME? on relation broken, data is still there so cannot simply call
        #  self._process_status_and_configurations(). For this reason, the static config in
        #  traefik.STATIC_CONFIG_PATH will be updated only on update-status.
        #  https://github.com/canonical/operator/issues/888
        self._reconcile_lb()

    def _handle_traefik_route_ready(self, event: TraefikRouteRequirerReadyEvent):
        """A traefik_route charm has published some ingress data."""
        if self._static_config_changed:
            # This will regenerate the static configs and reevaluate all dynamic configs,
            # including this one.
            self._update_ingress_configurations()

        else:
            try:
                self._process_ingress_relation(event.relation)
            except IngressSetupError as e:
                err_msg = e.args[0]
                logger.error(
                    f"failed processing the ingress relation for "
                    f"traefik-route ready with: {err_msg!r}"
                )

                self.unit.status = ActiveStatus("traefik-route relation degraded")
                return

        try:
            self.traefik.generate_static_config(_raise=True)
        except StaticConfigMergeConflictError:
            # FIXME: it's pretty hard to tell which configs are conflicting
            # FIXME: this status is lost when the next event comes in.
            #  We should start using the collect-status OF hook.
            self.unit.status = BlockedStatus(
                "Failed to merge traefik-route static configs. " "Check logs for details."
            )
            return
        self._reconcile_lb()
        self.unit.status = ActiveStatus(f"Serving at {self._external_host}")

    def _process_ingress_relation(self, relation: Relation):
        # There's a chance that we're processing a relation event which was deferred until after
        # the relation was broken. Select the right per_app/per_unit provider and check it is ready
        # before continuing. However, the provider will NOT be ready if there are no units on the
        # other side, which is the case for the RelationDeparted for the last unit (i.e., the
        # proxied application scales to zero).
        if not self.ready:
            logger.warning("not ready: early exit")
            raise IngressSetupError("traefik is not ready")

        provider = self._provider_from_relation(relation)

        if not provider.is_ready(relation):
            logger.debug(f"Provider {provider} not ready; resetting ingress configurations.")
            self._wipe_ingress_for_relation(relation)
            raise IngressSetupError(f"provider is not ready: ingress for {relation} wiped.")

        rel = f"{relation.name}:{relation.id}"

        self.unit.status = MaintenanceStatus(f"updating ingress configuration for '{rel}'")
        logger.debug("Updating ingress for relation '%s'", rel)

        if provider is self.traefik_route:
            self._provide_routed_ingress(relation)
            return

        self._provide_ingress(relation, provider)  # type: ignore

    def _try_load_dict(self, raw_config_yaml: str) -> Optional[Dict[str, Any]]:
        try:
            config = yaml.safe_load(raw_config_yaml)
        except yaml.YAMLError:
            logger.exception("traefik route didn't send good YAML.")
            return None

        if not isinstance(config, dict):
            logger.error(f"traefik route sent unexpected object: {config} (expecting dict).")
            return None

        return config

    def _traefik_route_static_configs(self):
        """Fetch all static configurations passed through traefik route."""
        configs = []
        for relation in self.traefik_route.relations:
            config = self.traefik_route.get_static_config(relation)
            if config:
                dct = self._try_load_dict(config)
                if not dct:
                    continue
                configs.append(dct)
        return configs

    def _provide_routed_ingress(self, relation: Relation):
        """Provide ingress to a unit related through TraefikRoute."""
        config = self.traefik_route.get_dynamic_config(relation)
        if not config:
            logger.warning(
                f"traefik route config could not be accessed: "
                f"traefik_route.get_config({relation}) returned None"
            )
            return

        dct = self._try_load_dict(config)

        if not dct:
            return

        self._update_dynamic_config_route(relation, dct)

    def _update_dynamic_config_route(self, relation: Relation, config: dict):
        def _process_routes(route_config, protocol):
            for router_name in list(route_config.keys()):  # Work on a copy of the keys
                router_details = route_config[router_name]
                route_rule = router_details.get("rule", "")
                service_name = router_details.get("service", "")
                entrypoints = router_details.get("entryPoints", [])
                tls_config = router_details.get("tls", {})

                # Skip generating new routes if passthrough is True
                if tls_config.get("passthrough", False):
                    logger.debug(
                        f"Skipping TLS generation for {protocol} router {router_name} (passthrough True)."
                    )
                    continue

                entrypoint = entrypoints[0] if entrypoints else None
                if protocol == "http" and entrypoint == "web":
                    entrypoint = None  # Ignore "web" entrypoint for HTTP

                if not all([router_name, route_rule, service_name]):
                    logger.debug(
                        f"Not enough information to generate a TLS config for {protocol} router {router_name}!"
                    )
                    continue

                config[protocol]["routers"].update(
                    self.traefik.generate_tls_config_for_route(
                        router_name,
                        route_rule,
                        service_name,
                        self.external_host,
                        entrypoint,
                    )
                )

        if "http" in config:
            _process_routes(config["http"].get("routers", {}), protocol="http")

        if "tcp" in config:
            _process_routes(config["tcp"].get("routers", {}), protocol="tcp")

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

        config = config_getter(relation)
        self._push_configurations(relation, config)

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
        config = self.traefik.get_per_leader_http_config(
            prefix=prefix,
            scheme="http",  # IPL (aka ingress v1) has no https option
            port=data["port"],
            host=data["host"],
            redirect_https=data.get("redirect-https", False),
            strip_prefix=data.get("strip-prefix", False),
            external_host=self.external_host,
            forward_auth_app=self.forward_auth.is_protected_app(app=data.get("name")),
            forward_auth_config=self.forward_auth.get_provider_info(),
        )

        if self.unit.is_leader():
            ipa.publish_url(relation, self._get_external_url(prefix))

        return config

    def _get_configs_per_app(self, relation: Relation) -> Dict[str, Any]:
        # todo: IPA>=v2 uses pydantic models, the other providers use raw dicts.
        #  eventually switch all over to pydantic and handle this uniformly

        ipa = self.ingress_per_appv2
        if not relation.app:
            logger.error(f"no app on relation {relation}")
            return {}

        try:
            data = ipa.get_data(relation)
        except DataValidationError as e:
            logger.error(f"invalid data shared through {relation}... Error: {e}.")
            return {}

        prefix = self._get_prefix(
            data.app.dict(by_alias=True) if PYDANTIC_IS_V1 else data.app.model_dump(by_alias=True)
        )
        config = self.traefik.get_per_app_http_config(
            prefix=prefix,
            scheme=data.app.scheme,
            redirect_https=data.app.redirect_https,
            strip_prefix=data.app.strip_prefix,
            port=data.app.port,
            external_host=self.external_host,
            hosts=[udata.host for udata in data.units],
            forward_auth_app=self.forward_auth.is_protected_app(app=data.app.name),
            forward_auth_config=self.forward_auth.get_provider_info(),
        )

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
                unit_config = self.traefik.generate_per_unit_tcp_config(
                    prefix, data["host"], data["port"]
                )
                if self.unit.is_leader():
                    host = self.external_host
                    ipu.publish_url(relation, data["name"], f"{host}:{data['port']}")
            else:  # "http"
                unit_config = self.traefik.get_per_unit_http_config(
                    prefix=prefix,
                    host=data["host"],
                    port=data["port"],
                    scheme=data.get("scheme"),
                    strip_prefix=data.get("strip-prefix"),
                    redirect_https=data.get("redirect-https"),
                    external_host=self.external_host,
                    forward_auth_app=self.forward_auth.is_protected_app(app=data.get("name")),
                    forward_auth_config=self.forward_auth.get_provider_info(),
                )

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
            self.traefik.add_dynamic_config(self._relation_config_file(relation), yaml_config)
        else:
            self._wipe_ingress_for_relation(relation)

    @staticmethod
    def _get_prefix(data: Dict[str, Any]):
        name = data["name"].replace("/", "-")
        return f"{data['model']}-{name}"

    @property
    def _scheme(self):
        return "https" if self._is_tls_enabled() else "http"

    def _get_external_url(self, prefix):
        if self._routing_mode is RoutingMode.path:
            url = f"{self._scheme}://{self.external_host}/{prefix}"
        else:  # traefik.RoutingMode.subdomain
            url = f"{self._scheme}://{prefix}.{self.external_host}/"
        return url

    def _wipe_ingress_for_all_relations(self):
        self.unit.status = MaintenanceStatus("resetting all ingress relations")
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
            name = self._relation_config_file(relation)
            try:
                self.traefik.delete_dynamic_config(name)
                logger.debug(f"Deleted {name} ingress configuration file")
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

    def _restart_traefik(self):
        self.unit.status = MaintenanceStatus("restarting traefik...")
        self.traefik.restart()

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

    def _recv_ca_cert_requirer_from_relation(self, relation: Relation):
        """Returns the correct CertificateTransferRequirer based on a relation."""
        if self.recv_ca_cert_v0.is_ready(relation):
            return self.recv_ca_cert_v0
        if self.recv_ca_cert_v1.is_ready(relation):
            return self.recv_ca_cert_v1
        return None

    @property
    def _external_host(self) -> Optional[str]:
        """Determine the external address for the ingress gateway.

        It will prefer the `external-hostname` config if that is set, otherwise
        it will look up the load balancer address for the ingress gateway.

        If the gateway isn't available or doesn't have a load balancer address yet,
        returns None. Only use this directly when external_host is allowed to be None.
        """
        if external_hostname := self.model.config.get("external_hostname"):
            return cast(str, external_hostname)

        return self._get_loadbalancer_status

    @property
    def external_host(self) -> str:
        """The external address for the ingress gateway.

        If the gateway isn't available or doesn't have a load balancer address yet, it will
        raise an exception.

        To prevent that from happening, ensure this is only accessed behind an is_ready guard.
        """
        host = self._external_host
        if host is None or not isinstance(host, str):
            raise ExternalHostNotReadyError()
        return host

    @property
    def _routing_mode(self) -> RoutingMode:
        """Return the current routing mode for the ingress.

        The two modes are 'subdomain' and 'path', where 'path' is the default.
        """
        return RoutingMode(self.config["routing_mode"])

    @property
    def version(self) -> Optional[str]:
        """Return the workload version."""
        if not self.container.can_connect():
            return None
        return self.traefik.version

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
        # unsafe: it's allowed to be None in this case, CertHandler will take it
        target = self._external_host

        if is_hostname(target):
            assert isinstance(target, str), target  # for type checker
            return [target]

        # This is an IP address. Try to look up the hostname.
        with contextlib.suppress(OSError, TypeError):
            name, _, _ = socket.gethostbyaddr(target)  # type: ignore
            # Do not return "hostname" like '10-43-8-149.kubernetes.default.svc.cluster.local'
            if is_hostname(name) and not name.endswith(".svc.cluster.local"):
                return [name]

        # If all else fails, we'd rather use the bare IP
        return [target] if target else []

    def _validate_config(self):
        """Validate the charm configuration, emitting warning messages on misconfigurations.

        In scope for this validation is:
        * validating the combination of external_hostname and routing_mode
        """
        # FIXME: This will false positive in cases where the LoadBalancer provides an external host rather than an IP.
        #  The warning will occur, but the charm will function normally.  We could better validate the LoadBalancer if
        #  we want to avoid this, but it probably isn't worth the effort until someone notices.
        invalid_hostname_and_routing_mode_message = (
            "Likely configuration error: When using routing_mode=='subdomain', external_hostname should be "
            "set.  This is because when external_hostname is unset, Traefik uses the LoadBalancer's address as the "
            "hostname for all provided URLS and that hostname is typically an IP address.  This leads to invalid urls "
            "like `model-app.1.2.3.4`.  The charm will continue to operate as currently set, but will not provide urls"
            " to any related applications if they would be invalid."
        )

        if self.config.get("routing_mode", "") == "subdomain":
            # subdomain mode can only be used if an external_hostname is set and is not an IP address
            external_hostname = self.config.get("external_hostname", "")
            if not isinstance(external_hostname, str) or not is_valid_hostname(external_hostname):
                logger.warning(invalid_hostname_and_routing_mode_message)


def is_valid_hostname(hostname: str) -> bool:
    """Check if a hostname is valid.

    Modified from https://stackoverflow.com/a/33214423
    """
    if len(hostname) == 0:
        return False
    if hostname[-1] == ".":
        # strip exactly one dot from the right, if present
        hostname = hostname[:-1]
    if len(hostname) > 253:
        return False

    labels = hostname.split(".")

    # the TLD must be not all-numeric
    if re.match(r"[0-9]+$", labels[-1]):
        return False

    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(label) for label in labels)


def validate_annotation_key(key: str) -> bool:
    """Validate the annotation key."""
    if len(key) > 253:
        logger.error(f"Invalid annotation key: '{key}'. Key length exceeds 253 characters.")
        return False

    if not is_qualified_name(key.lower()):
        logger.error(f"Invalid annotation key: '{key}'. Must follow Kubernetes annotation syntax.")
        return False

    if key.startswith(("kubernetes.io/", "k8s.io/")):
        logger.error(f"Invalid annotation: Key '{key}' uses a reserved prefix.")
        return False

    return True


def validate_annotation_value(value: str) -> bool:
    """Validate the annotation value."""
    if not ANNOTATION_VALUE_PATTERN.match(value):
        logger.error(
            f"Invalid annotation value: '{value}'. Must follow Kubernetes annotation syntax."
        )
        return False

    return True


def parse_annotations(annotations: Optional[str]) -> Optional[Dict[str, str]]:
    """Parse and validate annotations from a string.

    logic is based on Kubernetes annotation validation as described here:
    https://github.com/kubernetes/apimachinery/blob/v0.31.3/pkg/api/validation/objectmeta.go#L44
    """
    if not annotations:
        return {}

    annotations = annotations.strip().rstrip(",")  # Trim spaces and trailing commas

    try:
        parsed_annotations = {
            key.strip(): value.strip()
            for key, value in (pair.split("=", 1) for pair in annotations.split(",") if pair)
        }
    except ValueError:
        logger.error(
            "Invalid format for 'loadbalancer_annotations'. "
            "Expected format: key1=value1,key2=value2."
        )
        return None

    # Validate each key-value pair
    for key, value in parsed_annotations.items():
        if not validate_annotation_key(key) or not validate_annotation_value(value):
            return None

    return parsed_annotations


def is_qualified_name(value: str) -> bool:
    """Check if a value is a valid Kubernetes qualified name."""
    parts = value.split("/")
    if len(parts) > 2:
        return False  # Invalid if more than one '/'

    if len(parts) == 2:  # If prefixed
        prefix, name = parts
        if not prefix or not DNS1123_SUBDOMAIN_PATTERN.match(prefix):
            return False
    else:
        name = parts[0]  # No prefix

    if not name or len(name) > 63 or not QUALIFIED_NAME_PATTERN.match(name):
        return False

    return True


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
