#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test TLS certificates on all traefik units."""

import jubilant
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, NUM_TRAEFIK_UNITS
from helpers import all_settled, pull_ssc_ca_certificate, verify_https_on_all_units


def test_https_on_all_units(
    juju: jubilant.Juju, traefik_charm, ssc_app, alertmanager_app, tmp_path
):
    """HTTPS endpoints are accessible through every traefik unit IP."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        config={"external_hostname": MOCK_HOSTNAME},
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )

    juju.integrate(f"{ssc_app}:certificates", TRAEFIK_APP_NAME)
    juju.integrate(f"{alertmanager_app}:ingress", TRAEFIK_APP_NAME)

    juju.wait(all_settled, timeout=600, delay=5, successes=5)

    # Pull the CA certificate from the SSC charm for HTTPS verification.
    pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ssc_app)

    units = juju.status().apps[TRAEFIK_APP_NAME].units
    assert len(units) == NUM_TRAEFIK_UNITS, (
        f"Expected {NUM_TRAEFIK_UNITS} traefik units, got {len(units)}"
    )

    verify_https_on_all_units(juju)
