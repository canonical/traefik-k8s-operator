# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test for the get-loadbalancer-ip action."""

import jubilant

from tests.integration.helpers import get_loadbalancer_ip


def test_get_loadbalancer_ip_action(juju: jubilant.Juju, traefik_app):
    """The get-loadbalancer-ip action returns a non-empty IP."""
    ip = get_loadbalancer_ip(juju, traefik_app)
    assert ip, "Expected a non-empty loadbalancer IP"
