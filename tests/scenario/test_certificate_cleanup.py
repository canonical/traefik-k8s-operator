# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from unittest.mock import patch

from scenario import State

from traefik import CERTS_DIR


def test_container_cleanup_keeps_excluded_cert_key_and_ca(traefik_ctx, traefik_container):
    state = State(
        leader=True,
        config={"routing_mode": "path"},
        containers=[traefik_container],
    )

    with traefik_ctx.manager("start", state) as mgr:
        charm = mgr.charm
        container = charm.unit.get_container("traefik")

        patched_ca_dir = Path("/opt/traefik/ca-certificates")
        with patch("traefik.CA_CERTS_DIR", patched_ca_dir):
            container.push(f"{CERTS_DIR}/example.com.cert", "cert", make_dirs=True)
            container.push(f"{CERTS_DIR}/example.com.key", "key", make_dirs=True)
            container.push(f"{CERTS_DIR}/stale.example.cert", "stale-cert", make_dirs=True)
            container.push(f"{CERTS_DIR}/stale.example.key", "stale-key", make_dirs=True)

            container.push(
                f"{patched_ca_dir}/example.com.traefik-charm.crt", "ca", make_dirs=True
            )
            container.push(
                f"{patched_ca_dir}/stale.example.traefik-charm.crt",
                "stale-ca",
                make_dirs=True,
            )

            charm.traefik._clean_up_certificates_in_traefik_container(
                excluded_certs={"example.com": {}}
            )

            assert container.exists(f"{CERTS_DIR}/example.com.cert")
            assert container.exists(f"{CERTS_DIR}/example.com.key")
            assert not container.exists(f"{CERTS_DIR}/stale.example.cert")
            assert not container.exists(f"{CERTS_DIR}/stale.example.key")

            assert container.exists(f"{patched_ca_dir}/example.com.traefik-charm.crt")
            assert not container.exists(f"{patched_ca_dir}/stale.example.traefik-charm.crt")


def test_update_cert_configuration_removes_only_stale_local_cert(traefik_ctx, traefik_container, tmp_path):
    state = State(
        leader=True,
        config={"routing_mode": "path"},
        containers=[traefik_container],
    )

    with traefik_ctx.manager("start", state) as mgr:
        charm = mgr.charm
        local_certs_dir = tmp_path / "certs"
        local_certs_dir.mkdir()
        (local_certs_dir / "example.com.cert").write_text("old-cert")
        (local_certs_dir / "stale.example.cert").write_text("stale")

        certs = {
            "example.com": {
                "chain": "new-cert-chain",
                "key": "new-private-key",
                "ca": "new-ca",
            }
        }

        with patch("traefik.CERTS_DIR", local_certs_dir), patch.object(
            charm.traefik, "_clean_up_certificates_in_traefik_container"
        ), patch.object(charm.traefik, "update_ca_certs"):
            charm.traefik.update_cert_configuration(certs)

        assert (local_certs_dir / "example.com.cert").exists()
        assert not (local_certs_dir / "stale.example.cert").exists()
