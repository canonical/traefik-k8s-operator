#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress-per-app (IPA) using jubilant."""

import json
import logging
import textwrap
from pathlib import Path
from urllib.parse import urlparse

import jubilant
import pytest

from tests.integration.helpers import all_settled, assert_can_connect, get_k8s_service_address

logger = logging.getLogger(__name__)

TRAEFIK_APP = "traefik-k8s"
IPA_TESTER_APP = "ipa-tester"

# any-charm injects this code into its src/ at deploy time.
# It replicates exactly what the legacy ipa-tester charm did: request ingress
# with a known host/port, and expose the received URL via RPC.
_ANY_CHARM_SRC_OVERWRITE = {
    "ingress.py": (Path("lib/charms/traefik_k8s/v2/ingress.py")).read_text(),
    "any_charm.py": textwrap.dedent(
        """\
        from ingress import IngressPerAppRequirer
        from any_charm_base import AnyCharmBase

        class AnyCharm(AnyCharmBase):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.ipa = IngressPerAppRequirer(self, host="foo.bar", port=80)

            def get_ingress_url(self):
                return self.ipa.url
        """
    ),
}


@pytest.fixture(scope="module")
def traefik_resources():
    metadata = __import__("yaml").safe_load(Path("./metadata.yaml").read_text())
    return {name: val["upstream-source"] for name, val in metadata["resources"].items()}


def test_deployment(juju: jubilant.Juju, traefik_charm, traefik_resources):
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP,
        resources=traefik_resources,
        trust=True,
    )
    juju.deploy(
        "ch:any-charm",
        IPA_TESTER_APP,
        channel="beta",
        config={"src-overwrite": json.dumps(_ANY_CHARM_SRC_OVERWRITE)},
    )
    juju.wait(all_settled, timeout=1000)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, timeout=600)


def test_ipa_charm_has_ingress(juju: jubilant.Juju):
    result = juju.run(f"{IPA_TESTER_APP}/0", "rpc", method="get_ingress_url")
    url = result.results["return"]
    assert url, "Expected a non-empty ingress URL"

    parsed = urlparse(url)
    ip = parsed.hostname
    port = parsed.port or 80
    assert_can_connect(ip, port)


def test_relation_data_shape(juju: jubilant.Juju):
    result = juju.run(f"{IPA_TESTER_APP}/0", "rpc", method="get_ingress_url")
    url = result.results["return"]
    assert url, "Expected ingress URL to be set"

    traefik_address = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_address, "Could not determine Traefik LoadBalancer IP"

    model_name = juju.model
    expected_url = f"http://{traefik_address}/{model_name}-{IPA_TESTER_APP}"
    assert url == expected_url, f"Expected URL {expected_url!r}, got {url!r}"


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(f"{IPA_TESTER_APP}:ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, IPA_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        timeout=300,
    )

    # Verify the URL is cleared after relation removal
    result = juju.run(f"{IPA_TESTER_APP}/0", "rpc", method="get_ingress_url")
    url = result.results["return"]
    assert not url, f"Expected ingress URL to be cleared after relation removal, got {url!r}"
