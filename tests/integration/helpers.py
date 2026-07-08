# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for traefik integration tests."""

import logging
import socket
import subprocess
import time
from typing import Optional

import jubilant
import requests

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


def delete_k8s_service(model: str, service_name: str) -> None:
    """Delete a Kubernetes service in the model namespace."""
    result = subprocess.run(
        ["kubectl", "-n", model, "delete", f"service/{service_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        logger.warning("Failed deleting service %s: %s", service_name, result.stderr.strip())


def remove_application(
    juju: jubilant.Juju,
    *app_names: str,
    timeout: int = 300,
    destroy_storage: bool = True,
    force: bool = True,
) -> None:
    """Remove applications if present and wait until Juju no longer reports them."""
    existing_apps = [app_name for app_name in app_names if app_name in juju.status().apps]
    if not existing_apps:
        return

    juju.remove_application(
        *existing_apps,
        destroy_storage=destroy_storage,
        force=force,
    )
    juju.wait(
        lambda status: all(app_name not in status.apps for app_name in existing_apps),
        timeout=timeout,
    )


def fetch_with_retry(url: str, expected_status: int = 200, retries: int = 30, delay: float = 5.0) -> requests.Response:
    """Fetch a URL with retries until the expected status is returned."""
    last_exc: Optional[Exception] = None
    for _ in range(retries):
        try:
            response = requests.get(url, verify=False, allow_redirects=True, timeout=10)
            if response.status_code == expected_status:
                return response
        except Exception as exc:
            last_exc = exc
        time.sleep(delay)
    if last_exc:
        raise AssertionError(f"Failed to reach {url} after {retries} retries") from last_exc
    raise AssertionError(
        f"Expected status {expected_status} from {url} after {retries} retries"
    )

