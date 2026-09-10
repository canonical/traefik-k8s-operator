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
from typing import Any, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx2
import jubilant
from charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateRequestAttributes,
    CertificateSigningRequest,
    PrivateKey,
)
from constants import (
    INGRESS_REQUIRER_APP_NAME,
    MANUAL_TLS_APP_NAME,
    MOCK_HOSTNAME,
    SSC_APP_NAME,
    TRAEFIK_APP_NAME,
)
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_delay,
    wait_fixed,
)
from tenacity.stop import stop_base
from tenacity.wait import wait_base

logger = logging.getLogger(__name__)

ca_key: Optional[PrivateKey] = None
ca_cert: Optional[Certificate] = None
ca_cert_path: Optional[Path] = None
signed_certificates: List[str] = []


def all_settled(status: jubilant.Status, *apps: str) -> bool:
    """Return True when all apps are active and all agents are idle."""
    return jubilant.all_active(status, *apps) and jubilant.all_agents_idle(status)


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
                "-n",
                model,
                "get",
                f"service/{service_name}",
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
        error=jubilant.any_error,
        timeout=timeout,
    )


def rpc(juju: jubilant.Juju, unit: str, method: str, **kwargs: Any) -> Any:
    """Call an any-charm tester's ``rpc`` action and return the decoded JSON result.

    Args:
        juju: The Juju instance.
        unit: The any-charm tester unit to run the action against (e.g. "ipu-tester/0").
        method: The name of the method to call on the tester's AnyCharm instance.
        **kwargs: Extra keyword arguments forwarded to the tester method, JSON-encoded.

    Returns:
        The JSON-decoded return value of the remote method call.
    """
    params = {"method": method}
    if kwargs:
        params["kwargs"] = json.dumps(kwargs)
    raw = juju.run(unit, "rpc", params=params).results["return"]
    return json.loads(raw)


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


def fetch_with_retry(
    url: str,
    expected_status: Optional[int] = None,
    *,
    client: Optional[httpx2.Client] = None,
    auth: Optional[Tuple[str, str]] = None,
    raise_for_status: bool = False,
    timeout: float = 10,
    stop: stop_base = stop_after_delay(150),
    wait: wait_base = wait_fixed(5),
    **kwargs: Any,
) -> httpx2.Response:
    """Fetch a URL with retries.

    Always retries on request errors, plus on a status mismatch if *expected_status* is
    given. Set *raise_for_status* to fail on a bad final response instead of retrying it
    forever (don't combine with a non-2xx *expected_status*). Pass an existing *client* to
    reuse its TLS/header/etc. config (needed e.g. for the ``extensions`` kwarg); otherwise
    each attempt is a one-off request.
    """
    retry_condition = retry_if_exception_type(httpx2.RequestError)
    if expected_status is not None:
        retry_condition = (
            retry_if_result(lambda r: r.status_code != expected_status) | retry_condition
        )

    @retry(
        stop=stop,
        wait=wait,
        retry=retry_condition,
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.DEBUG),
    )
    def _fetch() -> httpx2.Response:
        if client is not None:
            return client.get(url, timeout=timeout, **kwargs)
        return httpx2.get(
            url, auth=auth, verify=False, follow_redirects=True, timeout=timeout, **kwargs
        )

    response = _fetch()
    if raise_for_status:
        response.raise_for_status()
    return response


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
def get_outstanding_csrs(juju: jubilant.Juju, mtls_app: str = MANUAL_TLS_APP_NAME) -> List[dict]:
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
    """Sign each outstanding CSR and provide the certificate via the action.

    Populates the module-level ``signed_certificates`` list with the PEM strings.
    """
    global signed_certificates
    assert ca_key is not None and ca_cert is not None, (
        "CA not initialised; call generate_ca()/bring_up_certified_traefik() first"
    )
    ca_pem = str(ca_cert)
    signed_certificates = []
    for request in outstanding_csrs:
        csr_pem = request["csr"]
        certificate_pem = sign_csr(ca_key, ca_cert, csr_pem)
        signed_certificates.append(certificate_pem)
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


