#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the three basic ingress relation types using jubilant.

Deploys traefik once alongside an ingress-per-app (IPA) requirer, an
ingress-per-unit (IPU) requirer, and a TCP-mode ingress-per-unit requirer, and
integrates all three relations up front. Because all three stay related
throughout the reachability checks below, those checks also incidentally prove
the relation types coexist without interfering with each other (TCP+IPA on
different relation endpoints, TCP+IPU sharing the same ``ingress-per-unit``
endpoint in different modes) — no separate compatibility tests are needed.

Relation-databag shape/schema assertions are intentionally not repeated here:
that contract is already covered more thoroughly (and far more cheaply, with
more parametrization) by the ops-scenario unit tests in
tests/unit/test_ingress_per_app.py, tests/unit/test_ingress_per_unit.py, and
tests/unit/test_lib_per_app_provides.py / test_lib_per_unit_provides.py.
"""

from pathlib import Path
from urllib.parse import urlparse

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    ipa_src_overwrite,
    ipu_src_overwrite,
    tcp_ipu_src_overwrite,
)
from tests.integration.helpers import (
    all_settled,
    assert_can_connect,
    get_k8s_service_address,
    remove_application,
    rpc,
    wait_for_tcp_echo,
)

TRAEFIK_APP = "traefik-k8s"
IPA_TESTER_APP = "ipa-tester"
IPU_TESTER_APP = "ipu-tester"
TCP_TESTER_APP = "tcp-tester"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {name: val["upstream-source"] for name, val in _METADATA["resources"].items()}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    """Deploy traefik and all three testers, and integrate every relation up front."""
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM}",
        IPA_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": ipa_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
    )
    juju.deploy(
        f"ch:{ANY_CHARM}",
        IPU_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": ipu_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
    )
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
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.integrate(
        f"{IPU_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.integrate(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


# --- Reachability (also proves the three relation types coexist) -------------
def test_ipa_has_ingress(juju: jubilant.Juju):
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    url = data["url"]
    assert url, "Expected a non-empty ingress URL"
    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_ipu_has_ingress(juju: jubilant.Juju):
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    url = data["urls"].get(f"{IPU_TESTER_APP}/0")
    assert url, f"Expected URL for {IPU_TESTER_APP}/0"

    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_tcp_connection(juju: jubilant.Juju):
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    ingress = rpc(juju, f"{TCP_TESTER_APP}/0", "get_tcp_ingress_data")
    url = ingress["urls"].get(f"{TCP_TESTER_APP}/0")
    assert url, f"Expected URL for {TCP_TESTER_APP}/0"
    port = int(url.rsplit(":", 1)[1])
    wait_for_tcp_echo(traefik_ip, port)


# --- Relation removal ----------------------------------------------------------
def test_remove_all_relations(juju: jubilant.Juju):
    juju.remove_relation(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.remove_relation(
        f"{IPU_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.remove_relation(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(
        lambda status: all_settled(status, TRAEFIK_APP, IPA_TESTER_APP, IPU_TESTER_APP),
        error=jubilant.any_error,
        timeout=300,
        delay=5,
        successes=5,
    )


def test_ipa_relation_cleared(juju: jubilant.Juju):
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    assert not data["url"], "Expected ingress URL to be cleared after relation removal"


def test_ipu_relation_cleared(juju: jubilant.Juju):
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    assert not data.get("urls"), "Expected ingress URLs to be cleared after relation removal"


def test_cleanup(juju: jubilant.Juju):
    remove_application(
        juju, TCP_TESTER_APP, IPA_TESTER_APP, IPU_TESTER_APP, TRAEFIK_APP, timeout=300
    )
