#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Traefik workload interface."""
import dataclasses
import enum
import logging
import os
import re
import socket
from copy import deepcopy
from pathlib import Path
from string import Template
from typing import Any, Dict, Iterable, List, Optional, Union, cast

import yaml
from charms.oathkeeper.v0.forward_auth import ForwardAuthConfig
from cosl import JujuTopology
from ops import Container
from ops.pebble import LayerDict, PathError

from utils import is_hostname

logger = logging.getLogger(__name__)
DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"
STATIC_CONFIG_DIR = "/etc/traefik"
STATIC_CONFIG_PATH = f"{STATIC_CONFIG_DIR}/traefik.yaml"
DYNAMIC_CERTS_PATH = f"{DYNAMIC_CONFIG_DIR}/certificates.yaml"
DYNAMIC_TRACING_PATH = f"{DYNAMIC_CONFIG_DIR}/tracing.yaml"
SERVER_CERT_PATH = f"{DYNAMIC_CONFIG_DIR}/server.cert"
SERVER_KEY_PATH = f"{DYNAMIC_CONFIG_DIR}/server.key"
CERTS_DIR = Path(DYNAMIC_CONFIG_DIR)
CA_CERTS_DIR = Path("/usr/local/share/ca-certificates")
RECV_CA_TEMPLATE = Template(f"{str(CA_CERTS_DIR)}/receive-ca-cert-$rel_id-ca.crt")
BIN_PATH = "/usr/bin/traefik"
LOG_PATH = "/var/log/traefik.log"

_DIAGNOSTICS_PORT = 8082  # Prometheus metrics, healthcheck/ping


@dataclasses.dataclass
class CA:
    """Represents a Certificate Authority."""

    ca: str
    uid: Union[int, str]

    @property
    def path(self) -> str:
        """Predictable file path at which this CA will be stored on-disk in traefik."""
        return RECV_CA_TEMPLATE.substitute(rel_id=str(self.uid))


class RoutingMode(enum.Enum):
    """Routing mode."""

    path = "path"
    subdomain = "subdomain"


class TraefikError(Exception):
    """Base class for errors raised by this module."""


class ContainerNotReadyError(TraefikError):
    """Raised if the caller incorrectly assumes that the traefik container is ready."""


class StaticConfigMergeConflictError(TraefikError):
    """Raised when static configs coming from different sources can't be merged."""


def static_config_deep_merge(dict1: dict, dict2: dict, _path=None):
    """In-place deep merge dict2 into dict1."""
    _path = _path or []

    for key, val in dict2.items():
        if key in dict1:
            val1 = dict1[key]
            if isinstance(val, dict) and isinstance(val1, dict):
                static_config_deep_merge(val1, val, _path + [str(key)])
            elif val != val1:
                raise StaticConfigMergeConflictError(f"Conflict at path {'.'.join(_path)}")
        else:
            dict1[key] = val
    return dict1