def provide_existing_certificate(
    juju: jubilant.Juju,
    outstanding_csrs: List[dict],
) -> None:
    """Provide the previously signed certificate for each outstanding CSR.

    Uses the module-level ``signed_certificates`` (populated by
    ``provide_certificate``) to re-provide an old certificate for new CSRs
    generated with the same private key.
    """
    assert signed_certificates, (
        "No signed certificates available; call provide_certificate() first"
    )
    certificate_pem = signed_certificates[0]
    assert ca_cert is not None, (
        "CA not initialised; call generate_ca()/bring_up_certified_traefik() first"
    )
    ca_pem = str(ca_cert)
    for request in outstanding_csrs:
        csr_pem = request["csr"]
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
            "Provided existing certificate for relation %s / %s",
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
def proxied_ingress_url(juju: jubilant.Juju, traefik_app_name: str, endpoint_key: str) -> str:
    """Return endpoint_key's URL (no trailing slash), routed through traefik_app_name's gateway."""
    result = juju.run(f"{traefik_app_name}/leader", "show-proxied-endpoints")
    endpoints = json.loads(result.results["proxied-endpoints"])
    return endpoints[endpoint_key]["url"].rstrip("/")


def external_ingress_url(juju: jubilant.Juju, traefik_app_name: str, endpoint_key: str) -> str:
    """Return endpoint_key's URL (no trailing slash), honoring any upstream-ingress chaining."""
    result = juju.run(f"{traefik_app_name}/leader", "show-external-endpoints")
    endpoints = json.loads(result.results["external-endpoints"])
    return endpoints[endpoint_key]["url"].rstrip("/")


def _url_for_unit(url: str, unit_ip: str) -> str:
    """Rewrite *url* to target *unit_ip* directly, preserving the path.

    The proxied URL uses the external hostname (``traefik-demo.local``), which is
    not resolvable via DNS in the test runner. For plain HTTP we route the request
    to the unit IP instead and rely on the ``Host`` header for traefik routing.
    """
    parts = urlsplit(url)
    netloc = f"{unit_ip}:{parts.port}" if parts.port else unit_ip
    return urlunsplit(parts._replace(netloc=netloc))


def verify_https_through_all_traefik_units(
    juju: jubilant.Juju,
    expected_url: Optional[str] = None,
) -> str:
    """Assert HTTPS is reachable through every traefik unit with the CA cert.

    Returns the ingress URL that was verified so callers can assert it is
    unchanged across an upgrade.
    """
    base_url = proxied_ingress_url(juju, TRAEFIK_APP_NAME, INGRESS_REQUIRER_APP_NAME)
    ingress_url = f"{base_url}/health"
    if expected_url is not None:
        assert ingress_url == expected_url, (
            f"Proxied URL changed across upgrade: {expected_url!r} -> {ingress_url!r}"
        )

    status = juju.status()
    units = status.apps[TRAEFIK_APP_NAME].units

    with httpx2.Client(verify=str(ca_cert_path), headers={"Host": MOCK_HOSTNAME}) as client:
        for unit_name, unit_status in units.items():
            unit_ip = unit_status.address
            logger.info("Verifying HTTPS on %s (%s) -> %s", unit_name, unit_ip, ingress_url)
            fetch_with_retry(
                _url_for_unit(ingress_url, unit_ip),
                client=client,
                raise_for_status=True,
                extensions={"sni_hostname": MOCK_HOSTNAME},
            )

    return ingress_url


