#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the three basic ingress relation types using jubilant.

Deploys traefik once alongside an ingress-per-app (IPA) requirer, an
ingress-per-unit (IPU) requirer, and a TCP-mode ingress-per-unit requirer, then
verifies each relation type independently and their simultaneous compatibility
(TCP+IPA using different relation endpoints, TCP+IPU sharing the same
``ingress-per-unit`` endpoint in different modes) — all against one shared
deployment instead of five separate ones.
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
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
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
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


# --- IPA ---------------------------------------------------------------------
def test_relate_ipa(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


def test_ipa_has_ingress(juju: jubilant.Juju):
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    url = data["url"]
    assert url, "Expected a non-empty ingress URL"
    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_ipa_relation_data_shape(juju: jubilant.Juju):
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")

    # Provider gave back a well-formed URL pointing at the actual LB IP
    traefik_address = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_address, "Expected a traefik load balancer address"
    assert data["url"] == f"http://{traefik_address}/{juju.model}-{IPA_TESTER_APP}"

    # Requirer app databag (v2): model + name + port present; host must NOT be here
    assert data["app_data"].get("model") == juju.model
    assert data["app_data"].get("name") == IPA_TESTER_APP
    assert data["app_data"].get("port") == 80
    assert "host" not in data["app_data"], "v2: host must not be in app databag"

    # Requirer unit databag (v2): host IS here
    assert data["unit_data"].get("host") == "foo.bar"


# --- IPU ---------------------------------------------------------------------
def test_relate_ipu(juju: jubilant.Juju):
    juju.integrate(
        f"{IPU_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


def test_ipu_has_ingress(juju: jubilant.Juju):
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    url = data["urls"].get(f"{IPU_TESTER_APP}/0")
    assert url, f"Expected URL for {IPU_TESTER_APP}/0"

    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_ipu_relation_data_shape(juju: jubilant.Juju):
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


# --- TCP (ingress-per-unit, tcp mode) -----------------------------------------
def test_relate_tcp(juju: jubilant.Juju):
    juju.integrate(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


def test_tcp_relation_data_shape(juju: jubilant.Juju):
    # Read the raw relation databag (bypassing the traefik_k8s library's own
    # parsing) to assert on the actual wire-format/interface contract. This
    # relation is scoped separately from the IPU one above even though both
    # use the "ingress-per-unit" endpoint, so it must still equal exactly the
    # tcp-tester's own entry.
    data = rpc(juju, f"{TCP_TESTER_APP}/0", "get_relation_data")

    # Requirer unit databag, as written by the library on our own side
    unit_data = data["unit_data"]
    assert unit_data.get("name") == f"{TCP_TESTER_APP}/0"
    port = unit_data.get("port")
    assert isinstance(port, int)

    # Provider app data (ingress URL), as written by traefik
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"
    assert data["app_data"]["ingress"] == {f"{TCP_TESTER_APP}/0": {"url": f"{traefik_ip}:{port}"}}


def test_tcp_connection(juju: jubilant.Juju):
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    ingress = rpc(juju, f"{TCP_TESTER_APP}/0", "get_tcp_ingress_data")
    url = ingress["urls"].get(f"{TCP_TESTER_APP}/0")
    assert url, f"Expected URL for {TCP_TESTER_APP}/0"
    port = int(url.rsplit(":", 1)[1])
    wait_for_tcp_echo(traefik_ip, port)


# --- Compatibility (all three relations simultaneously active) ---------------
def test_tcp_ipa_compatibility(juju: jubilant.Juju):
    """TCP (ingress-per-unit) and IPA (ingress) relations don't interfere."""
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    tcp_data = rpc(juju, f"{TCP_TESTER_APP}/0", "get_tcp_ingress_data")
    tcp_url = tcp_data["urls"].get(f"{TCP_TESTER_APP}/0")
    assert tcp_url, f"Expected URL for {TCP_TESTER_APP}/0"
    wait_for_tcp_echo(traefik_ip, int(tcp_url.rsplit(":", 1)[1]))

    ipa_data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    ipa_url = ipa_data["url"]
    assert ipa_url, f"Expected URL for {IPA_TESTER_APP}/0"
    parsed = urlparse(ipa_url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_tcp_ipu_compatibility(juju: jubilant.Juju):
    """TCP and HTTP requirers sharing the same ingress-per-unit endpoint don't interfere."""
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    tcp_data = rpc(juju, f"{TCP_TESTER_APP}/0", "get_tcp_ingress_data")
    tcp_url = tcp_data["urls"].get(f"{TCP_TESTER_APP}/0")
    assert tcp_url, f"Expected URL for {TCP_TESTER_APP}/0"
    wait_for_tcp_echo(traefik_ip, int(tcp_url.rsplit(":", 1)[1]))

    ipu_data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    ipu_url = ipu_data["urls"].get(f"{IPU_TESTER_APP}/0")
    assert ipu_url, f"Expected URL for {IPU_TESTER_APP}/0"
    parsed = urlparse(ipu_url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


# --- Relation removal ----------------------------------------------------------
def test_remove_ipa_relation(juju: jubilant.Juju):
    juju.remove_relation(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, IPA_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        error=jubilant.any_error,
        timeout=300,
        delay=5,
        successes=5,
    )
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    assert not data["url"], "Expected ingress URL to be cleared after relation removal"


def test_remove_ipu_relation(juju: jubilant.Juju):
    juju.remove_relation(
        f"{IPU_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, IPU_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        error=jubilant.any_error,
        timeout=300,
        delay=5,
        successes=5,
    )
    data = rpc(juju, f"{IPU_TESTER_APP}/0", "get_ingress_data")
    assert not data.get("urls"), "Expected ingress URLs to be cleared after relation removal"


def test_remove_tcp_relation(juju: jubilant.Juju):
    juju.remove_relation(
        f"{TCP_TESTER_APP}:require-ingress-per-unit",
        f"{TRAEFIK_APP}:ingress-per-unit",
    )
    juju.wait(
        lambda status: jubilant.all_active(status, TRAEFIK_APP)
        and jubilant.all_agents_idle(status),
        error=jubilant.any_error,
        timeout=300,
        delay=5,
        successes=5,
    )


def test_cleanup(juju: jubilant.Juju):
    remove_application(
        juju, TCP_TESTER_APP, IPA_TESTER_APP, IPU_TESTER_APP, TRAEFIK_APP, timeout=300
    )
