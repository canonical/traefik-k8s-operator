#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for TLS termination using jubilant."""

from pathlib import Path

import jubilant
import pytest
import requests
import yaml

from tests.integration.dns_adapter import DNSResolverHTTPSAdapter
from tests.integration.helpers import (
    all_settled,
    get_k8s_service_address,
    remove_application,
)

TRAEFIK_APP = "traefik"
PROMETHEUS_APP = "prometheus"
ALERTMANAGER_APP = "alertmanager"
GRAFANA_APP = "grafana"
ROOT_CA_APP = "root-ca"
MOCK_HOSTNAME = "juju.local"
_ARTIFACT_DIR = Path("tests/integration/.artifacts")
_CERT_PATH = _ARTIFACT_DIR / "test-tls-local.cert"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_build_and_deploy(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy("ch:prometheus-k8s", PROMETHEUS_APP, channel="1/stable", trust=True)
    juju.deploy("ch:alertmanager-k8s", ALERTMANAGER_APP, channel="1/stable", trust=True)
    juju.deploy("ch:grafana-k8s", GRAFANA_APP, channel="1/stable", trust=True)
    juju.wait(jubilant.all_active, timeout=600)

    juju.integrate(f"{PROMETHEUS_APP}:ingress", TRAEFIK_APP)
    juju.integrate(f"{ALERTMANAGER_APP}:ingress", TRAEFIK_APP)
    juju.integrate(f"{GRAFANA_APP}:ingress", TRAEFIK_APP)
    juju.wait(all_settled, timeout=600)


def test_ingressed_endpoints_reachable_after_metallb_enabled(juju: jubilant.Juju):
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"
    for endpoint in _endpoints(juju.model, "http", traefik_ip):
        response = requests.get(endpoint, timeout=30)
        response.raise_for_status()


@pytest.mark.xfail(
    reason=(
        "Failing due to #491. Remove this after #509 is implemented. "
        "See also: https://github.com/canonical/traefik-k8s-operator/issues/521"
    )
)
def test_tls_termination(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP, {"external_hostname": MOCK_HOSTNAME})
    juju.deploy("ch:self-signed-certificates", ROOT_CA_APP, channel="1/stable")
    juju.config(ROOT_CA_APP, {"ca-common-name": "demo.ca.local"})
    juju.integrate(f"{ROOT_CA_APP}:certificates", TRAEFIK_APP)
    juju.wait(all_settled, timeout=300)

    cert_path = _pull_server_cert(juju)
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"
    _assert_https_endpoints(juju, cert_path, traefik_ip)


@pytest.mark.xfail(reason="Flaky test; cannot reproduce failure locally.")
def test_tls_termination_after_charm_upgrade(juju: jubilant.Juju, traefik_charm):
    juju.refresh(TRAEFIK_APP, path=traefik_charm, resources=_TRAEFIK_RESOURCES)
    juju.wait(all_settled, timeout=600)

    cert_path = _CERT_PATH if _CERT_PATH.exists() else _pull_server_cert(juju)
    traefik_ip = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_ip, "Expected a traefik load balancer address"
    _assert_https_endpoints(juju, cert_path, traefik_ip)


def test_disintegrate(juju: jubilant.Juju):
    if ROOT_CA_APP not in juju.status().apps:
        return
    juju.remove_relation(f"{ROOT_CA_APP}:certificates", f"{TRAEFIK_APP}:certificates")
    juju.wait(all_settled, timeout=600)


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60, force=False)


def _endpoints(model: str, scheme: str, netloc: str) -> list[str]:
    return [
        f"{scheme}://{netloc}/{model}-{PROMETHEUS_APP}-0",
        f"{scheme}://{netloc}/{model}-{ALERTMANAGER_APP}",
        f"{scheme}://{netloc}/{model}-{GRAFANA_APP}",
    ]


def _pull_server_cert(juju: jubilant.Juju) -> Path:
    _ARTIFACT_DIR.mkdir(exist_ok=True)
    cert = juju.ssh(
        f"{TRAEFIK_APP}/0",
        "cat /opt/traefik/juju/server.cert",
        container="traefik",
    )
    _CERT_PATH.write_text(cert, encoding="utf-8")
    return _CERT_PATH


def _assert_https_endpoints(juju: jubilant.Juju, cert_path: Path, traefik_ip: str) -> None:
    session = requests.Session()
    session.mount("https://", DNSResolverHTTPSAdapter(MOCK_HOSTNAME, traefik_ip))
    session.verify = str(cert_path)
    for endpoint in _endpoints(juju.model, "https", MOCK_HOSTNAME):
        response = session.get(endpoint, timeout=30)
        response.raise_for_status()
