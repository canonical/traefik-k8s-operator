# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from lightkube.models.core_v1 import LoadBalancerIngress, LoadBalancerStatus, ServiceStatus
from lightkube.resources.core_v1 import Service
from scenario import Context, State

from charm import TraefikIngressCharm


def _service_with(address):
    ingress = [address] if address else None
    return Service(status=ServiceStatus(loadBalancer=LoadBalancerStatus(ingress=ingress)))


@pytest.fixture
def lightkube_client():
    # Not the traefik_ctx fixture: it patches `_loadbalancer_host`, which these tests read.
    client = MagicMock()
    with charm_tracing_disabled(), patch("lightkube.core.client.GenericSyncClient"), patch(
        "charm.TraefikIngressCharm.lightkube_client",
        new_callable=PropertyMock,
        return_value=client,
    ):
        yield client


@pytest.mark.parametrize(
    "address, host, ip",
    [
        (
            LoadBalancerIngress(hostname="lb.example.com", ip="10.0.0.1"),
            "lb.example.com",
            "10.0.0.1",
        ),
        (LoadBalancerIngress(ip="10.0.0.1"), "10.0.0.1", "10.0.0.1"),
        (LoadBalancerIngress(hostname="lb.example.com"), "lb.example.com", None),
        (None, None, None),
    ],
)
def test_loadbalancer_host_and_ip(lightkube_client, traefik_container, address, host, ip):
    lightkube_client.get.return_value = _service_with(address)
    state = State(leader=True, containers=[traefik_container])

    with Context(charm_type=TraefikIngressCharm).manager("start", state) as mgr:
        assert mgr.charm._loadbalancer_host == host
        assert mgr.charm._loadbalancer_ip == ip


def test_upstream_ingress_configuration_reads_the_service_once(
    lightkube_client, traefik_container
):
    lightkube_client.get.return_value = _service_with(
        LoadBalancerIngress(hostname="lb.example.com", ip="10.0.0.1")
    )
    state = State(leader=True, containers=[traefik_container])

    with Context(charm_type=TraefikIngressCharm).manager("start", state) as mgr:
        config = mgr.charm._generate_upstream_ingress_route_configuration()
        service_reads = [
            call for call in lightkube_client.get.call_args_list if call.args[:1] == (Service,)
        ]

    assert config["host"] == "lb.example.com"
    assert config["ip"] == "10.0.0.1"
    assert len(service_reads) == 1
