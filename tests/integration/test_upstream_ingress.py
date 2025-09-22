"""Tests that Traefik works correctly when it has an upstream ingress."""

import asyncio
import logging

import pytest
import requests
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay, wait_fixed

from tests.integration.conftest import trfk_resources

TRAEFIK = "traefik-k8s"
UPSTREAM_INGRESS = f"{TRAEFIK}-upstream"
IPA_TESTER = "ipa-tester"
IPU_TESTER = "ipu-tester"
ROUTE_TESTER = "route-tester"
CERTIFICATE_PROVIDER = "self-signed-certificates"

INGRESS_REQUIRER_TESTER_RESOURCES = {"echo-server-image": "jmalloc/echo-server:v0.3.7"}


@pytest.mark.abort_on_fail
async def test_deployment(ops_test: OpsTest, traefik_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, application_name=TRAEFIK, resources=trfk_resources, trust=True
        ),
    )

    await ops_test.model.wait_for_idle([TRAEFIK], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_deploy_dependencies(ops_test: OpsTest, traefik_charm):
    """Deploy the external charm dependencies of this test."""
    await ops_test.model.deploy(
        "ch:self-signed-certificates",
        application_name=CERTIFICATE_PROVIDER,
        channel="1/stable",
    )

    # Deploy an ingress provider to use to ingress to this test's Traefik.
    # In this case, it happens to be another instance of Traefik,
    # but it could be any ingress provider.
    await ops_test.model.deploy(
        traefik_charm,
        application_name=UPSTREAM_INGRESS,
        resources=trfk_resources,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        [CERTIFICATE_PROVIDER, UPSTREAM_INGRESS], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_deploy_testers(ops_test: OpsTest, ingress_requirer_mock):
    await asyncio.gather(
        ops_test.model.deploy(
            ingress_requirer_mock, IPA_TESTER, resources=INGRESS_REQUIRER_TESTER_RESOURCES
        ),
        ops_test.model.deploy(
            ingress_requirer_mock, IPU_TESTER, resources=INGRESS_REQUIRER_TESTER_RESOURCES
        ),
        ops_test.model.deploy(
            ingress_requirer_mock, ROUTE_TESTER, resources=INGRESS_REQUIRER_TESTER_RESOURCES
        ),
    )

    await ops_test.model.wait_for_idle(
        [IPA_TESTER, IPU_TESTER, ROUTE_TESTER], status="active", timeout=1000
    )


@pytest.mark.abort_on_fail
async def test_relate_testers(ops_test: OpsTest):
    await ops_test.model.add_relation(f"{TRAEFIK}:ingress", f"{IPA_TESTER}:ingress")
    await ops_test.model.add_relation(f"{TRAEFIK}:ingress-per-unit", f"{IPU_TESTER}")
    await ops_test.model.add_relation(f"{TRAEFIK}:traefik-route", f"{ROUTE_TESTER}")
    await ops_test.model.wait_for_idle([TRAEFIK, IPA_TESTER, IPU_TESTER, ROUTE_TESTER])


@pytest.mark.abort_on_fail
async def test_ipa_ingressed_no_upstream_ingress(ops_test: OpsTest):
    """Assert that the IPA app can be reached through the Traefik ingress."""
    traefik_url = await get_traefik_url(ops_test, traefik_app_name=TRAEFIK)
    assert_get_url_returns(f"{traefik_url}/{ops_test.model.name}-{IPA_TESTER}", 200)


@pytest.mark.abort_on_fail
async def test_ipu_ingressed_no_upstream_ingress(ops_test: OpsTest):
    """Assert that the IPU app can be reached through the Traefik ingress."""
    traefik_url = await get_traefik_url(ops_test, traefik_app_name=TRAEFIK)
    assert_get_url_returns(f"{traefik_url}/{ops_test.model.name}-{IPU_TESTER}-0", 200)


@pytest.mark.abort_on_fail
async def test_traefik_route_ingressed_no_upstream_ingress(ops_test: OpsTest):
    """Assert that the traefik-route app can be reached through the Traefik ingress."""
    traefik_url = await get_traefik_url(ops_test, traefik_app_name=TRAEFIK)
    assert_get_url_returns(
        f"{traefik_url}/{ops_test.model.name}-{ROUTE_TESTER}-traefik-route", 200
    )


@pytest.mark.abort_on_fail
async def test_add_upstream_ingress(ops_test: OpsTest):
    """Ingress our Traefik through an additional ingress."""
    await ops_test.model.add_relation(f"{TRAEFIK}:upstream-ingress", f"{UPSTREAM_INGRESS}:ingress")

    await ops_test.model.wait_for_idle([TRAEFIK, UPSTREAM_INGRESS], status="active", timeout=300)


@pytest.mark.abort_on_fail
async def test_ipa_ingressed_through_upstream_ingress(ops_test: OpsTest):
    """Assert that the IPA app can be reached through the layered ingresses."""
    upstream_ingress_url = await get_traefik_url(ops_test, traefik_app_name=UPSTREAM_INGRESS)
    assert_get_url_returns(
        (
            f"{upstream_ingress_url}/{ops_test.model.name}-"
            f"{TRAEFIK}/{ops_test.model.name}-{IPA_TESTER}"
        ),
        200,
    )


@pytest.mark.abort_on_fail
async def test_ipu_ingressed_through_upstream_ingress(ops_test: OpsTest):
    """Assert that the IPU app can be reached through the layered ingresses."""
    upstream_ingress_url = await get_traefik_url(ops_test, traefik_app_name=UPSTREAM_INGRESS)
    assert_get_url_returns(
        (
            f"{upstream_ingress_url}/{ops_test.model.name}-"
            f"{TRAEFIK}/{ops_test.model.name}-{IPU_TESTER}-0"
        ),
        200,
    )


@pytest.mark.abort_on_fail
async def test_traefik_route_ingressed_through_upstream_ingress(ops_test: OpsTest):
    """Assert that the traefik-route app can be reached through the layered ingresses."""
    upstream_ingress_url = await get_traefik_url(ops_test, traefik_app_name=UPSTREAM_INGRESS)
    assert_get_url_returns(
        (
            f"{upstream_ingress_url}/{ops_test.model.name}-"
            f"{TRAEFIK}/{ops_test.model.name}-{ROUTE_TESTER}-traefik-route"
        ),
        200,
    )


@pytest.mark.abort_on_fail
async def test_traefik_with_upstream_ingress_blocked_if_in_subdomain_mode(ops_test: OpsTest):
    """Assert that traefik cannot be related to an upstream ingress if routing_mode=subdomain."""
    # Confirm we're not blocked already
    assert ops_test.model.applications[TRAEFIK].status == "active"

    # Set the Traefik app to routing_mode=subdomain and assert that it is blocked
    await ops_test.model.applications[TRAEFIK].set_config({"routing_mode": "subdomain"})
    await ops_test.model.wait_for_idle([TRAEFIK], status="blocked", timeout=300)

    # Return to path routing mode and assert that it is active again
    await ops_test.model.applications[TRAEFIK].set_config({"routing_mode": "path"})
    await ops_test.model.wait_for_idle([TRAEFIK], status="active", timeout=300)


@pytest.mark.abort_on_fail
async def test_add_tls_to_all_ingresses(ops_test: OpsTest):
    """Enable TLS for both ingresses.

    For the upstream ingress to validate the certificates of the inner Traefik,
    we need to give it the CA-certs. Because the `certificates` relation sends
    both your cert and the CA-chain, relating `traefik-upstream:certificates`
    to `self-signed-certificates` has the effect of sending the necessary
    CA certs to the upstream ingress.

    TODO: We could just use the certificate-transfer relation to pass the CA-certs to upstream,
    but that is blocked by https://github.com/canonical/traefik-k8s-operator/issues/495.
    """
    await ops_test.model.add_relation(f"{TRAEFIK}:certificates", f"{CERTIFICATE_PROVIDER}")
    await ops_test.model.add_relation(
        f"{UPSTREAM_INGRESS}:certificates", f"{CERTIFICATE_PROVIDER}"
    )
    await ops_test.model.wait_for_idle(
        [TRAEFIK, UPSTREAM_INGRESS, CERTIFICATE_PROVIDER], status="active", timeout=300
    )


@pytest.mark.abort_on_fail
async def test_ipa_ingressed_through_upstream_ingress_with_tls(ops_test: OpsTest):
    """Assert that the IPA app can be reached through the layered ingresses with TLS enabled."""
    upstream_ingress_url = await get_traefik_url(ops_test, traefik_app_name=UPSTREAM_INGRESS)
    assert_get_url_returns(
        (
            f"{upstream_ingress_url}/{ops_test.model.name}-"
            f"{TRAEFIK}/{ops_test.model.name}-{IPA_TESTER}"
        ),
        200,
    )


@pytest.mark.abort_on_fail
async def test_ipu_ingressed_through_upstream_ingress_with_tls(ops_test: OpsTest):
    """Assert that the IPU app can be reached through the layered ingresses with TLS enabled."""
    upstream_ingress_url = await get_traefik_url(ops_test, traefik_app_name=UPSTREAM_INGRESS)
    assert_get_url_returns(
        (
            f"{upstream_ingress_url}/{ops_test.model.name}-"
            f"{TRAEFIK}/{ops_test.model.name}-{IPU_TESTER}-0"
        ),
        200,
    )


@pytest.mark.abort_on_fail
async def test_traefik_route_ingressed_through_upstream_ingress_with_tls(ops_test: OpsTest):
    """Assert that the traefik-route app can be reached upstream ingress with TLS."""
    upstream_ingress_url = await get_traefik_url(ops_test, traefik_app_name=UPSTREAM_INGRESS)
    assert_get_url_returns(
        (
            f"{upstream_ingress_url}/{ops_test.model.name}-"
            f"{TRAEFIK}/{ops_test.model.name}-{ROUTE_TESTER}-traefik-route"
        ),
        200,
    )


async def get_traefik_url(ops_test: OpsTest, traefik_app_name: str = TRAEFIK):
    """Get the URL for the Traefik app, as provided by the show-external-endpoints action."""
    external_endpoints_action = (
        await ops_test.model.applications[traefik_app_name]
        .units[0]
        .run_action("show-external-endpoints")
    )
    external_endpoints_action_results = (await external_endpoints_action.wait()).results
    external_endpoints = yaml.safe_load(external_endpoints_action_results["external-endpoints"])
    return external_endpoints[traefik_app_name]["url"]


@retry(wait=wait_fixed(2), stop=stop_after_delay(5 * 1))
def assert_get_url_returns(url: str, expected: int):
    try:
        r = requests.get(url, timeout=1, verify=False)
    except requests.exceptions.RequestException as e:
        if e.response:
            if e.response.status_code == expected:
                return True
            logging.info(
                f"when accessing {url} got code {e.response.status_code}, expected {expected}"
            )
            raise AssertionError

        logging.info(f"when accessing {url} HTTP error: {e}")
        raise AssertionError
    except Exception as e:
        logging.info(f"when accessing {url} got uncaught exception: {e}")
        raise AssertionError

    if r.status_code == expected:
        return True

    logging.info(f"when accessing {url} got code {r.status_code}, expected {expected}")
    raise AssertionError
