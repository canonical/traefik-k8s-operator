# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from ops import Container
from scenario import PeerRelation, Relation, State

from traefik import Traefik

INGRESS_APP_DATA = {
    "model": "test-model",
    "name": "appname",
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


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
class TestTlsWithExternalHostname:

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_external_hostname_is_set_after_relation_joins(
        self, _mock_lb, traefik_ctx, traefik_container
    ):
        """When external_hostname is set AFTER the certs relation exists, a CSR is sent."""
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )
        certs_rel = Relation(
            endpoint="certificates",
            remote_app_name="root-ca",
        )
        peer_rel = PeerRelation(endpoint="peers")

        # STEP 1: Certs relation created — no external_hostname yet.
        # The TLS library observes relation_created and generates a private key.
        state_0 = State(
            leader=True,
            config={"external_hostname": ""},
            relations=[ingress_rel, certs_rel, peer_rel],
            containers=[traefik_container],
        )
        state_1 = traefik_ctx.run(certs_rel.created_event, state_0)
        certs_out = state_1.get_relations("certificates")[0]
        assert certs_out.local_app_data.get("certificate_signing_requests") is None

        # STEP 2: external_hostname is set — config_changed fires.
        # The TLS library also observes config_changed (via refresh_events)
        state_2 = traefik_ctx.run(
            "config_changed",
            state_1.replace(config={"external_hostname": "testhostname"}),
        )

        # THEN a CSR is sent in the app databag
        certs_out = state_2.get_relations("certificates")[0]
        assert certs_out.local_app_data.get("certificate_signing_requests") is not None

    def test_external_hostname_is_set_before_relation_joins(
        self, traefik_ctx, traefik_container
    ):
        """When external_hostname is already set when certs relation is created, a CSR is sent."""
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )
        certs_rel = Relation(
            endpoint="certificates",
            remote_app_name="root-ca",
        )
        peer_rel = PeerRelation(endpoint="peers")

        # Hostname is already set when the certs relation is created
        state = State(
            leader=True,
            config={"external_hostname": "testhostname"},
            relations=[ingress_rel, certs_rel, peer_rel],
            containers=[traefik_container],
        )

        # WHEN the certificates relation is created
        out = traefik_ctx.run(certs_rel.created_event, state)

        # THEN a CSR is sent in the app databag
        certs_out = out.get_relations("certificates")[0]
        assert certs_out.local_app_data.get("certificate_signing_requests") is not None


@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
def test_get_certs(traefik_ctx, traefik_container, mock_provider_certificate):
    """Verify _get_certs returns a properly formatted and ordered certificate chain."""
    certs_rel = Relation(
        endpoint="certificates",
        remote_app_name="certificates_provider",
    )
    peer_rel = PeerRelation(endpoint="peers")

    state = State(
        leader=True,
        config={"routing_mode": "path"},
        relations=[certs_rel, peer_rel],
        containers=[traefik_container],
    )

    with traefik_ctx.manager(certs_rel.changed_event, state) as mgr:
        charm = mgr.charm
        mock_csr = MagicMock()
        mock_csr.common_name = "example.com"
        charm.csrs = [mock_csr]

        with patch.object(
            charm.certs,
            "get_assigned_certificate",
            return_value=(mock_provider_certificate, "mock private key"),
        ):
            certs = charm._get_certs()

        assert certs["example.com"]["chain"].startswith(
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
        udp_entrypoints={},
        traefik_route_static_configs=[],
        topology=MagicMock(),
    )
    traefik.cleanup_tls_configuration()
    if not tls_enabled:
        container_mock.remove_path.assert_called_once()
    else:
        container_mock.remove_path.assert_not_called()
