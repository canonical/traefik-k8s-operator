#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


from unittest.mock import MagicMock, PropertyMock, patch

from scenario import Container, State

from charm import _TRAEFIK_SERVICE_NAME, TraefikIngressCharm


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
def test_start_traefik_is_not_running(*_):
    #
    # equivalent to:
    # META = yaml.safe_load((Path(__file__).parent.parent.parent / "metadata.yaml").read_text())
    # ACTIONS = yaml.safe_load((Path(__file__).parent.parent.parent / "actions.yaml").read_text())
    # CONFIG = yaml.safe_load((Path(__file__).parent.parent.parent / "config.yaml").read_text())
    # charm_spec = CharmSpec(TraefikIngressCharm, meta=META, config=CONFIG, actions=ACTIONS))

    out = State(
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
    ).trigger(
        "start",
        TraefikIngressCharm,
    )

    assert out.status.unit == ("waiting", f"waiting for service: '{_TRAEFIK_SERVICE_NAME}'")


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
def test_start_traefik_no_hostname(*_):
    out = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=False)],
    ).trigger(
        "start",
        TraefikIngressCharm
    )
    assert out.status.unit == ("waiting", "gateway address unavailable")


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
@patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
def test_start_traefik_active(*_):
    out = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=False)],
    ).trigger(
        "start",
        TraefikIngressCharm
    )

    assert out.status.unit == ("active", "")


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
def test_start_traefik_invalid_routing_mode(*_):
    out = State(
        config={"routing_mode": "invalid_routing"},
        containers=[Container(name="traefik", can_connect=False)],
    ).trigger(
        "start", TraefikIngressCharm
    )
    assert out.status.unit == ("blocked", "invalid routing mode: invalid_routing; see logs.")
