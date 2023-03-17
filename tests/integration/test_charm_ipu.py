# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    assert_can_connect,
    deploy_traefik_if_not_deployed,
    get_relation_data,
)
from tests.integration.helpers import get_address


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, ipu_tester_charm):
    await deploy_traefik_if_not_deployed(ops_test, traefik_charm)
    await ops_test.model.deploy(ipu_tester_charm, "ipu-tester")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "ipu-tester"], status="active", timeout=1000
        )


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation(
        "ipu-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "ipu-tester"])


def assert_ipu_charm_has_ingress(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipu-tester/0:ingress-per-unit",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
        model=ops_test.model_full_name,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    url = provider_app_data["ipu-tester/0"]["url"]
    ip, port = url.split("//")[1].split("/")[0].split(":")
    assert_can_connect(ip, port)


@pytest.mark.abort_on_fail
async def test_ipu_charm_has_ingress(ops_test: OpsTest):
    assert_ipu_charm_has_ingress(ops_test)


@pytest.mark.abort_on_fail
async def test_relation_data_shape(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipu-tester/0:ingress-per-unit",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
        model=ops_test.model_full_name,
    )

    requirer_unit_data = data.requirer.unit_data
    # example:
    # host: 10.1.232.176
    # model: foo
    # name: ipu-tester/0
    # port: 9090
    assert requirer_unit_data["name"] == "ipu-tester/0"
    assert requirer_unit_data["port"] == "80"
    assert requirer_unit_data["host"] == "foo.bar"
    model = requirer_unit_data["model"]

    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    # example:
    #  ingress:
    #   ipu-tester/0:
    #     url: http://foo.bar:80/foo-ipu-tester-0
    traefik_address = await get_address(ops_test, "traefik-k8s")
    assert provider_app_data == {
        "ipu-tester/0": {"url": f"http://{traefik_address}:80/{model}-ipu-tester-0"}
    }


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("relate", "ipu-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "ipu-tester"], status="active")
    await ops_test.model.applications["traefik-k8s"].destroy(
        destroy_storage=True, force=True, no_wait=True
    )
