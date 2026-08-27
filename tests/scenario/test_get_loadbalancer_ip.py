# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

from scenario import Action, State


def test_get_loadbalancer_ip_available(traefik_ctx, traefik_container):
    """Test that the action returns the IP when it is immediately available."""
    state = State(leader=True, containers=[traefik_container])

    with patch(
        "charm.TraefikIngressCharm._fetch_loadbalancer_ip",
        return_value="10.0.0.1",
    ):
        out = traefik_ctx.run_action(
            Action("get-loadbalancer-ip", params={"timeout": 300}),
            state,
        )

    assert out.success
    assert out.results == {"loadbalancer-ip": "10.0.0.1"}


def test_get_loadbalancer_ip_unavailable(traefik_ctx, traefik_container):
    """Test that the action fails when IP is not available within timeout."""
    state = State(leader=True, containers=[traefik_container])

    with patch(
        "charm.TraefikIngressCharm._fetch_loadbalancer_ip",
        return_value=None,
    ):
        out = traefik_ctx.run_action(
            Action("get-loadbalancer-ip", params={"timeout": 1}),
            state,
        )

    assert not out.success
    assert "not available" in out.failure
