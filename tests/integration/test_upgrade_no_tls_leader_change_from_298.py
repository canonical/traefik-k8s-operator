#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Leadership-change upgrade behavior without a certificate provider on revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate only with
   ``alertmanager``.
2. Verify HTTP ingress URL reachability on all units and no blocked/error state.
3. Force a leadership change by stopping the old leader's unit agent.
4. Verify surviving units stay active/idle (not blocked/error) and keep serving
   the same HTTP URL.
5. Refresh traefik to the locally built charm and re-verify surviving units.
"""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, NUM_TRAEFIK_UNITS, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    all_settled,
    bring_up_traefik_without_certificate_provider,
    force_leader_change,
    leader_unit_name,
    verify_http_on_unit,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_no_tls_leader_change_from_298(
    juju: jubilant.Juju, traefik_charm, alertmanager_app
):
    """Surviving units remain healthy and serve HTTP across leader change and upgrade."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    alertmanager_url = bring_up_traefik_without_certificate_provider(juju)

    previous_leader = leader_unit_name(juju, TRAEFIK_APP_NAME)
    new_leader = force_leader_change(juju, TRAEFIK_APP_NAME)

    juju.config(TRAEFIK_APP_NAME, {"loadbalancer_annotations": " "})

    surviving_units = [
        unit_name
        for unit_name in juju.status().apps[TRAEFIK_APP_NAME].units
        if unit_name != previous_leader
    ]
    assert len(surviving_units) == NUM_TRAEFIK_UNITS - 1

    juju.wait(
        lambda status: all(
            unit_name in status.apps[TRAEFIK_APP_NAME].units
            and status.apps[TRAEFIK_APP_NAME].units[unit_name].workload_status.current == "active"
            and status.apps[TRAEFIK_APP_NAME].units[unit_name].juju_status.current == "idle"
            for unit_name in surviving_units
        ),
        timeout=900,
        delay=5,
    )
    for unit_name in surviving_units:
        verify_http_on_unit(juju, unit_name, alertmanager_url)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, timeout=900, delay=5)
    for unit_name in surviving_units:
        verify_http_on_unit(juju, unit_name, alertmanager_url)

    assert new_leader in surviving_units
