#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging

import pytest
import yaml
from charms.traefik_k8s.v0.ingress import INGRESS_SCHEMA
from charms.traefik_k8s.v0.ingress_per_unit import (
    INGRESS_REQUIRES_UNIT_SCHEMA,
    _validate_data,
)
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import REQUIRER_MOCK_CHARM, TRAEFIK_CHARM
from tests.integration.helpers import (
    APP_NAME,
    RESOURCES,
    assert_app_databag_equals,
    assert_status_reached,
    fast_forward,
)

INGRESS_PROVIDES_APP_SCHEMA = INGRESS_SCHEMA["v1"]["provides"]["app"]
logger = logging.getLogger(__name__)
REQUIRER_MOCK_APP_NAME = "ingress-requirer-mock"
HOSTNAME = "foo.bar"
PORT = 80


@pytest.mark.abort_on_fail
async def test_deploy_traefik(ops_test: OpsTest):
    """Build traefik-k8s and deploy it together with a tester charm."""
    # build and deploy charm from local source folder
    await ops_test.model.deploy(TRAEFIK_CHARM, resources=RESOURCES, application_name=APP_NAME)
    await ops_test.juju("config", APP_NAME, f"external_hostname={HOSTNAME}")

    async with fast_forward(ops_test):
        await assert_status_reached(ops_test, "active")


@pytest.mark.abort_on_fail
async def test_deploy_requirer_mock(ops_test: OpsTest):
    """Build traefik-k8s and deploy it together with a tester charm."""
    # build and deploy ingress-requirer-mock tester charm
    await ops_test.model.deploy(REQUIRER_MOCK_CHARM, application_name=REQUIRER_MOCK_APP_NAME)

    async with fast_forward(ops_test):
        # is blocked until related
        await assert_status_reached(ops_test, "blocked", apps=[REQUIRER_MOCK_APP_NAME])


@pytest.mark.abort_on_fail
async def test_relate(ops_test: OpsTest):
    """Relate traefik and tester and check that all is green and ready."""
    # traefik calls it 'ingress', the tester calls it ingress-per-app
    await ops_test.model.add_relation(
        f"{REQUIRER_MOCK_APP_NAME}:ingress-per-app", f"{APP_NAME}:ingress"
    )

    async with fast_forward(ops_test):
        # now should go to active; but this might race with us checking for
        # active --> we don't raise on blocked
        await assert_status_reached(
            ops_test, "active", apps=[REQUIRER_MOCK_APP_NAME], raise_on_blocked=False
        )


async def test_requirer_app_databag(ops_test: OpsTest):
    # we related the apps and ipu is up and running, so we expect to see:
    unit = APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", unit)

    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    requirer_unit_databag = yaml.safe_load(info)[unit]["relation-info"][0]["application-data"][
        "data"
    ]
    model_name = ops_test.model_name
    expected_requirer_unit_data = {
        "host": "0.0.0.0",
        "model": model_name,
        "name": remote_unit,
        "port": PORT,
    }

    # let's ensure it matches our own schema
    _validate_data(expected_requirer_unit_data, INGRESS_REQUIRES_UNIT_SCHEMA)

    ingress_data = yaml.safe_load(requirer_unit_databag)
    assert ingress_data == expected_requirer_unit_data


async def test_provider_app_databag(ops_test: OpsTest):
    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", remote_unit)
    model_name = ops_test.model_name

    expected_requirer_app_data = {
        "ingress": {"url": f"http://{HOSTNAME}:{PORT}/{model_name}-{REQUIRER_MOCK_APP_NAME}"}
    }

    assert_app_databag_equals(
        info, remote_unit, expected_requirer_app_data, INGRESS_PROVIDES_APP_SCHEMA
    )


async def test_scale_up_requirer(ops_test: OpsTest):
    # add two units of requirer mock
    await ops_test.juju("add-unit", REQUIRER_MOCK_APP_NAME, "-n2")
    await assert_status_reached(ops_test,
        apps=[REQUIRER_MOCK_APP_NAME], status="active", raise_on_blocked=False, wait_for_exact_units=3
    )


async def test_traefik_relation_data_after_upscale(ops_test: OpsTest):
    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", remote_unit)
    model_name = ops_test.model_name

    expected_requirer_app_data = {
        "ingress": {"url": f"http://{HOSTNAME}:{PORT}/{model_name}-{REQUIRER_MOCK_APP_NAME}"}
    }

    assert_app_databag_equals(
        info, remote_unit, expected_requirer_app_data, INGRESS_PROVIDES_APP_SCHEMA
    )


async def test_scale_down_requirer(ops_test: OpsTest):
    # remove one unit; there should be two left
    await ops_test.juju("remove-unit", REQUIRER_MOCK_APP_NAME, "--num-units", "1")
    await assert_status_reached(
        ops_test, apps=[REQUIRER_MOCK_APP_NAME], status="active", wait_for_exact_units=2
    )


async def test_traefik_relation_data_after_downscale(ops_test: OpsTest):
    remote_unit = REQUIRER_MOCK_APP_NAME + "/0"
    _, info, _ = await ops_test.juju("show-unit", remote_unit)
    model_name = ops_test.model_name

    expected_requirer_app_data = {
        "ingress": {"url": f"http://{HOSTNAME}:{PORT}/{model_name}-{REQUIRER_MOCK_APP_NAME}"}
    }

    assert_app_databag_equals(
        info, remote_unit, expected_requirer_app_data, INGRESS_PROVIDES_APP_SCHEMA
    )


# cleanup before closing this test module: unrelate applications, scale requirer
# mock back down to 1 and check final status
async def test_reset_to_initial_state(ops_test):
    await ops_test.juju("remove-unit", REQUIRER_MOCK_APP_NAME, "--num-units", "1")
    async with fast_forward(ops_test):
        await assert_status_reached(ops_test, "active", apps=[REQUIRER_MOCK_APP_NAME])

    await ops_test.juju(
        "remove-relation", f"{REQUIRER_MOCK_APP_NAME}:ingress-per-app", f"{APP_NAME}:ingress"
    )

    async with fast_forward(ops_test):
        # wait for it to get back to blocked; verify traefik goes to active
        await asyncio.gather(
            assert_status_reached(ops_test, "blocked", apps=[REQUIRER_MOCK_APP_NAME]),
            assert_status_reached(ops_test, "active", apps=[APP_NAME]),
        )
