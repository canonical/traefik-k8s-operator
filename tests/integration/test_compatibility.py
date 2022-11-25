# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio

import juju.errors
import pytest_asyncio
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    deploy_charm_if_not_deployed,
    deploy_traefik_if_not_deployed,
)
from tests.integration.test_charm_ipa import assert_ipa_charm_has_ingress  # noqa
from tests.integration.test_charm_ipu import assert_ipu_charm_has_ingress  # noqa
from tests.integration.test_charm_tcp import (  # noqa
    assert_tcp_charm_has_ingress,
    tcp_charm_resources,
)


async def safe_relate(ops_test: OpsTest, ep1, ep2):
    # in pytest-operator CI, we deploy all tests in the same model.
    # Therefore, it might be that by the time we run this module, the two endpoints
    # are already related.
    try:
        await ops_test.model.add_relation(ep1, ep2)
    except juju.errors.JujuAPIError:
        # relation already exists? skip
        pass


@pytest_asyncio.fixture
async def tcp_ipa_deployment(
    ops_test: OpsTest, traefik_charm, tcp_tester_charm, ipa_tester_charm  # noqa
):
    await asyncio.gather(
        deploy_traefik_if_not_deployed(ops_test, traefik_charm),
        deploy_charm_if_not_deployed(
            ops_test, tcp_tester_charm, "tcp-tester", resources=tcp_charm_resources
        ),
        deploy_charm_if_not_deployed(ops_test, ipa_tester_charm, "ipa-tester"),
    )
    await asyncio.gather(
        safe_relate(ops_test, "tcp-tester", "traefik-k8s"),
        safe_relate(ops_test, "ipa-tester", "traefik-k8s"),
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "tcp-tester", "ipa-tester"], status="active", timeout=1000
        )

    yield
    await ops_test.model.applications["tcp-tester"].remove()
    await ops_test.model.applications["ipa-tester"].remove()


@pytest_asyncio.fixture
async def tcp_ipu_deployment(
    ops_test: OpsTest, traefik_charm, tcp_tester_charm, ipu_tester_charm  # noqa
):
    await asyncio.gather(
        deploy_traefik_if_not_deployed(ops_test, traefik_charm),
        await deploy_charm_if_not_deployed(
            ops_test, tcp_tester_charm, "tcp-tester", resources=tcp_charm_resources
        ),
        await deploy_charm_if_not_deployed(ops_test, ipu_tester_charm, "ipu-tester"),
    )
    await asyncio.gather(
        safe_relate(ops_test, "tcp-tester", "traefik-k8s"),
        safe_relate(ops_test, "ipu-tester", "traefik-k8s"),
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "tcp-tester", "ipu-tester"], status="active", timeout=1000
        )
    yield
    await ops_test.model.applications["tcp-tester"].remove()
    await ops_test.model.applications["ipu-tester"].remove()


async def test_tcp_ipu_compatibility(ops_test, tcp_ipu_deployment):
    assert_tcp_charm_has_ingress(ops_test)
    assert_ipu_charm_has_ingress(ops_test)


async def test_tcp_ipa_compatibility(ops_test, tcp_ipa_deployment):
    assert_tcp_charm_has_ingress(ops_test)
    assert_ipa_charm_has_ingress(ops_test)
