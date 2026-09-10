#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik without a certificate provider from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate only with
    an ingress requirer (no certificate provider relation).
2. Verify the ingress URL is reachable over HTTP through every traefik unit
   while no unit enters blocked/error.
3. Refresh traefik to the locally built charm.
4. Verify the same HTTP URL remains reachable on every unit and no unit is
   blocked/error.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from upgrade_tests_helper import run_no_tls_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_no_tls_from_revision_298(juju: jubilant.Juju, traefik_charm, ingress_app):
    """Traefik stays healthy and serves HTTP after upgrading from rev 298."""
    run_no_tls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, SOURCE_REVISION)
