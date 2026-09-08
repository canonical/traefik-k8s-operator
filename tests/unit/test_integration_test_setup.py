# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "integration"))

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    health_src_overwrite,
)
from tests.integration.conftest import ingress_fixture
from tests.integration.constants import INGRESS_APP_NAME
from tests.integration.helpers import _ingress_url


def test_ingress_fixture_deploys_health_any_charm():
    juju = Mock()

    result = ingress_fixture.__wrapped__(juju)

    juju.deploy.assert_called_once_with(
        f"ch:{ANY_CHARM_K8S}",
        INGRESS_APP_NAME,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": health_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        trust=True,
    )
    assert result == INGRESS_APP_NAME


def test_ingress_url_targets_health_endpoint():
    juju = Mock()
    juju.run.return_value.results = {
        "proxied-endpoints": json.dumps(
            {INGRESS_APP_NAME: {"url": "https://example.test/model-ingress"}}
        )
    }

    assert _ingress_url(juju) == "https://example.test/model-ingress/health"