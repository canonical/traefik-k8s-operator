# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import yaml
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness
from test_lib_helpers import MockIPARequirer, MockIPURequirer

from charm import TraefikIngressCharm


class TestTraefikIngressCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)

    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_gateway_address_from_config_and_path_routing_mode(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        traefik_container = self.harness.charm.unit.get_container("traefik")
        try:
            yaml.safe_load(traefik_container.pull("/opt/traefik/juju").read())
            raise Exception("The previous line should have failed")
        except IsADirectoryError:
            # If the directory did not exist, the method would have thrown
            # a FileNotFoundError instead.
            pass

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(host="10.1.10.1", port=9000)
        assert requirer.is_available(relation)

        traefik_container = self.harness.charm.unit.get_container("traefik")
        file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
        conf = yaml.safe_load(traefik_container.pull(file).read())

        expected = {
            "http": {
                "routers": {
                    "juju-test-model-ingress-per-unit-remote-0-router": {
                        "entryPoints": ["web"],
                        "rule": "PathPrefix(`/test-model-ingress-per-unit-remote-0`)",
                        "service": "juju-test-model-ingress-per-unit-remote-0-service",
                    }
                },
                "services": {
                    "juju-test-model-ingress-per-unit-remote-0-service": {
                        "loadBalancer": {"servers": [{"url": "http://10.1.10.1:9000"}]}
                    }
                },
            }
        }

        self.assertEqual(conf, expected)

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://testhostname:80/test-model-ingress-per-unit-remote-0"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_gateway_address_from_config_and_path_routing_mode_per_app(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        requirer = MockIPARequirer(self.harness)
        relation = requirer.relate()
        requirer.request(host="foo.bar", port=3000)
        assert requirer.is_available(relation)

        traefik_container = self.harness.charm.unit.get_container("traefik")
        file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
        conf = yaml.safe_load(traefik_container.pull(file).read())

        expected = {
            "http": {
                "routers": {
                    "juju-test-model-ingress-remote-router": {
                        "entryPoints": ["web"],
                        "rule": "PathPrefix(`/test-model-ingress-remote`)",
                        "service": "juju-test-model-ingress-remote-service",
                    }
                },
                "services": {
                    "juju-test-model-ingress-remote-service": {
                        "loadBalancer": {"servers": [{"url": "http://foo.bar:3000"}]}
                    }
                },
            }
        }
        self.assertEqual(conf, expected)

        self.assertEqual(
            requirer.url,
            "http://testhostname:80/test-model-ingress-remote",
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_gateway_address_from_config_and_subdomain_routing_mode_per_app(
        self,
    ):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config(
            {"external_hostname": "testhostname", "routing_mode": "subdomain"}
        )
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        requirer = MockIPARequirer(self.harness)
        relation = requirer.relate()
        requirer.request(host="foo.bar", port=3000)
        assert requirer.is_available(relation)

        traefik_container = self.harness.charm.unit.get_container("traefik")
        file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
        conf = yaml.safe_load(traefik_container.pull(file).read())

        expected = {
            "http": {
                "routers": {
                    "juju-test-model-ingress-remote-router": {
                        "entryPoints": ["web"],
                        "rule": "Host(`test-model-ingress-remote.testhostname`)",
                        "service": "juju-test-model-ingress-remote-service",
                    }
                },
                "services": {
                    "juju-test-model-ingress-remote-service": {
                        "loadBalancer": {"servers": [{"url": "http://foo.bar:3000"}]}
                    }
                },
            }
        }
        self.assertEqual(conf, expected)

        self.assertEqual(
            requirer.url,
            "http://test-model-ingress-remote.testhostname:80/",
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_gateway_address_from_config_and_subdomain_routing_mode(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.harness.update_config(
            {
                "external_hostname": "testhostname",
                "routing_mode": "subdomain",
            }
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(host="10.1.10.1", port=9000)
        assert requirer.is_available(relation)

        traefik_container = self.harness.charm.unit.get_container("traefik")
        file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
        conf = yaml.safe_load(traefik_container.pull(file).read())

        expected = {
            "http": {
                "routers": {
                    "juju-test-model-ingress-per-unit-remote-0-router": {
                        "entryPoints": ["web"],
                        "rule": "Host(`test-model-ingress-per-unit-remote-0.testhostname`)",
                        "service": "juju-test-model-ingress-per-unit-remote-0-service",
                    }
                },
                "services": {
                    "juju-test-model-ingress-per-unit-remote-0-service": {
                        "loadBalancer": {"servers": [{"url": "http://10.1.10.1:9000"}]}
                    }
                },
            }
        }

        self.assertEqual(conf, expected)

        self.assertEqual(
            requirer.urls,
            {
                "ingress-per-unit-remote/0": "http://test-model-ingress-per-unit-remote-0.testhostname:80/"
            },
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_bad_routing_mode_config_and_recovery(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.harness.update_config(
            {
                "external_hostname": "testhostname",
                "routing_mode": "FOOBAR",
            }
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("invalid routing mode: FOOBAR; see logs."),
        )

        self.harness.update_config(
            {
                "routing_mode": "path",
            }
        )

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **unused: None)
    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_without_gateway_address(self):
        """Test that requirers do not get addresses until the gateway address is available."""
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address unavailable")
        )

        self.harness.container_pebble_ready("traefik")

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(host="10.1.10.1", port=9000)

        assert requirer.is_available(relation)
        assert not requirer.is_ready(relation)

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address unavailable")
        )

    @patch("charm._get_loadbalancer_status", lambda **unused: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda **unused: None)
    def test_pebble_ready_with_joined_relations(self):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        requirer = MockIPURequirer(self.harness)
        relation = requirer.relate()
        requirer.request(host="10.1.10.1", port=9000)

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
        requirer.request(host="10.1.10.1", port=9000)

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
        requirer.request(host="10.1.10.1", port=9000)
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
            self.harness.charm.unit.status, WaitingStatus("gateway address unavailable")
        )

        self.assertEqual(requirer.urls, {"ingress-per-unit-remote/0": ""})

    def test_relation_broken(self):
        self.test_pebble_ready_with_gateway_address_from_config_and_path_routing_mode()

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
