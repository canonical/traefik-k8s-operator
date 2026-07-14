# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for traefik integration tests."""

import base64
import datetime
import json
import logging
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlsplit, urlunsplit

import jubilant
import requests
from charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateRequestAttributes,
    CertificateSigningRequest,
    PrivateKey,
)
from constants import (
    ALERTMANAGER_APP_NAME,
    MANUAL_TLS_APP_NAME,
    MOCK_HOSTNAME,
    SSC_APP_NAME,
    TRAEFIK_APP_NAME,
)
from dns_adapter import DNSResolverHTTPSAdapter
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_delay,
    wait_fixed,
)

logger = logging.getLogger(__name__)

ca_key: Optional[PrivateKey] = None
ca_cert: Optional[Certificate] = None
ca_cert_path: Optional[Path] = None


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


def get_relation_info(
    juju: jubilant.Juju,
    remote_unit: str,
    remote_endpoint: str,
    local_unit: str,
    local_endpoint: str,
) -> dict[str, Any]:
    """Return relation data as seen from remote_unit's perspective.

    Args:
        juju: The Juju instance.
        remote_unit: The unit whose view of the relation we query (e.g. "traefik/0").
        remote_endpoint: The endpoint name on the remote side.
        local_unit: The unit we want to find in the related-units dict.
        local_endpoint: The endpoint name on the local (requirer) side.

    Returns:
        The matching relation-info dict from ``juju show-unit``.

    Raises:
        AssertionError: If no matching relation is found.
    """
    data = json.loads(juju.cli("show-unit", remote_unit, "--format", "json"))[remote_unit]
    for relation in data.get("relation-info", []):
        if (
            relation.get("endpoint") == remote_endpoint
            and relation.get("related-endpoint") == local_endpoint
            and local_unit in relation.get("related-units", {})
        ):
            return relation
    raise AssertionError(
        f"No relation data for {remote_unit}:{remote_endpoint} and "
        f"{local_unit}:{local_endpoint}"
    )


