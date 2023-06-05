# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio

import pytest_asyncio
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    deploy_charm_if_not_deployed,
    deploy_traefik_if_not_deployed,
    safe_relate,
)
from tests.integration.helpers import remove_application
from tests.integration.test_charm_ipa import assert_ipa_charm_has_ingress  # noqa
from tests.integration.test_charm_ipu import assert_ipu_charm_has_ingress  # noqa
from tests.integration.test_charm_tcp import (  # noqa
    assert_tcp_charm_has_ingress,
    tcp_charm_resources,
)


@pytest_asyncio.fixture
async def tcp_ipu_deployment(
    ops_test: OpsTest, traefik_charm, tcp_tester_charm, ipu_tester_charm  # noqa
):
    await asyncio.gather(
        deploy_traefik_if_not_deployed(ops_test, traefik_charm),
        deploy_charm_if_not_deployed(
            ops_test, tcp_tester_charm, "tcp-tester", resources=tcp_charm_resources
        ),
        deploy_charm_if_not_deployed(ops_test, ipu_tester_charm, "ipu-tester"),
    )
    await asyncio.gather(
        safe_relate(ops_test, "tcp-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"),
        safe_relate(ops_test, "ipu-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"),
    )

    # Make sure update-status triggers once so everything is up-to-date
    async with ops_test.fast_forward("10s"):
        await asyncio.sleep(15)

    # ensure update-status does not fire "too" quickly, else traefik will flip between
    # active/idle and maintenance: updating ingress configuration
    async with ops_test.fast_forward("60s"):
        # Use "idle_period" to make sure traefik is functioning
        # Otherwise, occasionally getting "Connection refused"
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "tcp-tester", "ipu-tester"],
            status="active",
            timeout=3000,
            idle_period=30,
        )

    yield
    await ops_test.model.applications["tcp-tester"].remove()
    await ops_test.model.applications["ipu-tester"].remove()


async def test_tcp_ipu_compatibility(ops_test, tcp_ipu_deployment):
    await assert_tcp_charm_has_ingress(ops_test)
    assert_ipu_charm_has_ingress(ops_test)


async def test_cleanup(ops_test):
    await remove_application(ops_test, "traefik-k8s", timeout=60)
