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
import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import disable_metallb, enable_metallb, get_address

logger = logging.getLogger(__name__)


METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}
trfk = SimpleNamespace(name="traefik", resources=resources)

ipu = SimpleNamespace(charm="ch:prometheus-k8s", name="prometheus")  # per unit
ipa = SimpleNamespace(charm="ch:alertmanager-k8s", name="alertmanager")  # per app
ipr = SimpleNamespace(charm="ch:grafana-k8s", name="grafana")  # traefik route

idle_period = 90


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_charm):
    logger.info("First, disable metallb, in case it's enabled")
    await disable_metallb()
    logger.info("Now enable metallb")
    await enable_metallb()

    await asyncio.gather(
        ops_test.model.deploy(
            traefik_charm, resources=trfk.resources, application_name=trfk.name, series="focal"
        ),
        ops_test.model.deploy(
            ipu.charm,
            application_name=ipu.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
            series="focal",
        ),
        ops_test.model.deploy(
            ipa.charm,
            application_name=ipa.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
            series="focal",
        ),
        ops_test.model.deploy(
            ipr.charm,
            application_name=ipr.name,
            channel="edge",  # TODO change to "stable" once available
            trust=True,
            series="focal",
        ),
    )

    await ops_test.model.wait_for_idle(status="active", timeout=600, idle_period=30)

    await asyncio.gather(
        ops_test.model.add_relation(f"{ipu.name}:ingress", trfk.name),
        ops_test.model.add_relation(f"{ipa.name}:ingress", trfk.name),
        ops_test.model.add_relation(f"{ipr.name}:ingress", trfk.name),
    )

    await ops_test.model.wait_for_idle(status="active", timeout=600, idle_period=30)


@pytest.mark.abort_on_fail
async def test_ingressed_endpoints_reachable_after_metallb_enabled(ops_test: OpsTest):
    ip = get_address(ops_test, trfk.name)
    endpoints = [
        quote(f"{ip}/{path}")
        for path in [
            f"{ops_test.model_name}-{ipr.name}",
            f"{ops_test.model_name}-{ipu.name}-0",
            f"{ops_test.model_name}-{ipa.name}",
        ]
    ]
    for ep in endpoints:
        urlopen(f"http://{ep}")
        # A 404 would result in an exception:
        #   urllib.error.HTTPError: HTTP Error 404: Not Found
        # so just `urlopen` on its own should suffice for the test.


@pytest.mark.abort_on_fail
async def test_tls_termination(ops_test: OpsTest):
    # TODO move this to the bundle tests
    await ops_test.model.applications[trfk.name].set_config({"external_hostname": "juju.local"})

    await ops_test.model.deploy(
        "ch:tls-certificates-operator",
        application_name="root-ca",
        channel="edge",
    )
    await ops_test.model.applications["root-ca"].set_config(
        {
            "ca-common-name": "demo.ca.local",
            "generate-self-signed-certificates": True,
        }
    )
    await ops_test.model.add_relation("root-ca", f"{trfk.name}:certificates")
    await ops_test.model.wait_for_idle(status="active", timeout=300)

    # Get self-signed cert from peer app data
    rc, stdout, stderr = await ops_test.run("juju", "show-unit", "root-ca/0", "--format=json")
    data = json.loads(stdout)
    peer_data = next(
        filter(lambda d: d["endpoint"] == "replicas", data["root-ca/0"]["relation-info"])
    )
    cert = peer_data["application-data"]["self_signed_ca_certificate"]

    with tempfile.TemporaryDirectory() as certs_dir:
        cert_path = f"{certs_dir}/local.cert"
        with open(cert_path, "wt") as f:
            f.writelines(cert)

        endpoints = [
            quote(f"https://juju.local/{path}")
            for path in [
                f"{ops_test.model_name}-{ipr.name}",
                f"{ops_test.model_name}-{ipu.name}-0",
                f"{ops_test.model_name}-{ipa.name}",
            ]
        ]
        ip = get_address(ops_test, trfk.name)
        for endpoint in endpoints:
            rc, stdout, stderr = await ops_test.run(
                "curl",
                "--resolve",
                f"juju.local:443:{ip}",
                "--capath",
                certs_dir,
                "--cacert",
                cert_path,
                endpoint,
            )
            logger.info("%s: %s", endpoint, (rc, stdout, stderr))