def verify_http_through_all_traefik_units(
    juju: jubilant.Juju,
    expected_url: Optional[str] = None,
) -> str:
    """Assert HTTP is reachable through every traefik unit.

    Returns the ingress URL that was verified so callers can assert it is
    unchanged across an upgrade.
    """
    base_url = proxied_ingress_url(juju, TRAEFIK_APP_NAME, INGRESS_REQUIRER_APP_NAME)
    ingress_url = f"{base_url}/health"
    assert ingress_url.startswith("http://"), (
        f"expected plain HTTP proxied URL without a certificate provider, got {ingress_url!r}"
    )
    if expected_url is not None:
        assert ingress_url == expected_url, (
            f"Proxied URL changed across upgrade: {expected_url!r} -> {ingress_url!r}"
        )

    status = juju.status()
    units = status.apps[TRAEFIK_APP_NAME].units

    with httpx2.Client(headers={"Host": MOCK_HOSTNAME}) as client:
        for unit_name, unit_status in units.items():
            unit_ip = unit_status.address
            logger.info("Verifying HTTP on %s (%s) -> %s", unit_name, unit_ip, ingress_url)
            fetch_with_retry(
                _url_for_unit(ingress_url, unit_ip),
                client=client,
                raise_for_status=True,
            )

    return ingress_url


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
    logger.info(
        "Stopping the container-agent on leader %s to force a leadership change", old_leader
    )
    # stop-checks liveness prevents pebble from restarting the agent as unhealthy.
    juju.ssh(old_leader, "/charm/bin/pebble", "stop-checks", "liveness", container="charm")
    juju.ssh(old_leader, "/charm/bin/pebble", "stop", "container-agent", container="charm")

    def _reelected(status: jubilant.Status) -> bool:
        units = status.apps[app].units
        leaders = [name for name, unit in units.items() if unit.leader]
        return len(leaders) == 1 and leaders[0] != old_leader

    try:
        # No error= here: the old leader's agent is deliberately stopped above, so it
        # may legitimately report "lost"/error while we wait for a new leader to be elected.
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


def verify_https_through_unit(juju: jubilant.Juju, unit_name: str, ingress_url: str) -> None:
    """Assert HTTPS returns 200 with the CA cert on a specific traefik unit."""
    unit_ip = _unit_address(juju, unit_name)
    logger.info("Verifying HTTPS on %s (%s) -> %s", unit_name, unit_ip, ingress_url)
    with httpx2.Client(verify=str(ca_cert_path), headers={"Host": MOCK_HOSTNAME}) as client:
        response = client.get(
            _url_for_unit(ingress_url, unit_ip),
            timeout=30,
            extensions={"sni_hostname": MOCK_HOSTNAME},
        )
    response.raise_for_status()


# --- Composite flows --------------------------------------------------------
def bring_up_certified_traefik(juju: jubilant.Juju, tmp_path: Path) -> None:
    """Integrate the mTLS + ingress stack and sign traefik's CSRs.

    Creates the throwaway CA (populating the module-level CA globals) and assumes
    traefik, manual-tls-certificates and the ingress requirer have all been deployed (the
    latter two via the ``mtls_app`` / ``ingress_app`` fixtures).
    """
    generate_ca(tmp_path)

    juju.integrate(f"{INGRESS_REQUIRER_APP_NAME}:require-ingress", TRAEFIK_APP_NAME)
    juju.integrate(f"{MANUAL_TLS_APP_NAME}:certificates", f"{TRAEFIK_APP_NAME}:certificates")

    juju.wait(
        lambda status: all_settled(status, MANUAL_TLS_APP_NAME),
        error=jubilant.any_error,
        delay=5,
        timeout=900,
        successes=5,
    )
    sign_csrs_and_provide_cert(juju)


def bring_up_self_signed_traefik(
    juju: jubilant.Juju, tmp_path: Path, ssc_app: str = SSC_APP_NAME
) -> None:
    """Integrate self-signed-certificates + the ingress requirer and pull the CA cert."""
    juju.integrate(f"{INGRESS_REQUIRER_APP_NAME}:require-ingress", TRAEFIK_APP_NAME)
    juju.integrate(f"{ssc_app}:certificates", f"{TRAEFIK_APP_NAME}:certificates")

    juju.wait(
        lambda status: all_settled(status, ssc_app),
        error=jubilant.any_error,
        delay=5,
        timeout=900,
        successes=5,
    )
    pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ssc_app)


def bring_up_traefik_without_certificate_provider(juju: jubilant.Juju) -> None:
    """Integrate the ingress requirer."""
    juju.integrate(f"{INGRESS_REQUIRER_APP_NAME}:require-ingress", TRAEFIK_APP_NAME)
