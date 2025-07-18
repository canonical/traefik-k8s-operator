#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import http.client
import json
from urllib.parse import urlparse

import pytest
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    trfk_resources,
)
from tests.integration.helpers import (
    get_k8s_service_address,
    remove_application,
)

health_tester_resources = {
    "python-image": "ubuntu/python:3.10-22.04_stable",
}


def fetch_health_sync(url: str):
    """Perform a simple HTTP GET using http.client.

    Returns a tuple (status, content) where content is JSON-decoded.
    """
    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.netloc)
    conn.request("GET", parsed.path)
    resp = conn.getresponse()
    status = resp.status
    data = resp.read()
    conn.close()
    try:
        content = json.loads(data)
    except Exception:
        content = {}
    return status, content


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, health_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm,
            application_name="traefik-k8s",
            resources=trfk_resources,
            trust=True,
        ),
        ops_test.model.deploy(
            health_tester_charm,
            "health-tester",
            num_units=3,
            resources=health_tester_resources,
        ),
    )

    await ops_test.model.wait_for_idle(
        ["traefik-k8s", "health-tester"], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation("health-tester:ingress", "traefik-k8s:ingress")
    await ops_test.model.wait_for_idle(["traefik-k8s", "health-tester"])


async def test_health(ops_test: OpsTest):
    traefik_address = await get_k8s_service_address(ops_test, "traefik-k8s-lb")
    health_address = f"http://{traefik_address}/{ops_test.model.name}-health-tester/health"

    third_application_unit = ops_test.model.applications["health-tester"].units[2]
    set_health_action = await third_application_unit.run_action(
        "set-health", **{"is-healthy": False}
    )
    await set_health_action.wait()
    await ops_test.model.wait_for_idle(["traefik-k8s", "health-tester"])
    for _ in range(10):
        status, content = fetch_health_sync(health_address)
        assert status == 200, f"Expected 200 OK but got {status}"
        expected_options = [
            {"host": "health-tester-0", "status": "up"},
            {"host": "health-tester-1", "status": "up"},
        ]
        assert content in expected_options, f"Unexpected response: {content}"

    second_application_unit = ops_test.model.applications["health-tester"].units[1]
    set_health_action = await second_application_unit.run_action(
        "set-health", **{"is-healthy": False}
    )
    await set_health_action.wait()
    await ops_test.model.wait_for_idle(["traefik-k8s", "health-tester"])

    for _ in range(10):
        status, content = fetch_health_sync(health_address)
        assert status == 200, f"Expected 200 OK but got {status}"
        expected = {"host": "health-tester-0", "status": "up"}
        assert content == expected, f"Unexpected response: {content}"


async def test_cleanup(ops_test):
    await remove_application(ops_test, "traefik-k8s", timeout=60)