def wait_for_tcp_echo(host: str, port: int, payload: bytes = b"Hello, world") -> None:
    """Connect to host:port, send payload, and assert the echo matches."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                sock.sendall(payload)
                response = sock.recv(1024)
            assert response == payload
            return
        except OSError:
            time.sleep(5)
    raise AssertionError(f"Timed out waiting for TCP echo on {host}:{port}")


def fetch_with_retry(url: str, expected_status: int = 200) -> requests.Response:
    """Fetch a URL with retries until the expected status is returned."""
    @retry(
        stop=stop_after_delay(150),
        wait=wait_fixed(5),
        retry=(
            retry_if_result(lambda r: r.status_code != expected_status)
            | retry_if_exception_type(requests.exceptions.RequestException)
        ),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.DEBUG),
    )
    def _fetch() -> requests.Response:
        return requests.get(url, verify=False, allow_redirects=True, timeout=10)

    return _fetch()


def assert_traefik_revision(juju: jubilant.Juju, expected_revision: int) -> None:
    """Assert traefik's deployed charm revision matches *expected_revision*.

    The locally built charm reports revision ``0``; a charm refreshed to a
    specific Charmhub revision reports that revision.
    """
    actual_revision = juju.status().apps[TRAEFIK_APP_NAME].charm_rev
    assert actual_revision == expected_revision, (
        f"Expected traefik at revision {expected_revision}, but found {actual_revision}"
    )


def generate_ca(tmp_path: Path) -> None:
    """Create a self-signed CA and write its certificate to disk.

    Populates the module-level ``ca_key``, ``ca_cert`` and ``ca_cert_path`` so
    the signing and verification helpers can reuse the same CA.
    """
    global ca_key, ca_cert, ca_cert_path
    ca_key = PrivateKey.generate()
    attributes = CertificateRequestAttributes(
        common_name="traefik-itest-ca",
        add_unique_id_to_subject_name=False,
    )
    ca_cert = Certificate.generate_self_signed_ca(
        attributes, ca_key, datetime.timedelta(days=3650)
    )
    ca_cert_path = tmp_path / "ca.cert"
    ca_cert_path.write_text(str(ca_cert))


def sign_csr(ca_key: PrivateKey, ca_cert: Certificate, csr_pem: str) -> str:
    """Sign a PEM CSR with the CA and return the certificate PEM."""
    csr = CertificateSigningRequest(raw=csr_pem)
    cert = Certificate.generate(csr, ca_cert, ca_key, datetime.timedelta(days=365))
    return str(cert)


# --- manual-tls-certificates actions ---------------------------------------
def get_outstanding_csrs(
    juju: jubilant.Juju, mtls_app: str = MANUAL_TLS_APP_NAME
) -> List[dict]:
    """Return the list of outstanding certificate requests on the mTLS charm."""
    task = juju.run(f"{mtls_app}/leader", "get-outstanding-certificate-requests")
    raw = task.results.get("result", [])
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else []
    return list(raw)


def provide_certificate(
    juju: jubilant.Juju,
    outstanding_csrs: List[dict],
) -> None:
    assert ca_key is not None and ca_cert is not None, (
        "CA not initialised; call generate_ca()/bring_up_certified_traefik() first"
    )
    ca_pem = str(ca_cert)
    for request in outstanding_csrs:
        csr_pem = request["csr"]
        certificate_pem = sign_csr(ca_key, ca_cert, csr_pem)
        juju.run(
            f"{MANUAL_TLS_APP_NAME}/leader",
            "provide-certificate",
            {
                "certificate": base64.b64encode(certificate_pem.encode()).decode(),
                "ca-certificate": base64.b64encode(ca_pem.encode()).decode(),
                "certificate-signing-request": base64.b64encode(csr_pem.encode()).decode(),
            },
        )
        logger.info(
            "Provided certificate for relation %s / %s",
            request.get("relation_id"),
            request.get("unit_name") or request.get("application_name"),
        )


def sign_csrs_and_provide_cert(
    juju: jubilant.Juju, mtls_app: str = MANUAL_TLS_APP_NAME, timeout: int = 300
) -> None:
    """Wait for traefik to post its CSR(s), then sign and provide them.

    After a (re)integration or a refresh, traefik regenerates/re-requests its
    certificate, but the CSR can take a moment to reach manual-tls-certificates.
    ``all_agents_idle`` may briefly be true in that gap, so a single
    ``get_outstanding_csrs`` snapshot can come back empty and we would sign
    nothing (leaving traefik on its self-signed fallback). Poll until at least
    one CSR is outstanding before signing.
    """

    @retry(
        retry=retry_if_result(lambda csrs: not csrs),
        stop=stop_after_delay(timeout),
        wait=wait_fixed(10),
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True,
    )
    def _wait_for_csrs() -> List[dict]:
        return get_outstanding_csrs(juju, mtls_app)

    outstanding_csrs = _wait_for_csrs()
    provide_certificate(juju, outstanding_csrs)


def pull_ssc_ca_certificate(
    juju: jubilant.Juju, tmp_path: Path, ssc_app: str = SSC_APP_NAME
) -> Path:
    """Pull the self-signed provider CA certificate and store it for HTTPS verification."""
    global ca_cert_path
    result = juju.run(f"{ssc_app}/0", "get-ca-certificate")
    ca_pem = result.results["ca-certificate"]
    ca_cert_path = tmp_path / "ca.cert"
    ca_cert_path.write_text(ca_pem)
    logger.info("Pulled CA cert (%d bytes) from %s to %s", len(ca_pem), ssc_app, ca_cert_path)
    return ca_cert_path


# --- Verification -----------------------------------------------------------
def _alertmanager_url(juju: jubilant.Juju) -> str:
    # show-proxied-endpoints only returns the full endpoint map on the leader.
    result = juju.run(f"{TRAEFIK_APP_NAME}/leader", "show-proxied-endpoints")
    endpoints = json.loads(result.results["proxied-endpoints"])
    return endpoints[ALERTMANAGER_APP_NAME]["url"]


@retry(
    retry=retry_if_exception_type(requests.exceptions.ConnectionError),
    stop=stop_after_delay(120),
    wait=wait_fixed(5),
    before_sleep=before_sleep_log(logger, logging.INFO),
    reraise=True,
)
def _get_with_retry(session: requests.Session, url: str) -> None:
    """GET *url*, retrying on connection errors for up to two minutes.

    Juju can report a unit ``active/idle`` a beat before the traefik workload has
    reloaded and started listening on :443 with the freshly-signed certificate, so
    the first request to a just-upgraded unit may be refused. Retry that transient
    window instead of failing the whole test.
    """
    response = session.get(url, timeout=30)
    response.raise_for_status()


def _url_for_unit(url: str, unit_ip: str) -> str:
    """Rewrite *url* to target *unit_ip* directly, preserving the path.

    The proxied URL uses the external hostname (``traefik-demo.local``), which is
    not resolvable via DNS in the test runner. For plain HTTP we route the request
    to the unit IP instead and rely on the ``Host`` header for traefik routing.
    """
    parts = urlsplit(url)
    netloc = f"{unit_ip}:{parts.port}" if parts.port else unit_ip
    return urlunsplit(parts._replace(netloc=netloc))


def verify_https_on_all_units(
    juju: jubilant.Juju,
    expected_url: Optional[str] = None,
) -> str:
    """Assert HTTPS is reachable through every traefik unit with the CA cert.

    Returns the alertmanager URL that was verified so callers can assert it is
    unchanged across an upgrade.
    """
    alertmanager_url = _alertmanager_url(juju)
    if expected_url is not None:
        assert alertmanager_url == expected_url, (
            f"Proxied URL changed across upgrade: {expected_url!r} -> {alertmanager_url!r}"
        )

    status = juju.status()
    units = status.apps[TRAEFIK_APP_NAME].units

    for unit_name, unit_status in units.items():
        unit_ip = unit_status.address
        logger.info("Verifying HTTPS on %s (%s) -> %s", unit_name, unit_ip, alertmanager_url)
        session = requests.Session()
        session.mount("https://", DNSResolverHTTPSAdapter(MOCK_HOSTNAME, unit_ip))
        session.verify = str(ca_cert_path)
        _get_with_retry(session, alertmanager_url)

    return alertmanager_url


def verify_http_on_all_units(
    juju: jubilant.Juju,
    expected_url: Optional[str] = None,
) -> str:
    """Assert HTTP is reachable through every traefik unit.

    Returns the alertmanager URL that was verified so callers can assert it is
    unchanged across an upgrade.
    """
    alertmanager_url = _alertmanager_url(juju)
    assert alertmanager_url.startswith("http://"), (
        "expected plain HTTP proxied URL without a certificate provider, got "
        f"{alertmanager_url!r}"
    )
    if expected_url is not None:
        assert alertmanager_url == expected_url, (
            f"Proxied URL changed across upgrade: {expected_url!r} -> {alertmanager_url!r}"
        )

    status = juju.status()
    units = status.apps[TRAEFIK_APP_NAME].units

    for unit_name, unit_status in units.items():
        unit_ip = unit_status.address
        logger.info("Verifying HTTP on %s (%s) -> %s", unit_name, unit_ip, alertmanager_url)
        session = requests.Session()
        session.headers["Host"] = MOCK_HOSTNAME
        _get_with_retry(session, _url_for_unit(alertmanager_url, unit_ip))

    return alertmanager_url


def leader_unit_name(juju: jubilant.Juju, app: str = TRAEFIK_APP_NAME) -> str:
    """Return the name of the current leader unit of *app*."""
    for name, unit in juju.status().apps[app].units.items():
        if unit.leader:
            return name
    raise AssertionError(f"no leader found for {app!r}")


def _unit_address(juju: jubilant.Juju, unit_name: str, app: str = TRAEFIK_APP_NAME) -> str:
    """Return unit IP address for *unit_name* in *app* or raise if missing."""
    units = juju.status().apps[app].units
    assert unit_name in units, f"{unit_name} not found in {app} units"
    return units[unit_name].address


def force_leader_change(juju: jubilant.Juju, app: str = TRAEFIK_APP_NAME) -> str:
    """Force a leadership change by stopping the current leader's unit agent."""
    old_leader = leader_unit_name(juju, app)
    logger.info("Stopping the container-agent on leader %s to force a leadership change", old_leader)
    # stop-checks liveness prevents pebble from restarting the agent as unhealthy.
    juju.ssh(old_leader, "/charm/bin/pebble", "stop-checks", "liveness", container="charm")
    juju.ssh(old_leader, "/charm/bin/pebble", "stop", "container-agent", container="charm")

    def _reelected(status: jubilant.Status) -> bool:
        units = status.apps[app].units
        leaders = [name for name, unit in units.items() if unit.leader]
        return len(leaders) == 1 and leaders[0] != old_leader

    try:
        juju.wait(_reelected, timeout=120, delay=5)
    except TimeoutError as exc:
        raise AssertionError(
            f"leadership did not move away from {old_leader} within 2 minutes"
        ) from exc
    new_leader = leader_unit_name(juju, app)
    logger.info("Leadership moved from %s to %s", old_leader, new_leader)
    # Trigger a hook on the new leader so it can react to the leadership change.
    # Traefik currently does not observe leader-elected hook.
    juju.config(app, {"loadbalancer_annotations": " "})
    # Bring the old leader back: re-enable liveness checks and restart its
    # container-agent.
    logger.info("Restarting container-agent and liveness checks on %s", old_leader)
    juju.ssh(old_leader, "/charm/bin/pebble", "start", "container-agent", container="charm")
    juju.ssh(old_leader, "/charm/bin/pebble", "start-checks", "liveness", container="charm")
    return new_leader


