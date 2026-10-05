#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test: Traefik workload logs reach Loki via the ``logging`` relation.

Traefik uses ``LogForwarder`` (from the ``loki_push_api`` library), which configures a
Pebble log-target that ships the workload's stdout to the Loki push API endpoint
advertised over the relation.

The shape of the log target that gets written to the Pebble plan is asserted in
``tests/scenario/test_logging.py``; this test covers only what a real model can show,
that Pebble accepted the plan and the logs arrive in Loki.

Pebble log targets only forward output written *after* the target is added to the plan
(the gatherer tails the service ring buffer), so this test restarts the workload to
produce fresh lines rather than relying on an idle Traefik happening to log.
"""

import logging
import time

import httpx2
import jubilant
from tenacity import Retrying, retry_if_result, stop_after_delay, wait_fixed

from tests.integration.helpers import all_settled, any_error_after

logger = logging.getLogger(__name__)

LOKI_APP_NAME = "loki"
LOKI_APP_CHANNEL = "dev/edge"
LOKI_PORT = 3100
LOG_LOOKBACK_SECONDS = 600
WORKLOAD_SERVICE = "traefik"


def test_workload_logs_reach_loki(juju: jubilant.Juju, traefik_app: str):
    """Logs the workload writes after relating are queryable from Loki."""
    # GIVEN Traefik and Loki are deployed and related over ``logging``
    juju.deploy("loki-k8s", LOKI_APP_NAME, channel=LOKI_APP_CHANNEL, trust=True)
    juju.integrate(f"{traefik_app}:logging", f"{LOKI_APP_NAME}:logging")
    juju.wait(
        all_settled,
        error=any_error_after(failures=5),
        delay=5,
        timeout=900,
        successes=5,
    )

    # The shape of the log target itself is asserted in the scenario tests; what only a
    # real model can show is that Pebble accepted the plan and the logs arrive in Loki.

    # WHEN the workload is restarted so it emits output after the target exists
    juju.ssh(
        f"{traefik_app}/0",
        "/charm/bin/pebble",
        "restart",
        WORKLOAD_SERVICE,
        container="traefik",
    )

    # THEN those log lines are queryable from Loki under the juju_application label
    loki_host = juju.status().apps[LOKI_APP_NAME].address
    _assert_logs_from_application(f"http://{loki_host}:{LOKI_PORT}", traefik_app)


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
        stop=stop_after_delay(60 * 3),
    )
    found = retrying(_has_logs)
    assert found, (
        f"Loki has no log lines labelled juju_application={application} "
        f"in the last {LOG_LOOKBACK_SECONDS}s"
    )
