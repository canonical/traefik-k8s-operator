#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from traefik import CA_CERTS_DIR, CERTS_DIR, RoutingMode, Traefik


def _new_traefik(container: MagicMock) -> Traefik:
    return Traefik(
        container=container,
        routing_mode=RoutingMode.PATH,
        tls_enabled=True,
        experimental_forward_auth_enabled=False,
        tcp_entrypoints={},
        udp_entrypoints={},
        traefik_route_static_configs=[],
        topology=MagicMock(),
    )


def test_cleanup_excludes_matching_cert_key_and_ca_names():
    container = MagicMock()
    traefik = _new_traefik(container)

    cert_files = [
        SimpleNamespace(path=f"{CERTS_DIR}/example.com.cert", name="example.com.cert"),
        SimpleNamespace(path=f"{CERTS_DIR}/example.com.key", name="example.com.key"),
        SimpleNamespace(path=f"{CERTS_DIR}/stale.example.cert", name="stale.example.cert"),
        SimpleNamespace(path=f"{CERTS_DIR}/stale.example.key", name="stale.example.key"),
    ]
    ca_files = [
        SimpleNamespace(
            path=f"{CA_CERTS_DIR}/example.com.traefik-charm.crt",
            name="example.com.traefik-charm.crt",
        ),
        SimpleNamespace(
            path=f"{CA_CERTS_DIR}/stale.example.traefik-charm.crt",
            name="stale.example.traefik-charm.crt",
        ),
    ]

    container.isdir.side_effect = lambda path: path in (CERTS_DIR, CA_CERTS_DIR)
    container.list_files.side_effect = lambda path: cert_files if path == CERTS_DIR else ca_files

    traefik._clean_up_certificates_in_traefik_container(excluded_certs={"example.com": {}})

    removed_paths = {call.args[0] for call in container.remove_path.call_args_list}
    assert f"{CERTS_DIR}/stale.example.cert" in removed_paths
    assert f"{CERTS_DIR}/stale.example.key" in removed_paths
    assert f"{CA_CERTS_DIR}/stale.example.traefik-charm.crt" in removed_paths
    assert f"{CERTS_DIR}/example.com.cert" not in removed_paths
    assert f"{CERTS_DIR}/example.com.key" not in removed_paths
    assert f"{CA_CERTS_DIR}/example.com.traefik-charm.crt" not in removed_paths


def test_update_cert_configuration_removes_only_stale_local_cert(tmp_path):
    container = MagicMock()
    traefik = _new_traefik(container)

    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "example.com.cert").write_text("old-cert")
    (certs_dir / "stale.example.cert").write_text("stale")

    certs = {
        "example.com": {
            "chain": "new-cert-chain",
            "key": "new-private-key",
            "ca": "new-ca",
        }
    }

    with patch("traefik.CERTS_DIR", certs_dir), patch.object(
        traefik, "_clean_up_certificates_in_traefik_container"
    ), patch.object(traefik, "update_ca_certs"):
        traefik.update_cert_configuration(certs)

    assert (certs_dir / "example.com.cert").exists()
    assert not (certs_dir / "stale.example.cert").exists()
