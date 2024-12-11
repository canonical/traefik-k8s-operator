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
from tests.integration.helpers import (
    delete_k8s_service,
    get_k8s_service_address,
    remove_application,
)

APP_NAME = "traefik"
TESTER_APP_NAME = "route"


@pytest.mark.abort_on_fail
@pytest.mark.setup
async def test_deployment(ops_test: OpsTest, traefik_charm, route_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(traefik_charm, application_name=APP_NAME, resources=trfk_resources),
        ops_test.model.deploy(route_tester_charm, TESTER_APP_NAME),
    )

    await ops_test.model.wait_for_idle([APP_NAME, TESTER_APP_NAME], status="active", timeout=1000)


@pytest.mark.setup
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation(
        f"{TESTER_APP_NAME}:traefik-route", f"{APP_NAME}:traefik-route"
    )
    await ops_test.model.wait_for_idle([APP_NAME, TESTER_APP_NAME])


async def test_dynamic_config_created(ops_test: OpsTest):
    relation = [
        r
        for r in ops_test.model.relations
        if r.matches(f"{TESTER_APP_NAME}:traefik-route", f"{APP_NAME}:traefik-route")
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


async def test_static_config_updated(ops_test: OpsTest):
    cmd = f"juju ssh -m {ops_test.model_name} --container traefik {APP_NAME}/0 cat /etc/traefik/traefik.yaml"
    proc = Popen(shlex.split(cmd), stdout=PIPE, text=True)
    contents = proc.stdout.read()
    contents_yaml = yaml.safe_load(contents)
    # the route tester charm does:
    # static = {"entryPoints": {"test-port": {"address": ":4545"}}},
    assert contents_yaml["entryPoints"]["test-port"] == {"address": ":4545"}


async def test_added_entrypoint_reachable(ops_test: OpsTest):
    traefik_ip = await get_k8s_service_address(ops_test, f"{APP_NAME}-lb")

    req = Request(f"http://{traefik_ip}:4545")

    with pytest.raises(urllib.error.HTTPError, match="404"):
        urlopen(req, timeout=60)


@pytest.mark.teardown
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju(
        "remove-relation", f"{TESTER_APP_NAME}:traefik-route", f"{APP_NAME}:traefik-route"
    )
    await ops_test.model.wait_for_idle([APP_NAME], status="active")


async def test_cleanup(ops_test):
    await delete_k8s_service(ops_test, f"{APP_NAME}-lb")
    await remove_application(ops_test, APP_NAME, timeout=60)
