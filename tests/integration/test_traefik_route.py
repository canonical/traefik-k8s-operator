#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for traefik-route using jubilant."""

import socket

import jubilant
import yaml
from tenacity import retry, stop_after_delay, wait_fixed

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    route_src_overwrite,
)
from tests.integration.conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from tests.integration.helpers import (
    all_settled,
    any_error_after,
    fetch_with_retry,
    get_loadbalancer_ip,
    remove_application,
    rpc,
)

ROUTE_TESTER_APP = "route"
DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"
STATIC_CONFIG_PATH = "/etc/traefik/traefik.yaml"


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP_NAME, resources=TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        ROUTE_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={"src-overwrite": route_src_overwrite()},
        trust=True,
    )
    juju.wait(
        all_settled,
        error=any_error_after(failures=5),
        delay=5,
        successes=5,
    )
    juju.integrate(
        f"{ROUTE_TESTER_APP}:require-traefik-route",
        f"{TRAEFIK_APP_NAME}:traefik-route",
    )
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)


def test_dynamic_config_created(juju: jubilant.Juju):
    config_path = _get_route_config_path(juju)
    contents = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        f"cat {config_path}",
        container="traefik",
    )
    contents_yaml = yaml.safe_load(contents)
    assert contents_yaml["some"] == "config"


def test_static_config_updated(juju: jubilant.Juju):
    contents = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
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
    traefik_ip = get_loadbalancer_ip(juju, TRAEFIK_APP_NAME)

    payload = b"traefik-route-udp-echo"
    _assert_udp_echo(traefik_ip, 4646, payload)

    fetch_with_retry(f"http://{traefik_ip}:4545", expected_status=404)


@retry(stop=stop_after_delay(60), wait=wait_fixed(5), reraise=True)
def _assert_udp_echo(host: str, port: int, payload: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
        udp_sock.settimeout(5)
        udp_sock.sendto(payload, (host, port))
        response, _ = udp_sock.recvfrom(512)
    assert response == payload


def test_scale_and_get_external_host(juju: jubilant.Juju):
    juju.add_unit(ROUTE_TESTER_APP, num_units=1)
    juju.wait(
        lambda status: len(status.apps[ROUTE_TESTER_APP].units) == 2 and all_settled(status),
        error=any_error_after(failures=5),
        timeout=1000,
        delay=5,
        successes=5,
    )

    external_host_0 = rpc(juju, f"{ROUTE_TESTER_APP}/0", "get_external_host")
    external_host_1 = rpc(juju, f"{ROUTE_TESTER_APP}/1", "get_external_host")
    traefik_ip = get_loadbalancer_ip(juju, TRAEFIK_APP_NAME)

    assert external_host_0 == external_host_1
    assert external_host_0
    assert external_host_0 == traefik_ip


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(
        f"{ROUTE_TESTER_APP}:require-traefik-route",
        f"{TRAEFIK_APP_NAME}:traefik-route",
    )
    juju.wait(
        lambda status: all_settled(status, TRAEFIK_APP_NAME, ROUTE_TESTER_APP),
        error=any_error_after(failures=5),
        timeout=300,
        delay=5,
        successes=5,
    )


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP_NAME, timeout=60)


def _get_route_config_path(juju: jubilant.Juju) -> str:
    output = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        (
            "find /opt/traefik/juju -maxdepth 1 "
            "-name 'juju_ingress_traefik-route_*_route.yaml' -print"
        ),
        container="traefik",
    ).strip()
    assert output, "Expected a traefik-route dynamic config file"
    return output.splitlines()[0]
