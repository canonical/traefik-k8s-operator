# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import get_relation_data

meta = yaml.safe_load((Path() / "metadata.yaml").read_text())
resources = {name: val["upstream-source"] for name, val in meta["resources"].items()}


@pytest.fixture(autouse=True)
@pytest.mark.abort_on_fail
async def deployment(ops_test: OpsTest, traefik_charm):
    if not ops_test.model.applications.get("traefik-k8s"):
        await ops_test.model.deploy(traefik_charm, resources=resources)
    await ops_test.model.applications["traefik-k8s"].set_config({"external_hostname": "foo.bar"})

    # we pin revision 36 to prevent upstream changes breaking our itests,
    #   bump this version sometime in the future.
    await ops_test.juju("deploy", "prometheus-k8s", "--channel=edge", "--revision=36")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "prometheus-k8s"], status="active", timeout=1000
        )


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.juju("relate", "prometheus-k8s:ingress", "traefik-k8s:ingress-per-unit")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "prometheus-k8s"])


@pytest.mark.abort_on_fail
async def test_relation_data_shape():
    data = get_relation_data(
        requirer_endpoint="prometheus-k8s/0:ingress",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
    )

    requirer_unit_data = yaml.safe_load(data.requirer.unit_data["data"])
    # example:
    # host: 10.1.232.176
    # model: foo
    # name: prometheus-k8s/0
    # port: 9090
    assert requirer_unit_data["name"] == "prometheus-k8s/0"
    assert requirer_unit_data["host"] == "9090"
    model = requirer_unit_data["model"]

    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    # example:
    #  ingress:
    #   prometheus-k8s/0:
    #     url: http://foo.bar:80/foo-prometheus-k8s-0

    assert provider_app_data == {
        "prometheus-k8s/0": {"url": f"http://foo.bar:80/{model}-prometheus-k8s-0"}
    }


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("relate", "prometheus-k8s:ingress", "traefik-k8s:ingress-per-unit")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "spring-music"], status="active")
