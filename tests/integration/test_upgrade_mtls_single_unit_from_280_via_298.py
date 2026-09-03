#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment from revision 280 via 298.

Scenario:

1. Deploy traefik-k8s (1 unit) at revision 280 and integrate it with
   ``manual-tls-certificates`` and ``alertmanager``.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through the single traefik unit.
4. Refresh traefik to revision 298 (intermediate hop), re-signing any CSR that
   the intermediate revision raises, and re-verify HTTPS.
5. Refresh traefik to the locally built charm.
6. Verify the *same* certificate still serves the *same* URL and that the
   manual-tls charm has no outstanding certificate requests.
"""

import logging

import jubilant
import pytest
from conftest import MANUAL_TLS_APP_NAME, TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    all_settled,
    any_error,
    assert_traefik_revision,
    bring_up_certified_traefik,
    get_outstanding_csrs,
    sign_csrs_and_provide_cert,
    verify_https_on_unit,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 280
INTERMEDIATE_REVISION = 298


@pytest.mark.setup
def test_upgrade_mtls_single_unit_from_280_via_298(
    juju: jubilant.Juju, traefik_charm, mtls_app, alertmanager_app, tmp_path
):
    """A single traefik unit keeps serving the same certificate across 280 -> 298 -> current."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=any_error, timeout=900, delay=5, successes=5)
    url = bring_up_certified_traefik(juju, tmp_path)
    unit_name = next(iter(juju.status().apps[TRAEFIK_APP_NAME].units))

    juju.refresh(TRAEFIK_APP_NAME, channel=SOURCE_CHANNEL, revision=INTERMEDIATE_REVISION)
    juju.wait(jubilant.all_agents_idle, error=any_error, timeout=900, delay=5, successes=5)

    sign_csrs_and_provide_cert(juju, MANUAL_TLS_APP_NAME)
    juju.wait(all_settled, error=any_error, timeout=900, delay=5, successes=5)
    assert_traefik_revision(juju, INTERMEDIATE_REVISION)

    verify_https_on_unit(juju, unit_name, url)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, error=any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_unit(juju, unit_name, url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )
