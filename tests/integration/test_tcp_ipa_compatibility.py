#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Compatibility test for simultaneous TCP and IPA ingress using jubilant."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    ipa_src_overwrite,
    tcp_ipu_src_overwrite,
)
from tests.integration.helpers import (
    all_settled,
    assert_can_connect,
    get_k8s_service_address,
    get_relation_info,
    remove_application,
    wait_for_tcp_echo,
)

TRAEFIK_APP = "traefik-k8s"
TCP_TESTER_APP = "tcp-tester"
IPA_TESTER_APP = "ipa-tester"

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
    juju.deploy(
        f"ch:{ANY_CHARM}",
        IPA_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": ipa_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
    )
    juju.wait(all_settled, timeout=1000)


def test_relate(juju: jubilant.Juju):
    juju.integrate(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, timeout=1000)


def test_tcp_ipa_compatibility(juju: jubilant.Juju):
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    tcp_data = _rpc(juju, f"{TCP_TESTER_APP}/0", "get_tcp_ingress_data")
    tcp_url = tcp_data["urls"].get(f"{TCP_TESTER_APP}/0")
    assert tcp_url, f"Expected URL for {TCP_TESTER_APP}/0"
    wait_for_tcp_echo(traefik_ip, int(tcp_url.rsplit(":", 1)[1]))

    ipa_relation = get_relation_info(
        juju,
        remote_unit=f"{IPA_TESTER_APP}/0",
        remote_endpoint="require-ingress",
        local_unit=f"{TRAEFIK_APP}/0",
        local_endpoint="ingress",
    )
    ipa_url = yaml.safe_load(ipa_relation["application-data"]["ingress"])["url"]
    parsed = urlparse(ipa_url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TCP_TESTER_APP, IPA_TESTER_APP, TRAEFIK_APP, timeout=300)


def _rpc(juju: jubilant.Juju, unit: str, method: str) -> Any:
    raw = juju.run(unit, "rpc", params={"method": method}).results["return"]
    return json.loads(raw)
