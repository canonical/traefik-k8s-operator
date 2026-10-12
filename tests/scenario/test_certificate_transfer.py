# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from dataclasses import replace

from ops import MaintenanceStatus
from scenario import Relation, State

from traefik import RECV_CA_TEMPLATE, Traefik


def test_ca_cert_written_from_unit_databag_on_pebble_ready(traefik_ctx, traefik_container):
    """On pebble-ready, CA certs read from the relation databag should not have extra quotes."""
    # GIVEN a receive-ca-cert relation with a CA cert in the v0 unit databag format.
    # DatabagModel.dump() serializes each value with json.dumps(), so a string
    # gets wrapped in literal double quotes in the databag.
    ca_cert = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----"

    remote_unit_data = {
        "ca": json.dumps(ca_cert),  # '"-----BEGIN CERTIFICATE..."'
        "certificate": json.dumps(ca_cert),
        "chain": json.dumps([ca_cert]),
    }

    receive_ca_cert_relation = Relation(
        "receive-ca-cert",
        remote_units_data={0: remote_unit_data},
    )

    state = State(
        leader=True,
        containers=[traefik_container],
        relations=[receive_ca_cert_relation],
    )

    # WHEN pebble-ready fires (which calls _update_received_ca_certs without an event)
    state_out = traefik_ctx.run(traefik_container.pebble_ready_event, state)

    # THEN the CA cert file written to disk should NOT have surrounding double quotes
    traefik_fs = state_out.get_container("traefik").get_filesystem(traefik_ctx)
    ca_certs_dir = traefik_fs / "usr" / "local" / "share" / "ca-certificates"

    ca_files = list(ca_certs_dir.glob("receive-ca-cert-*-ca.crt"))
    assert len(ca_files) == 1, f"Expected 1 CA cert file, found: {ca_files}"

    written_content = ca_files[0].read_text()

    # The content must be the raw PEM — no wrapping quotes
    assert not written_content.startswith('"')

    assert not written_content.endswith('"')

    assert written_content == ca_cert


def test_ca_cert_written_from_app_databag_on_pebble_ready(traefik_ctx, traefik_container):
    """On pebble-ready, CA certs in the v1 app databag format are written correctly to disk."""
    # GIVEN a receive-ca-cert relation with a CA cert in the v1 app databag format.
    # The provider app databag stores the cert as a JSON-encoded list under "certificates".
    ca_cert = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----"

    receive_ca_cert_relation = Relation(
        "receive-ca-cert",
        remote_app_data={
            "certificates": json.dumps([ca_cert]),
            "version": "1",
        },
    )

    state = State(
        leader=True,
        containers=[traefik_container],
        relations=[receive_ca_cert_relation],
    )

    # WHEN pebble-ready fires (which calls _update_received_ca_certs without an event)
    state_out = traefik_ctx.run(traefik_container.pebble_ready_event, state)

    # THEN the CA cert file written to disk should contain the raw PEM
    traefik_fs = state_out.get_container("traefik").get_filesystem(traefik_ctx)
    ca_certs_dir = traefik_fs / "usr" / "local" / "share" / "ca-certificates"

    ca_files = list(ca_certs_dir.glob("receive-ca-cert-*-ca.crt"))
    assert len(ca_files) == 1, f"Expected 1 CA cert file, found: {ca_files}"

    written_content = ca_files[0].read_text()

    assert not written_content.startswith('"')
    assert not written_content.endswith('"')
    assert written_content == ca_cert


def test_pebble_ready_does_not_install_ca_when_container_is_unreachable(
    traefik_ctx, traefik_container
):
    """Pebble-ready should return before installing CAs when the container is unreachable."""
    container = replace(traefik_container, can_connect=False)
    ca_cert = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----"
    receive_ca_cert_relation = Relation(
        "receive-ca-cert",
        remote_app_data={
            "certificates": json.dumps([ca_cert]),
            "version": "1",
        },
    )
    state = State(
        leader=True,
        containers=[container],
        relations=[receive_ca_cert_relation],
    )

    state_out = traefik_ctx.run(container.pebble_ready_event, state)

    traefik_fs = state_out.get_container("traefik").get_filesystem(traefik_ctx)
    ca_certs_dir = traefik_fs / "usr" / "local" / "share" / "ca-certificates"
    assert not list(ca_certs_dir.glob("receive-ca-cert-*-ca.crt"))


def test_received_ca_cert_is_installed_before_traefik_restarts(
    traefik_ctx, traefik_container, monkeypatch
):
    """Received CAs must enter system trust before Pebble starts Traefik."""
    ca_cert = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----"
    receive_ca_cert_relation = Relation(
        "receive-ca-cert",
        remote_app_data={
            "certificates": json.dumps([ca_cert]),
            "version": "1",
        },
    )
    ca_path = RECV_CA_TEMPLATE.substitute(rel_id=receive_ca_cert_relation.relation_id)
    original_restart = Traefik.restart

    def assert_ca_is_installed_before_restart(traefik):
        assert traefik._container.exists(ca_path)
        original_restart(traefik)

    monkeypatch.setattr(Traefik, "restart", assert_ca_is_installed_before_restart)

    state = State(
        leader=True,
        containers=[traefik_container],
        relations=[receive_ca_cert_relation],
    )

    traefik_ctx.run(traefik_container.pebble_ready_event, state)


def test_relation_add_does_not_leave_status_in_restart(traefik_ctx, traefik_container):
    """After receive-ca-cert relation changes, unit status must not be stuck in maintenance."""
    # GIVEN a receive-ca-cert relation (no cert data needed — the charm only restarts on the event)
    receive_ca_cert_relation = Relation("receive-ca-cert")

    state = State(
        leader=True,
        containers=[traefik_container],
        relations=[receive_ca_cert_relation],
    )

    # WHEN a certificate_set_updated event fires (triggered by relation-changed)
    state_out = traefik_ctx.run(receive_ca_cert_relation.changed_event, state)

    # THEN the unit is not stuck with "restarting traefik..." maintenance status
    assert state_out.unit_status != MaintenanceStatus("restarting traefik...")


def test_relation_remove_does_not_leave_status_in_restart(traefik_ctx, traefik_container):
    """After receive-ca-cert relation is removed, unit status must not be stuck in maintenance."""
    # GIVEN a receive-ca-cert relation already in the state
    receive_ca_cert_relation = Relation("receive-ca-cert")

    state = State(
        leader=True,
        containers=[traefik_container],
        relations=[receive_ca_cert_relation],
    )

    # WHEN a certificates_removed event fires (triggered by relation-broken)
    state_out = traefik_ctx.run(receive_ca_cert_relation.broken_event, state)

    # THEN the unit is not stuck with "restarting traefik..." maintenance status
    assert state_out.unit_status != MaintenanceStatus("restarting traefik...")
