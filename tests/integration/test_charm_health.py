#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress health checks using jubilant."""

from typing import Any

import httpx2
import jubilant
from tenacity import retry, stop_after_delay, wait_fixed

from tests.integration.any_charm_helpers import (
    ANY_CHARM,
    ANY_CHARM_CHANNEL,
    HEALTH_PYTHON_PACKAGES,
    health_src_overwrite,
)
from tests.integration.conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from tests.integration.helpers import (
    all_settled,
    any_error_after,
    proxied_url,
    remove_application,
    rpc,
)

HEALTH_TESTER_APP = "health-tester"


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP_NAME, resources=TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM}",
        HEALTH_TESTER_APP,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": health_src_overwrite(),
            "python-packages": HEALTH_PYTHON_PACKAGES,
        },
        num_units=3,
        trust=True,
    )
    juju.wait(
        all_settled,
        error=any_error_after(failures=5),
        delay=5,
        successes=5,
    )
    juju.integrate(f"{HEALTH_TESTER_APP}:require-ingress", f"{TRAEFIK_APP_NAME}:ingress")
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)


def test_health(juju: jubilant.Juju):
    health_address = f"{proxied_url(juju, TRAEFIK_APP_NAME, HEALTH_TESTER_APP)}/health"

    rpc(juju, f"{HEALTH_TESTER_APP}/2", "set_health", is_healthy=False)
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)
    _assert_healthy_backends(
        health_address,
        [
            {"host": "health-tester-0", "status": "up"},
            {"host": "health-tester-1", "status": "up"},
        ],
    )

    rpc(juju, f"{HEALTH_TESTER_APP}/1", "set_health", is_healthy=False)
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)
    _assert_healthy_backends(
        health_address,
        [{"host": "health-tester-0", "status": "up"}],
    )


@retry(stop=stop_after_delay(60), wait=wait_fixed(5), reraise=True)
def _assert_healthy_backends(url: str, expected: list[dict[str, str]]) -> None:
    for _ in range(10):
        status, content = _fetch_health(url)
        assert status == 200
        assert content in expected


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP_NAME, timeout=60)


def _fetch_health(url: str) -> tuple[int, Any]:
    response = httpx2.get(url, timeout=10)
    try:
        content = response.json()
    except ValueError:
        content = {}
    return response.status_code, content
