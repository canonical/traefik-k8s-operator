# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import PropertyMock, patch

import ops.testing
from ops.framework import Framework
from ops.testing import Harness

from charm import TraefikIngressCharm

ops.testing.SIMULATE_CAN_CONNECT = True

INGRESS_APP_DATA = {
    "model": '"test-model"',
    "name": '"appname"',
    "port": "5555",
}
INGRESS_UNIT_DATA = {
    "host": '"example.local"',
}

def reinstantiate_charm(harness: Harness):
    harness._framework = Framework(
            harness._storage, harness._charm_dir, harness._meta, harness._model)
    harness._charm = None
    harness.begin()

class TlsWithExternalHostname(unittest.TestCase):
    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def setUp(self, mock_get_loadbalancer_status):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)
        self.harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)
        self.harness.handle_exec(
            "traefik", ["find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"], result=0
        )

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness.set_leader(True)
        self.harness.container_pebble_ready("traefik")
        self.harness.begin_with_initial_hooks()
        rel_id = self.harness.add_relation("ingress", "server", app_data=INGRESS_APP_DATA, unit_data=INGRESS_UNIT_DATA)
        self.harness.update_relation_data(rel_id, "traefik-k8s", {"ingress": '{"url": "https://example.com/test-model-appname"}'})
        reinstantiate_charm(self.harness)

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def test_external_hostname_is_set_after_relation_joins(self, mock_get_loadbalancer_status):
        # GIVEN an external hostname is not set
        self.assertFalse(self.harness.charm.config.get("external_hostname"))
        self.assertEqual(self.harness.charm.ingressed_address, "10.0.0.1")

        # WHEN a "certificates" relation is formed
        # THEN the charm logs an appropriate DEBUG line
        self.rel_id = self.harness.add_relation("certificates", "root-ca")
        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # AND WHEN an external hostname is set
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEqual(self.harness.charm.ingressed_address, "testhostname")
        # AND when a root ca joins

        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # THEN a CSR is sent
        unit_databag = self.harness.get_relation_data(self.rel_id, self.harness.charm.unit.name)
        self.assertIsNotNone(unit_databag.get("certificate_signing_requests"))

    def test_external_hostname_is_set_before_relation_joins(self):
        # GIVEN an external hostname is set
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEqual(self.harness.charm.ingressed_address, "testhostname")

        # WHEN a "certificates" relation is formed
        self.rel_id = self.harness.add_relation("certificates", "root-ca")
        self.harness.add_relation_unit(self.rel_id, "root-ca/0")

        # THEN a CSR is sent
        unit_databag = self.harness.get_relation_data(self.rel_id, self.harness.charm.unit.name)
        print(unit_databag)
        self.assertIsNotNone(unit_databag.get("certificate_signing_requests"))
