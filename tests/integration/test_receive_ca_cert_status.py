#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Regression test for receive-ca-cert status after relation removal (#670)."""

import time
from pathlib import Path

import jubilant
import pytest
import yaml

APP_NAME = "traefik-rca"
SSC_NAME = "ssc-rca"

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
RESOURCES = {"traefik-image": METADATA["resources"]["traefik-image"]["upstream-source"]}


@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        juju.wait_timeout = 10 * 60
        yield juju


def test_build_and_deploy(juju: jubilant.Juju, traefik_charm):
    juju.deploy(
        traefik_charm,
        APP_NAME,
        resources=RESOURCES,
        trust=True,
    )
    juju.deploy(
        "ch:self-signed-certificates",
        SSC_NAME,
        channel="1/stable",
        trust=True,
    )

    juju.wait(jubilant.all_active, timeout=900)


def test_status_is_not_stuck_restarting_after_receive_ca_cert_removal(juju: jubilant.Juju):
    juju.integrate(f"{SSC_NAME}:send-ca-cert", f"{APP_NAME}:receive-ca-cert")
    juju.wait(jubilant.all_active, timeout=600)

    juju.remove_relation(f"{SSC_NAME}:send-ca-cert", f"{APP_NAME}:receive-ca-cert")

    deadline = time.monotonic() + 180
    current, message = "", ""
    while time.monotonic() < deadline:
        status = juju.status()
        unit = status.apps[APP_NAME].units[f"{APP_NAME}/0"]
        current = unit.workload_status.current
        message = unit.workload_status.message
        if not (current == "maintenance" and message == "restarting traefik..."):
            break
        time.sleep(5)

    assert not (
        current == "maintenance" and message == "restarting traefik..."
    ), "Traefik unit remained in maintenance/restarting after receive-ca-cert removal"

    juju.wait(jubilant.all_active, timeout=600)
