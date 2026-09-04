#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for traefik-route using jubilant."""

import socket
from pathlib import Path

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    route_src_overwrite,
)
from tests.integration.helpers import (
    all_settled,
    fetch_with_retry,
    get_k8s_service_address,
    remove_application,
    rpc,
)

TRAEFIK_APP = "traefik"
ROUTE_TESTER_APP = "route"
DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"
STATIC_CONFIG_PATH = "/etc/traefik/traefik.yaml"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        ROUTE_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={"src-overwrite": route_src_overwrite()},
        trust=True,
    )
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


def test_relate(juju: jubilant.Juju):
    juju.integrate(
        f"{ROUTE_TESTER_APP}:require-traefik-route",
        f"{TRAEFIK_APP}:traefik-route",
    )
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)


def test_dynamic_config_created(juju: jubilant.Juju):
    config_path = _get_route_config_path(juju)
    contents = juju.ssh(
        f"{TRAEFIK_APP}/0",
        f"cat {config_path}",
        container="traefik",
    )
    contents_yaml = yaml.safe_load(contents)
    assert contents_yaml["some"] == "config"


def test_static_config_updated(juju: jubilant.Juju):
    contents = juju.ssh(
        f"{TRAEFIK_APP}/0",
        f"cat {STATIC_CONFIG_PATH}",
        container="traefik",
    )
    contents_yaml = yaml.safe_load(contents)
    assert contents_yaml["entryPoints"]["test-port"] == {
        "address": ":4545",
        "transport": {"respondingTimeouts": {"readTimeout": "0s"}},
    }
    assert contents_yaml["entryPoints"]["test-udp-port"] == {"address": ":4646/udp"}


def test_added_entrypoint_reachable(juju: jubilant.Juju):
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"

    payload = b"traefik-route-udp-echo"
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.settimeout(60)
    try:
        udp_sock.sendto(payload, (traefik_ip, 4646))
        response, _ = udp_sock.recvfrom(512)
    finally:
        udp_sock.close()
    assert response == payload

    fetch_with_retry(f"http://{traefik_ip}:4545", expected_status=404)


def test_scale_and_get_external_host(juju: jubilant.Juju):
    juju.add_unit(ROUTE_TESTER_APP, num_units=1)
    juju.wait(
        lambda status: (
            len(status.apps[ROUTE_TESTER_APP].units) == 2 and all_settled(status)
        ),
        error=jubilant.any_error,
        timeout=1000,
        delay=5,
        successes=5,
    )

    external_host_0 = rpc(juju, f"{ROUTE_TESTER_APP}/0", "get_external_host")
    external_host_1 = rpc(juju, f"{ROUTE_TESTER_APP}/1", "get_external_host")
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")

    assert external_host_0 == external_host_1
    assert external_host_0
    assert external_host_0 == traefik_ip


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(
        f"{ROUTE_TESTER_APP}:require-traefik-route",
        f"{TRAEFIK_APP}:traefik-route",
    )
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, ROUTE_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        error=jubilant.any_error,
        timeout=300,
        delay=5,
        successes=5,
    )


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)


def _get_route_config_path(juju: jubilant.Juju) -> str:
    output = juju.ssh(
        f"{TRAEFIK_APP}/0",
        (
            "find /opt/traefik/juju -maxdepth 1 "
            "-name 'juju_ingress_traefik-route_*_route.yaml' -print"
        ),
        container="traefik",
    ).strip()
    assert output, "Expected a traefik-route dynamic config file"
    return output.splitlines()[0]
