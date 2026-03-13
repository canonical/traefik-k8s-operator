# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for TraefikIngressCharm._refresh_certs_if_needed."""

from unittest.mock import PropertyMock, patch

from charms.tls_certificates_interface.v4.tls_certificates import CertificateRequestAttributes
from scenario import State


def _make_csr(common_name, sans_dns=None, sans_ip=None):
    """Helper to create a CertificateRequestAttributes."""
    return CertificateRequestAttributes(
        common_name=common_name,
        sans_dns=frozenset(sans_dns or []),
        sans_ip=frozenset(sans_ip or []),
    )


@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="foo.bar"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
class TestRefreshCertsIfNeeded:
    """Tests for _refresh_certs_if_needed."""

    def test_no_change_does_not_call_sync(self, traefik_ctx, traefik_container):
        """When hostnames haven't changed, sync() should NOT be called."""
        csrs = [_make_csr("foo.bar", sans_dns=["foo.bar"])]

        state = State(
            leader=True,
            config={"routing_mode": "path"},
            containers=[traefik_container],
        )

        with traefik_ctx.manager("start", state) as mgr:
            charm = mgr.charm
            charm.csrs = csrs
            with patch.object(charm, "_get_valid_csrs", return_value=csrs):
                with patch.object(charm.certs, "sync") as mock_sync:
                    charm._refresh_certs_if_needed()
                    mock_sync.assert_not_called()

    def test_hostname_added_triggers_sync(self, traefik_ctx, traefik_container):
        """When a new hostname appears, sync() should be called."""
        old_csrs = [_make_csr("foo.bar", sans_dns=["foo.bar"])]
        new_csrs = [
            _make_csr("foo.bar", sans_dns=["foo.bar"]),
            _make_csr("new.host", sans_dns=["new.host"]),
        ]

        state = State(
            leader=True,
            config={"routing_mode": "path"},
            containers=[traefik_container],
        )

        with traefik_ctx.manager("start", state) as mgr:
            charm = mgr.charm
            charm.csrs = old_csrs
            with patch.object(charm, "_get_valid_csrs", return_value=new_csrs):
                with patch.object(charm.certs, "sync") as mock_sync:
                    charm._refresh_certs_if_needed()
                    mock_sync.assert_called_once()

    def test_hostname_removed_triggers_sync(self, traefik_ctx, traefik_container):
        """When a hostname is removed, sync() should be called."""
        old_csrs = [
            _make_csr("foo.bar", sans_dns=["foo.bar"]),
            _make_csr("removed.host", sans_dns=["removed.host"]),
        ]
        new_csrs = [_make_csr("foo.bar", sans_dns=["foo.bar"])]

        state = State(
            leader=True,
            config={"routing_mode": "path"},
            containers=[traefik_container],
        )

        with traefik_ctx.manager("start", state) as mgr:
            charm = mgr.charm
            charm.csrs = old_csrs
            with patch.object(charm, "_get_valid_csrs", return_value=new_csrs):
                with patch.object(charm.certs, "sync") as mock_sync:
                    charm._refresh_certs_if_needed()
                    mock_sync.assert_called_once()

    def test_hostname_changed_triggers_sync(self, traefik_ctx, traefik_container):
        """When hostname changes (e.g., DNS changed), sync() should be called."""
        old_csrs = [_make_csr("old.host", sans_dns=["old.host"])]
        new_csrs = [_make_csr("new.host", sans_dns=["new.host"])]

        state = State(
            leader=True,
            config={"routing_mode": "path"},
            containers=[traefik_container],
        )

        with traefik_ctx.manager("start", state) as mgr:
            charm = mgr.charm
            charm.csrs = old_csrs
            with patch.object(charm, "_get_valid_csrs", return_value=new_csrs):
                with patch.object(charm.certs, "sync") as mock_sync:
                    charm._refresh_certs_if_needed()
                    mock_sync.assert_called_once()

    def test_sans_ip_changed_triggers_sync(self, traefik_ctx, traefik_container):
        """When SANs IP changes, sync() should be called."""
        old_csrs = [_make_csr("10.0.0.1", sans_ip=["10.0.0.1"])]
        new_csrs = [_make_csr("10.0.0.1", sans_ip=["10.0.0.1", "10.0.0.2"])]

        state = State(
            leader=True,
            config={"routing_mode": "path"},
            containers=[traefik_container],
        )

        with traefik_ctx.manager("start", state) as mgr:
            charm = mgr.charm
            charm.csrs = old_csrs
            with patch.object(charm, "_get_valid_csrs", return_value=new_csrs):
                with patch.object(charm.certs, "sync") as mock_sync:
                    charm._refresh_certs_if_needed()
                    mock_sync.assert_called_once()
