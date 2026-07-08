#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for experimental forward auth using jubilant."""

import json
from pathlib import Path

import jubilant
import pytest
import requests
import yaml
from lightkube import Client
from lightkube.resources.core_v1 import ConfigMap
from tenacity import retry, stop_after_attempt, wait_exponential

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    forward_auth_src_overwrite,
)
from tests.integration.helpers import all_settled, get_k8s_service_address, remove_application

OATHKEEPER_APP = "oathkeeper"
TRAEFIK_APP = "traefik-k8s"
IAP_REQUIRER_APP = "iap-requirer"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


@pytest.fixture(scope="module")
def lightkube_client(juju: jubilant.Juju) -> Client:
    return Client(field_manager=OATHKEEPER_APP, namespace=juju.model)


def _reverse_proxy_app_url(juju: jubilant.Juju, ingress_app_name: str, app_name: str) -> str:
    address = get_k8s_service_address(juju.model, f"{ingress_app_name}-lb")
    assert address, "Expected a traefik load balancer address"
    return f"http://{address}/{juju.model}-{app_name}/"


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.config(TRAEFIK_APP, {"enable_experimental_forward_auth": "True"})

    juju.deploy(OATHKEEPER_APP, channel="latest/edge", trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        IAP_REQUIRER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": forward_auth_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        trust=True,
    )

    juju.integrate(f"{IAP_REQUIRER_APP}:require-ingress", TRAEFIK_APP)
    juju.integrate(f"{IAP_REQUIRER_APP}:require-auth-proxy", OATHKEEPER_APP)
    juju.integrate(f"{TRAEFIK_APP}:experimental-forward-auth", OATHKEEPER_APP)
    juju.model_config({"update-status-hook-interval": "5m"})
    juju.wait(all_settled, timeout=1000)


@pytest.mark.xfail(reason="See https://github.com/canonical/traefik-k8s-operator/issues/522")
@retry(
    wait=wait_exponential(multiplier=3, min=1, max=30),
    stop=stop_after_attempt(30),
    reraise=True,
)
def test_allowed_forward_auth_url_redirect(juju: jubilant.Juju) -> None:
    requirer_url = _reverse_proxy_app_url(juju, TRAEFIK_APP, IAP_REQUIRER_APP)
    response = requests.get(f"{requirer_url}anything/allowed", verify=False, timeout=30)
    assert response.status_code == 200


def test_protected_forward_auth_url_redirect(juju: jubilant.Juju) -> None:
    requirer_url = _reverse_proxy_app_url(juju, TRAEFIK_APP, IAP_REQUIRER_APP)
    response = requests.get(f"{requirer_url}anything/deny", verify=False, timeout=30)
    assert response.status_code == 401


def test_forward_auth_url_response_headers(
    juju: jubilant.Juju, lightkube_client: Client
) -> None:
    requirer_url = _reverse_proxy_app_url(juju, TRAEFIK_APP, IAP_REQUIRER_APP)
    protected_url = f"{requirer_url}anything/anonymous"

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

    _update_access_rules_configmap(juju, lightkube_client, anonymous_rule)
    _update_config_configmap(juju, lightkube_client)
    _assert_anonymous_response(protected_url)


@retry(
    wait=wait_exponential(multiplier=3, min=1, max=30),
    stop=stop_after_attempt(30),
    reraise=True,
)
def _assert_anonymous_response(url: str) -> None:
    response = requests.get(url, verify=False, timeout=30)
    assert response.status_code == 200
    headers = response.json().get("headers", {})
    assert headers["X-User"] == "anonymous"


@retry(
    wait=wait_exponential(multiplier=3, min=1, max=10),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _update_access_rules_configmap(
    juju: jubilant.Juju,
    lightkube_client: Client,
    rule: list[dict[str, object]],
) -> None:
    cm = lightkube_client.get(ConfigMap, "access-rules", namespace=juju.model)
    cm.data = {"access-rules-iap-requirer-anonymous.json": json.dumps(rule)}
    lightkube_client.replace(cm)


@retry(
    wait=wait_exponential(multiplier=3, min=1, max=10),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _update_config_configmap(juju: jubilant.Juju, lightkube_client: Client) -> None:
    cm = lightkube_client.get(ConfigMap, name="oathkeeper-config", namespace=juju.model)
    config = yaml.safe_load(cm.data["oathkeeper.yaml"])
    config["access_rules"]["repositories"] = [
        "file://etc/config/access-rules/access-rules-iap-requirer-anonymous.json"
    ]
    patch = {"data": {"oathkeeper.yaml": yaml.safe_dump(config)}}
    lightkube_client.patch(
        ConfigMap,
        name="oathkeeper-config",
        namespace=juju.model,
        obj=patch,
    )


def test_remove_forward_auth_integration(juju: jubilant.Juju):
    juju.remove_relation(OATHKEEPER_APP, f"{TRAEFIK_APP}:experimental-forward-auth")
    juju.wait(all_settled, timeout=600)


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)
