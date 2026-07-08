#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress-per-unit (IPU) using jubilant."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    PYTHON_PACKAGES,
    ipu_src_overwrite,
)
from tests.integration.helpers import (
    all_settled,
    assert_can_connect,
    get_k8s_service_address,
    remove_application,
)

TRAEFIK_APP = "traefik-k8s"
IPU_TESTER_APP = "ipu-tester"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM}",
        IPU_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": ipu_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
    )
    juju.wait(all_settled, timeout=1000)


def test_relate(juju: jubilant.Juju):
    juju.integrate(
        f"{IPU_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(all_settled, timeout=600)


def test_ipu_charm_has_ingress(juju: jubilant.Juju):
    data = _rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    url = data["urls"].get(f"{IPU_TESTER_APP}/0")
    assert url, f"Expected URL for {IPU_TESTER_APP}/0"

    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_relation_data_shape(juju: jubilant.Juju):
    # Requirer unit data is visible from the provider (traefik) side
    traefik_rel = _relation_info(
        juju,
        remote_unit=f"{TRAEFIK_APP}/0",
        remote_endpoint="ingress-per-unit",
        local_unit=f"{IPU_TESTER_APP}/0",
        local_endpoint="require-ingress-per-unit",
    )
    requirer_unit_data = traefik_rel["related-units"][f"{IPU_TESTER_APP}/0"]["data"]
    assert _dequote(requirer_unit_data["name"]) == f"{IPU_TESTER_APP}/0"
    assert _dequote(requirer_unit_data["port"]) == "80"
    assert _dequote(requirer_unit_data["host"]) == "foo.bar"
    model = _dequote(requirer_unit_data["model"])

    # Provider app data (ingress URL) is visible from the requirer side
    tester_rel = _relation_info(
        juju,
        remote_unit=f"{IPU_TESTER_APP}/0",
        remote_endpoint="require-ingress-per-unit",
        local_unit=f"{TRAEFIK_APP}/0",
        local_endpoint="ingress-per-unit",
    )
    provider_app_data = yaml.safe_load(tester_rel["application-data"]["ingress"])
    traefik_address = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_address, "Expected a traefik load balancer address"
    assert provider_app_data == {
        f"{IPU_TESTER_APP}/0": {"url": f"http://{traefik_address}/{model}-ipu-tester-0"}
    }


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(
        f"{IPU_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, IPU_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        timeout=300,
    )
    data = _rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    assert not data.get("urls"), "Expected ingress URLs to be cleared after relation removal"


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)


def _rpc(juju: jubilant.Juju, unit: str, method: str) -> Any:
    raw = juju.run(unit, "rpc", params={"method": method}).results["return"]
    return json.loads(raw)


def _relation_info(
    juju: jubilant.Juju,
    remote_unit: str,
    remote_endpoint: str,
    local_unit: str,
    local_endpoint: str,
) -> dict[str, Any]:
    data = json.loads(juju.cli("show-unit", remote_unit, "--format", "json"))[remote_unit]
    for relation in data.get("relation-info", []):
        if (
            relation.get("endpoint") == remote_endpoint
            and relation.get("related-endpoint") == local_endpoint
            and local_unit in relation.get("related-units", {})
        ):
            return relation
    raise AssertionError(
        f"No relation data for {remote_unit}:{remote_endpoint} and "
        f"{local_unit}:{local_endpoint}"
    )


def _dequote(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value
