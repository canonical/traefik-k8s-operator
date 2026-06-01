# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import os
from pathlib import Path
from typing import cast

import jubilant
import pytest


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


@pytest.fixture(autouse=True, scope="module")
def copy_traefik_library_into_tester_charms():
    """No-op: jubilant tests deploy from Charmhub, not local tester charms."""


@pytest.fixture(autouse=True, scope="module")
async def setup_env():
    """No-op: jubilant tests manage their own model via jubilant."""
