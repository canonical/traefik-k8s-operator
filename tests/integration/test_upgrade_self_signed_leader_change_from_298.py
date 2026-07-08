#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Leadership-change TLS behavior with self-signed certificates on revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
   ``self-signed-certificates`` and ``alertmanager``; verify HTTPS works.
2. Force a leadership change by stopping the old leader's unit agent.
3. Trigger hook execution on the new leader and wait for the remaining units to
   settle so the self-signed provider can issue replacement material.
4. Verify HTTPS remains reachable on the surviving units.
5. Refresh traefik to the locally built charm.
6. Verify HTTPS remains reachable on the surviving units after the upgrade.
"""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, NUM_TRAEFIK_UNITS, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    bring_up_self_signed_traefik,
    force_leader_change,
    leader_unit_name,
    verify_https_on_unit,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_self_signed_leader_change_from_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, alertmanager_app, tmp_path
):
    """Self-signed certs remain trusted on surviving units across leader change and upgrade."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    alertmanager_url = bring_up_self_signed_traefik(juju, tmp_path)

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
        verify_https_on_unit(juju, unit_name, alertmanager_url)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(jubilant.all_agents_idle, timeout=900, delay=5, successes=5)

    for unit_name in surviving_units:
        verify_https_on_unit(juju, unit_name, alertmanager_url)

    assert new_leader in surviving_units
