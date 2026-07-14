#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for TCP ingress-per-unit using jubilant."""

import json
from pathlib import Path
from typing import Any

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    tcp_ipu_src_overwrite,
)
from tests.integration.helpers import (
    all_settled,
    get_k8s_service_address,
    get_relation_info,
    remove_application,
    wait_for_tcp_echo,
)

TRAEFIK_APP = "traefik-k8s"
TCP_TESTER_APP = "tcp-tester"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        TCP_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": tcp_ipu_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        trust=True,
    )
    juju.wait(all_settled, timeout=1000)


def test_relate(juju: jubilant.Juju):
    juju.integrate(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(all_settled, timeout=600, delay=2)


def test_relation_data_shape(juju: jubilant.Juju):
    # Requirer unit data is visible from the provider (traefik) side
    traefik_rel = get_relation_info(
        juju,
        remote_unit=f"{TRAEFIK_APP}/0",
        remote_endpoint="ingress-per-unit",
        local_unit=f"{TCP_TESTER_APP}/0",
        local_endpoint="require-ingress-per-unit",
    )
    requirer_unit_data = traefik_rel["related-units"][f"{TCP_TESTER_APP}/0"]["data"]
    assert _dequote(requirer_unit_data["name"]) == f"{TCP_TESTER_APP}/0"
    port = _dequote(requirer_unit_data["port"])
    assert port.isdigit()

    # Provider app data (ingress URL) is visible from the requirer side
    tester_rel = get_relation_info(
        juju,
        remote_unit=f"{TCP_TESTER_APP}/0",
        remote_endpoint="require-ingress-per-unit",
        local_unit=f"{TRAEFIK_APP}/0",
        local_endpoint="ingress-per-unit",
    )
    provider_app_data = yaml.safe_load(tester_rel["application-data"]["ingress"])
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"
    assert provider_app_data == {f"{TCP_TESTER_APP}/0": {"url": f"{traefik_ip}:{port}"}}


def test_tcp_connection(juju: jubilant.Juju):
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    ingress = _rpc(juju, f"{TCP_TESTER_APP}/0", "get_tcp_ingress_data")
    url = ingress["urls"].get(f"{TCP_TESTER_APP}/0")
    assert url, f"Expected URL for {TCP_TESTER_APP}/0"
    port = int(url.rsplit(":", 1)[1])
    wait_for_tcp_echo(traefik_ip, port)


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(
        lambda status: jubilant.all_active(status, TRAEFIK_APP)
        and jubilant.all_agents_idle(status),
        timeout=300,
    )


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)


def _rpc(juju: jubilant.Juju, unit: str, method: str) -> Any:
    raw = juju.run(unit, "rpc", params={"method": method}).results["return"]
    return json.loads(raw)


def _dequote(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value
