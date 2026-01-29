# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import shlex
import urllib.error
from subprocess import PIPE, Popen
from urllib.request import Request, urlopen

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import trfk_resources
from tests.integration.helpers import get_k8s_service_address, remove_application

APP_NAME = "traefik"
TESTER_APP_NAME = "route"


@pytest.mark.abort_on_fail
@pytest.mark.setup
async def test_deployment(ops_test: OpsTest, traefik_charm, route_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, application_name=APP_NAME, resources=trfk_resources, trust=True
        ),
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
    cmd = (
        f"juju ssh -m {ops_test.model_name} --container traefik"
        f" {APP_NAME}/0 cat /etc/traefik/traefik.yaml"
    )
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


async def test_scale_and_get_external_host(ops_test: OpsTest):
    """Test that traefik application data is available in all units of the route tester charm."""
    await ops_test.juju("add-unit", TESTER_APP_NAME)
    await ops_test.model.wait_for_idle([TESTER_APP_NAME], status="active", timeout=1000)

    unit_0 = ops_test.model.applications[TESTER_APP_NAME].units[0]
    unit_1 = ops_test.model.applications[TESTER_APP_NAME].units[1]

    action_0 = await unit_0.run_action("get-external-host")
    action_1 = await unit_1.run_action("get-external-host")

    result_0 = await action_0.wait()
    result_1 = await action_1.wait()

    traefik_ip = await get_k8s_service_address(ops_test, f"{APP_NAME}-lb")

    external_host_0 = result_0.results.get("external-host")
    external_host_1 = result_1.results.get("external-host")

    assert external_host_0 == external_host_1, (
        f"External host values should match: {external_host_0} vs {external_host_1}"
    )
    assert external_host_0 is not None, "External host should not be None"
    assert external_host_0 == traefik_ip, (
        f"External host should match traefik IP: {external_host_0} vs {traefik_ip}"
    )


@pytest.mark.teardown
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.juju(
        "remove-relation", f"{TESTER_APP_NAME}:traefik-route", f"{APP_NAME}:traefik-route"
    )
    await ops_test.model.wait_for_idle([APP_NAME], status="active")


async def test_cleanup(ops_test):
    await remove_application(ops_test, APP_NAME, timeout=60)
