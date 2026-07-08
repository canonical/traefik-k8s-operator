# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions for traefik integration tests."""

import base64
import datetime
import json
import logging
from pathlib import Path
from typing import List, Optional

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
        _get_with_retry(session, alertmanager_url)

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
    juju.exec("/charm/bin/pebble", "stop-checks", "liveness", unit=old_leader)
    # Run the agent stop in the background: a blocking juju exec would otherwise
    # wait for the task to complete, but the task kills the agent that reports
    # completion and can therefore get stuck until Juju times it out.
    juju.exec(
        "nohup /charm/bin/pebble stop container-agent >/dev/null 2>&1 &",
        unit=old_leader,
    )

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
    # Bring the old leader back: re-enable liveness checks and restart its container-agent.
    logger.info("Restarting container-agent and liveness checks on %s", old_leader)
    juju.exec("/charm/bin/pebble", "start-checks", "liveness", unit=old_leader)
    juju.exec("/charm/bin/pebble", "start", "container-agent", unit=old_leader)
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
    _get_with_retry(session, alertmanager_url)


def verify_https_broken_on_unit(juju: jubilant.Juju, unit_name: str, alertmanager_url: str) -> None:
    """Assert HTTPS is NOT reachable with the CA cert on a specific traefik unit."""
    unit_ip = _unit_address(juju, unit_name)
    logger.info("Expecting broken HTTPS on %s (%s) -> %s", unit_name, unit_ip, alertmanager_url)
    session = requests.Session()
    session.mount("https://", DNSResolverHTTPSAdapter(MOCK_HOSTNAME, unit_ip))
    session.verify = str(ca_cert_path)
    try:
        response = session.get(alertmanager_url, timeout=30)
        response.raise_for_status()
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        return  # expected: cert no longer trusted / endpoint down
    raise AssertionError(
        f"HTTPS unexpectedly succeeded on {unit_name}; the served certificate "
        "is still trusted after the leadership change"
    )


# --- Composite flows --------------------------------------------------------
def bring_up_certified_traefik(juju: jubilant.Juju, tmp_path: Path) -> str:
    """Integrate the mTLS + alertmanager stack, sign traefik's CSRs and verify HTTPS.

    Creates the throwaway CA (populating the module-level CA globals) and assumes
    traefik, manual-tls-certificates and alertmanager have all been deployed (the
    latter two via the ``manual_tls_app`` / ``alertmanager_app`` fixtures). Returns
    the alertmanager URL so the caller can assert it is unchanged after upgrading.
    """
    generate_ca(tmp_path)

    juju.integrate(f"{MANUAL_TLS_APP_NAME}:certificates", f"{TRAEFIK_APP_NAME}:certificates")
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)

    juju.wait(jubilant.all_agents_idle, timeout=900, delay=5, successes=5)
    sign_csrs_and_provide_cert(juju)
    juju.wait(all_settled, timeout=900)

    return verify_https_on_all_units(juju)


def bring_up_self_signed_traefik(
    juju: jubilant.Juju, tmp_path: Path, ssc_app: str = SSC_APP_NAME
) -> str:
    """Integrate self-signed-certificates + alertmanager and verify HTTPS on traefik."""
    juju.integrate(f"{ssc_app}:certificates", f"{TRAEFIK_APP_NAME}:certificates")
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)

    juju.wait(all_settled, delay=5, timeout=900)
    pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ssc_app)

    return verify_https_on_all_units(juju)


def bring_up_traefik_without_certificate_provider(juju: jubilant.Juju) -> str:
    """Integrate alertmanager only and verify plain HTTP on all traefik units."""
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, delay=5, timeout=900)
    return verify_http_on_all_units(juju)

