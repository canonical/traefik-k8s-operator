#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test TLS routing still works after Traefik gains a certificates relation."""

import json
from pathlib import Path

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    health_src_overwrite,
)
from tests.integration.helpers import all_settled, fetch_with_retry

TRAEFIK_APP = "traefik"
INGRESS_APP = "ingress"
SSC_APP = "ssc"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_build_and_deploy(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        INGRESS_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": health_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        trust=True,
    )
    juju.deploy("ch:self-signed-certificates", SSC_APP, channel="1/stable", trust=True)
    juju.wait(jubilant.all_active, error=jubilant.any_error, delay=5, successes=5)

    juju.integrate(f"{INGRESS_APP}:require-ingress", TRAEFIK_APP)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)


def test_can_route_ingress_using_tls(juju: jubilant.Juju):
    juju.integrate(f"{SSC_APP}:certificates", TRAEFIK_APP)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)

    traefik_url = _external_url(juju, TRAEFIK_APP)
    ingress_url = f"{traefik_url}/{juju.model}-{INGRESS_APP}/health"

    fetch_with_retry(ingress_url)
    fetch_with_retry(ingress_url.replace("https://", "http://"))


def _external_url(juju: jubilant.Juju, app_name: str) -> str:
    action = juju.run(f"{app_name}/0", "show-external-endpoints")
    endpoints = json.loads(action.results["external-endpoints"])
    return endpoints[app_name]["url"]
