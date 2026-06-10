# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
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

@pytest.fixture(scope="module")
def traefik_charm():
    charm_path = os.environ.get("CHARM_PATH")
    if charm_path:
        return Path(charm_path).resolve()
    charms = sorted(Path(".").glob("traefik*.charm"))
    if charms:
        return charms[0]
    raise FileNotFoundError(
        "Set CHARM_PATH to the built traefik charm, "
        "or place a traefik*.charm file in the repo root."
    )


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
