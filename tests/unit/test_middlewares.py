# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
import scenario
import yaml
from scenario import Relation, State

from tests.unit._utils import _render_config, create_ingress_relation
from traefik import DYNAMIC_CONFIG_DIR


def _create_relation(
    *,
    rel_id: int,
    rel_name: str,
    app_name: str,
    strip_prefix: bool,
    redirect_https: bool,
    scheme: str,
    port: int,
    unit_name: str = "remote/0",
):
    if rel_name == "ingress":
        return create_ingress_relation(
            app_name=app_name,
            rel_id=rel_id,
            unit_name=unit_name,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
            port=port,
            scheme=scheme,
            hosts=["10.1.10.1"],
        )

    if rel_name == "ingress-per-unit":
        unit_data = {
            "port": str(port),
            "host": "10.1.10.1",
            "model": "test-model",
            "name": unit_name,
            "mode": "http",
            "scheme": scheme,
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
@pytest.mark.parametrize("scheme", ("http", "https"))
def test_middleware_config(
    traefik_ctx, traefik_container, rel_name, routing_mode, strip_prefix, redirect_https, scheme
):

    # GIVEN a relation is requesting some middlewares
    rel_id = 0
    app_name = "remote"
    relation = _create_relation(
        rel_id=rel_id,
        rel_name=rel_name,
        app_name=app_name,
        unit_name="remote/0",
        strip_prefix=strip_prefix,
        redirect_https=redirect_https,
        scheme=scheme,
        port=42,
    )

    # AND GIVEN external host is set (see also decorator)
    state = State(
        leader=True,
        config={"routing_mode": routing_mode, "external_hostname": "testhostname"},
        containers=[traefik_container],
        relations=[relation],
    )

    # WHEN a `relation-changed` hook fires
    out = traefik_ctx.run(relation.changed_event, state)

    # THEN the rendered config file contains middlewares
    with out.get_container("traefik").get_filesystem(traefik_ctx).joinpath(
        f"opt/traefik/juju/juju_ingress_{rel_name}_0_{app_name}.yaml",
    ) as f:
        config_file = f.read_text()
    expected = _render_config(
        rel_name=rel_name,
        routing_mode=routing_mode,
        strip_prefix=strip_prefix,
        scheme=scheme,
        port="42",
    )

    assert yaml.safe_load(config_file) == expected


@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
def test_basicauth_config(traefik_ctx: scenario.Context, traefik_container):
    # GIVEN traefik is configured with a sample basicauth user
    ingress = create_ingress_relation()
    basicauth_user = "user:hashed-password"
    state = State(
        config={"basic_auth_user": basicauth_user},
        relations=[ingress],
        containers=[traefik_container],
    )

    # WHEN we process a config-changed event
    state_out = traefik_ctx.run("config_changed", state)

    # THEN traefik writes a dynamic config file with the expected basicauth middleware
    traefik_fs = state_out.get_container("traefik").get_filesystem(traefik_ctx)
    dynamic_config_path = (
        Path(str(traefik_fs) + DYNAMIC_CONFIG_DIR)
        / f"juju_ingress_{ingress.endpoint}_{ingress.relation_id}_{ingress.remote_app_name}.yaml"
    )
    assert dynamic_config_path.exists()
    http_cfg = yaml.safe_load(dynamic_config_path.read_text())["http"]
    assert http_cfg["middlewares"]["juju-basic-auth-test-model-remote-0"] == {
        "basicAuth": {"users": [basicauth_user]}
    }
    for router in http_cfg["routers"].values():
        assert "juju-basic-auth-test-model-remote-0" in router["middlewares"]
