# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for traefik integration tests."""

import logging
import socket

import jubilant

logger = logging.getLogger(__name__)


def all_settled(status: jubilant.Status) -> bool:
    """Return True when all apps are active and all agents are idle."""
    return jubilant.all_active(status) and jubilant.all_agents_idle(status)


def assert_can_connect(ip: str, port: int) -> None:
    """Assert that a TCP connection can be established to ip:port."""
    target = (ip, int(port))
    logger.info("Attempting to connect to %s", target)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(target)
    except Exception as exc:
        raise AssertionError(f"{ip}:{port} is down/unreachable") from exc
    finally:
        s.close()

