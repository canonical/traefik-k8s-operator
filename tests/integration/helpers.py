#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import contextlib
from pathlib import Path
from typing import Sequence

import yaml
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {
    resource_name: METADATA["resources"][resource_name]["upstream-source"]
    for resource_name in METADATA.get("resources", [])
}


@contextlib.asynccontextmanager
async def fast_forward(ops_test: OpsTest, fast_interval: str = "10s", slow_interval: str = "60m"):
    """Temporarily speed up update-status firing rate."""
    await ops_test.model.set_config({"update-status-hook-interval": fast_interval})
    yield
    await ops_test.model.set_config({"update-status-hook-interval": slow_interval})


async def assert_status_reached(
    ops_test: OpsTest,
    status: str,
    apps: Sequence[str] = (APP_NAME,),
    raise_on_blocked=True,
    timeout=600,
):
    """Wait for all `apps` to reach the given status."""
    print(f"waiting for {apps} to reach {status}...")

    await ops_test.model.wait_for_idle(
        apps=apps,
        status=status,
        timeout=timeout,
        raise_on_blocked=False if status == "blocked" else raise_on_blocked,
    )

    for app in apps:
        assert ops_test.model.applications[app].units[0].workload_status == status
