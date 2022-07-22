# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import get_relation_data

ipu_charm_root = (Path(__file__).parent / "testers" / "ipu").absolute()
meta = yaml.safe_load((Path() / "metadata.yaml").read_text())
resources = {name: val["upstream-source"] for name, val in meta["resources"].items()}


@pytest_asyncio.fixture
async def ipu_tester_charm(ops_test: OpsTest):
    lib_source = Path() / "lib" / "charms" / "traefik_k8s" / "v1" / "ingress_per_unit.py"
    libs_folder = ipu_charm_root / "lib" / "charms" / "traefik_k8s" / "v1"
    libs_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(lib_source, libs_folder)
    return await ops_test.build_charm(ipu_charm_root)


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, ipu_tester_charm):
    if not ops_test.model.applications.get("traefik-k8s"):
        await ops_test.model.deploy(traefik_charm, resources=resources)
    await ops_test.model.applications["traefik-k8s"].set_config({"external_hostname": "foo.bar"})

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

    assert provider_app_data == {
        "ipu-tester/0": {"url": f"http://foo.bar:80/{model}-ipu-tester-0"}
    }


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("relate", "ipu-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "ipu-tester"], status="active")
