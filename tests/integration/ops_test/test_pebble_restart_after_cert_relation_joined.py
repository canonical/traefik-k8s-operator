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
import yaml
from helpers import fetch_with_retry
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}
mock_hostname = "juju.local"

async def get_traefik_url(ops_test: OpsTest, traefik_app_name: str = "traefik"):
    """Get the URL for the Traefik app, as provided by the show-external-endpoints action."""
    external_endpoints_action = (
        await ops_test.model.applications[traefik_app_name]
        .units[0]
        .run_action("show-external-endpoints")
    )
    external_endpoints_action_results = (await external_endpoints_action.wait()).results
    external_endpoints = yaml.safe_load(external_endpoints_action_results["external-endpoints"])
    return external_endpoints[traefik_app_name]["url"]

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
            channel="2/edge",
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
    # Important to test integrating traefik and ssc here, after traefik has been active/idle.
    # This means pebble has started traefik.
    # This helps ascertain that Traefik behaves as expected when it is related to SSC.
    await asyncio.gather(
        ops_test.model.add_relation("ssc:certificates", "traefik"),
    )

    traefik_address = await get_traefik_url(ops_test, "traefik")

    alertmanager_address = f"{traefik_address}/{ops_test.model.info.name}-alertmanager"

    # Ensure we are able to get a 200 when calling AM. The helper asserts the status code.
    fetch_with_retry(alertmanager_address)

    alertmanager_address_http = alertmanager_address.replace("https://", "http://")
    # Ensure we are able to get a 200 when calling AM. The helper asserts the status code.
    # This should also work with HTTP.
    fetch_with_retry(alertmanager_address_http)
