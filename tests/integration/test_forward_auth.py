# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
from os.path import join

import pytest
import requests
import yaml
from helpers import delete_k8s_service, get_k8s_service_address, remove_application
from lightkube import Client
from lightkube.resources.core_v1 import ConfigMap
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed

from tests.integration.conftest import deploy_traefik_if_not_deployed

logger = logging.getLogger(__name__)

OATHKEEPER_CHARM = "oathkeeper"
TRAEFIK_CHARM = "traefik-k8s"
IAP_REQUIRER_CHARM = "iap-requirer"


@pytest.fixture(scope="module")
def lightkube_client(ops_test: OpsTest) -> Client:
    client = Client(field_manager=OATHKEEPER_CHARM, namespace=ops_test.model.name)
    return client


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

    # Deploy oathkeeper
    await ops_test.model.deploy(
        OATHKEEPER_CHARM,
        channel="latest/edge",
        config={"dev": "True"},
        trust=True,
    )

    # Deploy the iap-requirer charm with integrations
    await ops_test.model.deploy(
        application_name=IAP_REQUIRER_CHARM,
        entity_url=forward_auth_tester_charm,
        resources={"oci-image": "kennethreitz/httpbin"},
        trust=True,
    )

    await ops_test.model.integrate(f"{IAP_REQUIRER_CHARM}:ingress", TRAEFIK_CHARM)
    await ops_test.model.integrate(f"{IAP_REQUIRER_CHARM}:auth-proxy", OATHKEEPER_CHARM)

    await ops_test.model.integrate(f"{TRAEFIK_CHARM}:experimental-forward-auth", OATHKEEPER_CHARM)

    await ops_test.model.wait_for_idle(
        [TRAEFIK_CHARM, OATHKEEPER_CHARM, IAP_REQUIRER_CHARM], status="active", timeout=1000
    )


@retry(
    wait=wait_fixed(60),
    stop=stop_after_attempt(20),
    reraise=True,
)
async def test_allowed_forward_auth_url_redirect(ops_test: OpsTest) -> None:
    """Test that a request hitting an application protected by IAP is forwarded by traefik to oathkeeper.

    An allowed request should be performed without authentication.
    Retry the request to ensure the access rules were populated by oathkeeper.
    """
    requirer_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, IAP_REQUIRER_CHARM)

    protected_url = join(requirer_url, "anything/allowed")

    resp = requests.get(protected_url, verify=False)
    assert resp.status_code == 200


async def test_protected_forward_auth_url_redirect(ops_test: OpsTest) -> None:
    """Test that when trying to reach a protected url, the request is forwarded by traefik to oathkeeper.

    An unauthenticated request should then be denied with 401 Unauthorized response.
    """
    requirer_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, IAP_REQUIRER_CHARM)

    protected_url = join(requirer_url, "anything/deny")

    resp = requests.get(protected_url, verify=False)
    assert resp.status_code == 401


async def test_forward_auth_url_response_headers(
    ops_test: OpsTest, lightkube_client: Client
) -> None:
    """Test that a response mutated by oathkeeper contains expected custom headers."""
    requirer_url = await get_reverse_proxy_app_url(ops_test, TRAEFIK_CHARM, IAP_REQUIRER_CHARM)
    protected_url = join(requirer_url, "anything/anonymous")

    # Push an anonymous access rule as a workaround to avoid deploying identity-platform bundle
    anonymous_rule = [
        {
            "id": "iap-requirer:anonymous",
            "match": {
                "url": protected_url,
                "methods": ["GET", "POST", "OPTION", "PUT", "PATCH", "DELETE"],
            },
            "authenticators": [{"handler": "anonymous"}],
            "mutators": [{"handler": "header"}],
            "authorizer": {"handler": "allow"},
            "errors": [{"handler": "json"}],
        }
    ]

    update_access_rules_configmap(ops_test, lightkube_client, rule=anonymous_rule)
    update_config_configmap(ops_test, lightkube_client)

    assert_anonymous_response(protected_url)


@retry(
    wait=wait_exponential(multiplier=3, min=1, max=20),
    stop=stop_after_attempt(20),
    reraise=True,
)
def assert_anonymous_response(url):
    resp = requests.get(url, verify=False)
    assert resp.status_code == 200

    headers = json.loads(resp.content).get("headers")
    assert headers["X-User"] == "anonymous"


@retry(
    wait=wait_exponential(multiplier=3, min=1, max=10),
    stop=stop_after_attempt(5),
    reraise=True,
)
def update_access_rules_configmap(ops_test: OpsTest, lightkube_client: Client, rule):
    """Modify the configmap to force access rules update.

    This is a workaround to test response headers without deploying identity-platform bundle.
    The anonymous authenticator is used only for testing purposes.
    """
    cm = lightkube_client.get(ConfigMap, "access-rules", namespace=ops_test.model.name)
    data = {"access-rules-iap-requirer-anonymous.json": str(rule)}
    cm.data = data
    lightkube_client.replace(cm)


@retry(
    wait=wait_exponential(multiplier=3, min=1, max=10),
    stop=stop_after_attempt(5),
    reraise=True,
)
def update_config_configmap(ops_test: OpsTest, lightkube_client: Client):
    cm = lightkube_client.get(ConfigMap, name="oathkeeper-config", namespace=ops_test.model.name)
    cm = yaml.safe_load(cm.data["oathkeeper.yaml"])
    cm["access_rules"]["repositories"] = [
        "file://etc/config/access-rules/access-rules-iap-requirer-anonymous.json"
    ]
    patch = {"data": {"oathkeeper.yaml": yaml.dump(cm)}}
    lightkube_client.patch(
        ConfigMap, name="oathkeeper-config", namespace=ops_test.model.name, obj=patch
    )


async def test_remove_forward_auth_integration(ops_test: OpsTest):
    await ops_test.juju("remove-relation", "oathkeeper", "traefik-k8s:experimental-forward-auth")
    await ops_test.model.wait_for_idle(
        [TRAEFIK_CHARM, OATHKEEPER_CHARM, IAP_REQUIRER_CHARM], status="active"
    )


async def test_cleanup(ops_test):
    await delete_k8s_service(ops_test, "traefik-k8s-lb")
    await remove_application(ops_test, "traefik-k8s", timeout=60)
