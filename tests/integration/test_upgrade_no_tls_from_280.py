#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik without a certificate provider from Charmhub revision 280.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate only with
    an ingress requirer (no certificate provider relation).
2. Verify the ingress URL is reachable over HTTP through every traefik unit
   and all units are active / idle.
3. Refresh traefik to the locally built charm.
4. Verify the same HTTP URL remains reachable on every unit and no unit is
   blocked/error.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from upgrade_tests_scenarios import run_no_tls_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_no_tls_from_revision_280(juju: jubilant.Juju, traefik_charm, ingress_app):
    """Traefik stays healthy and serves HTTP after upgrading from rev 280."""
    run_no_tls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, SOURCE_REVISION)
