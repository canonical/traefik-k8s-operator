#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Traefik basic auth using jubilant."""

import json
import time
from pathlib import Path
from typing import Any

import jubilant
import requests
import yaml

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    PYTHON_PACKAGES,
    ipa_src_overwrite,
)
from tests.integration.helpers import all_settled

TRAEFIK_APP = "traefik"
IPA_TESTER_APP = "ipa-tester"
USERNAME = "admin"
PASSWORD = "admin"
SUCCESS_STATUS = 502
TEST_AUTH_USER = r"admin:$2a$13$XOHdzKdVS4mPKT0LvOfXru4LqyLbwcEvFlssXGS3laC6d/i6cKrLS"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def _relation_info(
    juju: jubilant.Juju,
    remote_unit: str,
    remote_endpoint: str,
    local_unit: str,
    local_endpoint: str,
) -> dict[str, Any]:
    data = json.loads(juju.cli("show-unit", remote_unit, "--format", "json"))[remote_unit]
    for relation in data.get("relation-info", []):
        if (
            relation.get("endpoint") == remote_endpoint
            and relation.get("related-endpoint") == local_endpoint
            and local_unit in relation.get("related-units", {})
        ):
            return relation
    raise AssertionError(
        f"No relation data for {remote_unit}:{remote_endpoint} and "
        f"{local_unit}:{local_endpoint}"
    )


def _get_tester_url(juju: jubilant.Juju) -> str:
    relation = _relation_info(
        juju,
        remote_unit=f"{TRAEFIK_APP}/0",
        remote_endpoint="ingress",
        local_unit=f"{IPA_TESTER_APP}/0",
        local_endpoint="require-ingress",
    )
    app_data = yaml.safe_load(relation["application-data"]["ingress"])
    return app_data["url"]


def _assert_status(
    url: str,
    expected_status: int,
    auth: tuple[str, str] | None = None,
) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, auth=auth, verify=False, timeout=10)
            if response.status_code == expected_status:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise AssertionError(f"Expected HTTP {expected_status} from {url}")


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
    juju.wait(all_settled, timeout=1000)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, timeout=600)


def test_ipa_charm_ingress_noauth(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP, {"basic_auth_user": ""})
    juju.wait(all_settled, timeout=600)
    _assert_status(_get_tester_url(juju), SUCCESS_STATUS)


def test_ipa_charm_ingress_auth(juju: jubilant.Juju):
    tester_url = _get_tester_url(juju)
    juju.config(TRAEFIK_APP, {"basic_auth_user": TEST_AUTH_USER})
    juju.wait(all_settled, timeout=600)
    _assert_status(tester_url, 401)
    _assert_status(tester_url, SUCCESS_STATUS, auth=(USERNAME, PASSWORD))


def test_ipa_charm_ingress_auth_disable(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP, {"basic_auth_user": ""})
    juju.wait(all_settled, timeout=600)
    _assert_status(_get_tester_url(juju), SUCCESS_STATUS)
