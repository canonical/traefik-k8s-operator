#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress-per-unit (IPU) using jubilant."""

from pathlib import Path
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
    rpc,
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
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    url = data["urls"].get(f"{IPU_TESTER_APP}/0")
    assert url, f"Expected URL for {IPU_TESTER_APP}/0"

    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_relation_data_shape(juju: jubilant.Juju):
    # Read the raw relation databag (bypassing the traefik_k8s library's own
    # parsing) to assert on the actual wire-format/interface contract.
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_relation_data")

    # Requirer unit databag, as written by the library on our own side
    unit_data = data["unit_data"]
    assert unit_data.get("name") == f"{IPU_TESTER_APP}/0"
    assert unit_data.get("port") == 80
    assert unit_data.get("host") == "foo.bar"
    model = unit_data.get("model")

    # Provider app data (ingress URL), as written by traefik
    traefik_address = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_address, "Expected a traefik load balancer address"
    assert data["app_data"]["ingress"] == {
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
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    assert not data.get("urls"), "Expected ingress URLs to be cleared after relation removal"


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)
