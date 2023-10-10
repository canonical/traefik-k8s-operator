#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Traefik workload interface."""
import contextlib
import enum
import logging
import re
import socket
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, cast

import yaml
from lightkube.models.core_v1 import ServicePort
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
CA_CERTS_PATH = "/usr/local/share/ca-certificates"
CA_CERT_PATH = f"{CA_CERTS_PATH}/traefik-ca.crt"
RECV_CA_TEMPLATE = Template(f"{CA_CERTS_PATH}/receive-ca-cert-$rel_id-ca.crt")
BIN_PATH = "/usr/bin/traefik"


class RoutingMode(enum.Enum):
    """Routing mode."""

    path = "path"
    subdomain = "subdomain"


class TraefikError(RuntimeError):
    """Base class for errors raised by this module."""


class ContainerNotReadyError(TraefikError):
    """Raised if the caller incorrectly assumes that the traefik container is ready."""


class Traefik:
    """Traefik workload representation."""

    diagnostics_port = 8082  # Prometheus metrics, healthcheck/ping
    _port = 80
    _tls_port = 443
    log_path = "/var/log/traefik.log"
    _layer_name = "traefik"

    def __init__(
        self,
        service_name: str,
        container: Container,
        routing_mode: RoutingMode,
        tls_enabled: bool,
        tcp_entrypoints: Dict[str, int],
    ):
        self._service_name = service_name
        self._container = container
        self._tcp_entrypoints = tcp_entrypoints
        self._routing_mode = routing_mode
        self._tls_enabled = tls_enabled

    @property
    def _hostname(self) -> str:
        return socket.getfqdn()

    @property
    def service_ports(self) -> List[ServicePort]:
        """Kubernetes service ports to be opened for this workload."""
        web = ServicePort(self._port, name=f"{self._service_name}")
        websecure = ServicePort(self._tls_port, name=f"{self._service_name}-tls")
        return [web, websecure] + [
            [ServicePort(int(port), name=name) for name, port in self._tcp_entrypoints.items()]
        ]

    @property
    def scrape_jobs(self) -> list:
        """List of static configs for prometheus scrape."""
        return [
            {
                "static_configs": [{"targets": [f"{self._hostname}:{self.diagnostics_port}"]}],
            }
        ]

    def _config_tls(self) -> str:
        """Generate tls config yaml for traefik."""
        config = yaml.safe_dump(
            {
                "tls": {
                    "certificates": [
                        {
                            "certFile": SERVER_CERT_PATH,
                            "keyFile": SERVER_KEY_PATH,
                        }
                    ],
                    "stores": {
                        "default": {
                            # When the external hostname is a bare IP, traefik cannot match a domain,
                            # so we must set the default cert for the TLS handshake to succeed.
                            "defaultCertificate": {
                                "certFile": SERVER_CERT_PATH,
                                "keyFile": SERVER_KEY_PATH,
                            },
                        },
                    },
                }
            }
        )
        self._container.push(DYNAMIC_CERTS_PATH, config, make_dirs=True)

    def configure(self):
        """Configure static and tls."""
        # Ensure the required basic configurations and folders exist
        tcp_entrypoints = self._tcp_entrypoints
        self._config_static(tcp_entrypoints)

        if self._tls_enabled:
            self._config_tls()

    def config_cert(self, cert: Optional[str], key: Optional[str], ca: Optional[str]):
        """Update the server cert, ca, and key configuration files."""
        if cert:
            self._container.push(SERVER_CERT_PATH, cert, make_dirs=True)
        else:
            self._container.remove_path(SERVER_CERT_PATH, recursive=True)

        if key:
            self._container.push(SERVER_KEY_PATH, key, make_dirs=True)
        else:
            self._container.remove_path(SERVER_KEY_PATH, recursive=True)

        if ca:
            self._container.push(CA_CERT_PATH, ca, make_dirs=True)
        else:
            self._container.remove_path(CA_CERT_PATH, recursive=True)

        self.update_ca_certs()

    def add_ca(self, ca: str, uid: str | int):
        """Add a ca."""
        ca_path = RECV_CA_TEMPLATE.substitute(rel_id=str(uid))
        self._container.push(ca_path, ca, make_dirs=True)

    def remove_ca(self, uid: str | int):
        """Remove a ca."""
        ca_path = RECV_CA_TEMPLATE.substitute(rel_id=str(uid))
        self._container.remove_path(ca_path)

    def update_ca_certs(self):
        """Update ca certificates and restart traefik."""
        self._container.exec(["update-ca-certificates", "--fresh"]).wait()

        # Must restart traefik after refreshing certs, otherwise:
        # - newly added certs will not be loaded and traefik will keep erroring-out with "signed by
        #   unknown authority".
        # - old certs will be kept active.
        self.restart()

    def _config_static(self, tcp_entrypoints: Dict[str, int]) -> str:
        """Get Traefik's static config yaml file."""
        logger.debug(f"Statically configuring traefik with tcp entrypoints: {tcp_entrypoints}.")

        # TODO Disable static config with telemetry and check new version
        raw_config = {
            "log": {
                "level": "DEBUG",
            },
            "entryPoints": {
                "diagnostics": {
                    "address": f":{self.diagnostics_port}",
                    "web": {"address": f":{self._port}"},
                    "websecure": {"address": f":{self._tls_port}"},
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
            },
        }
        config = yaml.safe_dump(raw_config)

        # TODO Use the Traefik user and group?
        self._container.push(STATIC_CONFIG_PATH, config, make_dirs=True)

    # wokeignore:rule=master
    # ref: https://doc.traefik.io/traefik/master/observability/tracing/opentelemetry/
    def config_tracing(self, endpoint: str, grpc: bool):
        """Push yaml config with opentelemetry configuration."""
        config = yaml.safe_dump(
            {
                "tracing": {
                    "openTelemetry": {
                        "address": endpoint,
                        **({"grpc": {}} if grpc else {}),
                        # todo: we have an option to use CA or to use CERT+KEY (available with mtls) authentication.
                        #  when we have mTLS, consider this again.
                        **({"ca": CA_CERT_PATH} if self._tls_enabled else {"insecure": True}),
                    }
                }
            }
        )
        logger.debug(f"dumping tracing config to {DYNAMIC_TRACING_PATH}")

        self._container.push(DYNAMIC_TRACING_PATH, config, make_dirs=True)

    def get_per_unit_http_config(
        self,
        *,
        prefix: str,
        scheme: str = "http",
        host: str,
        port: int,
        strip_prefix: bool,
        redirect_https: bool,
        external_host: str,
    ) -> dict:
        """Generate a config dict for IngressPerUnit."""
        lb_servers = [{"url": f"{scheme}://{host}:{port}"}]
        return self._generate_config_block(
            prefix=prefix,
            lb_servers=lb_servers,
            scheme=scheme,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
            external_host=external_host,
        )

    def get_per_app_http_config(
        self,
        *,
        prefix: str,
        scheme: str = "http",
        hosts: List[str],
        port: int,
        strip_prefix: bool,
        redirect_https: bool,
        external_host: str,
    ) -> dict:
        """Generate a config dict for Ingress(PerApp)."""
        lb_servers = [{"url": f"{scheme}://{host}:{port}"} for host in hosts]
        return self._generate_config_block(
            prefix=prefix,
            lb_servers=lb_servers,
            scheme=scheme,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
            external_host=external_host,
        )

    def get_per_leader_http_config(
        self,
        *,
        prefix: str,
        scheme: str = "http",
        host: str,
        port: int,
        strip_prefix: bool,
        redirect_https: bool,
        external_host: str,
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
        )

    def _generate_config_block(
        self,
        prefix: str,
        lb_servers: List[Dict[str, str]],
        scheme: str,
        redirect_https: bool,
        strip_prefix: bool,
        external_host: str,
    ) -> Dict[str, Any]:
        """Generate a configuration segment.

        Per-unit and per-app configuration blocks are mostly similar, with the principal
        difference being the list of servers to load balance across (where IPU is one server per
        unit and IPA may be more than one).
        """
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
            self._route_tls_config(
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
        internal_tls = scheme == "https"

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

        middlewares = self._generate_middleware_config(
            redirect_https=redirect_https, strip_prefix=strip_prefix, scheme=scheme, prefix=prefix
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
    ) -> dict:
        """Generate a middleware config.

        We need to generate a different section per middleware type, otherwise traefik complains:
          "cannot create middleware: multi-types middleware not supported, consider declaring two
          different pieces of middleware instead"
        """
        no_prefix_middleware = {}  # type: Dict[str, Dict[str, Any]]
        if self._routing_mode is RoutingMode.path:
            if strip_prefix:
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

        return {**no_prefix_middleware, **redir_scheme_middleware}

    @staticmethod
    def _route_tls_config(
        router_name: str,
        route_rule: str,
        service_name: str,
        external_host: str,
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
                "entryPoints": ["websecure"],
                "tls": tls_entry,
            }
        }

    def pull_tcp_entrypoints(self) -> Dict[str, int]:
        """Pull the currently configured tcp entrypoints from the static config."""
        try:
            static_config_raw = self._container.pull(STATIC_CONFIG_PATH).read()
        except PathError as e:
            logger.error(f"Could not fetch static config from container; {e}")
            return {}

        static_config = yaml.safe_load(static_config_raw)
        eps = static_config["entryPoints"]
        return {k: v for k, v in eps.items() if k not in {"diagnostics", "web", "websecure"}}

    @property
    def is_running(self):
        """Whether the traefik service is running."""
        if not self._container.can_connect():
            return False
        return bool(self._container.get_services(self._service_name))

    def restart(self):
        """Restart the pebble service."""
        layer = {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                self._service_name: {
                    "override": "replace",
                    "summary": "Traefik",
                    # trick to drop the logs to a file but also keep them available in the pod logs
                    "command": '/bin/sh -c "{} | tee {}"'.format(BIN_PATH, self.log_path),
                    "startup": "enabled",
                },
            },
        }

        if not self.is_running:
            self._container.add_layer(self._layer_name, cast(LayerDict, layer), combine=True)
            logger.debug(f"replanning {self._service_name!r} after a service update")
            self._container.replan()
        else:
            logger.debug(f"restarting {self._service_name!r}")
            self._container.restart(self._service_name)

    def clear_dynamic_configs(self):
        """Delete all yamls from the dynamic config dir."""
        self._container.exec(["find", DYNAMIC_CONFIG_DIR, "-name", "*.yaml", "-delete"])
        logger.debug("Deleted all dynamic configuration files.")

    def delete_dynamic_config(self, file_name: str):
        """Delete a specific yaml from the dynamic config dir."""
        self._container.remove_path(Path(DYNAMIC_CONFIG_DIR) / file_name)
        logger.debug("deleted dynamic configuration file: %s", file_name)

    def add_dynamic_config(self, file_name: str, config: str):
        """Push a yaml to the dynamic config dir."""
        self._container.push(Path(DYNAMIC_CONFIG_DIR) / file_name, config, make_dirs=True)

        logger.debug("Updated dynamic configuration file: %s", file_name)

    def clear_certs(self):
        """Delete the server cert and server key."""
        self._container.remove_path(SERVER_CERT_PATH)
        self._container.remove_path(SERVER_KEY_PATH)

    def clear_tracing_config(self):
        """Delete the tracing config yaml."""
        with contextlib.suppress(PathError):
            self._container.remove_path(DYNAMIC_TRACING_PATH)

    @property
    def version(self):
        """Traefik workload version."""
        version_output, _ = self._container.exec([BIN_PATH, "version"]).wait_output()
        # Output looks like this:
        # Version:      2.9.6
        # Codename:     banon
        # Go version:   go1.18.9
        # Built:        2022-12-07_04:28:37PM
        # OS/Arch:      linux/amd64

        if result := re.search(r"Version:\s*(.+)", version_output):
            return result.group(1)
        return None

    @staticmethod
    def get_per_unit_tcp_config(prefix: str, host: str, port: int) -> dict:
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
