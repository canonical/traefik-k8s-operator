#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""TLS integration tests for Traefik (jubilant framework).

Tests:
- Frontend TLS on multiple traefik units.
- serversTransport.rootCAs populated via receive-ca-cert relation.
"""

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
# Fixtures
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
    """Deploy traefik with external_hostname configured."""
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
    """Deploy self-signed-certificates and integrate with traefik for frontend TLS."""
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


@pytest.fixture(scope="module", name="receive_ca_cert_relation")
def receive_ca_cert_fixture(juju, traefik_app, ssc_app):
    """Integrate SSC send-ca-cert with traefik receive-ca-cert.

    This is the relation that triggers serversTransport.rootCAs in static config.
    """
    juju.integrate(f"{SSC_APP_NAME}:send-ca-cert", f"{TRAEFIK_APP_NAME}:receive-ca-cert")
    juju.wait(jubilant.all_active, timeout=600)
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pull_ca_cert(juju, tmp_path):
    """Pull the SSC CA cert to disk and return the path."""
    ca_cert_path = tmp_path / "ca.cert"
    result = juju.run(f"{SSC_APP_NAME}/0", "get-ca-certificate")
    ca_cert = result.results["ca-certificate"]
    ca_cert_path.write_text(ca_cert)
    logger.info("Pulled CA cert (%d bytes) to %s", len(ca_cert), ca_cert_path)
    return ca_cert_path


def _get_alertmanager_url(juju):
    """Get the alertmanager ingress URL from traefik's proxied-endpoints action."""
    result = juju.run(f"{TRAEFIK_APP_NAME}/0", "show-proxied-endpoints")
    endpoints = json.loads(result.results["proxied-endpoints"])
    url = endpoints[ALERTMANAGER_APP_NAME]["url"]
    logger.info("Alertmanager URL: %s", url)
    return url


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_tls_on_all_units(
    juju: jubilant.Juju, traefik_app, ssc_app, alertmanager_app, tmp_path: Path
):
    """HTTPS endpoints are accessible through every traefik unit IP."""
    juju.add_unit(traefik_app, num_units=NUM_TRAEFIK_UNITS - 1)

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

    juju.wait(all_active_and_idle_with_expected_units, timeout=600)

    ca_cert_path = _pull_ca_cert(juju, tmp_path)
    alertmanager_url = _get_alertmanager_url(juju)

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


def test_root_cas_in_static_config(
    juju: jubilant.Juju, traefik_app, ssc_app, receive_ca_cert_relation
):
    """After receive-ca-cert integration, static config has serversTransport.rootCAs."""
    # Read the static config from the traefik container.
    static_config_raw = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        "cat /etc/traefik/traefik.yaml",
        container="traefik",
    )
    static_config = yaml.safe_load(static_config_raw)
    logger.info("Static config keys: %s", list(static_config.keys()))

    assert "serversTransport" in static_config, (
        "Expected serversTransport in static config after receive-ca-cert integration. "
        f"Got keys: {list(static_config.keys())}"
    )
    root_cas = static_config["serversTransport"].get("rootCAs", [])
    assert len(root_cas) > 0, "Expected at least one CA path in serversTransport.rootCAs"

    # Verify the paths point to files in the CA certs directory.
    for ca_path in root_cas:
        assert ca_path.startswith("/usr/local/share/ca-certificates/"), (
            f"Unexpected CA path: {ca_path}"
        )
        assert ca_path.endswith(".crt"), f"CA path should end in .crt: {ca_path}"

    logger.info("serversTransport.rootCAs contains %d CA path(s): %s", len(root_cas), root_cas)


def test_https_ingress_accessible_with_root_cas(
    juju: jubilant.Juju,
    traefik_app,
    ssc_app,
    receive_ca_cert_relation,
    alertmanager_app,
    tmp_path: Path,
):
    """HTTPS ingress endpoint is accessible when rootCAs are configured."""
    ca_cert_path = _pull_ca_cert(juju, tmp_path)
    alertmanager_url = _get_alertmanager_url(juju)

    # Get traefik unit IP.
    status = juju.status()
    unit_ip = status.apps[TRAEFIK_APP_NAME].units[f"{TRAEFIK_APP_NAME}/0"].address

    # Hit the HTTPS endpoint, resolving MOCK_HOSTNAME to traefik's IP.
    session = requests.Session()
    session.mount("https://", DNSResolverHTTPSAdapter(MOCK_HOSTNAME, unit_ip))
    session.verify = str(ca_cert_path)

    response = session.get(alertmanager_url, timeout=30)
    logger.info("Response: status=%s body=%s", response.status_code, response.text[:200])
    response.raise_for_status()
