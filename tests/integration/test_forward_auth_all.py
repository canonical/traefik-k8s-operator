# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import pytest
import requests
from helpers import get_k8s_service_address
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import deploy_traefik_if_not_deployed

logger = logging.getLogger(__name__)

OATHKEEPER_CHARM = "oathkeeper"
TRAEFIK_CHARM = "traefik-k8s"

APP1_CHARM = "app1"
APP2_CHARM = "app2"


async def get_reverse_proxy_app_url(
    ops_test: OpsTest, ingress_app_name: str, app_name: str
) -> str:
    """Get the ingress address of an app."""
    address = await get_k8s_service_address(ops_test, f"{ingress_app_name}-lb")
    proxy_app_url = f"http://{address}/{ops_test.model.name}-{app_name}/"
    logger.debug(f"Retrieved address: {proxy_app_url}")
    return proxy_app_url


@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm, forward_auth_tester_charm):
    """Deploy the charms and integrations required to set up an Identity and Access Proxy."""
    await deploy_traefik_if_not_deployed(ops_test, traefik_charm)

    # Enable experimental-forward-auth
    await ops_test.model.applications[TRAEFIK_CHARM].set_config(
        {"enable_experimental_forward_auth": "True"}
    )

    # Deploy oauth2-proxy
    await ops_test.model.deploy(
        OATHKEEPER_CHARM,
        channel="latest/edge",
        trust=True,
    )

    # Deploy the app1 charm
    await ops_test.model.deploy(
        application_name=APP1_CHARM,
        entity_url=forward_auth_tester_charm,
        resources={"oci-image": "kennethreitz/httpbin"},
        trust=True,
    )

    # Deploy the app2 charm
    await ops_test.model.deploy(
        application_name=APP2_CHARM,
        entity_url=forward_auth_tester_charm,
        resources={"oci-image": "kennethreitz/httpbin"},
        trust=True,
    )

    await ops_test.model.integrate(f"{APP1_CHARM}:ingress", TRAEFIK_CHARM)
    await ops_test.model.integrate(f"{APP2_CHARM}:ingress", TRAEFIK_CHARM)

    # Only app1 is integrated with Oathkeeper
    await ops_test.model.integrate(f"{APP1_CHARM}:auth-proxy", OATHKEEPER_CHARM)

    await ops_test.model.integrate(f"{TRAEFIK_CHARM}:experimental-forward-auth", OATHKEEPER_CHARM)

    # The auth lib uses event deferral, so by extension it depends on the update-status hook.
    # As a result, when we use our 60m interval from the autouse fixture, test occasionally fail.
    # Here we override the interval just for this test.
    await ops_test.model.set_config({"update-status-hook-interval": "5m"})

    await ops_test.model.wait_for_idle(
        [
            TRAEFIK_CHARM,
            OATHKEEPER_CHARM,
            APP1_CHARM,
            APP2_CHARM,
        ],
        status="active",
        timeout=1000,
    )


async def test_allowed_urls(ops_test: OpsTest) -> None:
    """Test that app1 is protected and not app2."""
    app1_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP1_CHARM)
    app2_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP2_CHARM)

    resp = requests.get(app1_url, verify=False)
    assert resp.status_code == 401

    resp = requests.get(app2_url, verify=False)
    assert resp.status_code == 200


async def test_protected_everything(ops_test: OpsTest) -> None:
    """Test protected everything."""
    await ops_test.model.applications[TRAEFIK_CHARM].set_config({"forward_auth_all": "True"})

    await ops_test.model.wait_for_idle(
        [
            TRAEFIK_CHARM,
        ],
        status="active",
        timeout=1000,
    )

    app1_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP1_CHARM)
    app2_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP2_CHARM)

    resp = requests.get(app1_url, verify=False)
    assert resp.status_code == 401

    resp = requests.get(app2_url, verify=False)
    assert resp.status_code == 401


async def test_protected_everything_but_forward_auth_is_off(
    ops_test: OpsTest,
) -> None:
    """Test protected everything with enable_experimental_forward_auth off.

    Since the experimental forward auth is off, the forward_auth_all should not
    protect the applications.
    """
    await ops_test.model.applications[TRAEFIK_CHARM].set_config({"forward_auth_all": "True"})
    await ops_test.model.applications[TRAEFIK_CHARM].set_config(
        {"enable_experimental_forward_auth": "False"}
    )

    await ops_test.model.wait_for_idle(
        [
            TRAEFIK_CHARM,
        ],
        status="active",
        timeout=1000,
    )

    app1_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP1_CHARM)
    app2_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP2_CHARM)

    resp = requests.get(app1_url, verify=False)
    assert resp.status_code == 200

    resp = requests.get(app2_url, verify=False)
    assert resp.status_code == 200

    await ops_test.model.applications[TRAEFIK_CHARM].set_config(
        {"enable_experimental_forward_auth": "True"}
    )


async def test_model_exclusion(ops_test: OpsTest) -> None:
    """Test unprotecting the current model.

    Make sure app1 is protected since its integrated with auth-proxy.
    The rest is unprotected.
    """
    await ops_test.model.applications[TRAEFIK_CHARM].set_config({"forward_auth_all": "True"})
    await ops_test.model.applications[TRAEFIK_CHARM].set_config(
        {"forward_auth_all_exclude": ops_test.model.name}
    )

    await ops_test.model.wait_for_idle(
        [
            TRAEFIK_CHARM,
        ],
        status="active",
        timeout=1000,
    )

    app1_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP1_CHARM)
    app2_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP2_CHARM)

    resp = requests.get(app1_url, verify=False)
    assert resp.status_code == 401

    resp = requests.get(app2_url, verify=False)
    assert resp.status_code == 200


async def test_app_exclusion(ops_test: OpsTest) -> None:
    """Test unprotecting a specific app.

    Exclude app2 from the forward_auth_all.
    """
    await ops_test.model.applications[TRAEFIK_CHARM].set_config({"forward_auth_all": "True"})
    await ops_test.model.applications[TRAEFIK_CHARM].set_config(
        {"forward_auth_all_exclude": f"{ops_test.model.name}/{APP2_CHARM}"}
    )

    await ops_test.model.wait_for_idle(
        [
            TRAEFIK_CHARM,
        ],
        status="active",
        timeout=1000,
    )

    app1_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP1_CHARM)
    app2_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, APP2_CHARM)

    resp = requests.get(app1_url, verify=False)
    assert resp.status_code == 401

    resp = requests.get(app2_url, verify=False)
    assert resp.status_code == 200
