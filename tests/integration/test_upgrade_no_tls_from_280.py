#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik without a certificate provider from Charmhub revision 280.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate only with
   ``alertmanager`` (no certificate provider relation).
2. Verify the ingress URL is reachable over HTTP through every traefik unit
   and all units are active / idle.
3. Refresh traefik to the locally built charm.
4. Verify the same HTTP URL remains reachable on every unit and no unit is
   blocked/error.
"""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, NUM_TRAEFIK_UNITS, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    all_settled,
    bring_up_traefik_without_certificate_provider,
    verify_http_on_all_units,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_no_tls_from_revision_280(
    juju: jubilant.Juju, traefik_charm, alertmanager_app
):
    """Traefik stays healthy and serves HTTP after upgrading from rev 280."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    url = bring_up_traefik_without_certificate_provider(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, delay=5, timeout=900)

    verify_http_on_all_units(juju, expected_url=url)
