# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from urllib.parse import urlparse

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    assert_can_connect,
    deploy_traefik_if_not_deployed,
    get_relation_data,
)
from tests.integration.helpers import (
    delete_k8s_service,
    dequote,
    get_k8s_service_address,
    remove_application,
)

# FIXME Replace parts of this itest with a utest


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, ipu_tester_charm):
    await deploy_traefik_if_not_deployed(ops_test, traefik_charm)
    await ops_test.model.deploy(ipu_tester_charm, "ipu-tester")
    await ops_test.model.wait_for_idle(
        ["traefik-k8s", "ipu-tester"], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation(
        "ipu-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"
    )
    await ops_test.model.wait_for_idle(["traefik-k8s", "ipu-tester"])


def assert_ipu_charm_has_ingress(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipu-tester/0:ingress-per-unit",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
        model=ops_test.model_full_name,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    url = provider_app_data["ipu-tester/0"]["url"]
    url_parts = urlparse(url)
    ip = url_parts.hostname
    port = url_parts.port or 80
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
    assert dequote(requirer_unit_data["name"] == "ipu-tester/0")
    assert dequote(requirer_unit_data["port"] == "80")
    assert dequote(requirer_unit_data["host"] == "foo.bar")
    model = dequote(requirer_unit_data["model"])

    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    # example:
    #  ingress:
    #   ipu-tester/0:
    #     url: http://foo.bar/foo-ipu-tester-0
    traefik_address = await get_k8s_service_address(ops_test, "traefik-k8s-lb")
    assert provider_app_data == {
        "ipu-tester/0": {"url": f"http://{traefik_address}/{model}-ipu-tester-0"}
    }


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("relate", "ipu-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit")
    await ops_test.model.wait_for_idle(["traefik-k8s", "ipu-tester"], status="active")


async def test_cleanup(ops_test):
    await delete_k8s_service(ops_test, "traefik-k8s-lb")
    await remove_application(ops_test, "traefik-k8s", timeout=60)
