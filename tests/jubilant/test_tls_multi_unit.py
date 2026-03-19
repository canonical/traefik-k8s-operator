#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test: TLS certificates work on all traefik units."""

import json
import logging
from pathlib import Path

import jubilant
import requests
from conftest import MOCK_HOSTNAME
from helper import DNSResolverHTTPSAdapter

NUM_TRAEFIK_UNITS = 2

logger = logging.getLogger(__name__)


def test_tls_on_all_units(juju: jubilant.Juju, traefik_app, ssc_app, alertmanager_app, tmp_path: Path):
    """HTTPS endpoints are accessible through every traefik unit IP."""
    juju.add_unit(traefik_app, num_units=1)
    juju.wait(jubilant.all_active, timeout=600)

    # Pull the CA certificate from the SSC charm.
    ca_cert_path = tmp_path / "ca.cert"
    result = juju.run(f"{ssc_app}/0", "get-ca-certificate")
    ca_cert = result.results["ca-certificate"]
    ca_cert_path.write_text(ca_cert)
    logger.info("Pulled CA cert (%d bytes) to %s", len(ca_cert), ca_cert_path)

    # Get the alertmanager endpoint from traefik's proxied endpoints action.
    result = juju.run(f"{traefik_app}/0", "show-proxied-endpoints")
    endpoints = json.loads(result.results["proxied-endpoints"])
    alertmanager_url = endpoints[alertmanager_app]["url"]

    # Get unit IPs from status
    status = juju.status()
    units = status.apps[traefik_app].units

    assert len(units) == NUM_TRAEFIK_UNITS, (
        f"Expected {NUM_TRAEFIK_UNITS} traefik units, got {len(units)}"
    )

    # Hit the HTTPS endpoint through every traefik unit
    for unit_name, unit_status in units.items():
        unit_ip = unit_status.address
        logger.info("Testing TLS on %s (IP: %s) -> %s", unit_name, unit_ip, alertmanager_url)

        session = requests.Session()
        session.mount("https://", DNSResolverHTTPSAdapter(MOCK_HOSTNAME, unit_ip))
        session.verify = str(ca_cert_path)

        response = session.get(alertmanager_url, timeout=30)
        logger.info(
            "%s result: status=%s body=%s",
            unit_name, response.status_code, response.text[:200],
        )
        response.raise_for_status()
