#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module tests that traefik ends up in active state when deployed AFTER metallb.

...And without the help of update-status.

1. Enable metallb (in case it's disabled).
2. Deploy traefik + one charm per relation type (as if deployed as part of a bundle).

NOTE: This module implicitly relies on in-order execution (test running in the order they are
 written).
"""

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import get_address, remove_application

logger = logging.getLogger(__name__)

idle_period = 90

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}
trfk = SimpleNamespace(name="traefik", resources=resources)
mock_hostname = "juju.local"  # For TLS

ipu = SimpleNamespace(charm="ch:prometheus-k8s", name="prometheus")  # per unit
ipa = SimpleNamespace(charm="ch:alertmanager-k8s", name="alertmanager")  # per app
ipr = SimpleNamespace(charm="ch:grafana-k8s", name="grafana")  # traefik route


def get_endpoints(ops_test: OpsTest, *, scheme: str, netloc: str) -> list:
    """Return a list of all the URLs that are expected to be reachable (HTTP code < 400)."""
    return [
        f"{scheme}://{netloc}/{path}"
        for path in [
            f"{ops_test.model_name}-{ipu.name}-0",
            f"{ops_test.model_name}-{ipa.name}",
            f"{ops_test.model_name}-{ipr.name}",
        ]
    ]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_charm):
    await asyncio.gather(
        ops_test.model.deploy(traefik_charm, resources=trfk.resources, application_name=trfk.name),
        ops_test.model.deploy(
            ipu.charm,
            application_name=ipu.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
        ),
        ops_test.model.deploy(
            ipa.charm,
            application_name=ipa.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
        ),
        ops_test.model.deploy(
            ipr.charm,
            application_name=ipr.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
        ),
    )

    await ops_test.model.wait_for_idle(
        status="active", timeout=600, idle_period=30, raise_on_error=False
    )

    await asyncio.gather(
        ops_test.model.add_relation(f"{ipu.name}:ingress", trfk.name),
        ops_test.model.add_relation(f"{ipa.name}:ingress", trfk.name),
        ops_test.model.add_relation(f"{ipr.name}:ingress", trfk.name),
    )

    await ops_test.model.wait_for_idle(status="active", timeout=600, idle_period=30)


@pytest.mark.abort_on_fail
async def test_ingressed_endpoints_reachable_after_metallb_enabled(ops_test: OpsTest):
    ip = await get_address(ops_test, trfk.name)
    for ep in get_endpoints(ops_test, scheme="http", netloc=ip):
        logger.debug("Attempting to reach %s", ep)  # Traceback doesn't spell out the endpoint
        urlopen(ep)


async def curl_endpoints(ops_test: OpsTest, certs_dir, cert_path, traefik_app_ip):
    for endpoint in get_endpoints(ops_test, scheme="https", netloc=mock_hostname):
        # Tell curl to resolve the mock_hostname as traefik's IP (to avoid using a custom DNS
        # server). This is needed because the certificate issued by the CA would have that same
        # hostname as the subject, and for TLS to succeed, the target url's hostname must match
        # the one in the certificate.
        cmd = [
            "curl",
            "-s",
            "--fail-with-body",
            "--resolve",
            f"{mock_hostname}:443:{traefik_app_ip}",
            "--capath",
            certs_dir,
            "--cacert",
            cert_path,
            endpoint,
        ]

        rc, stdout, stderr = await ops_test.run(*cmd)
        logger.info("%s: %s", endpoint, (rc, stdout, stderr))
        assert rc == 0, (
            f"curl exited with rc={rc} for {endpoint}; "
            f"non-zero return code means curl encountered a >= 400 HTTP code; "
            f"cmd={cmd}"
        )

        # fixme:
        #          sans:
        #          - '*.juju.local'
        #  services:
        #    juju-test-tls-yuh5-alertmanager-service:
        #      loadBalancer:
        #        servers: []  # should not be empty!


async def pull_server_cert(ops_test, path):
    # Get self-signed cert from peer app data
    rc, stdout, stderr = await ops_test.run(
        "juju",
        "ssh",
        "--container=traefik",
        f"{trfk.name}/0",
        "cat",
        "/opt/traefik/juju/server.cert",
    )
    logger.info(f"pulled server cert from traefik: {stdout[:100]}...")
    with open(path, "wt") as f:
        f.writelines(stdout)

        # fixme:
        #          sans:
        #          - '*.juju.local'
        #  services:
        #    juju-test-tls-yuh5-alertmanager-service:
        #      loadBalancer:
        #        servers: []  # should not be empty!


@pytest.mark.abort_on_fail
async def test_tls_termination(ops_test: OpsTest, temp_dir):
    # TODO move this to the bundle tests
    await ops_test.model.applications[trfk.name].set_config({"external_hostname": mock_hostname})

    await ops_test.model.deploy(
        "ch:self-signed-certificates",
        application_name="root-ca",
        channel="edge",
    )
    await ops_test.model.applications["root-ca"].set_config(
        {
            "ca-common-name": "demo.ca.local",
        }
    )
    await ops_test.model.add_relation("root-ca", f"{trfk.name}:certificates")
    await ops_test.model.wait_for_idle(status="active", timeout=300)

    # Get self-signed cert from peer app data
    cert_path = temp_dir / "local.cert"
    await pull_server_cert(ops_test, cert_path)

    ip = await get_address(ops_test, trfk.name)
    await curl_endpoints(ops_test, temp_dir, cert_path, ip)


# @pytest.mark.abort_on_fail
@pytest.mark.xfail  # FIXME: flaky test, cannot reproduce failure locally.
async def test_tls_termination_after_charm_upgrade(
    ops_test: OpsTest,
    traefik_charm,
    temp_dir,
):
    logger.info(
        "Refreshing charm to test TLS termination still works with the same certificate after"
        " charm upgrade..."
    )
    await ops_test.model.applications[trfk.name].refresh(
        path=traefik_charm, resources=trfk.resources
    )
    # insanely high wait period otherwise for some reason it won't work?
    await ops_test.model.wait_for_idle(status="active", timeout=600, idle_period=10)

    cert_path = temp_dir / "local.cert"
    if not cert_path.exists():  # allow running this test in isolation for debugging
        await pull_server_cert(ops_test, cert_path)

    ip = await get_address(ops_test, trfk.name)

    await curl_endpoints(ops_test, temp_dir, temp_dir / "local.cert", ip)


async def test_cleanup(ops_test):
    await remove_application(ops_test, "traefik", timeout=60)
