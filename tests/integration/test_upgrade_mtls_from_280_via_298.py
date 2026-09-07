#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik from revision 280 to 298 to the charm under test.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate it with
   ``manual-tls-certificates`` and ``alertmanager``.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through every traefik unit.
4. Refresh traefik to revision 298 (intermediate hop), re-signing any CSR that
   the intermediate revision raises, and re-verify HTTPS.
5. Refresh traefik to the locally built charm.
6. Verify the *same* certificate still serves the *same* URL on every unit and
   that the manual-tls charm has no outstanding certificate requests.
7. Remove and re-add the certificates relation.
8. Provide the *old* certificate (from before the relation removal) for the
   new CSRs and verify HTTPS still works — the reused private key means the
   old certificate's public key matches the new CSR.
"""

import logging

import jubilant
import pytest
from conftest import MANUAL_TLS_APP_NAME, TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
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
    provide_existing_certificate,
    sign_csrs_and_provide_cert,
    verify_https_on_all_units,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 280
INTERMEDIATE_REVISION = 298


@pytest.mark.setup
def test_upgrade_mtls_from_280_via_298(
    juju: jubilant.Juju, traefik_charm, mtls_app, alertmanager_app, tmp_path
):
    """Traefik keeps serving the same certificate across a 280 -> 298 -> current path."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_certified_traefik(juju, tmp_path)

    # Intermediate hop: 280 -> 298. The intermediate revision raises a fresh
    # CSR, so sign until every unit is serving again, then confirm HTTPS works.
    juju.refresh(TRAEFIK_APP_NAME, channel=SOURCE_CHANNEL, revision=INTERMEDIATE_REVISION)
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)

    # Sign CSRs; the resulting cert PEMs are stored in the module-level
    # ``signed_certificates`` global for re-use after the relation is re-created.
    sign_csrs_and_provide_cert(juju, MANUAL_TLS_APP_NAME)
    juju.wait(all_settled, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    assert_traefik_revision(juju, INTERMEDIATE_REVISION)

    verify_https_on_all_units(juju, expected_url=url)

    # Final hop: 298 -> charm under test.
    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    # The migrated key must still match the certificate on every unit ...
    verify_https_on_all_units(juju, expected_url=url)
    # ... and no new certificate request should have been raised.
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )

    juju.remove_relation(f"{mtls_app}:certificates", f"{TRAEFIK_APP_NAME}:certificates")
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)

    juju.integrate(f"{mtls_app}:certificates", f"{TRAEFIK_APP_NAME}:certificates")
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, delay=5, timeout=900, successes=5)

    # A new CSR is expected (the relation data is fresh) but the private key
    # is reused, so the old certificate's public key still matches. Provide
    # the old certificate without re-signing and verify HTTPS works.
    outstanding = get_outstanding_csrs(juju)
    assert outstanding, (
        "Expected outstanding CSRs after re-integrating the certificates "
        "relation, but none were found"
    )

    provide_existing_certificate(juju, outstanding)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)

    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates still has outstanding requests after providing "
        "the old certificate for the new CSRs"
    )

    verify_https_on_all_units(juju, expected_url=url)
