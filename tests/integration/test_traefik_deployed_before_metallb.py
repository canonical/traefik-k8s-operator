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
from types import SimpleNamespace

import pytest
import yaml
from helpers import disable_metallb, enable_metallb
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}
trfk = SimpleNamespace(name="traefik", resources=resources)

ipu = SimpleNamespace(charm="ch:prometheus-k8s", name="prometheus")  # per unit
ipa = SimpleNamespace(charm="ch:alertmanager-k8s", name="alertmanager")  # per app
ipr = SimpleNamespace(charm="ch:grafana-k8s", name="grafana")  # traefik route

idle_period = 90


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_charm):
    logger.info("First, disable metallb, in case it's enabled")
    await disable_metallb()

    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, resources=trfk.resources, application_name=trfk.name, series="focal"
        ),
        ops_test.model.deploy(
            ipu.charm,
            application_name=ipu.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
            series="focal",
        ),
        ops_test.model.deploy(
            ipa.charm,
            application_name=ipa.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
            series="focal",
        ),
        ops_test.model.deploy(
            ipr.charm,
            application_name=ipr.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
            series="focal",
        ),
    )

    await ops_test.model.wait_for_idle(timeout=600, idle_period=30, raise_on_error=False)

    await asyncio.gather(
        ops_test.model.add_relation(f"{ipu.name}:ingress", trfk.name),
        ops_test.model.add_relation(f"{ipa.name}:ingress", trfk.name),
        ops_test.model.add_relation(f"{ipr.name}:ingress", trfk.name),
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
            f"{ops_test.model_name}-{ipr.name}",
            f"{ops_test.model_name}-{ipu.name}-0",
            f"{ops_test.model_name}-{ipa.name}",
        ]
    ]
    for ep in endpoints:
        # FIXME make sure the response is from the workload and not from traefik
        pass
