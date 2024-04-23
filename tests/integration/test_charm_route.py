# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import shlex
import urllib.error
from subprocess import PIPE, Popen
from urllib.request import Request, urlopen

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import (
    trfk_resources,
)
from tests.integration.helpers import get_address

APP_NAME = "traefik-k8s"


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, route_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(traefik_charm, application_name=APP_NAME, resources=trfk_resources),
        ops_test.model.deploy(route_tester_charm, "tr-tester"),
    )

    await ops_test.model.wait_for_idle([APP_NAME, "tr-tester"], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation("tr-tester:traefik-route", "traefik-k8s:traefik-route")
    await ops_test.model.wait_for_idle([APP_NAME, "tr-tester"])


@pytest.mark.abort_on_fail
async def test_dynamic_config_created(ops_test: OpsTest):
    relation = [
        r
        for r in ops_test.model.relations
        if r.matches("tr-tester:traefik-route", "traefik-k8s:traefik-route")
    ][0]
    relation_id = relation.entity_id
    cmd = (
        f"juju ssh -m {ops_test.model_name} --container traefik {APP_NAME}/0 "
        f"cat /opt/traefik/juju/juju_ingress_traefik-route_{relation_id}_route.yaml"
    )
    proc = Popen(shlex.split(cmd), stdout=PIPE, text=True)
    contents = proc.stdout.read()
    contents_yaml = yaml.safe_load(contents)
    # the route tester charm does:
    # config = {"some": "config"},
    assert contents_yaml["some"] == "config"


@pytest.mark.abort_on_fail
async def test_static_config_updated(ops_test: OpsTest):
    cmd = f"juju ssh -m {ops_test.model_name} --container traefik {APP_NAME}/0 cat /etc/traefik/traefik.yaml"
    proc = Popen(shlex.split(cmd), stdout=PIPE, text=True)
    contents = proc.stdout.read()
    contents_yaml = yaml.safe_load(contents)
    # the route tester charm does:
    # static = {"entryPoints": {"testPort": {"address": ":4545"}}},
    assert contents_yaml["entryPoints"]["testPort"] == {"address": ":4545"}


@pytest.mark.abort_on_fail
async def test_added_entrypoint_reachable(ops_test: OpsTest):
    traefik_ip = await get_address(ops_test, "traefik-k8s")

    req = Request(f"http://{traefik_ip}:4545")

    with pytest.raises(urllib.error.HTTPError, match="404"):
        urlopen(req)


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju("remove-relation", "tr-tester:traefik-route", f"{APP_NAME}:traefik-route")
    await ops_test.model.wait_for_idle([APP_NAME], status="active")
