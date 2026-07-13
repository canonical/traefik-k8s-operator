#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Leadership-change upgrade behavior without a certificate provider on revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate only with
   ``alertmanager``.
2. Verify HTTP ingress URL reachability on all units and no blocked/error state.
3. Force a leadership change; the old leader is restored afterwards.
4. Verify all units stay active/idle and keep serving the same HTTP URL.
5. Refresh traefik to the locally built charm and re-verify all units.
"""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, NUM_TRAEFIK_UNITS, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    all_settled,
    assert_traefik_revision,
    bring_up_traefik_without_certificate_provider,
    force_leader_change,
    verify_http_on_all_units,
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
    juju.wait(jubilant.all_agents_idle, timeout=900, delay=5, successes=5)
    alertmanager_url = bring_up_traefik_without_certificate_provider(juju)

    force_leader_change(juju, TRAEFIK_APP_NAME)

    juju.wait(all_settled, timeout=900, delay=5, successes=5)
    verify_http_on_all_units(juju, alertmanager_url)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, timeout=900, delay=5)
    assert_traefik_revision(juju, 0)
    verify_http_on_all_units(juju, alertmanager_url)
