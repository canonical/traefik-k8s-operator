#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for TLS termination using jubilant."""

import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
import jubilant

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    health_src_overwrite,
)
from tests.integration.conftest import (
    INGRESS_REQUIRER_APP_NAME,
    TRAEFIK_APP_NAME,
    TRAEFIK_RESOURCES,
)
from tests.integration.helpers import (
    all_settled,
    any_error_after,
    get_loadbalancer_ip,
    proxied_url,
    pull_ssc_ca_certificate,
    remove_application,
)

ROOT_CA_APP = "root-ca"
MOCK_HOSTNAME = "juju.local"


def test_build_and_deploy(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP_NAME, resources=TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        f"ch:{ANY_CHARM_K8S}",
        INGRESS_REQUIRER_APP_NAME,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": health_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        trust=True,
    )

    juju.integrate(f"{INGRESS_REQUIRER_APP_NAME}:require-ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)
    endpoint = f"{proxied_url(juju, TRAEFIK_APP_NAME, INGRESS_REQUIRER_APP_NAME)}/health"
    response = httpx2.get(endpoint, timeout=30)
    response.raise_for_status()


def test_tls_termination(juju: jubilant.Juju, tmp_path: Path):
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": MOCK_HOSTNAME})
    juju.deploy("ch:self-signed-certificates", ROOT_CA_APP, channel="1/stable", trust=True)
    juju.config(ROOT_CA_APP, {"ca-common-name": "demo.ca.local"})
    juju.integrate(f"{ROOT_CA_APP}:certificates", TRAEFIK_APP_NAME)
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)

    cert_path = pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ROOT_CA_APP)
    traefik_ip = get_loadbalancer_ip(juju, TRAEFIK_APP_NAME)
    _assert_https_endpoint(juju, cert_path, traefik_ip)


def test_tls_termination_with_custom_csr_subject_attributes_without_cn(
    juju: jubilant.Juju, tmp_path: Path
):
    traefik_ip = get_loadbalancer_ip(juju, TRAEFIK_APP_NAME)

    old_certificate = _get_served_certificate(traefik_ip)

    juju.config(
        TRAEFIK_APP_NAME,
        {
            "csr-subject-atttributes": (
                "C=DE, ST=Hesse, L=Frankfurt, O=Canonical, OU=Engineering, "
                "emailAddress=ops@example.com"
            )
        },
    )
    juju.wait(all_settled, timeout=600, delay=2, successes=5)

    cert_path = pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ROOT_CA_APP)
    new_certificate = _get_served_certificate(traefik_ip)

    assert new_certificate != old_certificate, (
        "Expected a new certificate to be served after updating csr-subject-atttributes"
    )
    _assert_https_endpoint(juju, cert_path, traefik_ip)


def test_tls_termination_after_charm_upgrade(juju: jubilant.Juju, traefik_charm, tmp_path: Path):
    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)

    cert_path = pull_ssc_ca_certificate(juju, tmp_path, ssc_app=ROOT_CA_APP)
    traefik_ip = get_loadbalancer_ip(juju, TRAEFIK_APP_NAME)
    _assert_https_endpoint(juju, cert_path, traefik_ip)


def test_disintegrate(juju: jubilant.Juju):
    if ROOT_CA_APP not in juju.status().apps:
        return
    juju.remove_relation(f"{ROOT_CA_APP}:certificates", f"{TRAEFIK_APP_NAME}:certificates")
    juju.wait(all_settled, error=any_error_after(failures=5), delay=5, successes=5)


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP_NAME, timeout=60, force=False)


def _endpoint(juju: jubilant.Juju, scheme: str, netloc: str) -> str:
    base_url = proxied_url(juju, TRAEFIK_APP_NAME, INGRESS_REQUIRER_APP_NAME)
    ingress_path = f"{urlsplit(base_url).path}/health"
    return f"{scheme}://{netloc}{ingress_path}"


def _assert_https_endpoint(juju: jubilant.Juju, cert_path: Path, traefik_ip: str) -> None:
    with httpx2.Client(verify=str(cert_path), headers={"Host": MOCK_HOSTNAME}) as client:
        response = client.get(
            _endpoint(juju, "https", traefik_ip),
            timeout=30,
            extensions={"sni_hostname": MOCK_HOSTNAME},
        )
    response.raise_for_status()


def _get_served_certificate(traefik_ip: str) -> str:
    return ssl.get_server_certificate((traefik_ip, 443))
