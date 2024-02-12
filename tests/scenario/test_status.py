# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, PropertyMock, patch

from ops import ActiveStatus, BlockedStatus, WaitingStatus
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
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
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


@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="1.2.3.4"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
def test_block_if_no_ext_host_in_subdomain_routing(traefik_ctx, *_):
    # GIVEN external host is a bare IP from metallb (see decorator)
    # WHEN a `config-change` hook fires and routing mode is subdomain
    state = State(
        config={"routing_mode": "subdomain"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    out = traefik_ctx.run("config-changed", state)

    # THEN unit status is `blocked`
    assert isinstance(out.unit_status, BlockedStatus)

    # AND WHEN the routing mode is reverted to path
    out.config["routing_mode"] = "path"

    # THEN unit status is `active`
    out = traefik_ctx.run("config-changed", out)
    assert out.unit_status == ActiveStatus("")
