import json
from dataclasses import replace

from ops import pebble
from scenario import Relation, State


def test_pebble_restart_when_receiving_ca_cert(traefik_ctx, traefik_container):
    # Initially setting the service to inactive.
    # After a receive-ca-cert relation is added, it must be active.
    # This helps test whether a restart happens when needed.
    traefik_container = replace(traefik_container, service_status={"traefik": pebble.ServiceStatus.INACTIVE})

    certs = [
        "-----BEGIN CERTIFICATE-----\nMIIB...END CERTIFICATE-----",
    ]

    remote_app_data = {
        "certificates": json.dumps(
            certs
        ),
    }

    receive_ca_cert_relation = Relation(
        "receive-ca-cert",
        remote_app_data=remote_app_data,
    )

    state = State(
        leader=True,
        containers=[traefik_container],
        relations=[
            receive_ca_cert_relation
        ],
    )
    # WHEN a relation is joined
    with traefik_ctx.manager(receive_ca_cert_relation.changed_event, state) as mgr:

        state_out = mgr.run()

        traefik = state_out.get_container("traefik")

        # THEN the agent service has started
        assert traefik.services["traefik"].is_running()

