#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test TLS certificates on all traefik units."""

import json
import logging
import os
from pathlib import Path

import jubilant
import pytest
import requests
import yaml

from dns_adapter import DNSResolverHTTPSAdapter

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
# Fixtures (inline — shadows the parent conftest fixtures for this file)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        juju.wait_timeout = 10 * 60
        yield juju


@pytest.fixture(scope="module")
def traefik_charm():
    charm_path = os.environ.get("CHARM_PATH")
    if charm_path:
        return Path(charm_path)
    charms = sorted(Path(".").glob("traefik*.charm"))
    if charms:
        return charms[0]
    raise FileNotFoundError(
        "Set CHARM_PATH to the built traefik charm, "
        "or place a traefik*.charm file in the repo root."
    )


@pytest.fixture(scope="module", name="traefik_app")
def traefik_fixture(juju, traefik_charm):
    """Deploy traefik."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        trust=True,
    )
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": MOCK_HOSTNAME})
    juju.wait(jubilant.all_active, timeout=600)
    return TRAEFIK_APP_NAME


@pytest.fixture(scope="module", name="alertmanager_app")
def alertmanager_fixture(juju, traefik_app):
    """Deploy alertmanager and integrate with traefik."""
    juju.deploy(
        "ch:alertmanager-k8s",
        ALERTMANAGER_APP_NAME,
        channel="2/edge",
        trust=True,
    )
    juju.wait(jubilant.all_active, timeout=600)
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active, timeout=600)
    return ALERTMANAGER_APP_NAME


@pytest.fixture(scope="module", name="ssc_app")
def ssc_fixture(juju, traefik_app):
    """Deploy self-signed-certificates and integrate with traefik."""
    juju.deploy(
        "ch:self-signed-certificates",
        SSC_APP_NAME,
        channel="1/stable",
        trust=True,
    )
    juju.wait(jubilant.all_active, timeout=600)
    juju.integrate(f"{SSC_APP_NAME}:certificates", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active, timeout=600)
    return SSC_APP_NAME


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def test_tls_on_all_units(
    juju: jubilant.Juju, traefik_app, ssc_app, alertmanager_app, tmp_path: Path
):
    """HTTPS endpoints are accessible through every traefik unit IP."""
    juju.add_unit(traefik_app, num_units=NUM_TRAEFIK_UNITS - 1)
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
