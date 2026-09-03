#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test for Traefik workload tracing using jubilant."""

import socket
from pathlib import Path

import jubilant
import requests
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential

from tests.integration.helpers import all_settled, any_error

TRAEFIK_APP = "traefik"
TEMPO_APP = "tempo"
TEMPO_WORKER_APP = "tempo-worker"
S3_INTEGRATOR_APP = "s3-integrator"

# Must match the values set up by s3-installation.sh (microceph RGW).
S3_ACCESS_KEY = "my-lovely-key"
S3_SECRET_KEY = "this-is-very-secret"
S3_BUCKET = "tests"
S3_PORT = 7480

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}


def test_setup_env(juju: jubilant.Juju):
    juju.model_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


def test_workload_tracing_is_present(juju: jubilant.Juju, traefik_charm):
    _deploy_tempo_cluster(juju)

    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.wait(
        lambda status: jubilant.all_active(status, TRAEFIK_APP),
        error=any_error,
        timeout=300,
        delay=5,
        successes=5,
    )

    juju.integrate(f"{TRAEFIK_APP}:workload-tracing", f"{TEMPO_APP}:tracing")
    juju.integrate(f"{TEMPO_APP}:ingress", f"{TRAEFIK_APP}:traefik-route")
    juju.wait(all_settled, error=any_error, timeout=1000, delay=5, successes=5)

    tempo_host = juju.status().apps[TEMPO_APP].address
    assert _get_traces_patiently(tempo_host)


def _get_routable_host_ip() -> str:
    """Return this host's outbound-facing IP address.

    ``socket.gethostbyname(socket.gethostname())`` is unreliable here: on Debian/Ubuntu
    hosts, ``/etc/hosts`` commonly maps the hostname to ``127.0.1.1``, which is
    unreachable from inside k8s pods. Opening a UDP "connection" (no packets are
    actually sent) forces the kernel to pick the real outbound interface/IP via the
    routing table, which is reachable from the single-node k8s cluster.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]


def _deploy_tempo_cluster(juju: jubilant.Juju) -> None:
    juju.deploy("ch:tempo-worker-k8s", TEMPO_WORKER_APP, channel="2/edge", trust=True)
    juju.deploy("ch:tempo-coordinator-k8s", TEMPO_APP, channel="2/edge", trust=True)
    juju.deploy("ch:s3-integrator", S3_INTEGRATOR_APP, channel="edge")

    juju.integrate(f"{TEMPO_APP}:s3", f"{S3_INTEGRATOR_APP}:s3-credentials")
    juju.integrate(f"{TEMPO_APP}:tempo-cluster", f"{TEMPO_WORKER_APP}:tempo-cluster")

    # s3-integrator's unit agent must be up (installed) before we can run an action
    # against it below.
    juju.wait(jubilant.all_agents_idle, error=any_error, delay=5, successes=5)

    # microceph's RGW runs on the spread runner host (set up by s3-installation.sh) and
    # is reachable from the single-node k8s cluster via the host's own IP address.
    host_ip = _get_routable_host_ip()
    juju.config(
        S3_INTEGRATOR_APP,
        {
            "endpoint": f"http://{host_ip}:{S3_PORT}",
            "bucket": S3_BUCKET,
        },
    )
    juju.run(
        f"{S3_INTEGRATOR_APP}/0",
        "sync-s3-credentials",
        params={"access-key": S3_ACCESS_KEY, "secret-key": S3_SECRET_KEY},
    )
    juju.wait(all_settled, error=any_error, timeout=2000, delay=5, successes=5)


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
