# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import ops.testing
import pytest
from ops import Container
from ops.framework import Framework
from ops.testing import Harness

from charm import TraefikIngressCharm
from traefik import Traefik

ops.testing.SIMULATE_CAN_CONNECT = True

INGRESS_APP_DATA = {
    "model": '"test-model"',
    "name": '"appname"',
    "port": "5555",
}
INGRESS_UNIT_DATA = {
    "host": '"example.local"',
}


@pytest.fixture(scope="function", name="mock_provider_certificate")
def mock_provider_certificate_fixture() -> MagicMock:
    """Mock tls certificate from a tls provider charm."""
    cert = "-----BEGIN CERTIFICATE-----mock certificate-----END CERTIFICATE-----"
    ca = "-----BEGIN CERTIFICATE-----mock ca-----END CERTIFICATE-----"
    chain = [
        ("-----BEGIN CERTIFICATE-----mock ca-----END CERTIFICATE-----"),
        ("-----BEGIN CERTIFICATE-----mock certificate-----END CERTIFICATE-----"),
    ]
    provider_cert_mock = MagicMock()
    provider_cert_mock.certificate = cert
    provider_cert_mock.ca = ca
    provider_cert_mock.chain = chain
    return provider_cert_mock


def reinstantiate_charm(harness: Harness):
    harness._framework = Framework(
        harness._storage, harness._charm_dir, harness._meta, harness._model
    )
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
        rel_id = self.harness.add_relation(
            "ingress", "server", app_data=INGRESS_APP_DATA, unit_data=INGRESS_UNIT_DATA
        )
        self.harness.update_relation_data(
            rel_id, "traefik-k8s", {"ingress": '{"url": "https://example.com/test-model-appname"}'}
        )
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


def test_get_certs(monkeypatch: pytest.MonkeyPatch, mock_provider_certificate):
    """Set up a TraefikIngressCharm with mocked relation and get_assigned_certificate method.

    Then, run the _get_certs method.
    The certificate chain should gets properly formatted and ordered.
    """
    monkeypatch.setattr(
        "charm.TLSCertificatesRequiresV4.get_assigned_certificate",
        MagicMock(return_value=(mock_provider_certificate, "mock private key")),
    )
    harness = Harness(TraefikIngressCharm)
    harness.add_relation("certificates", "certificates_provider")
    harness.begin()
    mock_csr = MagicMock()
    mock_csr.common_name = "example.com"
    harness.charm.csrs = [mock_csr]
    assert harness.charm._get_certs()["example.com"]["chain"].startswith(
        mock_provider_certificate.certificate
    )


@pytest.mark.parametrize("tls_enabled", [(True,), (False)])
def test_cleanup_tls_configuration(tls_enabled: bool):
    container_mock = MagicMock(spec=Container)
    container_mock.exists = MagicMock(return_value=True)
    container_mock.can_connect = MagicMock(return_value=True)

    traefik = Traefik(
        container=container_mock,
        routing_mode="path",
        tls_enabled=tls_enabled,
        experimental_forward_auth_enabled=False,
        tcp_entrypoints={},
        traefik_route_static_configs=[],
        topology=MagicMock(),
    )
    traefik.cleanup_tls_configuration()
    if not tls_enabled:
        container_mock.remove_path.assert_called_once()
    else:
        container_mock.remove_path.assert_not_called()