def verify_https_on_unit(juju: jubilant.Juju, unit_name: str, alertmanager_url: str) -> None:
    """Assert HTTPS returns 200 with the CA cert on a specific traefik unit."""
    unit_ip = _unit_address(juju, unit_name)
    logger.info("Verifying HTTPS on %s (%s) -> %s", unit_name, unit_ip, alertmanager_url)
    session = requests.Session()
    session.mount("https://", DNSResolverHTTPSAdapter(MOCK_HOSTNAME, unit_ip))
    session.verify = str(ca_cert_path)
    response = session.get(alertmanager_url, timeout=30)
    response.raise_for_status()


def verify_http_on_unit(juju: jubilant.Juju, unit_name: str, alertmanager_url: str) -> None:
    """Assert HTTP returns 200 on a specific traefik unit."""
    assert alertmanager_url.startswith("http://"), (
        "expected plain HTTP proxied URL without a certificate provider, got "
        f"{alertmanager_url!r}"
    )
    unit_ip = _unit_address(juju, unit_name)
    logger.info("Verifying HTTP on %s (%s) -> %s", unit_name, unit_ip, alertmanager_url)
    session = requests.Session()
    session.headers["Host"] = MOCK_HOSTNAME
    _get_with_retry(session, _url_for_unit(alertmanager_url, unit_ip))


