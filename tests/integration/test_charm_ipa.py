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

    # we pin the revision to prevent upstream changes breaking our itests,
    #   bump this version sometime in the future.
    await ops_test.juju("deploy", "spring-music", "--channel=edge", "--revision=3")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "spring-music"], status="active")


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.juju("relate", "spring-music:ingress", "traefik-k8s:ingress")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "spring-music"])


async def test_relation_data_shape(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="spring-music/0:ingress", provider_endpoint="traefik-k8s/0:ingress"
    )

    requirer_app_data = data.requirer.application_data
    # example:
    # host: spring-music.foo.svc.cluster.local
    # model: foo
    # name: spring-music/0
    # port: 8080
    model = requirer_app_data["model"]
    assert requirer_app_data["host"] == f"spring-music.{model}.svc.cluster.local"
    assert requirer_app_data["name"] == "spring-music/0"
    assert requirer_app_data["host"] == "8080"

    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    # example:
    #  ingress:
    #    url: http://foo.bar:80/foo-spring-music/0

    assert provider_app_data == {"url": f"http://foo.bar:80/{model}-spring-music/0"}


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("remove-relation", "spring-music:ingress", "traefik-k8s:ingress")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "spring-music"], status="active")
