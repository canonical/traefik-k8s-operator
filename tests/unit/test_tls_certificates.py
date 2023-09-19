# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops.testing
from charm import TraefikIngressCharm
from ops.testing import Harness

ops.testing.SIMULATE_CAN_CONNECT = True


class TlsWithExternalHostname(unittest.TestCase):
    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def setUp(self):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)
        self.harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_external_hostname_is_set_after_relation_joins(self):
        # GIVEN an external hostname is not set
        self.assertFalse(self.harness.charm.config.get("external_hostname"))
        self.assertEqual(self.harness.charm.external_host, "10.0.0.1")

        # WHEN a "certificates" relation is formed
        # THEN the charm logs an appropriate DEBUG line
        self.rel_id = self.harness.add_relation("certificates", "root-ca")
        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # AND WHEN an external hostname is set
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEqual(self.harness.charm.external_host, "testhostname")
        # AND when a root ca joins

        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # THEN a CSR is sent
        unit_databag = self.harness.get_relation_data(self.rel_id, self.harness.charm.unit.name)
        self.assertIsNotNone(unit_databag.get("certificate_signing_requests"))

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_external_hostname_is_set_before_relation_joins(self):
        # GIVEN an external hostname is set
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEqual(self.harness.charm.external_host, "testhostname")

        # WHEN a "certificates" relation is formed
        self.rel_id = self.harness.add_relation("certificates", "root-ca")
        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # THEN a CSR is sent
        unit_databag = self.harness.get_relation_data(self.rel_id, self.harness.charm.unit.name)
        self.assertIsNotNone(unit_databag.get("certificate_signing_requests"))
