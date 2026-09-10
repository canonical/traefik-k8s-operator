#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik with self-signed certificates from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
    ``self-signed-certificates`` and an ingress requirer.
2. Verify the ingress URL is reachable over HTTPS through every traefik unit.
3. Refresh traefik to the locally built charm.
4. Verify the same CA still serves the same URL on every unit.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from upgrade_tests_scenarios import run_ssc_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_ssc_from_revision_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, ingress_app, tmp_path
):
    """Traefik keeps serving HTTPS after upgrading from rev 298 with self-signed certs."""
    run_ssc_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION)
