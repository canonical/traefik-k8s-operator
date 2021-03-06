# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import get_relation_data

ipa_charm_root = (Path(__file__).parent / "testers" / "ipa").absolute()
meta = yaml.safe_load((Path() / "metadata.yaml").read_text())
resources = {name: val["upstream-source"] for name, val in meta["resources"].items()}


@pytest_asyncio.fixture
async def ipa_tester_charm(ops_test: OpsTest):
    lib_source = Path() / "lib" / "charms" / "traefik_k8s" / "v1" / "ingress.py"
    libs_folder = ipa_charm_root / "lib" / "charms" / "traefik_k8s" / "v1"
    libs_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(lib_source, libs_folder)
    return await ops_test.build_charm(ipa_charm_root)


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, ipa_tester_charm):
    if not ops_test.model.applications.get("traefik-k8s"):
        await ops_test.model.deploy(traefik_charm, resources=resources)
    await ops_test.model.applications["traefik-k8s"].set_config({"external_hostname": "foo.bar"})

    await ops_test.model.deploy(ipa_tester_charm, "ipa-tester")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "ipa-tester"], status="active")


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation("ipa-tester:ingress", "traefik-k8s:ingress")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "ipa-tester"])


@pytest.mark.abort_on_fail
async def test_relation_data_shape(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipa-tester/0:ingress",
        provider_endpoint="traefik-k8s/0:ingress",
        model=ops_test.model_full_name,
    )

    requirer_app_data = data.requirer.application_data
    # example:
    # host: foo.bar
    # model: foo
    # name: ipa-tester/0
    # port: 8080
    model = requirer_app_data["model"]
    assert requirer_app_data["host"] == "foo.bar"
    assert requirer_app_data["name"] == "ipa-tester"
    assert requirer_app_data["port"] == "80"

    # example:
    #  ingress:
    #    url: http://foo.bar:80/foo-ipa-tester/0
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    assert provider_app_data == {"url": f"http://foo.bar:80/{model}-ipa-tester"}


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("remove-relation", "ipa-tester:ingress", "traefik-k8s:ingress")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "ipa-tester"], status="active")
