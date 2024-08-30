# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import subprocess
import urllib.request
from urllib.error import HTTPError

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay

from tests.integration.conftest import (
    get_relation_data,
    trfk_resources,
)

USERNAME = "admin"
PASSWORD = "admin"

# user:hashed-password pair generated via https://www.transip.nl/htpasswd/
TEST_AUTH_USER = r"admin:$2a$13$XOHdzKdVS4mPKT0LvOfXru4LqyLbwcEvFlssXGS3laC6d/i6cKrLS"
APP_NAME = "traefik"


@pytest.mark.abort_on_fail
@pytest.mark.skip_on_deployed
async def test_deployment(ops_test: OpsTest, traefik_charm, ipa_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(traefik_charm, application_name=APP_NAME, resources=trfk_resources),
        ops_test.model.deploy(ipa_tester_charm, "ipa-tester"),
    )

    await ops_test.model.wait_for_idle([APP_NAME, "ipa-tester"], status="active", timeout=1000)


@pytest.mark.abort_on_fail
@pytest.mark.skip_on_deployed
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation("ipa-tester:ingress", f"{APP_NAME}:ingress")
    await ops_test.model.wait_for_idle([APP_NAME, "ipa-tester"])


def get_tester_url(ops_test: OpsTest):
    data = get_relation_data(
        requirer_endpoint="ipa-tester/0:ingress",
        provider_endpoint=f"{APP_NAME}/0:ingress",
        model=ops_test.model_full_name,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    return provider_app_data["url"]


def get_url(url: str, auth: str = None):
    if auth:
        passman = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passman.add_password(None, url, USERNAME, PASSWORD)
        authhandler = urllib.request.HTTPBasicAuthHandler(passman)
        opener = urllib.request.build_opener(authhandler)
        urllib.request.install_opener(opener)

    try:
        urllib.request.urlopen(url, timeout=1)
    except HTTPError as e:
        return e.code
    return 200


def set_basic_auth(model: str, user: str):
    option = f"basic_auth_user={user}" if user else "basic_auth_user="
    subprocess.run(["juju", "config", "-m", model, APP_NAME, option])


async def test_ipa_charm_ingress_noauth(ops_test: OpsTest):
    # GIVEN basic auth is disabled (initial condition)
    model_name = ops_test.model_full_name
    set_basic_auth(model_name, "")
    tester_url = get_tester_url(ops_test)

    # WHEN we GET the tester url
    # THEN we get it fine
    for attempt in Retrying(stop=stop_after_delay(60 * 5)):  # 5 minutes
        with attempt:
            assert get_url(tester_url) == 200


@pytest.mark.abort_on_fail
async def test_ipa_charm_ingress_auth(ops_test: OpsTest):
    # GIVEN basic auth is disabled (previous test)
    model_name = ops_test.model_full_name
    tester_url = get_tester_url(ops_test)

    # WHEN we enable basic auth
    set_basic_auth(model_name, TEST_AUTH_USER)

    # THEN we can't GET the tester url
    for attempt in Retrying(stop=stop_after_delay(60 * 5)):  # 5 minutes
        with attempt:
            # might take a little bit to apply the new config
            # 401 unauthorized
            assert get_url(tester_url) == 401

    # UNLESS we use auth
    assert get_url(tester_url, TEST_AUTH_USER) == 401


@pytest.mark.abort_on_fail
async def test_ipa_charm_ingress_auth_disable(ops_test: OpsTest):
    # GIVEN auth is enabled (previous test)
    model_name = ops_test.model_full_name
    tester_url = get_tester_url(ops_test)

    # WHEN we disable it again
    set_basic_auth(model_name, "")

    # THEN we eventually can GET the endpoint without auth
    for attempt in Retrying(stop=stop_after_delay(60 * 5)):  # 5 minutes
        with attempt:
            # might take a little bit to apply the new config
            assert get_url(tester_url) == 200
