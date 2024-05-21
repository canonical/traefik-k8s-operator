# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from typing import Optional

from lightkube import AsyncClient
from lightkube.resources.core_v1 import Service
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def get_k8s_service_address(ops_test: OpsTest, service_name: str) -> Optional[str]:
    """Find the address of a Kubernetes service.

    Args:
        ops_test: pytest-operator plugin
        service_name: The name of the Kubernetes service

    Returns:
        The service address as a string, or None if the service or address is not found
    """
    model = ops_test.model.info
    client = AsyncClient(namespace=model.name)

    try:
        service = await client.get(Service, name=service_name)
        if service.spec.type == "LoadBalancer" and service.status.loadBalancer.ingress:
            return (
                service.status.loadBalancer.ingress[0].ip
                or service.status.loadBalancer.ingress[0].hostname
            )

        if service.spec.type == "ClusterIP":
            return service.spec.clusterIP

        if service.spec.type == "NodePort":
            # NodePort type services do not have a single IP address. Return ClusterIP as a fallback.
            return service.spec.clusterIP

        return None
    except Exception as e:
        logger.error("Error retrieving service address %s", e, exc_info=1)
        return None


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


async def remove_application(
    ops_test: OpsTest, name: str, *, timeout: int = 60, force: bool = True
):
    # In CI, tests consistently timeout on `waiting: gateway address unavailable`.
    # Just in case there's an unreleased socket, let's try to remove traefik more gently.

    app = ops_test.model.applications.get(name)
    if not app:
        return

    # Wrapping in `create_task` to be able to timeout with `wait`
    tasks = [asyncio.create_task(app.destroy(destroy_storage=True, force=False, no_wait=False))]
    await asyncio.wait(tasks, timeout=timeout)

    if not force:
        return

    # Now, after the workload has hopefully terminated, force removal of the juju leftovers
    await app.destroy(destroy_storage=True, force=True, no_wait=True)


def dequote(s: str):
    if isinstance(s, str) and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s
