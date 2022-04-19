#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
import shutil
from os import unlink

import pytest
import yaml
from charms.traefik_k8s.v0.ingress_per_unit import (
    INGRESS_PROVIDES_APP_SCHEMA,
    INGRESS_REQUIRES_UNIT_SCHEMA,
    _validate_data,
)
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import (
    APP_NAME,
    RESOURCES,
    assert_status_reached,
    fast_forward,
)

logger = logging.getLogger(__name__)
REQUIRER_MOCK_APP_NAME = "ingress-requirer-mock"
HOSTNAME = "foo.bar"
PORT = 80


@pytest.mark.abort_on_fail
async def test_build_and_deploy_traefik(ops_test: OpsTest):
    """Build traefik-k8s and deploy it together with a tester charm."""
    # build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(charm, resources=RESOURCES, application_name=APP_NAME)
    await ops_test.juju("config", APP_NAME, f"external_hostname={HOSTNAME}")

    async with fast_forward(ops_test):
        await assert_status_reached(ops_test, "active")


@pytest.fixture(scope="session", autouse=True)
def copy_libs_to_tester_charm():
    install_paths = []
    for lib in ("ingress_per_unit", "ingress"):
        library_path = f"lib/charms/traefik_k8s/v0/{lib}.py"
        install_path = f"tests/integration/ingress-requirer-mock/{library_path}"
        install_paths.append(install_path)
        shutil.copyfile(library_path, install_path)

    yield

    # be nice and clean up
    for install_path in install_paths:
        unlink(install_path)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_requirer_mock(ops_test: OpsTest):
    """Build traefik-k8s and deploy it together with a tester charm."""
    # build and deploy ingress-requirer-mock tester charm
    charm = await ops_test.build_charm("./tests/integration/ingress-requirer-mock")
    await ops_test.model.deploy(charm, application_name=REQUIRER_MOCK_APP_NAME)

    async with fast_forward(ops_test):
        # is blocked until related
        await assert_status_reached(ops_test, "blocked", apps=[REQUIRER_MOCK_APP_NAME])


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    """Relate traefik and tester and check that all is green and ready."""
    await ops_test.model.add_relation(
        f"{REQUIRER_MOCK_APP_NAME}:ingress-per-unit", f"{APP_NAME}:ingress-per-unit"
    )

    async with fast_forward(ops_test):
        # now should go to active
        await assert_status_reached(ops_test, "active", apps=[REQUIRER_MOCK_APP_NAME])


async def test_requirer_unit_databag(ops_test: OpsTest):
    # we related the apps and ipu is up and running, so we expect to see:
    unit = APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", unit)

    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    requirer_unit_databag = yaml.safe_load(info)[unit]["relation-info"][0]["related-units"][
        remote_unit
    ]["data"]
    model_name = ops_test.model_name
    expected_requirer_unit_data = {
        "host": "0.0.0.0",
        "model": model_name,
        "name": remote_unit,
        "port": PORT,
    }

    # let's ensure it matches our own schema
    _validate_data(expected_requirer_unit_data, INGRESS_REQUIRES_UNIT_SCHEMA)

    ingress_data = yaml.safe_load(requirer_unit_databag["data"])
    assert ingress_data == expected_requirer_unit_data


def assert_requirer_app_databag_matches(raw, remote_unit, expected):
    requirer_app_databag = yaml.safe_load(raw)[remote_unit]["relation-info"][0]["application-data"]

    # let's ensure it matches our own schema
    _validate_data(expected, INGRESS_PROVIDES_APP_SCHEMA)

    ingress_data = yaml.safe_load(requirer_app_databag["data"])
    assert ingress_data == expected


async def test_provider_app_databag(ops_test: OpsTest):
    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", remote_unit)
    model_name = ops_test.model_name

    expected_requirer_app_data = {
        "ingress": {
            remote_unit: {
                "url": f"http://{HOSTNAME}:{PORT}/{model_name}-{remote_unit.replace('/', '-')}"
            }
        }
    }

    assert_requirer_app_databag_matches(info, remote_unit, expected_requirer_app_data)


async def test_scale_up_requirer(ops_test: OpsTest):
    # add two units of requirer mock
    await ops_test.juju("add-unit", REQUIRER_MOCK_APP_NAME, "-n2")
    await ops_test.model.wait_for_idle(
        [REQUIRER_MOCK_APP_NAME], status="active", wait_for_exact_units=3
    )


async def test_traefik_relation_data_after_upscale(ops_test: OpsTest):
    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", remote_unit)
    model_name = ops_test.model_name

    expected_requirer_app_data = {
        "ingress": {
            f"{REQUIRER_MOCK_APP_NAME}/{i}": {
                "url": f"http://{HOSTNAME}:{PORT}/{model_name}-{REQUIRER_MOCK_APP_NAME}-{i}"
            }
            for i in range(3)
        }
    }

    assert_requirer_app_databag_matches(info, remote_unit, expected_requirer_app_data)


async def test_scale_down_requirer(ops_test: OpsTest):
    # remove one unit; there should be two left
    await ops_test.juju("remove-unit", REQUIRER_MOCK_APP_NAME, "--num-units", "1")
    await ops_test.model.wait_for_idle(
        [REQUIRER_MOCK_APP_NAME], status="active", wait_for_exact_units=2
    )


async def test_traefik_relation_data_after_downscale(ops_test: OpsTest):
    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", remote_unit)
    model_name = ops_test.model_name

    expected_requirer_app_data = {
        "ingress": {
            f"{REQUIRER_MOCK_APP_NAME}/{i}": {
                "url": f"http://{HOSTNAME}:{PORT}/{model_name}-{REQUIRER_MOCK_APP_NAME}-{i}"
            }
            for i in range(2)
        }
    }

    assert_requirer_app_databag_matches(info, remote_unit, expected_requirer_app_data)
