# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import itertools
from unittest.mock import MagicMock, PropertyMock, patch

from lightkube.models.core_v1 import LoadBalancerIngress, LoadBalancerStatus, ServiceStatus
from lightkube.resources.core_v1 import Service
from scenario import Action, State


def test_get_loadbalancer_ip_available(traefik_ctx, traefik_container):
    """Test that the action returns the IP when it is immediately available."""
    state = State(leader=True, containers=[traefik_container])

    with patch(
        "charm.TraefikIngressCharm._loadbalancer_address",
        new_callable=PropertyMock,
        return_value=LoadBalancerIngress(ip="10.0.0.1"),
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
        "charm.TraefikIngressCharm._loadbalancer_address",
        new_callable=PropertyMock,
        return_value=None,
    ):
        out = traefik_ctx.run_action(
            Action("get-loadbalancer-ip", params={"timeout": 1}),
            state,
        )

    assert not out.success
    assert "not available" in out.failure


def test_get_loadbalancer_ip_reads_the_service_on_each_attempt(traefik_ctx, traefik_container):
    """Test that the action returns an IP assigned while it waits."""
    state = State(leader=True, containers=[traefik_container])
    pending = Service(status=ServiceStatus(loadBalancer=LoadBalancerStatus(ingress=None)))
    ready = Service(
        status=ServiceStatus(
            loadBalancer=LoadBalancerStatus(ingress=[LoadBalancerIngress(ip="10.0.0.1")])
        )
    )
    client = MagicMock()
    client.get.side_effect = itertools.chain([pending], itertools.repeat(ready))

    with patch(
        "charm.TraefikIngressCharm.lightkube_client",
        new_callable=PropertyMock,
        return_value=client,
    ), patch("tenacity.nap.time.sleep"):
        out = traefik_ctx.run_action(
            Action("get-loadbalancer-ip", params={"timeout": 1}),
            state,
        )

    assert out.success
    assert out.results == {"loadbalancer-ip": "10.0.0.1"}
