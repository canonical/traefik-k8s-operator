# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import subprocess
import time
import urllib.request
from urllib.error import HTTPError

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay

from tests.integration.conftest import get_relation_data, trfk_resources

USERNAME = "admin"
PASSWORD = "admin"

# we don't expect a 200 because ipa-tester has no real server listening
SUCCESS_EXIT_CODE = 502

# user:hashed-password pair generated via https://www.transip.nl/htpasswd/
TEST_AUTH_USER = r"admin:$2a$13$XOHdzKdVS4mPKT0LvOfXru4LqyLbwcEvFlssXGS3laC6d/i6cKrLS"
APP_NAME = "traefik"
IPA = "ipa-tester"


@pytest.mark.abort_on_fail
@pytest.mark.skip_on_deployed
async def test_deployment(ops_test: OpsTest, traefik_charm, ipa_tester_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, application_name=APP_NAME, resources=trfk_resources, trust=True
        ),
        ops_test.model.deploy(ipa_tester_charm, IPA),
    )

    await ops_test.model.wait_for_idle([APP_NAME, IPA], status="active", timeout=1000)


@pytest.mark.abort_on_fail
@pytest.mark.skip_on_deployed
async def test_relate(ops_test: OpsTest):
    await ops_test.model.add_relation("ipa-tester:ingress", f"{APP_NAME}:ingress")
    await ops_test.model.wait_for_idle([APP_NAME, IPA])


def get_tester_url(model):
    data = get_relation_data(
        requirer_endpoint=f"{IPA}/0:ingress",
        provider_endpoint=f"{APP_NAME}/0:ingress",
        model=model,
    )
    provider_app_data = yaml.safe_load(data.provider.application_data["ingress"])
    return provider_app_data["url"]


@retry(stop=stop_after_delay(60 * 1))  # 5 minutes
def assert_get_url_returns(url: str, expected: int, auth: str = None):
    print(f"attempting to curl {url} (with auth? {'yes' if auth else 'no'})")
    if auth:
        passman = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passman.add_password(None, url, USERNAME, PASSWORD)
        authhandler = urllib.request.HTTPBasicAuthHandler(passman)
        opener = urllib.request.build_opener(authhandler)
        urllib.request.install_opener(opener)

    try:
        urllib.request.urlopen(url, timeout=1)
    except HTTPError as e:
        if e.code == expected:
            return True

        print(f"unexpected exit code {e.code}")
        time.sleep(0.1)
        raise AssertionError

    if expected == 200:
        return True

    print("unexpected 200")
    time.sleep(0.1)
    raise AssertionError


@pytest.fixture
def model(ops_test):
    return ops_test.model_full_name


def set_basic_auth(model: str, user: str):
    print(f"setting basic auth to {user!r}")
    option = f"basic_auth_user={user}" if user else "basic_auth_user="
    subprocess.run(["juju", "config", "-m", model, APP_NAME, option])


def test_ipa_charm_ingress_noauth(model):
    # GIVEN basic auth is disabled (initial condition)
    set_basic_auth(model, "")
    tester_url = get_tester_url(model)

    # WHEN we GET the tester url
    # THEN we get it fine
    assert_get_url_returns(tester_url, expected=SUCCESS_EXIT_CODE)


def test_ipa_charm_ingress_auth(model):
    # GIVEN basic auth is disabled (previous test)
    tester_url = get_tester_url(model)

    # WHEN we enable basic auth
    set_basic_auth(model, TEST_AUTH_USER)

    # THEN we can't GET the tester url
    # might take a little bit to apply the new config
    # 401 unauthorized
    assert_get_url_returns(tester_url, expected=401)

    # UNLESS we use auth
    assert_get_url_returns(tester_url, expected=SUCCESS_EXIT_CODE, auth=TEST_AUTH_USER)


def test_ipa_charm_ingress_auth_disable(model):
    # GIVEN auth is enabled (previous test)
    tester_url = get_tester_url(model)

    # WHEN we disable it again
    set_basic_auth(model, "")

    # THEN we eventually can GET the endpoint without auth
    # might take a little bit to apply the new config
    assert_get_url_returns(tester_url, expected=SUCCESS_EXIT_CODE)
