# TODO: Add a module docstring explaining that this is either a ingressed app's TLS or Traefik's TLS test
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from scenario import Relation, State

from tests.unit._utils import _render_config, create_ingress_relation


def _create_tls_relation(*, app_name: str, strip_prefix: bool, redirect_https: bool):
    app_data = {
        "certificates": "{CERTS}",
    }
    return Relation(
        endpoint="certificates",
        remote_app_name=app_name,
        remote_app_data=app_data,
    )


@pytest.mark.parametrize("routing_mode", ("path", "subdomain"))
@pytest.mark.parametrize("strip_prefix", (False, True))
@pytest.mark.parametrize("redirect_https", (False, True))
@pytest.mark.parametrize("tls_from_configs", (True, False))
@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="testhostname"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", MagicMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
def test_middleware_config(
    traefik_ctx, traefik_container, routing_mode, strip_prefix, redirect_https, tls_from_configs
):
    containers = [traefik_container]

    # GIVEN a relation is requesting some middlewares
    rel_id = 0
    app_name = "remote"
    ipa = create_ingress_relation(
        rel_id=rel_id,
        app_name=app_name,
        unit_name=f"{app_name}/0",
        strip_prefix=strip_prefix,
        redirect_https=redirect_https,
        hosts=["0.0.0.42"],
    )

    if tls_from_configs:
        # AND GIVEN external host is set (see also decorator)
        state = State(
            leader=True,
            config={
                "routing_mode": routing_mode,
                "external_hostname": "testhostname",
                "tls-cert": "helloworld",
                "tls-key": "helloworld",
                "tls-ca": "helloworld",
            },
            containers=containers,
            relations=[ipa],
        )

    else:
        tls = _create_tls_relation(
            app_name=app_name,
            strip_prefix=strip_prefix,
            redirect_https=redirect_https,
        )

        # AND GIVEN external host is set (see also decorator)
        state = State(
            leader=True,
            config={"routing_mode": routing_mode, "external_hostname": "testhostname"},
            containers=containers,
            relations=[ipa, tls],
        )

    # WHEN a `relation-changed` hook fires
    out = traefik_ctx.run(ipa.changed_event, state)

    # THEN the rendered config file contains middlewares
    with out.get_container("traefik").get_filesystem(traefik_ctx).joinpath(
        f"opt/traefik/juju/juju_ingress_ingress_{rel_id}_{app_name}.yaml",
    ) as f:
        config_file = f.read_text()
    expected = _render_config(
        rel_name="ingress",
        routing_mode=routing_mode,
        strip_prefix=strip_prefix,
        redirect_https=redirect_https,
        scheme="http",
        host="0.0.0.42",
        tls_enabled=True,  # TODO: This test only runs for `ingress`, not `per_unit` or `route`
    )

    assert yaml.safe_load(config_file) == expected

    ipa_out = out.get_relations("ingress")[0]

    # AND Traefik publishes the ingress URL scheme as "https"
    if routing_mode == "path":
        url = "https://testhostname/test-model-remote-0"
    else:
        url = "https://test-model-remote-0.testhostname/"

    assert ipa_out.local_app_data == {"ingress": f'{{"url": "{url}"}}'}
