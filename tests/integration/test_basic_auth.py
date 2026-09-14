#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Traefik basic auth using jubilant."""

from pathlib import Path

import jubilant
import requests
import yaml
from tenacity import retry, retry_if_exception_type, retry_if_result, stop_after_delay, wait_fixed

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    PYTHON_PACKAGES,
    ipa_src_overwrite,
)
from tests.integration.helpers import all_settled, rpc

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
    juju.wait(all_settled, error=jubilant.any_error, timeout=1000, delay=5, successes=5)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)


def test_ipa_charm_ingress_noauth(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP, {"basic_auth_user": ""})
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)
    _assert_status(_get_tester_url(juju), SUCCESS_STATUS)


def test_ipa_charm_ingress_auth(juju: jubilant.Juju):
    tester_url = _get_tester_url(juju)
    juju.config(TRAEFIK_APP, {"basic_auth_user": TEST_AUTH_USER})
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)
    _assert_status(tester_url, 401)
    _assert_status(tester_url, SUCCESS_STATUS, auth=(USERNAME, PASSWORD))


def test_ipa_charm_ingress_auth_disable(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP, {"basic_auth_user": ""})
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)
    _assert_status(_get_tester_url(juju), SUCCESS_STATUS)


def _get_tester_url(juju: jubilant.Juju) -> str:
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    return data["url"]


def _assert_status(
    url: str,
    expected_status: int,
    auth: tuple[str, str] | None = None,
) -> None:
    @retry(
        stop=stop_after_delay(60),
        wait=wait_fixed(2),
        retry=(
            retry_if_result(lambda r: r.status_code != expected_status)
            | retry_if_exception_type(requests.exceptions.RequestException)
        ),
        reraise=True,
    )
    def _fetch() -> requests.Response:
        return requests.get(url, auth=auth, verify=False, timeout=10)

    _fetch()
