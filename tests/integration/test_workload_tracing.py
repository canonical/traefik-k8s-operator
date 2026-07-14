#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test for Traefik workload tracing using jubilant."""

from pathlib import Path

import jubilant
import requests
import yaml
from minio import Minio
from tenacity import retry, stop_after_attempt, wait_exponential

from tests.integration.helpers import all_settled

TRAEFIK_APP = "traefik"
TEMPO_APP = "tempo"
TEMPO_WORKER_APP = "tempo-worker"
S3_INTEGRATOR_APP = "s3-integrator"
MINIO_APP = "minio"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_setup_env(juju: jubilant.Juju):
    juju.model_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


def test_workload_tracing_is_present(juju: jubilant.Juju, traefik_charm):
    _deploy_tempo_cluster(juju)

    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.wait(lambda status: jubilant.all_active(status, TRAEFIK_APP), timeout=300)

    juju.integrate(f"{TRAEFIK_APP}:workload-tracing", f"{TEMPO_APP}:tracing")
    juju.integrate(f"{TEMPO_APP}:ingress", f"{TRAEFIK_APP}:traefik-route")
    juju.wait(all_settled, timeout=1000)

    tempo_host = juju.status().apps[TEMPO_APP].address
    assert _get_traces_patiently(tempo_host)


def _deploy_tempo_cluster(juju: jubilant.Juju) -> None:
    juju.deploy("ch:tempo-worker-k8s", TEMPO_WORKER_APP, channel="2/edge", trust=True)
    juju.deploy("ch:tempo-coordinator-k8s", TEMPO_APP, channel="2/edge", trust=True)
    juju.deploy("ch:s3-integrator", S3_INTEGRATOR_APP, channel="edge")
    juju.deploy(
        "ch:minio",
        MINIO_APP,
        channel="edge",
        trust=True,
        config={"access-key": "accesskey", "secret-key": "secretkey"},
    )

    juju.integrate(f"{TEMPO_APP}:s3", f"{S3_INTEGRATOR_APP}:s3-credentials")
    juju.integrate(f"{TEMPO_APP}:tempo-cluster", f"{TEMPO_WORKER_APP}:tempo-cluster")

    # Wait for minio to be active and have an address before connecting to it
    juju.wait(
        lambda status: (
            jubilant.all_active(status, MINIO_APP)
            and bool(status.apps[MINIO_APP].units.get(f"{MINIO_APP}/0", None))
            and bool(status.apps[MINIO_APP].units[f"{MINIO_APP}/0"].address)
        ),
        timeout=600,
    )
    minio_addr = juju.status().apps[MINIO_APP].units[f"{MINIO_APP}/0"].address
    client = Minio(
        f"{minio_addr}:9000",
        access_key="accesskey",
        secret_key="secretkey",
        secure=False,
    )
    if not client.bucket_exists("tempo"):
        client.make_bucket("tempo")

    juju.config(
        S3_INTEGRATOR_APP,
        {
            "endpoint": f"minio-0.minio-endpoints.{juju.model}.svc.cluster.local:9000",
            "bucket": "tempo",
        },
    )
    juju.run(
        f"{S3_INTEGRATOR_APP}/0",
        "sync-s3-credentials",
        params={"access-key": "accesskey", "secret-key": "secretkey"},
    )
    juju.wait(all_settled, timeout=2000)


@retry(stop=stop_after_attempt(15), wait=wait_exponential(multiplier=1, min=4, max=10))
def _get_traces_patiently(tempo_host: str, service_name: str = TRAEFIK_APP) -> list[dict]:
    response = requests.get(
        f"http://{tempo_host}:3200/api/search?tags=service.name={service_name}",
        verify=False,
        timeout=30,
    )
    response.raise_for_status()
    traces = response.json()["traces"]
    assert traces
    return traces
