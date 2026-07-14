#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Leadership-change TLS behavior with self-signed certificates on revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
   ``self-signed-certificates`` and ``alertmanager``; verify HTTPS works.
2. Force a leadership change; the old leader is restored afterwards.
3. Trigger hook execution on the new leader and wait for all units to settle
   so the self-signed provider can issue replacement material.
4. Verify HTTPS remains reachable on all units.
5. Refresh traefik to the locally built charm.
6. Verify HTTPS remains reachable on all units after the upgrade.
"""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, NUM_TRAEFIK_UNITS, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    all_settled,
    assert_traefik_revision,
    bring_up_self_signed_traefik,
    force_leader_change,
    verify_https_on_all_units,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_ssc_leader_change_from_298(
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
    juju.wait(jubilant.all_agents_idle, timeout=900, delay=5, successes=5)
    alertmanager_url = bring_up_self_signed_traefik(juju, tmp_path)

    force_leader_change(juju, TRAEFIK_APP_NAME)

    juju.wait(all_settled, timeout=900, delay=5, successes=5)
    verify_https_on_all_units(juju, alertmanager_url)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, timeout=900, delay=5)
    assert_traefik_revision(juju, 0)
    verify_https_on_all_units(juju, alertmanager_url)
