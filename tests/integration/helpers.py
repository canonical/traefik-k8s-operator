# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import subprocess
from typing import Optional

from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def disable_metallb():
    try:
        cmd = ["sg", "microk8s", "-c", "microk8s disable metallb"]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        logger.error(e.stdout.decode())
        raise

    await asyncio.sleep(30)  # why? just because, for now


async def enable_metallb():
    cmd = [
        "sh",
        "-c",
        "ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc'",
    ]
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ip = result.stdout.decode("utf-8").strip()

    try:
        cmd = ["sg", "microk8s", "-c", f"microk8s enable metallb:{ip}-{ip}"]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        logger.error(e.stdout.decode())
        raise

    await asyncio.sleep(30)  # why? just because, for now
    return ip


async def get_address(ops_test: OpsTest, app_name: str, unit_num: Optional[int] = None) -> str:
    """Find unit address for any application.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        unit address as a string
    """
    status = await ops_test.model.get_status()
    app = status["applications"][app_name]
    return (
        app.public_address
        if unit_num is None
        else app["units"][f"{app_name}/{unit_num}"]["address"]
    )
