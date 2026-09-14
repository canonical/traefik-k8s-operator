#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Traefik basic auth using jubilant."""


import jubilant
from tenacity import stop_after_delay, wait_fixed

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    PYTHON_PACKAGES,
    ipa_src_overwrite,
)
from tests.integration.conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from tests.integration.helpers import all_settled, any_error_after, fetch_with_retry, rpc

IPA_TESTER_APP = "ipa-tester"
USERNAME = "admin"
PASSWORD = "admin"
SUCCESS_STATUS = 502
TEST_AUTH_USER = r"admin:$2a$13$XOHdzKdVS4mPKT0LvOfXru4LqyLbwcEvFlssXGS3laC6d/i6cKrLS"


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP_NAME, resources=TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM}",
        IPA_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": ipa_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
    )
    juju.wait(all_settled, error=any_error_after(failures=5), timeout=1000, delay=5, successes=5)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP_NAME}:ingress")
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)


def test_ipa_charm_ingress_noauth(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP_NAME, {"basic_auth_user": ""})
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)
    fetch_with_retry(
        _get_tester_url(juju), SUCCESS_STATUS, stop=stop_after_delay(60), wait=wait_fixed(2)
    )


def test_ipa_charm_ingress_auth(juju: jubilant.Juju):
    tester_url = _get_tester_url(juju)
    juju.config(TRAEFIK_APP_NAME, {"basic_auth_user": TEST_AUTH_USER})
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)
    fetch_with_retry(tester_url, 401, stop=stop_after_delay(60), wait=wait_fixed(2))
    fetch_with_retry(
        tester_url,
        SUCCESS_STATUS,
        auth=(USERNAME, PASSWORD),
        stop=stop_after_delay(60),
        wait=wait_fixed(2),
    )


def test_ipa_charm_ingress_auth_disable(juju: jubilant.Juju):
    juju.config(TRAEFIK_APP_NAME, {"basic_auth_user": ""})
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)
    fetch_with_retry(
        _get_tester_url(juju), SUCCESS_STATUS, stop=stop_after_delay(60), wait=wait_fixed(2)
    )


def _get_tester_url(juju: jubilant.Juju) -> str:
    data = rpc(juju, f"{IPA_TESTER_APP}/0", "get_relation_data")
    return data["url"]
