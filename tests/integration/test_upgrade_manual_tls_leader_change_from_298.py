#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Leadership-change TLS behavior on upgrade from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
   ``manual-tls-certificates`` and ``alertmanager``; sign the CSRs and confirm
   HTTPS works on every unit.
2. Force a leadership change (by stopping the container-agent and its liveness check).
   On revision 298 the TLS private key is not app-scoped, so the newly elected leader
   cannot reproduce the served certificate and its ingress breaks.
3. Assert the ingress URL is indeed broken over HTTPS on leader and not broken on non-leaders.
4. Refresh traefik to the locally built charm (the version under test).
5. Assert the new leader is blocked with "Certificate not available yet" and
    manual-tls has exactly one outstanding CSR.
"""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import (
    MOCK_HOSTNAME,
    NUM_TRAEFIK_UNITS,
    SOURCE_CHANNEL,
    TRAEFIK_CHARM,
)
from helpers import (
    bring_up_certified_traefik,
    force_leader_change,
    get_outstanding_csrs,
    leader_unit_name,
    verify_https_broken_on_unit,
    verify_https_on_unit,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_leader_change_breaks_tls_then_upgrade_blocks_and_requests_certificate(
    juju: jubilant.Juju, traefik_charm, manual_tls_app, alertmanager_app, tmp_path
):
    """A leadership change breaks TLS on rev 298; upgrade blocks and requests a cert."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    alertmanager_url = bring_up_certified_traefik(juju, tmp_path)

    # newly elected leader is expected to break.
    previous_leader = leader_unit_name(juju, TRAEFIK_APP_NAME)
    new_leader = force_leader_change(juju, TRAEFIK_APP_NAME)

    # Trigger any hook on Traefik as it doesn't observe leadership changes automatically.
    juju.config(TRAEFIK_APP_NAME, {"loadbalancer_annotations": " "})

    surviving_units = [
        name
        for name in juju.status().apps[TRAEFIK_APP_NAME].units
        if name != previous_leader
    ]
    juju.wait(
        lambda status: all(
            (
                unit_name in status.apps[TRAEFIK_APP_NAME].units
                and status.apps[TRAEFIK_APP_NAME].units[unit_name].workload_status.current
                == "active"
                and status.apps[TRAEFIK_APP_NAME].units[unit_name].juju_status.current
                == "idle"
            )
            for unit_name in surviving_units
        ),
        timeout=300,
    )
    for unit_name in surviving_units:
        if unit_name == new_leader:
            continue
        verify_https_on_unit(juju, unit_name, alertmanager_url)

    juju.wait(lambda _: len(get_outstanding_csrs(juju)) == 1, timeout=300)
    verify_https_broken_on_unit(juju, new_leader, alertmanager_url)

    # Upgrade to the charm under test.
    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(jubilant.all_agents_idle, timeout=900, delay=5, successes=5)

    status = juju.status()
    leader_status = status.apps[TRAEFIK_APP_NAME].units[new_leader].workload_status
    assert leader_status.current == "blocked", (
        f"expected {new_leader} to be blocked after upgrade, got {leader_status.current!r}"
    )
    assert leader_status.message == "Certificate not available yet", (
        "unexpected blocked message on upgraded leader: "
        f"{leader_status.message!r}"
    )

    outstanding_csrs = get_outstanding_csrs(juju)
    assert len(outstanding_csrs) == 1, (
        "expected exactly one pending CSR on manual-tls after upgrade, "
        f"got {len(outstanding_csrs)}"
    )
