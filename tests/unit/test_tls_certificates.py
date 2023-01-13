# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops.testing
from ops.testing import Harness

from charm import TraefikIngressCharm

ops.testing.SIMULATE_CAN_CONNECT = True


class TlsWithExternalHostname(unittest.TestCase):
    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def setUp(self):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_external_hostname_not_set(self):
        # GIVEN an external hostname is not set
        self.assertFalse(self.harness.charm.config.get("external_hostname"))
        self.assertEquals(self.harness.charm.external_host, "10.0.0.1")

        # WHEN a "certificates" relation is formed
        # THEN the charm logs a warning
        with self.assertLogs(level="WARNING") as cm:
            self.rel_id = self.harness.add_relation("certificates", "root-ca")
            self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        self.assertEquals(
            cm.output,
            [
                "WARNING:charm:Cannot generate CSR: subject is invalid "
                "(hostname is '10.0.0.1', which is probably invalid)"
            ],
        )

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_external_hostname_is_set(self):
        # GIVEN an external hostname is set
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEquals(self.harness.charm.external_host, "testhostname")

        # WHEN a "certificates" relation is formed
        self.rel_id = self.harness.add_relation("certificates", "root-ca")
        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # THEN nothing raises
        # (Nothing to assert)
