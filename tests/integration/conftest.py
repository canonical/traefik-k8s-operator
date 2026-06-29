# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import subprocess
from pathlib import Path
from typing import cast

import jubilant
import pytest
import yaml

from tests.integration.helpers import all_settled

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}

ALERTMANAGER_APP_NAME = "alertmanager"
TRAEFIK_APP_NAME = "traefik"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Parse additional pytest options.

    Args:
        parser: Pytest parser.
    """
    parser.addoption(
        "--base", action="store", default="ubuntu@26.04", help="Base to use for the integration test",
    )


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
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": "traefik-demo.local"})
    juju.wait(all_settled, delay=5, timeout=600)
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
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", traefik_app)
    juju.wait(jubilant.all_active, timeout=600)
    return ALERTMANAGER_APP_NAME


@pytest.fixture(scope="module", name="juju")
def juju_fixture(request):
    """Jubilant Juju fixture.

    Honours ``--model`` (use a pre-existing model, e.g. the one bootstrapped by
    concierge in CI) and ``--keep-models`` (preserve the temp model on failure).
    """
    model = request.config.getoption("--model")
    if model:
        _juju = jubilant.Juju(model=model)
        _juju.wait_timeout = 10 * 60
        yield _juju
        return

    keep_models = cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as _juju:
        _juju.wait_timeout = 10 * 60
        yield _juju
