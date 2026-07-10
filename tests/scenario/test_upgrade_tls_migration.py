# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for re-using an existing TLS private key across upgrades."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from ops.model import SecretNotFoundError
from scenario import PeerRelation, Relation, State

CERTIFICATES_RELATION_NAME = "certificates"
TLS_CERTIFICATES_LIBID = "afd8c2bccf834997afce12c2706d2ede"
TLS_KEY_LABEL = "tls-key"
PRIVATE_KEY_FIELD = "private-key"




def _unit_key_label(unit_number="0"):
    return f"{TLS_CERTIFICATES_LIBID}-private-key-{unit_number}-{CERTIFICATES_RELATION_NAME}"


def _fake_secret(content):
    secret = MagicMock()
    secret.get_content.return_value = content
    return secret


def _tls_key_secret(private_keys):
    return _fake_secret({"private-keys": json.dumps(private_keys)})


def _make_get_secret(**secrets_by_label):
    """Build a get_secret side effect that resolves secrets by label."""

    def _get_secret(*, id=None, label=None):
        secret = secrets_by_label.get(label) if label is not None else None
        if secret is None:
            raise SecretNotFoundError(label)
        return secret

    return _get_secret


def _state(traefik_container, leader=True, with_certificates=True):
    relations: list = [PeerRelation(endpoint="peers")]
    if with_certificates:
        relations.append(
            Relation(
                endpoint=CERTIFICATES_RELATION_NAME,
                interface="tls-certificates",
                remote_app_name="ca",
            )
        )
    return State(
        leader=leader,
        config={"routing_mode": "path"},
        relations=relations,
        containers=[traefik_container],
    )


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
class TestReadKeyFromTlsKeySecret:
    """Tests for reading the library key from the app-owned ``tls-key`` secret."""

    def test_missing_secret_returns_none(self, traefik_ctx, traefik_container):
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model, "get_secret", side_effect=_make_get_secret()
            ):
                assert mgr.charm._read_key_from_tls_key_secret() is None

    def test_returns_library_key_excluding_local_config(self, traefik_ctx, traefik_container):
        """The 'local-config' entry (user config key) is skipped."""
        secret = _tls_key_secret({"local-config": "mock-data", "example.com": "mock-data"})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{TLS_KEY_LABEL: secret}),
            ):
                assert mgr.charm._read_key_from_tls_key_secret() == "mock-data"

    def test_only_local_config_returns_none(self, traefik_ctx, traefik_container):
        """A secret holding only the user 'local-config' key has nothing to migrate."""
        secret = _tls_key_secret({"local-config": "mock-data"})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{TLS_KEY_LABEL: secret}),
            ):
                assert mgr.charm._read_key_from_tls_key_secret() is None

    def test_malformed_json_raises(self, traefik_ctx, traefik_container):
        secret = _fake_secret({"private-keys": "not-json"})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{TLS_KEY_LABEL: secret}),
            ):
                with pytest.raises(RuntimeError):
                    mgr.charm._read_key_from_tls_key_secret()

    def test_empty_map_raises(self, traefik_ctx, traefik_container):
        """A well-formed but empty 'private-keys' map is treated as corruption."""
        secret = _tls_key_secret({})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{TLS_KEY_LABEL: secret}),
            ):
                with pytest.raises(RuntimeError):
                    mgr.charm._read_key_from_tls_key_secret()


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
class TestReadKeyFromUnitSecret:
    """Tests for reading the key from the legacy per-unit (Mode.UNIT) secret."""

    def test_missing_secret_returns_none(self, traefik_ctx, traefik_container):
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model, "get_secret", side_effect=_make_get_secret()
            ):
                assert mgr.charm._read_key_from_unit_secret() is None

    def test_returns_key_from_unit_secret(self, traefik_ctx, traefik_container):
        secret = _fake_secret({PRIVATE_KEY_FIELD: "mock-data"})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{_unit_key_label(): secret}),
            ):
                assert mgr.charm._read_key_from_unit_secret() == "mock-data"

    def test_missing_key_content_raises(self, traefik_ctx, traefik_container):
        secret = _fake_secret({})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{_unit_key_label(): secret}),
            ):
                with pytest.raises(RuntimeError):
                    mgr.charm._read_key_from_unit_secret()


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("traefik.Traefik.update_cert_configuration", MagicMock())
class TestLoadExistingPrivateKey:
    """Tests for the public entry point that selects and validates the key."""

    def test_both_secrets_returns_none(self, traefik_ctx, traefik_container):
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch("charm.PrivateKey") as mock_pk, patch.object(
                mgr.charm.model, "get_secret", side_effect=_make_get_secret()
            ):
                assert mgr.charm._load_existing_private_key() is None
                mock_pk.from_string.assert_not_called()

    def test_tls_key_secret_takes_precedence(self, traefik_ctx, traefik_container):
        """When both layouts exist, the app-owned tls-key wins."""
        tls_key_value = "tls-secret-key"
        unit_secret_value = "unit-secret-key"
        tls_key = _tls_key_secret({"example.com": tls_key_value})
        unit_secret = _fake_secret({PRIVATE_KEY_FIELD: unit_secret_value})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch("charm.PrivateKey") as mock_pk, patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(
                    **{TLS_KEY_LABEL: tls_key, _unit_key_label(): unit_secret}
                ),
            ):
                mock_pk.from_string.return_value.is_valid.return_value = True
                result = mgr.charm._load_existing_private_key()
                mock_pk.from_string.assert_called_once_with(tls_key_value)
                assert result is mock_pk.from_string.return_value

    def test_falls_back_to_unit_secret(self, traefik_ctx, traefik_container):
        unit_secret_value = "unit-secret-key"
        unit_secret = _fake_secret({PRIVATE_KEY_FIELD: unit_secret_value})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch("charm.PrivateKey") as mock_pk, patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{_unit_key_label(): unit_secret}),
            ):
                mock_pk.from_string.return_value.is_valid.return_value = True
                result = mgr.charm._load_existing_private_key()
                mock_pk.from_string.assert_called_once_with(unit_secret_value)
                assert result is mock_pk.from_string.return_value

    def test_invalid_key_raises(self, traefik_ctx, traefik_container):
        tls_key = _tls_key_secret({"example.com": "mock-data"})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch("charm.PrivateKey") as mock_pk, patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{TLS_KEY_LABEL: tls_key}),
            ):
                mock_pk.from_string.return_value.is_valid.return_value = False
                with pytest.raises(RuntimeError):
                    mgr.charm._load_existing_private_key()

    def test_unparseable_key_raises(self, traefik_ctx, traefik_container):
        tls_key = _tls_key_secret({"example.com": "mock-data"})
        state = _state(traefik_container)
        with traefik_ctx.manager("config-changed", state) as mgr:
            with patch("charm.PrivateKey") as mock_pk, patch.object(
                mgr.charm.model,
                "get_secret",
                side_effect=_make_get_secret(**{TLS_KEY_LABEL: tls_key}),
            ):
                mock_pk.from_string.side_effect = ValueError("bad pem")
                with pytest.raises(RuntimeError):
                    mgr.charm._load_existing_private_key()

