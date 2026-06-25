#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test upgrades."""

import jubilant

from tests.integration.helpers import all_settled

TRAEFIK_APP_NAME = "traefik"
SSC_APP_NAME = "ssc"
INGRESS_REQUIRER_APP_NAME = "alertmanager"

TRAEFIK_SOURCE_CHANNEL = "latest/edge"


def test_upgrade(juju: jubilant.Juju, traefik_charm, pytestconfig):
    """
    Refresh traefik from the latest revision on charmhub to the current
    local charm, and verify all charms are active and idle.
    """
    juju.deploy(
        "ch:traefik-k8s",
        TRAEFIK_APP_NAME,
        channel=TRAEFIK_SOURCE_CHANNEL,
        base=pytestconfig.getoption("--base"),
        config={"external_hostname": "traefik-demo.local"},
        trust=True,
    )

    juju.deploy(
        "ch:self-signed-certificates",
        SSC_APP_NAME,
        channel="1/stable",
        trust=True,
    )

    juju.deploy(
        "ch:alertmanager-k8s",
        INGRESS_REQUIRER_APP_NAME,
        channel="2/edge",
        trust=True,
    )

    juju.wait(jubilant.all_active, timeout=900)

    juju.integrate(f"{SSC_APP_NAME}:certificates", TRAEFIK_APP_NAME)
    juju.integrate(f"{INGRESS_REQUIRER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, delay=5, timeout=900)

    juju.refresh(
        TRAEFIK_APP_NAME,
        path=traefik_charm,
    )
    juju.wait(all_settled, delay=5, timeout=900)
