# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import socket
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import deploy_traefik_if_not_deployed, get_relation_data
from tests.integration.helpers import get_address

logger = logging.getLogger(__name__)


tcp_charm_root = (Path(__file__).parent / "testers" / "tcp").absolute()
tcp_charm_meta = yaml.safe_load((tcp_charm_root / "metadata.yaml").read_text())
tcp_charm_resources = {
    name: val["upstream-source"] for name, val in tcp_charm_meta["resources"].items()
}


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, tcp_tester_charm):
    await deploy_traefik_if_not_deployed(ops_test, traefik_charm)
    await ops_test.model.deploy(tcp_tester_charm, "tcp-tester", resources=tcp_charm_resources)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            ["traefik-k8s", "tcp-tester"], status="active", timeout=1000
        )


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation(
        "tcp-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s", "tcp-tester"])


@pytest.mark.abort_on_fail
async def test_relation_data_shape(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="tcp-tester/0:ingress-per-unit",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
        model=ops_test.model_full_name,
    )

    requirer_unit_data = data.requirer.unit_data
    # example:
    # host: foo.bar
    # model: foo
    # name: tcp-tester/0
    # port: 8080

    # model = requirer_unit_data["model"]
    # assert requirer_unit_data["host"] == "foo.bar"
    assert requirer_unit_data["name"] == "tcp-tester/0"
    port = requirer_unit_data["port"]
    assert port.isdigit()

    # example:
    #  ingress:
    #    url: http://foo.bar:80/foo-tcp-tester/0
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    traefik_ip = await get_address(ops_test, "traefik-k8s")

    assert provider_app_data == {"tcp-tester/0": {"url": f"{traefik_ip}:{port}"}}


async def assert_tcp_charm_has_ingress(ops_test: OpsTest):
    traefik_ip = await get_address(ops_test, "traefik-k8s")
    data = get_relation_data(
        requirer_endpoint="tcp-tester/0:ingress-per-unit",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
        model=ops_test.model_full_name,
    )
    port = data.requirer.unit_data["port"]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        logger.info("Attempting to connect %s:%s...", traefik_ip, int(port))
        s.connect((traefik_ip, int(port)))
        s.sendall(b"Hello, world")
        data = s.recv(1024)

    assert data == b"Hello, world"


@pytest.mark.abort_on_fail
async def test_tcp_connection(ops_test: OpsTest):
    await assert_tcp_charm_has_ingress(ops_test)


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju(
        "remove-relation", "tcp-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s"], status="active")
        # the tcp-tester is allowed to bork out, we don't really care
    await ops_test.model.applications["traefik-k8s"].destroy(
        destroy_storage=True, force=True, no_wait=True
    )
