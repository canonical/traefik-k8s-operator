# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test the charm reports WaitingStatus when the LB Service has no external IP."""

import jubilant

from tests.integration.helpers import all_settled

# An IP outside the MetalLB pool (10.43.45.0/28) so the LB stays pending.
UNREACHABLE_IP = "192.168.255.255"


def test_waiting_when_lb_pending(juju: jubilant.Juju, traefik_app):
    """When LB annotations request an unreachable IP, charm goes to waiting."""
    juju.config(
        traefik_app,
        {"loadbalancer_annotations": f"metallb.io/loadBalancerIPs={UNREACHABLE_IP}"},
    )

    juju.wait(
        lambda status: jubilant.all_waiting(status, traefik_app),
        error=jubilant.any_error,
        timeout=300,
        delay=5,
    )

    status = juju.status()
    unit_name = next(iter(status.apps[traefik_app].units))
    unit_status = status.apps[traefik_app].units[unit_name].workload_status
    assert unit_status.message == "Load balancer service has not yet obtained an external address.", (
        f"Unexpected waiting message: {unit_status.message}"
    )


def test_recovery_after_annotations_cleared(juju: jubilant.Juju, traefik_app):
    """Charm recovers to active once the LB gets an IP again."""
    # Clear the bad annotations so MetalLB assigns an IP from its pool.
    juju.config(traefik_app, {"loadbalancer_annotations": ""})
    juju.wait(all_settled, error=jubilant.any_error, delay=5, successes=5)

    status = juju.status()
    app_status = status.apps[traefik_app].app_status
    assert app_status.current == "active", (
        f"Expected recovery to active, got {app_status.current}: {app_status.message}"
    )
