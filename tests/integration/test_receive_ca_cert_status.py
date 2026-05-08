#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Regression test for receive-ca-cert status after relation removal (#670)."""

import asyncio
import json
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

APP_NAME = "traefik-rca"
SSC_NAME = "ssc-rca"

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
RESOURCES = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}


async def _workload_status(ops_test: OpsTest, unit_name: str) -> tuple[str, str]:
    rc, stdout, _ = await ops_test.juju("status", "--format", "json")
    assert rc == 0
    status = json.loads(stdout)
    app_name = unit_name.split("/")[0]
    unit = status["applications"][app_name]["units"][unit_name]
    workload_status = unit["workload-status"]
    return workload_status.get("current", ""), workload_status.get("message", "")


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm,
            resources=RESOURCES,
            application_name=APP_NAME,
            trust=True,
        ),
        ops_test.model.deploy(
            "ch:self-signed-certificates",
            application_name=SSC_NAME,
            channel="1/stable",
            trust=True,
        ),
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, SSC_NAME],
        status="active",
        timeout=900,
        idle_period=20,
    )


@pytest.mark.abort_on_fail
async def test_status_is_not_stuck_restarting_after_receive_ca_cert_removal(ops_test: OpsTest):
    await ops_test.model.add_relation(f"{SSC_NAME}:send-ca-cert", f"{APP_NAME}:receive-ca-cert")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, SSC_NAME],
        status="active",
        timeout=600,
        idle_period=20,
    )

    await ops_test.juju(
        "remove-relation",
        f"{SSC_NAME}:send-ca-cert",
        f"{APP_NAME}:receive-ca-cert",
    )

    deadline = asyncio.get_running_loop().time() + 180
    current, message = "", ""
    while asyncio.get_running_loop().time() < deadline:
        current, message = await _workload_status(ops_test, f"{APP_NAME}/0")
        if not (current == "maintenance" and message == "restarting traefik..."):
            break
        await asyncio.sleep(5)

    assert not (
        current == "maintenance" and message == "restarting traefik..."
    ), "Traefik unit remained in maintenance/restarting after receive-ca-cert removal"

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, SSC_NAME],
        status="active",
        timeout=600,
        idle_period=20,
    )
