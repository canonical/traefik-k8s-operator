# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for traefik integration tests."""

import jubilant


def all_settled(status: jubilant.Status) -> bool:
    """Return True when all apps are active and all agents are idle."""
    return jubilant.all_active(status) and jubilant.all_agents_idle(status)

