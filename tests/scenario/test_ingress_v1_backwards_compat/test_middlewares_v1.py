# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from scenario import Container, Mount, Relation, State

from tests.scenario.utils import _render_config


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
            "port": str(9000),
            "host": "10.1.10.1",
        }

        return Relation(
            endpoint=rel_name,
            remote_app_name=app_name,
            relation_id=rel_id,
            remote_app_data=app_data,
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

    raise RuntimeError(f"Unexpected relation name: '{rel_name}'")


@pytest.mark.parametrize("rel_name", ("ingress", "ingress-per-unit"))
@pytest.mark.parametrize("routing_mode", ("path", "subdomain"))
@pytest.mark.parametrize("strip_prefix", (False, True))
@pytest.mark.parametrize("redirect_https", (False, True))
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="testhostname"))
@patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
def test_middleware_config(
    traefik_ctx, rel_name, routing_mode, strip_prefix, redirect_https, caplog
):
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
    with caplog.at_level("WARNING"):
        out = traefik_ctx.run(relation.changed_event, state)

    if rel_name == "ingress":
        assert "is using a deprecated ingress v1 protocol to talk to Traefik." in caplog.text

    # THEN the rendered config file contains middlewares
    with out.get_container("traefik").get_filesystem(traefik_ctx).joinpath(
        f"opt/traefik/juju/juju_ingress_{rel_name}_{rel_id}_{app_name}.yaml",
    ) as f:
        config_file = f.read_text()
    expected = _render_config(
        rel_name="ingress",
        routing_mode=routing_mode,
        strip_prefix=strip_prefix,
        redirect_https=redirect_https,
        scheme="http",
        tls_enabled=False,
        port=9000,
    )

    assert yaml.safe_load(config_file) == expected


if __name__ == "__main__":
    unittest.main()
