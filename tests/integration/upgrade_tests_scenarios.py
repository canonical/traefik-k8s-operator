# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade-scenario orchestrators for traefik upgrade integration tests.

Each ``run_*_upgrade_scenario`` function encapsulates the deploy -> verify ->
refresh -> verify body shared by a pair of revision-pinned upgrade test files
(``*_from_280.py`` / ``*_from_298.py``), so those files can stay thin wrappers
that only supply their own ``SOURCE_REVISION``.

This module intentionally contains no helper functions of its own -- it only
orchestrates calls into the shared helpers in ``helpers.py``.
"""

from pathlib import Path

import jubilant
from constants import (
    MOCK_HOSTNAME,
    NUM_TRAEFIK_UNITS,
    SOURCE_CHANNEL,
    TRAEFIK_APP_NAME,
    TRAEFIK_CHARM,
)
from helpers import (
    all_settled,
    assert_traefik_revision,
    bring_up_certified_traefik,
    bring_up_self_signed_traefik,
    bring_up_traefik_without_certificate_provider,
    get_outstanding_csrs,
    verify_http_through_all_traefik_units,
    verify_https_through_all_traefik_units,
)


def run_no_tls_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    source_revision: int,
) -> None:
    """Deploy traefik at *source_revision* with no cert provider, then upgrade it.

    Verifies the ingress URL stays reachable over HTTP on every unit both before
    and after refreshing to the locally built charm.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    bring_up_traefik_without_certificate_provider(juju)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    url = verify_http_through_all_traefik_units(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_http_through_all_traefik_units(juju, expected_url=url)


def run_ssc_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy traefik at *source_revision* with self-signed certs, then upgrade it.

    Verifies HTTPS stays reachable on every unit both before and after refreshing
    to the locally built charm.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    bring_up_self_signed_traefik(juju, tmp_path)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    url = verify_https_through_all_traefik_units(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_through_all_traefik_units(juju, expected_url=url)


def run_ssc_single_unit_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy a single-unit traefik at *source_revision* with self-signed certs, then upgrade it.

    Verifies HTTPS stays reachable on the single unit both before and after
    refreshing to the locally built charm.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        trust=True,
    )
    bring_up_self_signed_traefik(juju, tmp_path)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    url = verify_https_through_all_traefik_units(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_through_all_traefik_units(juju, expected_url=url)


def run_mtls_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy traefik at *source_revision* with manual TLS certs, then upgrade it.

    Verifies the migrated key still matches the certificate on every unit and
    that no new certificate request was raised by the upgrade.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    bring_up_certified_traefik(juju, tmp_path)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    url = verify_https_through_all_traefik_units(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_through_all_traefik_units(juju, expected_url=url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )


def run_mtls_single_unit_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy a single-unit traefik at *source_revision* with manual TLS certs, then upgrade it.

    Verifies the migrated key still matches the certificate on the single unit
    and that no new certificate request was raised by the upgrade.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        trust=True,
    )
    bring_up_certified_traefik(juju, tmp_path)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    url = verify_https_through_all_traefik_units(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_through_all_traefik_units(juju, expected_url=url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )
