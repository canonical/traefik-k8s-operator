#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress-per-app (IPA) using jubilant."""

from pathlib import Path
from urllib.parse import urlparse

import jubilant
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    PYTHON_PACKAGES,
    ipa_src_overwrite,
)
from tests.integration.helpers import (
    all_settled,
    any_error,
    assert_can_connect,
    get_k8s_service_address,
    remove_application,
    rpc,
)

TRAEFIK_APP = "traefik-k8s"
IPA_TESTER_APP = "ipa-tester"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
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
    juju.wait(all_settled, error=any_error, delay=5, successes=5)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, error=any_error, delay=5, successes=5)


def test_ipa_charm_has_ingress(juju: jubilant.Juju):
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    url = data["url"]
    assert url, "Expected a non-empty ingress URL"
    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_relation_data_shape(juju: jubilant.Juju):
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


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, IPA_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        error=any_error,
        timeout=300,
        delay=5,
        successes=5,
    )
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    assert not data["url"], "Expected ingress URL to be cleared after relation removal"


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)
