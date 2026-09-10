#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests that Traefik works correctly when it has an upstream ingress."""

from pathlib import Path

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    ingress_requirer_mock_src_overwrite,
)
from tests.integration.helpers import all_settled, external_url, fetch_with_retry

TRAEFIK = "traefik-k8s"
UPSTREAM_INGRESS = f"{TRAEFIK}-upstream"
IPA_TESTER = "ipa-tester"
IPU_TESTER = "ipu-tester"
ROUTE_TESTER = "route-tester"
CERTIFICATE_PROVIDER = "self-signed-certificates"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK, resources=_TRAEFIK_RESOURCES, trust=True)

    juju.deploy(
        "ch:self-signed-certificates",
        CERTIFICATE_PROVIDER,
        channel="1/stable",
    )
    juju.deploy(
        traefik_charm,
        UPSTREAM_INGRESS,
        resources=_TRAEFIK_RESOURCES,
        trust=True,
    )

    config = {
        "src-overwrite": ingress_requirer_mock_src_overwrite(),
        "python-packages": PYTHON_PACKAGES,
    }
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        IPA_TESTER,
        channel=ANY_CHARM_CHANNEL,
        config=config,
        trust=True,
    )
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        IPU_TESTER,
        channel=ANY_CHARM_CHANNEL,
        config=config,
        trust=True,
    )
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        ROUTE_TESTER,
        channel=ANY_CHARM_CHANNEL,
        config=config,
        trust=True,
    )

    juju.integrate(f"{TRAEFIK}:ingress", f"{IPA_TESTER}:require-ingress")
    juju.integrate(f"{TRAEFIK}:ingress-per-unit", f"{IPU_TESTER}:require-ingress-per-unit")
    juju.integrate(f"{TRAEFIK}:traefik-route", f"{ROUTE_TESTER}:require-traefik-route")
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)


def test_ipa_ingressed_no_upstream_ingress(juju: jubilant.Juju):
    fetch_with_retry(external_url(juju, TRAEFIK, IPA_TESTER), 200)


def test_ipu_ingressed_no_upstream_ingress(juju: jubilant.Juju):
    fetch_with_retry(external_url(juju, TRAEFIK, f"{IPU_TESTER}/0"), 200)


def test_traefik_route_ingressed_no_upstream_ingress(juju: jubilant.Juju):
    traefik_url = external_url(juju, TRAEFIK, TRAEFIK)
    fetch_with_retry(f"{traefik_url}/{juju.model}-{ROUTE_TESTER}-traefik-route", 200)


def test_add_upstream_ingress(juju: jubilant.Juju):
    juju.integrate(f"{TRAEFIK}:upstream-ingress", f"{UPSTREAM_INGRESS}:ingress")
    juju.wait(all_settled, error=jubilant.any_error, timeout=300)


def test_ipa_ingressed_through_upstream_ingress(juju: jubilant.Juju):
    fetch_with_retry(external_url(juju, TRAEFIK, IPA_TESTER), 200)


def test_ipu_ingressed_through_upstream_ingress(juju: jubilant.Juju):
    fetch_with_retry(external_url(juju, TRAEFIK, f"{IPU_TESTER}/0"), 200)


def test_traefik_route_ingressed_through_upstream_ingress(juju: jubilant.Juju):
    traefik_url = external_url(juju, TRAEFIK, TRAEFIK)
    fetch_with_retry(f"{traefik_url}/{juju.model}-{ROUTE_TESTER}-traefik-route", 200)


def test_traefik_with_upstream_ingress_blocked_if_in_subdomain_mode(juju: jubilant.Juju):
    assert juju.status().apps[TRAEFIK].app_status.current == "active", (
        "Expected Traefik to be active before triggering subdomain-mode block"
    )
    juju.config(TRAEFIK, {"routing_mode": "subdomain"})
    juju.wait(
        lambda status: jubilant.all_blocked(status, TRAEFIK),
        error=jubilant.any_error,
        timeout=300,
    )

    juju.config(TRAEFIK, {"routing_mode": "path"})
    juju.wait(
        lambda status: jubilant.all_blocked(status, TRAEFIK),
        error=jubilant.any_error,
        timeout=300,
    )


def test_add_tls_to_all_ingresses(juju: jubilant.Juju):
    juju.integrate(f"{TRAEFIK}:certificates", CERTIFICATE_PROVIDER)
    juju.integrate(f"{UPSTREAM_INGRESS}:certificates", CERTIFICATE_PROVIDER)
    juju.wait(all_settled, error=jubilant.any_error, timeout=300)


def test_ipa_ingressed_through_upstream_ingress_with_tls(juju: jubilant.Juju):
    fetch_with_retry(external_url(juju, TRAEFIK, IPA_TESTER), 200)


def test_ipu_ingressed_through_upstream_ingress_with_tls(juju: jubilant.Juju):
    fetch_with_retry(external_url(juju, TRAEFIK, f"{IPU_TESTER}/0"), 200)


def test_traefik_route_ingressed_through_upstream_ingress_with_tls(juju: jubilant.Juju):
    traefik_url = external_url(juju, TRAEFIK, TRAEFIK)
    fetch_with_retry(f"{traefik_url}/{juju.model}-{ROUTE_TESTER}-traefik-route", 200)
