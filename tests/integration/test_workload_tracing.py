#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from helpers import deploy_tempo_cluster, get_application_ip, get_traces_patiently

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "traefik"
TEMPO_APP_NAME = "tempo"
RESOURCES = {
    "traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"],
}


async def test_setup_env(ops_test):
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


# TODO: Unskip this when https://github.com/canonical/tempo-coordinator-k8s-operator/pull/132 is merged
@pytest.mark.skip
async def test_workload_tracing_is_present(ops_test, traefik_charm):
    logger.info("deploying tempo cluster")
    await deploy_tempo_cluster(ops_test)

    logger.info("deploying local charm")
    await ops_test.model.deploy(
        traefik_charm, resources=RESOURCES, application_name=APP_NAME, trust=True
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=300, wait_for_exact_units=1
    )

    # we relate _only_ workload tracing not to confuse with charm traces
    await ops_test.model.add_relation(
        "{}:workload-tracing".format(APP_NAME), "{}:tracing".format(TEMPO_APP_NAME)
    )
    # but we also relate tempo to route through traefik so there's any traffic to generate traces from
    await ops_test.model.add_relation(
        "{}:ingress".format(TEMPO_APP_NAME), "{}:traefik-route".format(APP_NAME)
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active")

    # Verify workload traces are ingested into Tempo
    assert await get_traces_patiently(
        await get_application_ip(ops_test, TEMPO_APP_NAME),
        service_name=f"{APP_NAME}",
        tls=False,
    )
