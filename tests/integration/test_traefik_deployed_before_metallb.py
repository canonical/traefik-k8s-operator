#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module tests that traefik ends up in active state when deployed BEFORE metallb.

...And without the help of update-status.

1. Disable metallb (in case it's enabled).
2. Deploy traefik + one charm per relation type (as if deployed as part of a bundle).
3. Enable metallb.

NOTE: This module implicitly relies on in-order execution (test running in the order they are
 written).
"""

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import disable_metallb, enable_metallb

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}

idle_period = 90


@pytest.mark.abort_on_fail
async def test_build_and_deploy(
    ops_test: OpsTest, traefik_charm, ipa_tester_charm, ipu_tester_charm, route_tester_charm
):
    logger.info("First, disable metallb, in case it's enabled")
    await disable_metallb()

    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, resources=resources, application_name="traefik", series="focal"
        ),
        ops_test.model.deploy(ipu_tester_charm, application_name="ipu-tester", series="focal"),
        ops_test.model.deploy(ipa_tester_charm, application_name="ipa-tester", series="focal"),
        ops_test.model.deploy(route_tester_charm, application_name="route-tester", series="focal"),
    )

    await ops_test.model.wait_for_idle(timeout=600, idle_period=30)

    await asyncio.gather(
        ops_test.model.add_relation("ipu-tester", "traefik"),
        ops_test.model.add_relation("ipa-tester", "traefik"),
        ops_test.model.add_relation("route-tester", "traefik"),
    )

    await ops_test.model.wait_for_idle(timeout=600, idle_period=idle_period)


@pytest.mark.abort_on_fail
async def test_ingressed_endpoints_reachable_after_metallb_enabled(ops_test: OpsTest):
    logger.info("Now enable metallb")
    ip = await enable_metallb()

    await ops_test.model.wait_for_idle(status="active", timeout=600, idle_period=idle_period)

    endpoints = [
        f"{ip}/{path}"
        for path in [
            f"{ops_test.model_name}-route-tester",
            f"{ops_test.model_name}-ipu-tester-0",
            f"{ops_test.model_name}-ipa-tester",
        ]
    ]
    for ep in endpoints:
        # FIXME make sure the response is from the workload and not from traefik
        pass
