# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
from pathlib import Path

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}

TRAEFIK_APP_NAME = "traefik"
SSC_APP_NAME = "ssc"
ALERTMANAGER_APP_NAME = "alertmanager"
MOCK_HOSTNAME = "traefik-demo.local"


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
    # Fall back to the pre-built charm in the repo root
    charms = sorted(Path(".").glob("traefik*.charm"))
    if charms:
        return charms[0]
    raise FileNotFoundError(
        "Set CHARM_PATH to the built traefik charm, "
        "or place a traefik*.charm file in the repo root."
    )


@pytest.fixture(scope="module", name="traefik_app")
def traefik_fixture(juju, traefik_charm):
    """Deploy traefik with 3 units."""
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
def alertmanager_fixture(traefik_app):
    """Deploy alertmanager and integrate with traefik."""
    juju = traefik_app
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
def ssc_fixture(traefik_app):
    """Deploy self-signed-certificates and integrate with traefik."""
    juju = traefik_app
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
