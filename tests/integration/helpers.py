# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import subprocess


async def disable_metallb():
    try:
        cmd = ["sg", "microk8s", "-c", "microk8s disable metallb"]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        print(e)
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
    except Exception as e:
        print(e)
        raise

    await asyncio.sleep(30)  # why? just because, for now
    return ip
