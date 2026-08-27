# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test for the get-loadbalancer-ip action."""

import jubilant


def test_get_loadbalancer_ip_action(juju: jubilant.Juju, traefik_app):
    """The get-loadbalancer-ip action returns a non-empty IP."""
    result = juju.run(f"{traefik_app}/0", "get-loadbalancer-ip", params={"timeout": 60})
    assert "loadbalancer-ip" in result.results
    ip = result.results["loadbalancer-ip"]
    assert ip, "Expected a non-empty loadbalancer IP"
