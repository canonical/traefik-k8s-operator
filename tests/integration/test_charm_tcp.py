# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import re
import shutil
import socket
from pathlib import Path
from subprocess import PIPE, Popen

import pytest
import pytest_asyncio
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    charm_root,
    deploy_traefik_if_not_deployed,
    get_relation_data,
)

tcp_charm_root = (Path(__file__).parent / "testers" / "tcp").absolute()
tcp_charm_meta = yaml.safe_load((tcp_charm_root / "metadata.yaml").read_text())
tcp_charm_resources = {
    name: val["upstream-source"] for name, val in tcp_charm_meta["resources"].items()
}


@pytest_asyncio.fixture
async def tcp_tester_charm(ops_test: OpsTest):
    lib_source = charm_root / "lib" / "charms" / "traefik_k8s" / "v1" / "ingress_per_unit.py"
    libs_folder = tcp_charm_root / "lib" / "charms" / "traefik_k8s" / "v1"
    libs_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(lib_source, libs_folder)
    return await ops_test.build_charm(tcp_charm_root)


def get_unit_ip(ops_test: OpsTest):
    proc = Popen(f"juju status -m {ops_test.model_name}".split(), stdout=PIPE)
    raw_status = proc.stdout.read()
    trfk_lines = [line for line in raw_status.split(b"\n") if b"traefik-k8s/0" in line]
    if not trfk_lines:
        raise RuntimeError(raw_status)
    unit_status = trfk_lines[0]
    ip = re.findall(re.compile(rb"\d+\.\d+\.\d+\.\d+"), unit_status)[0]
    return ip.decode("ascii")


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, tcp_tester_charm):
    await deploy_traefik_if_not_deployed(ops_test, traefik_charm)
    await ops_test.model.deploy(
        tcp_tester_charm, "tcp-tester", resources=tcp_charm_resources, series="focal"
    )
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
    traefik_unit_ip = get_unit_ip(ops_test)

    assert provider_app_data == {"tcp-tester/0": {"url": f"{traefik_unit_ip}:{port}"}}


async def assert_tcp_charm_has_ingress(ops_test: OpsTest):
    traefik_unit_ip = get_unit_ip(ops_test)
    data = get_relation_data(
        requirer_endpoint="tcp-tester/0:ingress-per-unit",
        provider_endpoint="traefik-k8s/0:ingress-per-unit",
        model=ops_test.model_full_name,
    )
    port = data.requirer.unit_data["port"]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((traefik_unit_ip, int(port)))
        s.sendall(b"Hello, world")
        data = s.recv(1024)

    assert data == b"Hello, world"


async def test_tcp_connection(ops_test: OpsTest):
    await assert_tcp_charm_has_ingress(ops_test)


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju(
        "remove-relation", "tcp-tester:ingress-per-unit", "traefik-k8s:ingress-per-unit"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s"], status="active")
        # the tcp-tester is allowed to bork out, we don't really care
