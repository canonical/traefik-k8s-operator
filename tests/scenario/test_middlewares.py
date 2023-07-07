# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import itertools
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from charm import TraefikIngressCharm
from scenario import Container, Context, Mount, Relation, State


def _render_middlewares(*, strip_prefix: bool = False, redirect_https: bool = False) -> dict:
    middlewares = {}
    if redirect_https:
        middlewares.update({"redirectScheme": {"scheme": "https", "port": 443, "permanent": True}})
    if strip_prefix:
        middlewares.update(
            {
                "stripPrefix": {
                    "prefixes": ["/test-model-remote-0"],
                    "forceSlash": False,
                }
            }
        )
    return (
        {"middlewares": {"juju-sidecar-noprefix-test-model-remote-0": middlewares}}
        if middlewares
        else {}
    )


def _render_config(*, routing_mode: str, strip_prefix: bool, redirect_https: bool):
    routing_rule = {
        "path": "PathPrefix(`/test-model-remote-0`)",
        "subdomain": "Host(`test-model-remote-0.testhostname`)",
    }

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
            "services": {
                "juju-test-model-remote-0-service": {
                    "loadBalancer": {"servers": [{"url": f"http://10.1.10.1:9000"}]}
                }
            },
        }
    }

    if middlewares := _render_middlewares(
            strip_prefix=strip_prefix and routing_mode == "path", redirect_https=redirect_https
    ):
        expected["http"].update(middlewares)
        expected["http"]["routers"]["juju-test-model-remote-0-router"].update(
            {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
        )
        expected["http"]["routers"]["juju-test-model-remote-0-router-tls"].update(
            {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
        )

    return expected


def _create_relation(
        *, rel_id: int, rel_name: str, app_name: str, strip_prefix: bool, redirect_https: bool
):
    if rel_name == "ingress":
        app_data = {
            "model": "test-model",
            "name": "remote/0",
            "mode": "http",
            "strip-prefix": "true" if strip_prefix else "false",
            "redirect-https": "true" if redirect_https else "false",
        }
        unit_data = {
            "port": str(9000),
            "host": "10.1.10.1",
        }

        return Relation(
            endpoint=rel_name,
            remote_app_name=app_name,
            relation_id=rel_id,
            remote_app_data=app_data,
            remote_units_data={0: unit_data}
        )

    if rel_name == "ingress-per-unit":
        unit_data = {
            "port": str(9000),
            "host": "10.1.10.1",
            "model": "test-model",
            "name": "remote/0",
            "mode": "http",
            "strip-prefix": "true" if strip_prefix else "false",
            "redirect-https": "true" if redirect_https else "false",
        }
        return Relation(
            endpoint=rel_name,
            remote_app_name=app_name,
            relation_id=rel_id,
            remote_units_data={0: unit_data},
        )

    RuntimeError(f"Unexpected relation name: '{rel_name}'")
    return None


@pytest.mark.parametrize("rel_name", ("ingress", "ingress-per-unit"))
@pytest.mark.parametrize("routing_mode", ("path", "subdomain"))
@pytest.mark.parametrize("strip_prefix", (False, True))
@pytest.mark.parametrize("redirect_https", (False, True))
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="testhostname"))
@patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
def test_middleware_config(traefik_ctx, rel_name, routing_mode, strip_prefix, redirect_https):
    td = tempfile.TemporaryDirectory()
    containers = [
        Container(
            name="traefik",
            can_connect=True,
            mounts={"configurations": Mount("/opt/traefik/", td.name)},
        )
    ]

    # GIVEN a relation is requesting some middlewares
    rel_id = 0
    app_name = "remote"
    relation = _create_relation(
        rel_id=rel_id,
        rel_name=rel_name,
        app_name=app_name,
        strip_prefix=strip_prefix,
        redirect_https=redirect_https,
    )

    # AND GIVEN external host is set (see also decorator)
    state = State(
        leader=True,
        config={"routing_mode": routing_mode, "external_hostname": "testhostname"},
        containers=containers,
        relations=[relation],
    )

    # WHEN a `relation-changed` hook fires
    out = traefik_ctx.run(relation.changed_event, state)

    # THEN the rendered config file contains middlewares
    with out.get_container("traefik").filesystem.open(
            f"/opt/traefik/juju/juju_ingress_{rel_name}_{rel_id}_{app_name}.yaml",
    ) as f:
        config_file = f.read()
    expected = _render_config(
        routing_mode=routing_mode,
        strip_prefix=strip_prefix,
        redirect_https=redirect_https,
    )

    assert expected == yaml.safe_load(config_file)


if __name__ == "__main__":
    unittest.main()
