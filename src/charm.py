#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed traefik operator."""
import contextlib
import enum
import functools
import itertools
import json
import logging
import socket
from typing import Any, Dict, List, Optional, Tuple, Union
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
from charms.oathkeeper.v0.forward_auth import (
    AuthConfigChangedEvent,
    AuthConfigRemovedEvent,
    ForwardAuthRequirer,
    ForwardAuthRequirerConfig,
)
from charms.observability_libs.v1.cert_handler import CertHandler
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_k8s.v1.charm_tracing import trace_charm
from charms.tempo_k8s.v2.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v1.ingress import IngressPerAppProvider as IPAv1
from charms.traefik_k8s.v1.ingress_per_unit import DataValidationError, IngressPerUnitProvider
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider as IPAv2
from charms.traefik_route_k8s.v0.traefik_route import (
    TraefikRouteProvider,
    TraefikRouteRequirerReadyEvent,
)
from deepmerge import always_merger
from lightkube.core.client import Client
from lightkube.models.core_v1 import ServicePort
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
    ModelError,
    Relation,
    WaitingStatus,
)
from ops.pebble import PathError
from traefik import (
    CA,
    LOG_PATH,
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
        KubernetesServicePatch,
    ),
)
class TraefikIngressCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(
            current_external_host=None,
            current_routing_mode=None,
            current_forward_auth_mode=self.config["enable_experimental_forward_auth"],
        )

        self.container = self.unit.get_container(_TRAEFIK_CONTAINER_NAME)

        sans = self.server_cert_sans_dns
        self.cert = CertHandler(
            self,
            key="trfk-server-cert",
            # Route53 complains if CN is not a hostname
            cert_subject=sans[0] if sans else None,
            sans=sans,
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
            charm=self, external_host=self._external_host, scheme=self._scheme  # type: ignore
        )

        self.traefik = Traefik(
            container=self.container,
            routing_mode=self._routing_mode,
            tcp_entrypoints=self._tcp_entrypoints(),
            tls_enabled=self._is_tls_enabled(),
            experimental_forward_auth_enabled=self._is_forward_auth_enabled,
            traefik_route_static_configs=self._traefik_route_static_configs(),
        )

        self.service_patch = KubernetesServicePatch(
            charm=self,
            service_type="LoadBalancer",
            ports=self._service_ports,
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
        self._tracing = TracingEndpointRequirer(self, protocols=["otlp_http"])

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
        self._logging = LogProxyConsumer(self, relation_name="logging", log_files=[LOG_PATH])
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
        cas = []
        if event:
            cas.append(CA(event.ca, uid=event.relation_id))
        else:
            for relation in self.model.relations.get(self.recv_ca_cert.relationship_name, []):
                # For some reason, relation.units includes our unit and app. Need to exclude them.
                for unit in set(relation.units).difference([self.app, self.unit]):
                    # Note: this nested loop handles the case of multi-unit CA, each unit providing
                    # a different ca cert, but that is not currently supported by the lib itself.
                    if ca := relation.data[unit].get("ca"):
                        cas.append(CA(ca, uid=relation.id))

        self.traefik.add_cas(cas)

    def _on_recv_ca_cert_removed(self, event: CertificateTransferRemovedEvent):
        # Assuming only one cert per relation (this is in line with the original lib design).
        self.traefik.remove_cas([event.relation_id])

    @property
    def charm_tracing_endpoint(self) -> Optional[str]:
        """Otlp http endpoint for charm instrumentation."""
        if self._tracing.is_ready():
            return self._tracing.get_endpoint("otlp_http")
        return None

    @property
    def server_cert(self) -> Optional[str]:
        """Server certificate path for tls tracing."""
        if self._is_tls_enabled():
            return SERVER_CERT_PATH
        return None

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
        self.traefik.delete_tracing_config()

    def _on_tracing_endpoint_changed(self, event) -> None:
        # On slow machines, this event may come up before pebble is ready
        if not self.container.can_connect():
            event.defer()
            return

        if not self._tracing.is_ready():
            self.traefik.delete_tracing_config()

        self._configure_tracing()

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
            return self.config["tls-cert"], self.config["tls-key"], self.config["tls-ca"]
        return cert_handler.chain, cert_handler.private_key, cert_handler.ca_cert

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
                    entrypoints[entrypoint_name] = data["port"]

        return entrypoints

    def _configure_traefik(self):
        self.traefik.configure()
        self._configure_tracing()

    def _configure_tracing(self):
        # wokeignore:rule=master
        # ref: https://doc.traefik.io/traefik/master/observability/tracing/opentelemetry/
        if not self._is_tracing_enabled():
            logger.info("tracing not enabled: skipping tracing config")
            return

        if endpoint := self._tracing.otlp_http_endpoint():
            grpc = False
        else:
            logger.error(
                "tracing integration is active but none of the "
                "protocols traefik supports is available."
            )
            return

        self.traefik.update_tracing_configuration(endpoint, grpc=grpc)

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

    def _on_update_status(self, _: UpdateStatusEvent):
        self._process_status_and_configurations()
        self._set_workload_version()

    def _on_config_changed(self, _: ConfigChangedEvent):
        # If the external hostname is changed since we last processed it, we need to
        # reconsider all data sent over the relations and all configs
        new_external_host = self._external_host
        new_routing_mode = self.config["routing_mode"]
        new_forward_auth_mode = self._is_forward_auth_enabled

        # TODO set BlockedStatus here when compound_status is introduced
        #  https://github.com/canonical/operator/issues/665

        if (
            self._stored.current_external_host != new_external_host  # type: ignore
            or self._stored.current_routing_mode != new_routing_mode  # type: ignore
            or self._stored.current_forward_auth_mode != new_forward_auth_mode  # type: ignore
        ):
            self._process_status_and_configurations()
            self._stored.current_external_host = new_external_host  # type: ignore
            self._stored.current_routing_mode = new_routing_mode  # type: ignore
            self._stored.current_forward_auth_mode = new_forward_auth_mode  # type: ignore

        if self._is_tls_enabled():
            self._update_cert_configs()
            self._configure_traefik()
            self._process_status_and_configurations()

    def _process_status_and_configurations(self):
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
            self.unit.status = WaitingStatus("gateway address unavailable")
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
            self.unit.status = ActiveStatus()

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
            self.unit.status = WaitingStatus("gateway address unavailable")
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
        try:
            self._process_ingress_relation(event.relation)
        except IngressSetupError as e:
            # this can happen if the remote unit is being removed.
            err_msg = e.args[0]
            logger.error(
                f"failed processing the ingress relation {event.relation}: {err_msg!r}. "
                f"If the remote unit is being removed, this could be normal."
            )
            return

        # Without the following line, traefik.STATIC_CONFIG_PATH is updated with TCP endpoints only on
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
        #  traefik.STATIC_CONFIG_PATH will be updated only on update-status.
        #  https://github.com/canonical/operator/issues/888

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

        self.unit.status = ActiveStatus()

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
        logger.warning(f"provider: {provider}")

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
        if "http" in config.keys():
            route_config = config["http"].get("routers", {})
            router_name = next(iter(route_config.keys()))
            route_rule = route_config.get(router_name, {}).get("rule", "")
            service_name = route_config.get(router_name, {}).get("service", "")

            if not all([router_name, route_rule, service_name]):
                logger.debug("Not enough information to generate a TLS config!")
            else:
                config["http"]["routers"].update(
                    self.traefik.generate_tls_config_for_route(
                        router_name,
                        route_rule,
                        service_name,
                        # we're behind an is_ready guard, so this is guaranteed not to raise
                        self.external_host,
                    )
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

        prefix = self._get_prefix(data.app.dict(by_alias=True))
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
            try:
                provider.wipe_ingress_data(relation)  # type: ignore  # this is an ingress-type relation
            except ModelError as e:
                # if the relation is (being) deleted, sometimes we might get a:
                # ERROR cannot read relation application settings: permission denied (unauthorized access)
                logger.info(
                    f"error {e} wiping ingress data for {relation}; "
                    f"if this relation is dead or dying, this could be normal."
                )

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

    @property
    def _external_host(self) -> Optional[str]:
        """Determine the external address for the ingress gateway.

        It will prefer the `external-hostname` config if that is set, otherwise
        it will look up the load balancer address for the ingress gateway.

        If the gateway isn't available or doesn't have a load balancer address yet,
        returns None. Only use this directly when external_host is allowed to be None.
        """
        if external_hostname := self.model.config.get("external_hostname"):
            return external_hostname

        return _get_loadbalancer_status(namespace=self.model.name, service_name=self.app.name)

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


@functools.lru_cache
def _get_loadbalancer_status(namespace: str, service_name: str) -> Optional[str]:
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
