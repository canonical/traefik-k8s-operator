#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


from unittest.mock import MagicMock, PropertyMock, patch

from charm import _TRAEFIK_SERVICE_NAME, TraefikIngressCharm
from scenario import Container, Context, State


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
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
    assert out.unit_status == ("waiting", f"waiting for service: '{_TRAEFIK_SERVICE_NAME}'")


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
def test_start_traefik_no_hostname(*_, traefik_ctx):
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=False)],
    )
    out = Context(charm_type=TraefikIngressCharm).run("start", state)
    assert out.unit_status == ("waiting", "gateway address unavailable")


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
@patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
def test_start_traefik_active(*_, traefik_ctx):
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=False)],
    )
    out = Context(charm_type=TraefikIngressCharm).run("start", state)
    assert out.unit_status == ("active", "")


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
def test_start_traefik_invalid_routing_mode(*_, traefik_ctx):
    state = State(
        config={"routing_mode": "invalid_routing"},
        containers=[Container(name="traefik", can_connect=False)],
    )
    out = Context(charm_type=TraefikIngressCharm).run("start", state)
    assert out.unit_status == ("blocked", "invalid routing mode: invalid_routing; see logs.")
