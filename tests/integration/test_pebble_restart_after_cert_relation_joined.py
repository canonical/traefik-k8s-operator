#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module tests that after a certificates relation is joined by Traefik t
hat it can successfully route traffic to HTTPS endpoints.
"""

import asyncio
import logging
from pathlib import Path

import pytest
import requests
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import (
    get_k8s_service_address,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}
mock_hostname = "juju.local"

@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm,
            resources=resources,
            application_name="traefik",
            trust=True,
        ),
        ops_test.model.deploy(
            "ch:alertmanager-k8s",
            application_name="alertmanager",
            channel="1/stable",
            trust=True,
        ),
        ops_test.model.deploy(
            "ch:self-signed-certificates",
            application_name="ssc",
            channel="1/stable",
            trust=True,
        ),
    )

    await ops_test.model.wait_for_idle(
        status="active", timeout=600, idle_period=30, raise_on_error=False
    )

    await asyncio.gather(
        ops_test.model.add_relation("alertmanager:ingress", "traefik"),
        ops_test.model.add_relation("ssc:certificates", "alertmanager"),
    )

    await ops_test.model.wait_for_idle(status="active", timeout=600, idle_period=30)


@pytest.mark.abort_on_fail
async def test_can_route_ingress_using_tls(ops_test: OpsTest):
    await asyncio.gather(
        ops_test.model.add_relation("ssc:certificates", "traefik"),
    )

    traefik_address = await get_k8s_service_address(ops_test, "traefik-lb")

    # Both HTTP and HTTPS should work
    alertmanager_address = f"https://{traefik_address}/{ops_test.model.info.name}-alertmanager"
    response = requests.get(alertmanager_address)
    assert response.status_code == 200

    alertmanager_address = f"http://{traefik_address}/{ops_test.model.info.name}-alertmanager"
    response = requests.get(alertmanager_address)
    assert response.status_code == 200
