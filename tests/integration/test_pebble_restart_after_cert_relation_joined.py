#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test TLS routing still works after Traefik gains a certificates relation."""

import json
from pathlib import Path

import jubilant
import yaml

from tests.integration.helpers import all_settled, fetch_with_retry

TRAEFIK_APP = "traefik"
ALERTMANAGER_APP = "alertmanager"
SSC_APP = "ssc"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_build_and_deploy(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy("ch:alertmanager-k8s", ALERTMANAGER_APP, channel="2/edge", trust=True)
    juju.deploy("ch:self-signed-certificates", SSC_APP, channel="1/stable", trust=True)
    juju.wait(jubilant.all_active, error=jubilant.any_error, delay=5, successes=5)

    juju.integrate(f"{ALERTMANAGER_APP}:ingress", TRAEFIK_APP)
    juju.integrate(f"{SSC_APP}:certificates", ALERTMANAGER_APP)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)


def test_can_route_ingress_using_tls(juju: jubilant.Juju):
    juju.integrate(f"{SSC_APP}:certificates", TRAEFIK_APP)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)

    traefik_url = _external_url(juju, TRAEFIK_APP)
    alertmanager_url = f"{traefik_url}/{juju.model}-{ALERTMANAGER_APP}"

    fetch_with_retry(alertmanager_url)
    fetch_with_retry(alertmanager_url.replace("https://", "http://"))


def _external_url(juju: jubilant.Juju, app_name: str) -> str:
    action = juju.run(f"{app_name}/0", "show-external-endpoints")
    endpoints = json.loads(action.results["external-endpoints"])
    return endpoints[app_name]["url"]
