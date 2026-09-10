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
from upgrade_tests_helper import run_mtls_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_mtls_from_revision_280(
    juju: jubilant.Juju, traefik_charm, mtls_app, ingress_app, tmp_path
):
    """Traefik keeps serving the same certificate after upgrading from rev 280."""
    run_mtls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION)
