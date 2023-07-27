# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import json
from urllib.parse import urlparse

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    assert_can_connect,
    get_relation_data,
    trfk_resources,
)
from tests.integration.helpers import dequote, get_address, remove_application

# FIXME Replace parts of this itest with a utest


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, ipa_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, application_name="traefik-k8s", resources=trfk_resources
        ),
        ops_test.model.deploy(ipa_tester_charm, "ipa-tester"),
    )

    await ops_test.model.wait_for_idle(
        ["traefik-k8s", "ipa-tester"], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation("ipa-tester:ingress", "traefik-k8s:ingress")
    await ops_test.model.wait_for_idle(["traefik-k8s", "ipa-tester"])


def assert_ipa_charm_has_ingress(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipa-tester/0:ingress",
        provider_endpoint="traefik-k8s/0:ingress",
        model=ops_test.model_full_name,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    url = provider_app_data["url"]
    url_parts = urlparse(url)
    ip = url_parts.hostname
    port = url_parts.port or 80
    assert_can_connect(ip, port)


@pytest.mark.abort_on_fail
async def test_ipa_charm_has_ingress(ops_test: OpsTest):
    assert_ipa_charm_has_ingress(ops_test)


@pytest.mark.abort_on_fail
async def test_relation_data_shape(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipa-tester/0:ingress",
        provider_endpoint="traefik-k8s/0:ingress",
        model=ops_test.model_full_name,
    )

    requirer_app_data = data.requirer.application_data
    # example:
    # model: foo
    # name: ipa-tester/0
    # port: 8080
    model = dequote(requirer_app_data["model"])
    assert dequote(requirer_app_data["name"]) == "ipa-tester"
    assert dequote(requirer_app_data["port"]) == "80"

    # that was v1. ipa-tester talks v2
    assert not requirer_app_data.get("host")

    assert dequote(data.requirer.unit_data["host"]) == "foo.bar"

    # that was v1. ipa-tester talks v2
    assert not requirer_app_data.get("host")

    assert dequote(data.requirer.unit_data["host"]) == "foo.bar"

    # example:
    #  ingress:
    #    url: http://foo.bar/foo-ipa-tester/0
    traefik_address = await get_address(ops_test, "traefik-k8s")
    provider_app_data = json.loads(data.provider.application_data["ingress"])
    assert provider_app_data == {"url": f"http://{traefik_address}/{model}-ipa-tester"}


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("remove-relation", "ipa-tester:ingress", "traefik-k8s:ingress")
    await ops_test.model.wait_for_idle(["traefik-k8s", "ipa-tester"], status="active")


async def test_cleanup(ops_test):
    await remove_application(ops_test, "traefik-k8s", timeout=60)
