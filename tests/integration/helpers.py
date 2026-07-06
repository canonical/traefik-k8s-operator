# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for traefik integration tests."""

import logging
import socket
import subprocess
from typing import Optional

import jubilant

logger = logging.getLogger(__name__)


def all_settled(status: jubilant.Status) -> bool:
    """Return True when all apps are active and all agents are idle."""
    return jubilant.all_active(status) and jubilant.all_agents_idle(status)


def get_k8s_service_address(model: str, service_name: str) -> Optional[str]:
    """Get the address of a LoadBalancer Kubernetes service using kubectl.

    Args:
        model: Juju model name (used as the Kubernetes namespace).
        service_name: The name of the Kubernetes service.

    Returns:
        The LoadBalancer IP as a string, or None if not found.
    """
    try:
        result = subprocess.run(
            [
                "kubectl",
                "-n", model,
                "get", f"service/{service_name}",
                "-o=jsonpath={.status.loadBalancer.ingress[0].ip}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except Exception as e:
        logger.error("Error retrieving service address: %s", e, exc_info=True)
        return None


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

