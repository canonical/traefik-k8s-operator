#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test TLS certificates on all traefik units."""

import json
import logging
from pathlib import Path

import jubilant
import pytest
import requests
import yaml

from tests.integration.dns_adapter import DNSResolverHTTPSAdapter

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}

TRAEFIK_APP_NAME = "traefik"
SSC_APP_NAME = "ssc"
ALERTMANAGER_APP_NAME = "alertmanager"
MOCK_HOSTNAME = "traefik-demo.local"
NUM_TRAEFIK_UNITS = 2


# ---------------------------------------------------------------------------
# Deploy helpers (called from juju_setup tests, NOT fixtures)
# ---------------------------------------------------------------------------


def deploy_traefik(juju: jubilant.Juju, charm: Path) -> None:
    """Deploy traefik."""
    juju.deploy(
        charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        trust=True,
    )
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": MOCK_HOSTNAME})
    juju.wait(jubilant.all_active)


def deploy_alertmanager(juju: jubilant.Juju) -> None:
    """Deploy alertmanager and integrate with traefik."""
    juju.deploy(
        "ch:alertmanager-k8s",
        ALERTMANAGER_APP_NAME,
        channel="2/edge",
        trust=True,
    )
    juju.wait(jubilant.all_active)
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active)


def deploy_ssc(juju: jubilant.Juju) -> None:
    """Deploy self-signed-certificates and integrate with traefik."""
    juju.deploy(
        "ch:self-signed-certificates",
        SSC_APP_NAME,
        channel="1/stable",
        trust=True,
    )
    juju.wait(jubilant.all_active)
    juju.integrate(f"{SSC_APP_NAME}:certificates", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active)


def scale_traefik(juju: jubilant.Juju) -> None:
    """Scale traefik to multiple units."""
    juju.add_unit(TRAEFIK_APP_NAME, num_units=NUM_TRAEFIK_UNITS - 1)

    def all_active_and_idle_with_expected_units(status):
        app = status.apps.get(TRAEFIK_APP_NAME)
        if app is None or len(app.units) < NUM_TRAEFIK_UNITS:
            return False
        if not jubilant.all_active(status):
            return False
        for unit in app.units.values():
            if unit.juju_status.current != "idle":
                return False
        return True

    juju.wait(all_active_and_idle_with_expected_units)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


@pytest.mark.juju_setup
def test_deploy(juju: jubilant.Juju, charm: Path):
    """Deploy traefik, alertmanager, and self-signed-certificates."""
    deploy_traefik(juju, charm)
    deploy_alertmanager(juju)
    deploy_ssc(juju)
    scale_traefik(juju)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tls_on_all_units(juju: jubilant.Juju, tmp_path: Path):
    """HTTPS endpoints are accessible through every traefik unit IP."""
    # Pull the CA certificate from the SSC charm.
    ca_cert_path = tmp_path / "ca.cert"
    result = juju.run(f"{SSC_APP_NAME}/0", "get-ca-certificate")
    ca_cert = result.results["ca-certificate"]
    ca_cert_path.write_text(ca_cert)
    logger.info("Pulled CA cert (%d bytes) to %s", len(ca_cert), ca_cert_path)

    # Get the alertmanager endpoint from traefik's proxied endpoints action.
    result = juju.run(f"{TRAEFIK_APP_NAME}/0", "show-proxied-endpoints")
    endpoints = json.loads(result.results["proxied-endpoints"])
    alertmanager_url = endpoints[ALERTMANAGER_APP_NAME]["url"]

    # Get unit IPs from status
    status = juju.status()
    units = status.apps[TRAEFIK_APP_NAME].units

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
            unit_name,
            response.status_code,
            response.text[:200],
        )
        response.raise_for_status()
