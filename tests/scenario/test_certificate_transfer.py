import json
from scenario import Relation, State

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
