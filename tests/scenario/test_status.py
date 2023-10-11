# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, PropertyMock, patch

from ops import ActiveStatus, WaitingStatus
from scenario import Container, State


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="foo.bar"))
def test_start_traefik_is_not_running(traefik_ctx, *_):
    # GIVEN external host is set (see decorator)
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    # WHEN a `start` hook fires
    out = traefik_ctx.run("start", state)

    # THEN unit status is `waiting`
    assert out.unit_status == WaitingStatus("waiting for service: 'traefik'")


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value=False))
def test_start_traefik_no_hostname(traefik_ctx, *_):
    # GIVEN external host is not set (see decorator)
    # WHEN a `start` hook fires
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    out = traefik_ctx.run("start", state)

    # THEN unit status is `waiting`
    assert out.unit_status == WaitingStatus("gateway address unavailable")


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="foo.bar"))
@patch("traefik.Traefik.is_running", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
def test_start_traefik_active(traefik_ctx, *_):
    # GIVEN external host is set (see decorator), plus additional mockery
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN a `start` hook fires
    out = traefik_ctx.run("start", state)

    # THEN unit status is `active`
    assert out.unit_status == ActiveStatus("")
