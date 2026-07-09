#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik with self-signed certificates from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
   ``self-signed-certificates`` and ``alertmanager``.
2. Verify the ingress URL is reachable over HTTPS through every traefik unit.
3. Refresh traefik to the locally built charm.
4. Verify the same CA still serves the same URL on every unit.
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
    verify_https_on_all_units,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_self_signed_from_revision_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, alertmanager_app, tmp_path
):
    """Traefik keeps serving HTTPS after upgrading from rev 298 with self-signed certs."""
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
    url = bring_up_self_signed_traefik(juju, tmp_path)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, delay=5, timeout=900)
    assert_traefik_revision(juju, 0)

    verify_https_on_all_units(juju, expected_url=url)
