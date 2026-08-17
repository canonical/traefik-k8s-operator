#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test: charm reports WaitingStatus when LB has no external IP.

Regression test for https://github.com/canonical/traefik-k8s-operator/issues/759.
When the LoadBalancer Service is pending (no external IP assigned), the charm must
report WaitingStatus regardless of whether external_hostname is configured.
"""

import logging
from pathlib import Path

import jubilant
import yaml

from tests.integration.helpers import all_settled

logger = logging.getLogger(__name__)

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}

TRAEFIK_APP = "traefik-k8s"

# An IP outside the MetalLB pool (10.43.45.0/28) so the LB stays pending.
UNREACHABLE_IP = "192.168.255.255"


def test_deployment(juju: jubilant.Juju, traefik_charm):
    """Deploy traefik with external_hostname set."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP,
        resources=_TRAEFIK_RESOURCES,
        config={"external_hostname": "traefik.example.com"},
        trust=True,
    )
    juju.wait(all_settled, timeout=600, delay=5, successes=5)


def test_active_with_lb_ip(juju: jubilant.Juju):
    """Verify charm is active when LB has an IP."""
    status = juju.status()
    app_status = status.apps[TRAEFIK_APP].app_status
    assert app_status.current == "active", (
        f"Expected active, got {app_status.current}: {app_status.message}"
    )


def test_waiting_when_lb_pending(juju: jubilant.Juju):
    """When LB annotations request an unreachable IP, charm goes to waiting.

    Regression test for GH#759: previously the charm reported active/idle even
    though the LB Service had no external IP, because external_hostname masked
    the missing LB address.
    """
    # Request an IP outside MetalLB's pool so it can't be assigned.
    juju.config(
        TRAEFIK_APP,
        {"loadbalancer_annotations": f"metallb.io/loadBalancerIPs={UNREACHABLE_IP}"},
    )

    # Charm should transition to waiting (LB has no IP).
    juju.wait(
        lambda status: status.apps[TRAEFIK_APP].app_status.current == "waiting",
        timeout=300,
        delay=5,
    )

    status = juju.status()
    unit_name = next(iter(status.apps[TRAEFIK_APP].units))
    unit_status = status.apps[TRAEFIK_APP].units[unit_name].workload_status
    assert "external address" in unit_status.message.lower(), (
        f"Unexpected waiting message: {unit_status.message}"
    )


def test_recovery_after_annotations_cleared(juju: jubilant.Juju):
    """Charm recovers to active once the LB gets an IP again."""
    # Clear the bad annotations so MetalLB assigns an IP from its pool.
    juju.config(TRAEFIK_APP, {"loadbalancer_annotations": ""})
    juju.wait(all_settled, timeout=600, delay=5, successes=5)

    status = juju.status()
    app_status = status.apps[TRAEFIK_APP].app_status
    assert app_status.current == "active", (
        f"Expected recovery to active, got {app_status.current}: {app_status.message}"
    )
