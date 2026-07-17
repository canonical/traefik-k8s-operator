#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress health checks using jubilant."""

from pathlib import Path
from typing import Any

import jubilant
import requests
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    health_src_overwrite,
)
from tests.integration.helpers import all_settled, get_k8s_service_address, remove_application, rpc

TRAEFIK_APP = "traefik-k8s"
HEALTH_TESTER_APP = "health-tester"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        HEALTH_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": health_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        num_units=3,
        trust=True,
    )
    juju.wait(all_settled, timeout=1000)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{HEALTH_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, timeout=600)


def test_health(juju: jubilant.Juju):
    traefik_address = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_address, "Expected a traefik load balancer address"
    health_address = f"http://{traefik_address}/{juju.model}-{HEALTH_TESTER_APP}/health"

    rpc(juju, f"{HEALTH_TESTER_APP}/2", "set_health", is_healthy=False)
    juju.wait(all_settled, timeout=600, delay=5, successes=5)
    for _ in range(10):
        status, content = _fetch_health(health_address)
        assert status == 200
        assert content in [
            {"host": "health-tester-0", "status": "up"},
            {"host": "health-tester-1", "status": "up"},
        ]

    rpc(juju, f"{HEALTH_TESTER_APP}/1", "set_health", is_healthy=False)
    juju.wait(all_settled, timeout=600, delay=5, successes=5)
    for _ in range(10):
        status, content = _fetch_health(health_address)
        assert status == 200
        assert content == {"host": "health-tester-0", "status": "up"}


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)


def _fetch_health(url: str) -> tuple[int, Any]:
    response = requests.get(url, timeout=10)
    try:
        content = response.json()
    except ValueError:
        content = {}
    return response.status_code, content
