#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik from Charmhub revision 280 to the charm under test.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate it with
    ``manual-tls-certificates`` and an ingress requirer.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through every traefik unit.
4. Refresh traefik to the locally built charm.
5. Verify the *same* certificate still serves the *same* URL on every unit and
   that the manual-tls charm has no outstanding certificate requests.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from constants import (
    MOCK_HOSTNAME,
    NUM_TRAEFIK_UNITS,
    SOURCE_CHANNEL,
    TRAEFIK_APP_NAME,
    TRAEFIK_CHARM,
)
from helpers import (
    all_settled,
    assert_traefik_revision,
    bring_up_certified_traefik,
    get_outstanding_csrs,
    verify_https_through_all_traefik_units,
)

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_mtls_from_revision_280(
    juju: jubilant.Juju, traefik_charm, mtls_app, ingress_app, tmp_path
):
    """Traefik keeps serving the same certificate after upgrading from rev 280."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    bring_up_certified_traefik(juju, tmp_path)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    url = verify_https_through_all_traefik_units(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_through_all_traefik_units(juju, expected_url=url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )
