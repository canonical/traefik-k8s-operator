# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from ops import Container
from ops.model import BlockedStatus
from scenario import PeerRelation, Relation, Secret, State

from charm import TLS_KEY_LABEL
from traefik import Traefik

INGRESS_APP_DATA = {
    "model": "test-model",
    "name": "appname",
    "port": "5555",
}
INGRESS_UNIT_DATA = {
    "host": '"example.local"',
}

MOCK_CERT = "-----BEGIN CERTIFICATE-----mock cert-----END CERTIFICATE-----"
MOCK_CA = "-----BEGIN CERTIFICATE-----mock ca-----END CERTIFICATE-----"
MOCK_KEY = "-----BEGIN RSA PRIVATE KEY-----mock key-----END RSA PRIVATE KEY-----"
MOCK_CHAIN = f"{MOCK_CERT}\n\n{MOCK_CA}"


def _mock_provider_certificate():
    """Create a mock provider certificate."""
    provider_cert = MagicMock()
    provider_cert.certificate = MOCK_CERT
    provider_cert.ca = MOCK_CA
    provider_cert.chain = [MOCK_CA, MOCK_CERT]
    return provider_cert


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


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
class TestLeaderPublishesCerts:
    """Test that the leader publishes certs to peer databag and Juju secret."""

    def test_leader_publishes_public_certs_to_databag_and_keys_to_secret(
        self, traefik_ctx, traefik_container
    ):
        """Leader stores chain+CA in peer app databag and private keys in secret."""
        certs_rel = Relation(endpoint="certificates", remote_app_name="root-ca")
        peer_rel = PeerRelation(endpoint="peers")
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )

        state = State(
            leader=True,
            config={"external_hostname": "testhostname"},
            relations=[certs_rel, peer_rel, ingress_rel],
            containers=[traefik_container],
        )

        with traefik_ctx.manager(certs_rel.changed_event, state) as mgr:
            charm = mgr.charm
            mock_csr = MagicMock()
            mock_csr.common_name = "testhostname"
            charm.csrs = [mock_csr]

            with patch.object(
                charm.certs,
                "get_assigned_certificate",
                return_value=(_mock_provider_certificate(), MOCK_KEY),
            ):
                charm._sync_certs_to_peer_databag()
                certs = charm._get_certs()

            # Verify certs were returned correctly
            assert "testhostname" in certs
            assert certs["testhostname"]["key"] == MOCK_KEY
            assert certs["testhostname"]["ca"] == MOCK_CA

            # Verify public certs were written to peer databag
            peer_relation = charm.model.get_relation("peers")
            raw_tls_certs = peer_relation.data[charm.app].get("tls_certs")
            assert raw_tls_certs is not None
            public_certs = json.loads(raw_tls_certs)
            assert "testhostname" in public_certs
            assert "chain" in public_certs["testhostname"]
            assert "ca" in public_certs["testhostname"]
            # Private key must NOT be in the databag
            assert "key" not in public_certs["testhostname"]

            # Verify private keys were stored in a Juju secret
            secret = charm.model.get_secret(label=TLS_KEY_LABEL)
            secret_content = secret.get_content(refresh=True)
            raw_keys = secret_content.get("private-keys")
            assert raw_keys is not None
            private_keys = json.loads(raw_keys)
            assert private_keys["testhostname"] == MOCK_KEY

    def test_leader_clears_databag_when_tls_disabled(
        self, traefik_ctx, traefik_container
    ):
        """When TLS is disabled, leader clears peer databag and secret content."""
        existing_public_certs = json.dumps(
            {"old-host": {"chain": "old-chain", "ca": "old-ca"}}
        )
        existing_secret = Secret(
            id="secret:tls-keys",
            contents={0: {"private-keys": json.dumps({"old-host": "old-key"})}},
            label=TLS_KEY_LABEL,
            owner="app",
        )
        peer_rel = PeerRelation(
            endpoint="peers",
            local_app_data={"tls_certs": existing_public_certs},
        )

        state = State(
            leader=True,
            config={"external_hostname": "testhostname"},
            # No certificates relation -> TLS is disabled
            relations=[peer_rel],
            containers=[traefik_container],
            secrets=[existing_secret],
        )

        out = traefik_ctx.run("config_changed", state)

        # tls_certs should be removed from peer app databag
        peer_out = out.get_relations("peers")[0]
        assert "tls_certs" not in peer_out.local_app_data

        # Secret should be removed
        tls_secrets = [s for s in out.secrets if s.label == TLS_KEY_LABEL]
        if tls_secrets:
            # The scenario mock may keep the object with empty contents
            assert tls_secrets[0].contents == {}


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
class TestNonLeaderReadsCerts:
    """Test that non-leader units read certs from peer databag and secret."""

    def test_non_leader_reads_certs_from_peer_databag_and_secret(
        self, traefik_ctx, traefik_container
    ):
        """Non-leader reads public certs from databag and private keys from secret."""
        public_certs = {"testhostname": {"chain": MOCK_CHAIN, "ca": MOCK_CA}}
        private_keys = {"testhostname": MOCK_KEY}

        tls_secret = Secret(
            id="secret:tls-keys",
            contents={0: {"private-keys": json.dumps(private_keys)}},
            label=TLS_KEY_LABEL,
            owner="app",
        )

        certs_rel = Relation(endpoint="certificates", remote_app_name="root-ca")
        peer_rel = PeerRelation(
            endpoint="peers",
            local_app_data={
                "tls_certs": json.dumps(public_certs),
            },
        )
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )

        state = State(
            leader=False,
            config={"external_hostname": "testhostname"},
            relations=[certs_rel, peer_rel, ingress_rel],
            containers=[traefik_container],
            secrets=[tls_secret],
        )

        with traefik_ctx.manager(peer_rel.changed_event, state) as mgr:
            charm = mgr.charm
            certs = charm._get_certs()

            assert "testhostname" in certs
            assert certs["testhostname"]["key"] == MOCK_KEY

    def test_non_leader_blocked_when_no_tls_certs_in_databag(
        self, traefik_ctx, traefik_container
    ):
        """Non-leader sets BlockedStatus when no tls_certs in peer databag."""
        certs_rel = Relation(endpoint="certificates", remote_app_name="root-ca")
        peer_rel = PeerRelation(endpoint="peers")
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )

        state = State(
            leader=False,
            config={"external_hostname": "testhostname"},
            relations=[certs_rel, peer_rel, ingress_rel],
            containers=[traefik_container],
        )

        with traefik_ctx.manager(peer_rel.changed_event, state) as mgr:
            charm = mgr.charm
            certs = charm._get_certs()

            assert "testhostname" not in certs
            assert isinstance(charm.unit.status, BlockedStatus)
            assert "waiting for leader" in charm.unit.status.message.lower()

    def test_non_leader_blocked_when_secret_missing(
        self, traefik_ctx, traefik_container
    ):
        """Non-leader sets BlockedStatus when the Juju secret doesn't exist."""
        public_certs = {"testhostname": {"chain": MOCK_CHAIN, "ca": MOCK_CA}}

        certs_rel = Relation(endpoint="certificates", remote_app_name="root-ca")
        peer_rel = PeerRelation(
            endpoint="peers",
            local_app_data={
                "tls_certs": json.dumps(public_certs),
            },
        )
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )

        state = State(
            leader=False,
            config={"external_hostname": "testhostname"},
            relations=[certs_rel, peer_rel, ingress_rel],
            containers=[traefik_container],
        )

        with traefik_ctx.manager(peer_rel.changed_event, state) as mgr:
            charm = mgr.charm
            certs = charm._get_certs()

            assert "testhostname" not in certs
            assert isinstance(charm.unit.status, BlockedStatus)

    def test_non_leader_blocked_when_private_key_missing_for_hostname(
        self, traefik_ctx, traefik_container
    ):
        """Non-leader raises error when private key doesn't exist for a hostname."""
        public_certs = {"testhostname": {"chain": MOCK_CHAIN, "ca": MOCK_CA}}
        private_keys = {"other-hostname": "some-key"}

        tls_secret = Secret(
            id="secret:tls-keys",
            contents={0: {"private-keys": json.dumps(private_keys)}},
            label=TLS_KEY_LABEL,
            owner="app",
        )

        certs_rel = Relation(endpoint="certificates", remote_app_name="root-ca")
        peer_rel = PeerRelation(
            endpoint="peers",
            local_app_data={
                "tls_certs": json.dumps(public_certs),
            },
        )
        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="server",
            remote_app_data=INGRESS_APP_DATA,
            remote_units_data={0: INGRESS_UNIT_DATA},
        )

        state = State(
            leader=False,
            config={"external_hostname": "testhostname"},
            relations=[certs_rel, peer_rel, ingress_rel],
            containers=[traefik_container],
            secrets=[tls_secret],
        )

        with traefik_ctx.manager(peer_rel.changed_event, state) as mgr:
            charm = mgr.charm
            certs = charm._get_certs()

            assert "testhostname" not in certs
            assert isinstance(charm.unit.status, BlockedStatus)
