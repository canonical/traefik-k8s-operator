#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik from Charmhub revision 298 to the charm under test.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
   ``manual-tls-certificates`` and ``alertmanager``.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through every traefik unit.
4. Refresh traefik to the locally built charm.
5. Verify the *same* certificate still serves the *same* URL on every unit and
   that the manual-tls charm has no outstanding certificate requests..
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
    all_settled,
    assert_traefik_revision,
    bring_up_certified_traefik,
    get_outstanding_csrs,
    verify_https_on_all_units,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_mtls_from_revision_298(
    juju: jubilant.Juju, traefik_charm, mtls_app, alertmanager_app, tmp_path
):
    """Traefik keeps serving the same certificate after upgrading from rev 298."""
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
    url = bring_up_certified_traefik(juju, tmp_path)

    # Upgrade to the charm under test.
    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, delay=5, timeout=900)
    assert_traefik_revision(juju, 0)

    # The migrated key must still match the certificate on every unit ...
    verify_https_on_all_units(juju, expected_url=url)
    # ... and no new certificate request should have been raised.
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )
