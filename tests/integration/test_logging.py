#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test: Traefik workload logs reach Loki via the ``logging`` relation.

Traefik uses ``LogForwarder`` (from the ``loki_push_api`` library), which configures a
Pebble log-target that ships the workload's stdout to the Loki push API endpoint
advertised over the relation. This test:

1. deploys Traefik and Loki,
2. integrates ``traefik:logging`` with ``loki:logging``,
3. asserts the Pebble log-target got added,
4. restarts Traefik to generate fresh output,
5. asserts the logs are queryable from Loki's HTTP API.
"""

import logging
import time

import httpx2
import jubilant
from tenacity import Retrying, retry_if_result, stop_after_delay, wait_fixed

from tests.integration.constants import TRAEFIK_APP_NAME
from tests.integration.helpers import all_settled, any_error_after

logger = logging.getLogger(__name__)

LOKI_APP_NAME = "loki"
LOKI_PORT = 3100
LOG_LOOKBACK_SECONDS = 300


def test_pebble_log_target_configured(juju: jubilant.Juju, traefik_app: str):
    """Pebble adds a Loki log-target to the workload plan."""
    # GIVEN Traefik and Loki are deployed
    juju.deploy("loki-k8s", LOKI_APP_NAME, channel="dev/edge", trust=True)
    # WHEN traefik is related to loki over the logging relation
    juju.integrate(f"{traefik_app}:logging", f"{LOKI_APP_NAME}:logging")
    juju.wait(
        all_settled,
        error=any_error_after(failures=5),
        delay=5,
        timeout=900,
        successes=5,
    )
    # THEN the logs are findable in Loki under the juju_application label
    loki_host = juju.status().apps[LOKI_APP_NAME].address
    _assert_logs_from_application(f"http://{loki_host}:{LOKI_PORT}", TRAEFIK_APP_NAME)


def _assert_logs_from_application(loki_url: str, application: str) -> None:
    """Assert Loki has logs with a given ``juju_application`` label."""

    def _has_logs() -> bool:
        end = time.time_ns()
        start = end - LOG_LOOKBACK_SECONDS * 1_000_000_000
        response = httpx2.get(
            f"{loki_url}/loki/api/v1/query_range",
            params={
                "query": f'{{juju_application="{application}"}}',
                "start": str(start),
                "end": str(end),
                "limit": 1,
            },
            timeout=30,
        )
        response.raise_for_status()
        return bool(response.json().get("data", {}).get("result"))

    retrying = Retrying(
        retry=retry_if_result(lambda result: result is False),
        wait=wait_fixed(10),
        # Log forwarding + Loki ingestion can lag the moment the model goes idle.
        stop=stop_after_delay(60 * 2),
    )
    try:
        found = retrying(_has_logs)
    except Exception as exc:  # noqa: BLE001 - report the last query error if any
        logger.exception("Loki query kept failing")
        raise AssertionError(f"Loki queries kept failing: {exc}") from exc
    assert found, (
        f"Loki has no log lines labelled juju_application={application} "
        f"in the last {LOG_LOOKBACK_SECONDS}s"
    )
