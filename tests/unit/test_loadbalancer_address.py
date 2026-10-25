# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

import ops.testing
from lightkube.models.core_v1 import LoadBalancerIngress, LoadBalancerStatus, ServiceStatus
from lightkube.resources.core_v1 import Service
from ops.testing import Harness

from charm import TraefikIngressCharm

ops.testing.SIMULATE_CAN_CONNECT = True


def _service_with(address):
    """A LoadBalancer Service whose status carries the given external address, if any."""
    ingress = [address] if address else None
    return Service(status=ServiceStatus(loadBalancer=LoadBalancerStatus(ingress=ingress)))


class TestLoadBalancerAddress(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)
        self.harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = MagicMock()
        patcher = patch("charm.Client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _begin_with(self, address):
        """Start the charm with the LoadBalancer reporting the given address.

        The charm reads the address while initialising; that read is discarded so each test
        observes only its own reads, as a new charm instance would in production.
        """
        self.client.get.return_value = _service_with(address)
        self.harness.begin()
        charm = self.harness.charm
        for attr in ("_loadbalancer_address", "_traefik_external_address", "gateway_address"):
            charm.__dict__.pop(attr, None)
        self.client.get.reset_mock()
        return charm

    def test_host_prefers_hostname_over_ip(self):
        charm = self._begin_with(LoadBalancerIngress(hostname="lb.example.com", ip="10.0.0.1"))
        self.assertEqual(charm._loadbalancer_host, "lb.example.com")
        self.assertEqual(charm._loadbalancer_ip, "10.0.0.1")

    def test_host_falls_back_to_ip(self):
        charm = self._begin_with(LoadBalancerIngress(ip="10.0.0.1"))
        self.assertEqual(charm._loadbalancer_host, "10.0.0.1")
        self.assertEqual(charm._loadbalancer_ip, "10.0.0.1")

    def test_hostname_without_ip(self):
        charm = self._begin_with(LoadBalancerIngress(hostname="lb.example.com"))
        self.assertEqual(charm._loadbalancer_host, "lb.example.com")
        self.assertIsNone(charm._loadbalancer_ip)

    def test_no_address_yet(self):
        charm = self._begin_with(None)
        self.assertIsNone(charm._loadbalancer_host)
        self.assertIsNone(charm._loadbalancer_ip)

    def test_upstream_ingress_configuration_reads_the_service_once(self):
        charm = self._begin_with(LoadBalancerIngress(hostname="lb.example.com", ip="10.0.0.1"))

        config = charm._generate_upstream_ingress_route_configuration()

        self.assertEqual(config["host"], "lb.example.com")
        self.assertEqual(config["ip"], "10.0.0.1")
        self.client.get.assert_called_once_with(Service, name=charm._lb_name, namespace="test-model")