# --- Composite flows --------------------------------------------------------
def bring_up_certified_traefik(juju: jubilant.Juju, tmp_path: Path) -> str:
    """Integrate the mTLS + alertmanager stack, sign traefik's CSRs and verify HTTPS.

    Creates the throwaway CA (populating the module-level CA globals) and assumes
    traefik, manual-tls-certificates and alertmanager have all been deployed (the
    latter two via the ``mtls_app`` / ``alertmanager_app`` fixtures). Returns
    the alertmanager URL so the caller can assert it is unchanged after upgrading.
    """
    generate_ca(tmp_path)

    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, timeout=900, delay=5, successes=5)
    juju.integrate(f"{MANUAL_TLS_APP_NAME}:certificates", f"{TRAEFIK_APP_NAME}:certificates")

    juju.wait(jubilant.all_agents_idle, timeout=900, delay=5, successes=5)
    sign_csrs_and_provide_cert(juju)
    juju.wait(all_settled, timeout=900)

    return verify_https_on_all_units(juju)


def bring_up_self_signed_traefik(
    juju: jubilant.Juju, tmp_path: Path, ssc_app: str = SSC_APP_NAME
) -> str:
    """Integrate self-signed-certificates + alertmanager and verify HTTPS on traefik."""
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, timeout=900, delay=5, successes=5)
    juju.integrate(f"{ssc_app}:certificates", f"{TRAEFIK_APP_NAME}:certificates")

    juju.wait(all_settled, delay=5, timeout=900)
    pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ssc_app)

    return verify_https_on_all_units(juju)


def bring_up_traefik_without_certificate_provider(juju: jubilant.Juju) -> str:
    """Integrate alertmanager only and verify plain HTTP on all traefik units."""
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, delay=5, timeout=900)
    return verify_http_on_all_units(juju)

