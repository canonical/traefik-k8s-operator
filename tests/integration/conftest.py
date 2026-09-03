# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path

import jubilant
import pytest
import yaml

from tests.integration.constants import (
    ALERTMANAGER_APP_NAME,
    MANUAL_TLS_APP_NAME,
    MANUAL_TLS_CHANNEL,
    SSC_APP_NAME,
    SSC_CHANNEL,
    SSC_CHARM,
    TRAEFIK_APP_NAME,
)
from tests.integration.helpers import all_settled, any_error

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Parse additional pytest options.

    Args:
        parser: Pytest parser.
    """
    parser.addoption(
        "--base", action="store", default="ubuntu@26.04", help="Base to use for the integration test",
    )


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest) -> jubilant.Juju:
    """Connect to the model pre-created by concierge (named by ``--juju-model``).

    - Sets a longer wait_timeout (jubilant's default is 3 min; charm operations need 10 min).
    """
    model = request.config.getoption("--juju-model") or "testing"
    _juju = jubilant.Juju(model=model)
    _juju.wait_timeout = 10 * 60
    return _juju


@pytest.fixture(scope="module")
def traefik_charm(charm_paths, pytestconfig: pytest.Config):
    traefik_charm_paths = charm_paths["traefik-k8s"]
    if len(traefik_charm_paths) > 1:
        base = pytestconfig.getoption("--base")
        traefik_charm_path = traefik_charm_paths[base]
    else:
        traefik_charm_path = traefik_charm_paths.path
    logger.warning("Using traefik charm path: %s", traefik_charm_path)
    return traefik_charm_path


@pytest.fixture(scope="module", name="traefik_app")
def deploy_traefik(juju, traefik_charm):
    """Deploy traefik."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=any_error, timeout=900, delay=5, successes=5)
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": "traefik-demo.local"})
    juju.wait(all_settled, error=any_error, delay=5, successes=5)
    return TRAEFIK_APP_NAME


@pytest.fixture(scope="module", name="alertmanager_app")
def alertmanager_fixture(juju):
    """Deploy alertmanager-k8s."""
    juju.deploy(
        "ch:alertmanager-k8s",
        ALERTMANAGER_APP_NAME,
        channel="2/edge",
        trust=True,
    )
    juju.wait(
        lambda status: jubilant.all_active(status, ALERTMANAGER_APP_NAME),
        error=any_error,
        delay=5,
        successes=5,
    )
    return ALERTMANAGER_APP_NAME


@pytest.fixture(scope="module", name="mtls_app")
def mtls_fixture(juju):
    """Deploy the manual-tls-certificates charm (v4-capable ``1/stable`` track)."""
    juju.deploy(MANUAL_TLS_APP_NAME, MANUAL_TLS_APP_NAME, channel=MANUAL_TLS_CHANNEL)
    juju.wait(
        lambda status: jubilant.all_active(status, MANUAL_TLS_APP_NAME),
        error=any_error,
        delay=5,
        successes=5,
    )
    return MANUAL_TLS_APP_NAME


@pytest.fixture(scope="module", name="ssc_app")
def self_signed_certificates_fixture(juju):
    """Deploy the self-signed-certificates charm."""
    juju.deploy(SSC_CHARM, SSC_APP_NAME, channel=SSC_CHANNEL, trust=True)
    juju.wait(
        lambda status: jubilant.all_active(status, SSC_APP_NAME),
        error=any_error,
        delay=5,
        successes=5,
    )
    return SSC_APP_NAME
