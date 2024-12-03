# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
from typing import Optional

import requests
import sh
from juju.application import Application
from juju.unit import Unit
from minio import Minio
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


async def get_k8s_service_address(ops_test: OpsTest, service_name: str) -> Optional[str]:
    """Get the address of a LoadBalancer Kubernetes service using kubectl.

    Args:
        ops_test: pytest-operator plugin
        service_name: The name of the Kubernetes service

    Returns:
        The LoadBalancer service address as a string, or None if not found
    """
    model = ops_test.model.info
    try:
        result = sh.kubectl(
            *f"-n {model.name} get service/{service_name} -o=jsonpath='{{.status.loadBalancer.ingress[0].ip}}'".split()
        )
        ip_address = result.strip("'")
        return ip_address
    except Exception as e:
        logger.error("Error retrieving service address %s", e, exc_info=1)
        return None


async def delete_k8s_service(ops_test: OpsTest, service_name: str) -> None:
    """Delete a Kubernetes service using kubectl.

    Args:
        ops_test: pytest-operator plugin
        service_name: The name of the Kubernetes service to delete
    """
    # In CI, tests consistently timeout on `waiting: gateway address unavailable`.
    # Just in case lb service still exists before next run, let's remove it
    model = ops_test.model.info
    try:
        sh.kubectl(*f"-n {model.name} delete service/{service_name}".split())
    except Exception:
        return


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


async def deploy_and_configure_minio(ops_test: OpsTest) -> None:
    """Deploy and set up minio and s3-integrator needed for s3-like storage backend in the HA charms."""
    config = {
        "access-key": "accesskey",
        "secret-key": "secretkey",
    }
    await ops_test.model.deploy("minio", channel="edge", trust=True, config=config)
    await ops_test.model.wait_for_idle(apps=["minio"], status="active", timeout=2000)
    minio_addr = await get_address(ops_test, "minio", 0)

    mc_client = Minio(
        f"{minio_addr}:9000",
        access_key="accesskey",
        secret_key="secretkey",
        secure=False,
    )

    # create tempo bucket
    found = mc_client.bucket_exists("tempo")
    if not found:
        mc_client.make_bucket("tempo")

    # configure s3-integrator
    s3_integrator_app: Application = ops_test.model.applications["s3-integrator"]
    s3_integrator_leader: Unit = s3_integrator_app.units[0]

    await s3_integrator_app.set_config(
        {
            "endpoint": f"minio-0.minio-endpoints.{ops_test.model.name}.svc.cluster.local:9000",
            "bucket": "tempo",
        }
    )

    action = await s3_integrator_leader.run_action("sync-s3-credentials", **config)
    action_result = await action.wait()
    assert action_result.status == "completed"


async def deploy_tempo_cluster(ops_test: OpsTest):
    """Deploys tempo in its HA version together with minio and s3-integrator."""
    tempo_app = "tempo"
    worker_app = "tempo-worker"
    tempo_worker_charm_url, worker_channel = "tempo-worker-k8s", "edge"
    tempo_coordinator_charm_url, coordinator_channel = "tempo-coordinator-k8s", "edge"
    await ops_test.model.deploy(
        tempo_worker_charm_url, application_name=worker_app, channel=worker_channel, trust=True
    )
    await ops_test.model.deploy(
        tempo_coordinator_charm_url,
        application_name=tempo_app,
        channel=coordinator_channel,
        trust=True,
    )
    await ops_test.model.deploy("s3-integrator", channel="edge")

    await ops_test.model.integrate(tempo_app + ":s3", "s3-integrator" + ":s3-credentials")
    await ops_test.model.integrate(tempo_app + ":tempo-cluster", worker_app + ":tempo-cluster")

    await deploy_and_configure_minio(ops_test)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[tempo_app, worker_app, "s3-integrator"],
            status="active",
            timeout=2000,
            idle_period=30,
        )


def get_traces(tempo_host: str, service_name="tracegen-otlp_http", tls=True):
    """Get traces directly from Tempo REST API."""
    url = f"{'https' if tls else 'http'}://{tempo_host}:3200/api/search?tags=service.name={service_name}"
    req = requests.get(
        url,
        verify=False,
    )
    assert req.status_code == 200
    traces = json.loads(req.text)["traces"]
    return traces


@retry(stop=stop_after_attempt(15), wait=wait_exponential(multiplier=1, min=4, max=10))
async def get_traces_patiently(tempo_host, service_name="tracegen-otlp_http", tls=True):
    """Get traces directly from Tempo REST API, but also try multiple times.

    Useful for cases when Tempo might not return the traces immediately (its API is known for returning data in
    random order).
    """
    traces = get_traces(tempo_host, service_name=service_name, tls=tls)
    assert len(traces) > 0
    return traces


async def get_application_ip(ops_test: OpsTest, app_name: str) -> str:
    """Get the application IP address."""
    status = await ops_test.model.get_status()
    app = status["applications"][app_name]
    return app.public_address
