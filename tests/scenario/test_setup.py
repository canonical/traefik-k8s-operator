#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


from unittest.mock import PropertyMock, patch

from scenario import Container, Context, State

from charm import TraefikIngressCharm
from traefik import Traefik


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="foo.bar"))
def test_start_traefik_is_not_running(*_, traefik_ctx):
    #
    # equivalent to:
    # META = yaml.safe_load((Path(__file__).parent.parent.parent / "metadata.yaml").read_text())
    # ACTIONS = yaml.safe_load((Path(__file__).parent.parent.parent / "actions.yaml").read_text())
    # CONFIG = yaml.safe_load((Path(__file__).parent.parent.parent / "config.yaml").read_text())
    # charm_spec = CharmSpec(TraefikIngressCharm, meta=META, config=CONFIG, actions=ACTIONS))

    state = State(
        # ATM scenario can't use the defaults specified in config.yaml,
        # so we need to provide ourselves the values
        # of each config option
        config={"routing_mode": "path"},
        # you need to specify which containers are present, otherwise
        # the charm will raise exceptions when
        # assuming that there is a "traefik" container.
        containers=[
            Container(
                name="traefik",
                # we need to set can_connect=False for now because I didn't write
                # yet the mocking code for the other pebble interactions yet.
                # So if the charm tries to get_services, get_plan,
                # push, pull etc..., there will be errors.
                # Can implement this tomorrow so you can proceed.
                can_connect=False,
            )
        ],
    )
    out = Context(charm_type=TraefikIngressCharm).run("start", state)
    assert out.unit_status == ("waiting", f"waiting for service: '{Traefik.service_name}'")


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value=False))
def test_start_traefik_no_hostname(*_, traefik_ctx):
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=False)],
    )
    out = Context(charm_type=TraefikIngressCharm).run("start", state)
    assert out.unit_status == (
        "blocked",
        "Traefik load balancer is unable to obtain an IP or hostname from the cluster.",
    )


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="foo.bar"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
def test_start_traefik_active(*_, traefik_ctx):
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=False)],
    )
    out = Context(charm_type=TraefikIngressCharm).run("start", state)
    assert out.unit_status == ("active", "Serving at foo.bar")