class Traefik:
    """Traefik workload representation."""

    port = 80
    tls_port = 443

    _layer_name = "traefik"
    service_name = "traefik"
    _tracing_endpoint = None

    def __init__(
        self,
        *,
        container: Container,
        routing_mode: RoutingMode,
        tls_enabled: bool,
        experimental_forward_auth_enabled: bool,
        tcp_entrypoints: Dict[str, int],
        traefik_route_static_configs: Iterable[Dict[str, Any]],
        topology: JujuTopology,
        basic_auth_user: Optional[str] = None,
        tracing_endpoint: Optional[str] = None,
    ):
        self._container = container
        self._tcp_entrypoints = tcp_entrypoints
        self._traefik_route_static_configs = traefik_route_static_configs
        self._routing_mode = routing_mode
        self._tls_enabled = tls_enabled
        self._experimental_forward_auth_enabled = experimental_forward_auth_enabled
        self._topology = topology
        self._basic_auth_user = basic_auth_user
        self._tracing_endpoint = tracing_endpoint

    @property
    def scrape_jobs(self) -> list:
        """List of static configs for prometheus scrape."""
        return [
            {
                "static_configs": [{"targets": [f"{socket.getfqdn()}:{_DIAGNOSTICS_PORT}"]}],
            }
        ]

    def _update_tls_configuration(self):
        """Generate and push tls config yaml for traefik."""
        cert_files = [
            x.path for x in self._container.list_files(CERTS_DIR) if x.path.endswith(".cert")
        ]
        config = yaml.safe_dump(
            {
                "tls": {
                    "certificates": [
                        {
                            "certFile": cert_file,
                            "keyFile": f"{os.path.splitext(cert_file)[0]}.key",
                        }
                        for cert_file in cert_files
                    ],
                    "stores": {
                        "default": {
                            # When the external hostname is a bare IP, traefik cannot match a domain,
                            # so we must set the default cert for the TLS handshake to succeed.
                            "defaultCertificate": (
                                {
                                    "certFile": cert_files[0],
                                    "keyFile": f"{os.path.splitext(cert_files[0])[0]}.key",
                                }
                                if len(cert_files) == 1
                                else None
                            )
                        },
                    },
                }
            }
        )
        self._container.push(DYNAMIC_CERTS_PATH, config, make_dirs=True)

    def configure(self):
        """Configure static and tls."""
        # Ensure the required basic configurations and folders exist
        static_config = self.generate_static_config()
        self.push_static_config(static_config)

        self._setup_dynamic_config_folder()

        if self._tls_enabled:
            self._update_tls_configuration()

    def update_cert_configuration(self, certs: dict):
        """Update the server cert, ca, and key configuration files."""
        # Remove certs that are no longer needed.
        if certs:
            CERTS_DIR.mkdir(parents=True, exist_ok=True)
        if CERTS_DIR.is_dir():
            for path in CERTS_DIR.iterdir():
                if path.name.endswith(".cert") and path.name[:5] not in certs:
                    path.unlink()
        if self._container.isdir(CERTS_DIR):
            for path in self._container.list_files(CERTS_DIR):
                if path.name.endswith(".cert") and path.name[:5] not in certs:
                    self._container.remove_path(path.path)
                if path.name.endswith(".key") and path.name[:4] not in certs:
                    self._container.remove_path(path.path)
        if self._container.isdir(CA_CERTS_DIR):
            for path in self._container.list_files(CA_CERTS_DIR):
                # There could be other .crt files here so make sure the names are identifiable.
                if path.name.endswith(".traefik-charm.crt") and path.name[:18] not in certs:
                    self._container.remove_path(path.path)
        for hostname, cert in certs.items():
            with (CERTS_DIR / f"{hostname}.cert").open("w") as f:
                f.write(cert["cert"])
            self._container.push(CERTS_DIR / f"{hostname}.cert", cert["cert"], make_dirs=True)
            self._container.push(CERTS_DIR / f"{hostname}.key", cert["key"], make_dirs=True)
            self._container.push(
                CA_CERTS_DIR / f"{hostname}.traefik-charm.crt", cert["ca"], make_dirs=True
            )

        self.update_ca_certs()

    def add_cas(self, cas: Iterable[CA]):
        """Add any number of CAs to Traefik.

        Calls update-ca-certificates once done.
        """
        for ca in cas:
            self._add_ca(ca)
        self.update_ca_certs()

    def _add_ca(self, ca: CA):
        """Add a ca.

        After doing this (any number of times), the caller is responsible for invoking update-ca-certs.
        """
        self._container.push(ca.path, ca.ca, make_dirs=True)

    def remove_cas(self, uids: Iterable[Union[str, int]]):
        """Remove all CAs with these UIDs.

        BEWARE of potential race conditions.
        Traefik watches the dynamic config dir and reloads automatically on change.
        So make sure any traefik config depending on the certificates being there is updated
        **before** the certs are removed, otherwise you might have some downtime.

        Calls update-ca-certificates once done.
        """
        for uid in uids:
            ca_path = RECV_CA_TEMPLATE.substitute(rel_id=str(uid))
            self._container.remove_path(ca_path)
        self.update_ca_certs()

    def update_ca_certs(self):
        """Update ca certificates and restart traefik."""
        self._container.exec(["update-ca-certificates", "--fresh"]).wait()

        # Must restart traefik after refreshing certs, otherwise:
        # - newly added certs will not be loaded and traefik will keep erroring-out with "signed by
        #   unknown authority".
        # - old certs will be kept active.
        self.restart()

    def generate_static_config(self, _raise: bool = False) -> Dict[str, Any]:
        """Generate Traefik's static config yaml."""
        tcp_entrypoints = self._tcp_entrypoints
        logger.debug(f"Statically configuring traefik with tcp entrypoints: {tcp_entrypoints}.")

        web_config: Dict[str, Any] = {
            "address": f":{self.port}",
        }

        if self._tls_enabled:
            # enable http -> https redirect
            web_config["http"] = {
                "redirections": {"entryPoint": {"to": "websecure", "scheme": "https"}},
            }

        static_config = {
            "global": {
                "checknewversion": False,
                # TODO add juju config to disable anonymous usage
                # https://github.com/canonical/observability/blob/main/decision-records/2026-06-27--upstream-telemetry.md
                "sendanonymoususage": True,
            },
            "log": {
                "level": "DEBUG",
            },
            "entryPoints": {
                "diagnostics": {"address": f":{_DIAGNOSTICS_PORT}"},
                "web": web_config,
                "websecure": {"address": f":{self.tls_port}"},
                **{
                    tcp_entrypoint_name: {"address": f":{port}"}
                    for tcp_entrypoint_name, port in tcp_entrypoints.items()
                },
            },
            # We always start the Prometheus endpoint for simplicity
            # TODO: Generate this file in the dynamic configuration folder when the
            #  metrics-endpoint relation is established?
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
                    "directory": DYNAMIC_CONFIG_DIR,
                    "watch": True,
                }
            },
        }

        if self._tracing_endpoint:
            # ref: https://github.com/traefik/traefik/blob/v2.11/docs/content/observability/tracing/jaeger.md
            # TODO once we bump to Traefik v3, Jaeger needs to be replaced with otlp and config needs to be updated
            # see https://doc.traefik.io/traefik/observability/tracing/opentelemetry/ for more reference
            static_config["tracing"] = {
                "jaeger": {
                    "collector": {
                        "endpoint": f"{self._tracing_endpoint}/api/traces?format=jaeger.thrift"
                    },
                }
            }

        # we attempt to put together the base config with whatever the user passed via traefik_route.
        # in case there are conflicts between the base config and some route, or between the routes themselves,
        # we'll be forced to bail out.
        extra_configs = list(self._traefik_route_static_configs)

        for extra_config in extra_configs:
            # static_config_deep_merge does things in-place, so we deepcopy the base config in case things go wrong
            previous = deepcopy(static_config)
            try:
                static_config_deep_merge(static_config, extra_config)
            except StaticConfigMergeConflictError as e:
                if _raise:
                    raise e
                logger.exception(
                    f"Failed to merge {extra_config} into Traefik's static config." "Skipping..."
                )
                # roll back any changes static_config_deep_merge might have done to static_config
                static_config = previous
                continue

        return static_config

    def push_static_config(self, config: Dict[str, Any]):
        """Push static config yaml to the container."""
        config_yaml = yaml.safe_dump(config)
        # TODO Use the Traefik user and group?
        self._container.push(STATIC_CONFIG_PATH, config_yaml, make_dirs=True)

    def get_per_unit_http_config(
        self,
        *,
        prefix: str,
        host: str,
        port: int,
        scheme: Optional[str],
        strip_prefix: Optional[bool],
        redirect_https: Optional[bool],
        external_host: str,
        forward_auth_app: bool,
        forward_auth_config: Optional[ForwardAuthConfig],
    ) -> dict:
        """Generate a config dict for IngressPerUnit."""
        lb_servers = [{"url": f"{scheme or 'http'}://{host}:{port}"}]
        return self._generate_config_block(
            prefix=prefix,
            lb_servers=lb_servers,
            scheme=scheme,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
            external_host=external_host,
            forward_auth_app=forward_auth_app,
            forward_auth_config=forward_auth_config,
        )

    def get_per_app_http_config(
        self,
        *,
        prefix: str,
        scheme: Optional[str],
        hosts: List[str],
        port: int,
        strip_prefix: Optional[bool],
        redirect_https: Optional[bool],
        external_host: str,
        forward_auth_app: bool,
        forward_auth_config: Optional[ForwardAuthConfig],
        healthcheck_params: Optional[Dict[str, Any]],
    ) -> dict:
        """Generate a config dict for Ingress(PerApp)."""
        # purge potential Nones
        scheme = scheme or "http"
        lb_servers = [{"url": f"{scheme or 'http'}://{host}:{port}"} for host in hosts]
        return self._generate_config_block(
            prefix=prefix,
            lb_servers=lb_servers,
            scheme=scheme,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
            external_host=external_host,
            forward_auth_app=forward_auth_app,
            forward_auth_config=forward_auth_config,
            healthcheck_params=healthcheck_params,
        )

    def get_per_leader_http_config(
        self,
        *,
        prefix: str,
        scheme: str,
        host: str,
        port: int,
        strip_prefix: bool,
        redirect_https: bool,
        external_host: str,
        forward_auth_app: bool,
        forward_auth_config: Optional[ForwardAuthConfig],
    ) -> dict:
        """Generate a config dict for Ingress v1 (PerLeader)."""
        lb_servers = [{"url": f"http://{host}:{port}"}]
        return self._generate_config_block(
            prefix=prefix,
            lb_servers=lb_servers,
            scheme=scheme,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
            external_host=external_host,
            forward_auth_app=forward_auth_app,
            forward_auth_config=forward_auth_config,
        )

    def _generate_config_block(
        self,
        prefix: str,
        lb_servers: List[Dict[str, str]],
        scheme: Optional[str],
        redirect_https: Optional[bool],
        strip_prefix: Optional[bool],
        external_host: str,
        forward_auth_app: bool,
        forward_auth_config: Optional[ForwardAuthConfig],
        healthcheck_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a configuration segment.

        Per-unit and per-app configuration blocks are mostly similar, with the principal
        difference being the list of servers to load balance across (where IPU is one server per
        unit and IPA may be more than one).
        """
        # purge any optionals:
        scheme_: str = scheme if scheme is not None else "http"
        redirect_https_: bool = redirect_https if redirect_https is not None else False
        strip_prefix_: bool = strip_prefix if strip_prefix is not None else False

        host = external_host
        if self._routing_mode is RoutingMode.path:
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
            self.generate_tls_config_for_route(
                traefik_router_name, route_rule, traefik_service_name, external_host=external_host
            )
        )

        # Add the "rootsCAs" section only if TLS is enabled. If the rootCA section
        # is empty or the file does not exist, HTTP requests will fail with
        # "404 page not found".
        # Note: we're assuming here that the CA that signed traefik's own CSR is
        # the same CA that signed the service's servers CSRs.
        external_tls = self._tls_enabled

        # REVERSE TERMINATION: we are providing ingress for a unit who is itself behind https,
        # but traefik is not.
        internal_tls = scheme_ == "https"

        is_reverse_termination = not external_tls and internal_tls
        is_termination = external_tls and not internal_tls
        is_end_to_end = external_tls and internal_tls

        lb_def: Dict[str, Any] = {"servers": lb_servers}
        service_def = {
            "loadBalancer": lb_def,
        }
        if healthcheck_params:
            service_def["loadBalancer"]["healthCheck"] = healthcheck_params

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

        middlewares = self._generate_middleware_config(
            redirect_https=redirect_https_,
            strip_prefix=strip_prefix_,
            scheme=scheme_,
            prefix=prefix,
            forward_auth_app=forward_auth_app,
            forward_auth_config=forward_auth_config,
        )

        if middlewares:
            config["http"]["middlewares"] = middlewares
            router_cfg[traefik_router_name]["middlewares"] = list(middlewares.keys())

            if f"{traefik_router_name}-tls" in router_cfg:
                router_cfg[f"{traefik_router_name}-tls"]["middlewares"] = list(middlewares.keys())

        return config

    def _generate_middleware_config(
        self,
        redirect_https: bool,
        strip_prefix: bool,
        scheme: str,
        prefix: str,
        forward_auth_app: bool,
        forward_auth_config: Optional[ForwardAuthConfig],
    ) -> dict:
        """Generate a middleware config.

        We need to generate a different section per middleware type, otherwise traefik complains:
          "cannot create middleware: multi-types middleware not supported, consider declaring two
          different pieces of middleware instead"
        """
        basicauth_middleware = {}
        if basicauth_user := self._basic_auth_user:
            basicauth_middleware[f"juju-basic-auth-{prefix}"] = {
                "basicAuth": {
                    "users": [basicauth_user],
                }
            }

        forwardauth_middleware = {}
        if self._experimental_forward_auth_enabled:
            if forward_auth_app:
                forwardauth_middleware[f"juju-sidecar-forward-auth-{prefix}"] = {
                    "forwardAuth": {
                        "address": forward_auth_config.decisions_address,  # type: ignore
                        "authResponseHeaders": forward_auth_config.headers,  # type: ignore
                    }
                }

        no_prefix_middleware = {}  # type: Dict[str, Dict[str, Any]]
        if self._routing_mode is RoutingMode.path and strip_prefix:
            no_prefix_middleware[f"juju-sidecar-noprefix-{prefix}"] = {
                "stripPrefix": {"prefixes": [f"/{prefix}"], "forceSlash": False}
            }

        # Condition rendering the https-redirect middleware on the scheme, otherwise we'd get a 404
        # when attempting to reach an http endpoint.
        redir_scheme_middleware = {}
        if redirect_https and scheme == "https":
            redir_scheme_middleware[f"juju-sidecar-redir-https-{prefix}"] = {
                "redirectScheme": {"scheme": "https", "port": 443, "permanent": True}
            }

        return {
            **forwardauth_middleware,
            **no_prefix_middleware,
            **redir_scheme_middleware,
            **basicauth_middleware,
        }

    @staticmethod
    def generate_tls_config_for_route(
        router_name: str,
        route_rule: str,
        service_name: str,
        external_host: str,
        entrypoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a TLS configuration segment."""
        if is_hostname(external_host):
            tls_entry = {
                "domains": [
                    {
                        "main": external_host,
                        "sans": [f"*.{external_host}"],
                    },
                ],
            }

        else:
            # When the external host is a bare IP, we do not need the 'domains' entry.
            tls_entry = {}

        return {
            f"{router_name}-tls": {
                "rule": route_rule,
                "service": service_name,
                "entryPoints": [entrypoint if entrypoint else "websecure"],
                "tls": tls_entry,
            }
        }

    def pull_static_config(self) -> Dict[str, Any]:
        """Pull the currently configured tcp entrypoints from the static config."""
        try:
            static_config_raw = self._container.pull(STATIC_CONFIG_PATH).read()
        except PathError as e:
            logger.error(f"Could not fetch static config from container; {e}")
            return {}

        return yaml.safe_load(static_config_raw)

    @property
    def is_ready(self):
        """Whether the traefik service is running."""
        if not self._container.can_connect():
            return False
        return bool(self._container.get_services(self.service_name))

    def restart(self):
        """Restart the pebble service."""
        environment = {}
        if self._tracing_endpoint:
            environment = {
                "JAEGER_TAGS": f"juju_application={self._topology.application},juju_model={self._topology.model},juju_model_uuid={self._topology.model_uuid},juju_unit={self._topology.unit},juju_charm={self._topology.charm_name}"
            }

        layer = {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "Traefik",
                    # trick to drop the logs to a file but also keep them available in the pod logs
                    "command": '/bin/sh -c "{} | tee {}"'.format(BIN_PATH, LOG_PATH),
                    "startup": "enabled",
                    "environment": environment,
                },
            },
        }

        self._container.add_layer(self._layer_name, cast(LayerDict, layer), combine=True)
        logger.debug(f"replanning {self.service_name!r} after a service update")
        self._container.replan()

        if self.is_ready:
            logger.debug(f"restarting {self.service_name!r}")
            self._container.restart(self.service_name)

    def delete_dynamic_configs(self):
        """Delete **ALL** yamls from the dynamic config dir."""
        # instead of multiple calls to self._container.remove_path(), delete all files in a swoop
        self._container.exec(["find", DYNAMIC_CONFIG_DIR, "-name", "*.yaml", "-delete"])
        logger.debug("Deleted all dynamic configuration files.")

    def delete_dynamic_config(self, file_name: str):
        """Delete a specific yaml from the dynamic config dir."""
        self._container.remove_path(Path(DYNAMIC_CONFIG_DIR) / file_name)
        logger.debug("Deleted dynamic configuration file: %s", file_name)

    def add_dynamic_config(self, file_name: str, config: str):
        """Push a yaml to the dynamic config dir.

        The dynamic config dir is assumed to exist already.
        """
        # make_dirs is technically not necessary at runtime, since traefik.configure() should
        # guarantee that the dynamic config dir exists. However, it simplifies testing as it means
        # we don't have to worry about setting up manually the traefik container every time we
        # simulate an event.
        self._container.push(Path(DYNAMIC_CONFIG_DIR) / file_name, config, make_dirs=True)

        logger.debug("Updated dynamic configuration file: %s", file_name)

    @property
    def version(self):
        """Traefik workload version."""
        version_output, _ = self._container.exec([BIN_PATH, "version"]).wait_output()
        # Output looks like this:
        # Version:      v2.11.0
        # Codename:     mimolette
        # Go version:   go1.22.1
        # Built:        2024-03-14_05:12:45PM
        # OS/Arch:      linux/amd64

        if result := re.search(r"Version:\s*v?(.+)", version_output):
            return result.group(1)
        return None

    @staticmethod
    def generate_per_unit_tcp_config(prefix: str, host: str, port: int) -> dict:
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
                        "loadBalancer": {"servers": [{"address": f"{host}:{port}"}]}
                    },
                },
            }
        }
        return config

    def _setup_dynamic_config_folder(self):
        # ensure the dynamic config dir exists else traefik will error on startup and fail to
        # set up the watcher
        self._container.make_dir(DYNAMIC_CONFIG_DIR, make_parents=True)
