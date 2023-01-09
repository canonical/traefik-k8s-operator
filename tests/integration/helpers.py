# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import grp
import subprocess
from typing import List, Optional
import logging

from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


def get_sg_params() -> List[str]:
    groups = list(map(lambda grp_strct: grp_strct.gr_name, grp.getgrall()))
    for grp_name in ["microk8s", "snap_microk8s"]:
        if "microk8s" in groups:  # this means the itest is running in a github runner
            return ["sg", grp_name, "-c"]
    return []


async def disable_metallb():
    try:
        cmd = get_sg_params() + "microk8s disable metallb".split(" ")
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
        cmd = get_sg_params() + f"microk8s enable metallb:{ip}-{ip}".split(" ")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        print(e)
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
