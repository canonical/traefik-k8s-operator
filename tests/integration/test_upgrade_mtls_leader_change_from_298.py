#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Leadership-change TLS behavior on upgrade from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
   ``manual-tls-certificates`` and ``alertmanager``; sign the CSRs and confirm
   HTTPS works on every unit.
2. Force a leadership change; the old leader is restored afterwards.
   On revision 298 the TLS private key is not app-scoped, so the newly elected
   leader cannot reproduce the served certificate and its ingress breaks.
3. Assert the ingress URL is broken over HTTPS on the new leader only; all other
   units (including the restored old leader) continue to serve correctly.
4. Refresh traefik to the locally built charm (the version under test).
5. Assert the new leader is active with "Certificate not available yet" and
   manual-tls has exactly one outstanding CSR.
"""

import logging

import jubilant
import pytest
import requests
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import (
    MOCK_HOSTNAME,
    NUM_TRAEFIK_UNITS,
    SOURCE_CHANNEL,
    TRAEFIK_CHARM,
)
from helpers import (
    all_settled,
    assert_traefik_revision,
    bring_up_certified_traefik,
    force_leader_change,
    get_outstanding_csrs,
    verify_https_on_unit,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_leader_change_breaks_tls_then_upgrade_blocks_and_requests_certificate(
    juju: jubilant.Juju, traefik_charm, mtls_app, alertmanager_app, tmp_path
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
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    alertmanager_url = bring_up_certified_traefik(juju, tmp_path)

    # newly elected leader is expected to break.
    new_leader = force_leader_change(juju, TRAEFIK_APP_NAME)

    juju.wait(all_settled, error=jubilant.any_error, timeout=300, delay=5, successes=5)

    # All units except the new leader should still serve valid HTTPS (their per-unit
    # private keys are intact). The new leader lost the old leader's key on rev 298.
    working_units = [
        name
        for name in juju.status().apps[TRAEFIK_APP_NAME].units
        if name != new_leader
    ]
    for unit_name in working_units:
        verify_https_on_unit(juju, unit_name, alertmanager_url)

    juju.wait(lambda _: len(get_outstanding_csrs(juju)) == 1, error=jubilant.any_error, timeout=300)

    # The new leader lost the old leader's key, so its served certificate is no
    # longer trusted (or the endpoint is down) -- HTTPS must fail here.
    try:
        verify_https_on_unit(juju, new_leader, alertmanager_url)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        pass  # expected: cert no longer trusted / endpoint down
    else:
        raise AssertionError(
            f"HTTPS unexpectedly succeeded on {new_leader}; the served certificate "
            "is still trusted after the leadership change"
        )

    # Upgrade to the charm under test.
    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    assert_traefik_revision(juju, 0)

    status = juju.status()
    leader_status = status.apps[TRAEFIK_APP_NAME].units[new_leader].workload_status
    assert leader_status.current == "active", (
        f"expected {new_leader} to be active after upgrade, got {leader_status.current!r}"
    )
    assert leader_status.message == "Certificate not available yet", (
        "unexpected active message on upgraded leader: "
        f"{leader_status.message!r}"
    )

    outstanding_csrs = get_outstanding_csrs(juju)
    assert len(outstanding_csrs) == 1, (
        "expected exactly one pending CSR on manual-tls after upgrade, "
        f"got {len(outstanding_csrs)}"
    )
