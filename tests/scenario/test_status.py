# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from ops import WaitingStatus, ActiveStatus, BlockedStatus
from scenario import Container, State, Context
from scenario.runtime import trigger

from charm import TraefikIngressCharm


@pytest.fixture
def ctx(traefik_charm):
    return Context(charm_type=traefik_charm)


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
def test_start_traefik_is_not_running(ctx, *_):
    # GIVEN external host is set (see decorator)
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    # WHEN a `start` hook fires
    out = ctx.run("start", state)

    # THEN unit status is `waiting`
    assert out.status.unit == WaitingStatus("waiting for service: 'traefik'")


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
def test_start_traefik_no_hostname(ctx, *_):
    # GIVEN external host is not set (see decorator)
    # WHEN a `start` hook fires
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    out = ctx.run('start', state)

    # THEN unit status is `waiting`
    assert out.status.unit == WaitingStatus("gateway address unavailable")


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
@patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
def test_start_traefik_active(ctx, *_):
    # GIVEN external host is set (see decorator), plus additional mockery
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN a `start` hook fires
    out = ctx.run("start", state)

    # THEN unit status is `active`
    assert out.status.unit == ActiveStatus()


@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
def test_start_traefik_invalid_routing_mode(ctx, *_):
    # GIVEN external host is not set (see decorator)
    # AND an invalid config for routing mode
    state = State(
        config={"routing_mode": "invalid_routing"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN a `start` hook fires
    out = trigger(state, "start", TraefikIngressCharm)

    # THEN unit status is `blocked`
    assert out.status.unit == BlockedStatus("invalid routing mode: invalid_routing; see logs.")
