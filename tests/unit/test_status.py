# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, patch

import httpx
import pytest
from lightkube.core.exceptions import ApiError
from ops import ActiveStatus, BlockedStatus, WaitingStatus
from scenario import Container, State


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="foo.bar"))
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


@patch("charm.TraefikIngressCharm._traefik_external_address", PropertyMock(return_value=False))
def test_start_traefik_no_hostname(traefik_ctx, *_):
    # GIVEN external host is not set (see decorator)
    # WHEN a `start` hook fires
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    out = traefik_ctx.run("start", state)

    # THEN unit status is `waiting`
    assert out.unit_status == BlockedStatus(
        "Traefik load balancer is unable to obtain an IP or hostname from the cluster."
    )


@patch("charm.TraefikIngressCharm._get_loadbalancer_status", PropertyMock(return_value=None))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
def test_start_loadbalancer_pending(traefik_ctx, *_):
    """When the LB has no external IP, charm should be in waiting state."""
    state = State(
        config={"routing_mode": "path", "external_hostname": "foo.bar"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    out = traefik_ctx.run("start", state)

    assert out.unit_status == WaitingStatus(
        "Load balancer service has not yet obtained an external address."
    )


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="1.1.1.1"))
def test_start_traefik_subdomain_without_hostname(traefik_ctx, *_):
    # GIVEN external_hostname is not set but routing_mode is set to subdomain
    # WHEN a `start` hook fires
    state = State(
        config={"routing_mode": "subdomain"},
        containers=[Container(name="traefik", can_connect=True)],
    )
    out = traefik_ctx.run("start", state)

    # THEN unit status is `waiting`
    assert out.unit_status == BlockedStatus(
        '"external_hostname" must be set while using routing mode "subdomain"'
    )


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="foo.bar"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
def test_start_traefik_active(traefik_ctx, *_):
    # GIVEN external host is set (see decorator), plus additional mockery
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN a `start` hook fires
    out = traefik_ctx.run("start", state)

    # THEN unit status is `active`
    assert out.unit_status == ActiveStatus("Serving at http://foo.bar")


def _api_error(code: int) -> ApiError:
    return ApiError(
        response=httpx.Response(status_code=code, json={"code": code, "message": "error"})
    )


@patch("charm.TraefikIngressCharm._get_lb_resource_manager")
def test_start_without_trust(m_lb_manager, traefik_ctx, *_):
    # GIVEN the charm was deployed without `--trust`
    m_lb_manager.return_value.reconcile.side_effect = _api_error(403)
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN a `start` hook fires
    out = traefik_ctx.run("start", state)

    # THEN the unit is blocked instead of erroring, and says how to fix it
    assert out.unit_status == BlockedStatus(
        "Insufficient permissions, try: `juju trust traefik-k8s --scope=cluster`"
    )


@patch("charm.TraefikIngressCharm._get_lb_resource_manager")
def test_start_other_api_errors_are_raised(m_lb_manager, traefik_ctx, *_):
    # GIVEN reconciling the LoadBalancer fails for a reason other than permissions
    m_lb_manager.return_value.reconcile.side_effect = _api_error(500)
    state = State(
        config={"routing_mode": "path"},
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN a `start` hook fires
    # THEN the error is not swallowed
    with pytest.raises(Exception) as exc_info:
        traefik_ctx.run("start", state)
    assert isinstance(exc_info.value.__cause__, ApiError)


@patch("charm.TraefikIngressCharm._get_lb_resource_manager")
def test_remove_without_trust(m_lb_manager, traefik_ctx, *_):
    # GIVEN the charm was deployed without `--trust`
    m_lb_manager.return_value.delete.side_effect = _api_error(403)
    state = State(
        planned_units=0,
        containers=[Container(name="traefik", can_connect=True)],
    )

    # WHEN the last unit is removed
    # THEN the `remove` hook succeeds
    traefik_ctx.run("remove", state)
    m_lb_manager.return_value.delete.assert_called_once_with(ignore_missing=True)


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="foo.bar"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
def test_invalid_routing_mode_blocks_and_recovers(traefik_ctx, traefik_container, *_):
    invalid_state = State(
        config={"routing_mode": "FOOBAR"},
        containers=[traefik_container],
    )

    blocked_state = traefik_ctx.run("start", invalid_state)

    assert blocked_state.unit_status == BlockedStatus(
        "invalid routing mode: FOOBAR; see logs."
    )

    valid_state = blocked_state.replace(config={"routing_mode": "path"})

    recovered_state = traefik_ctx.run("start", valid_state)

    assert recovered_state.unit_status == ActiveStatus("Serving at http://foo.bar")
