# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import patch

from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness
from test_lib_helpers import MockIPURequirer

from charm import TraefikIngressCharm


class TestTraefikIngressCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(TraefikIngressCharm)
        self.addCleanup(self.harness.cleanup)

    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_gateway_address_from_config(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(hostname="10.1.10.1", port=9000)

        assert requirer.is_available(relation)

        traefik_container = self.harness.charm.unit.get_container("traefik")
        self.assertEqual(
            traefik_container.pull(
                f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
            ).read(),
            """http:
  routers:
    juju-test-model-ingress-per-unit-remote-0-router:
      entryPoints:
      - web
      rule: PathPrefix(`/test-model-ingress-per-unit-remote-0`)
      service: juju-test-model-ingress-per-unit-remote-0-service
  services:
    juju-test-model-ingress-per-unit-remote-0-service:
      loadBalancer:
        servers:
        - url: http://10.1.10.1:9000
""",
        )

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://testhostname:80/test-model-ingress-per-unit-remote-0"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **unused: None)
    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_without_gateway_address(self):
        """Test that requirers do not get addresses until the gateway address is available."""
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address not available")
        )

        self.harness.container_pebble_ready("traefik")

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(hostname="10.1.10.1", port=9000)

        assert requirer.is_available(relation)
        assert not requirer.is_ready(relation)

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address not available")
        )

    @patch("charm._get_loadbalancer_status", lambda **unused: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_joined_relations(self):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(hostname="10.1.10.1", port=9000)

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        assert requirer.is_available(relation)

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://10.0.0.1:80/test-model-ingress-per-unit-remote-0"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **unused: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_gateway_address_change_with_joined_relations(self):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(hostname="10.1.10.1", port=9000)

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        assert requirer.is_available(relation)

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://10.0.0.1:80/test-model-ingress-per-unit-remote-0"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.harness.update_config({"external_hostname": "testhostname"})

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://testhostname:80/test-model-ingress-per-unit-remote-0"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **unused: None)
    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_gateway_address_becomes_unavailable_after_relation_join(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.harness.container_pebble_ready("traefik")

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(hostname="10.1.10.1", port=9000)

        assert requirer.is_available(relation)
        assert requirer.is_ready(relation)

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://testhostname:80/test-model-ingress-per-unit-remote-0"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.harness.update_config(unset=["external_hostname"])

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address not available")
        )

        self.assertEqual(
            requirer.urls,
            {"ingress-per-unit-remote/0": ""},
        )

    def test_relation_broken(self):
        self.test_pebble_ready_with_gateway_address_from_config()

        relation = self.harness.model.relations["ingress-per-unit"][0]
        self.harness.remove_relation(relation.id)

        traefik_container = self.harness.charm.unit.get_container("traefik")

        try:
            traefik_container.pull(
                f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
            ).read()
            raise Exception("The line above should fail")
        except FileNotFoundError:
            pass
