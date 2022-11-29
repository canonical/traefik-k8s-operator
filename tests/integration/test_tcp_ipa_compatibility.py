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
from tests.integration.test_charm_ipa import assert_ipa_charm_has_ingress  # noqa
from tests.integration.test_charm_ipu import assert_ipu_charm_has_ingress  # noqa
from tests.integration.test_charm_tcp import (  # noqa
    assert_tcp_charm_has_ingress,
    tcp_charm_resources,
)


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
        safe_relate(ops_test, "tcp-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"),
        safe_relate(ops_test, "ipa-tester:ingress", "traefik-k8s:ingress"),
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "tcp-tester", "ipa-tester"], status="active", timeout=1000
        )


async def test_tcp_ipa_compatibility(ops_test, tcp_ipa_deployment):
    assert_tcp_charm_has_ingress(ops_test)
    assert_ipa_charm_has_ingress(ops_test)
