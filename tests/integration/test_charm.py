#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}
    await ops_test.model.deploy(traefik_charm, resources=resources, application_name=APP_NAME)
    await ops_test.model.applications[APP_NAME].set_config({"external_hostname": "foo.bar"})

    # issuing dummy update_status just to trigger an event
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
