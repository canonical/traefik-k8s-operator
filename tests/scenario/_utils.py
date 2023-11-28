import json
from typing import List

from scenario import Relation


def _render_middlewares(*, strip_prefix: bool = False, redirect_https: bool = False) -> dict:
    no_prefix_middleware = {}
    if strip_prefix:
        no_prefix_middleware["juju-sidecar-noprefix-test-model-remote-0"] = {
            "stripPrefix": {"prefixes": ["/test-model-remote-0"], "forceSlash": False}
        }

    # Condition rendering the https-redirect middleware on the scheme, otherwise we'd get a 404
    # when attempting to reach an http endpoint.
    redir_scheme_middleware = {}
    if redirect_https:
        redir_scheme_middleware["juju-sidecar-redir-https-test-model-remote-0"] = {
            "redirectScheme": {"scheme": "https", "port": 443, "permanent": True}
        }

    return {**no_prefix_middleware, **redir_scheme_middleware}


def _render_config(
    *,
    rel_name: str,
    routing_mode: str,
    strip_prefix: bool,
    redirect_https: bool,
    scheme: str = "http",
    tls_enabled: bool = True,
    host: str = "10.1.10.1",
    port: str = "42",
):
    routing_rule = {
        "path": "PathPrefix(`/test-model-remote-0`)",
        "subdomain": "Host(`test-model-remote-0.testhostname`)",
    }

    service_spec = {
        "loadBalancer": {"servers": [{"url": f"{scheme}://{host}:{port}"}]},
    }
    transports = {}
    if scheme == "https":
        # service_spec["rootCAs"] = ["/opt/traefik/juju/certificate.cert"]
        service_spec["loadBalancer"]["serversTransport"] = "reverseTerminationTransport"
        transports = {"reverseTerminationTransport": {"insecureSkipVerify": False}}

    expected = {
        "http": {
            "routers": {
                "juju-test-model-remote-0-router": {
                    "entryPoints": ["web"],
                    "rule": routing_rule[routing_mode],
                    "service": "juju-test-model-remote-0-service",
                },
                "juju-test-model-remote-0-router-tls": {
                    "entryPoints": ["websecure"],
                    "rule": routing_rule[routing_mode],
                    "service": "juju-test-model-remote-0-service",
                    "tls": {
                        "domains": [
                            {
                                "main": "testhostname",
                                "sans": ["*.testhostname"],
                            },
                        ],
                    },
                },
            },
            "services": {"juju-test-model-remote-0-service": service_spec},
        }
    }

    if transports:
        expected["http"]["serversTransports"] = transports

    if middlewares := _render_middlewares(
        strip_prefix=strip_prefix and routing_mode == "path",
        redirect_https=redirect_https and scheme == "https",
    ):
        expected["http"].update({"middlewares": middlewares})
        expected["http"]["routers"]["juju-test-model-remote-0-router"].update(
            {"middlewares": list(middlewares.keys())},
        )
        expected["http"]["routers"]["juju-test-model-remote-0-router-tls"].update(
            {"middlewares": list(middlewares.keys())},
        )

    return expected


def create_ingress_relation(
    *,
    rel_id: int = None,
    app_name: str = "remote",
    strip_prefix: bool = False,
    redirect_https: bool = False,
    model_name: str = "test-model",
    unit_name: str = "remote/0",
    port: int = 42,
    scheme: str = "http",
    hosts: List[str] = ["0.0.0.42"],
    ips: List[str] = ["0.0.0.42"],
) -> Relation:
    app_data = {
        "model": model_name,
        "name": unit_name,
        "scheme": scheme,
        "strip-prefix": strip_prefix,
        "redirect-https": redirect_https,
        "port": port,
    }
    remote_units_data = {
        i: {"host": json.dumps(h), "ip": json.dumps(ip)}
        for i, (h, ip) in enumerate(zip(hosts, ips))
    }

    args = {
        "endpoint": "ingress",
        "remote_app_name": app_name,
        "remote_app_data": {k: json.dumps(v) for k, v in app_data.items()},
        "remote_units_data": remote_units_data,
    }

    # No `next_relation_id()` nor `get_next_id()` in Relation.
    if rel_id is not None:
        args["relation_id"] = rel_id

    return Relation(**args)
