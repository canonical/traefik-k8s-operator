# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions exclusively used by traefik upgrade integration tests.

These orchestrate a full upgrade scenario (deploy an old Charmhub revision,
bring up an integration, verify, refresh to the locally built charm, verify
again) or support the leadership-change variants of those scenarios. They
have no shared mutable state with ``helpers.py`` and are never imported by
non-upgrade tests; the certificate/CA machinery and the verification
functions that non-upgrade tests also use (``verify_https_on_all_units``,
``pull_ssc_ca_certificate``, ``bring_up_certified_traefik``,
``bring_up_self_signed_traefik``, etc.) remain in ``helpers.py``.
"""

import logging
from pathlib import Path
from typing import Optional

import jubilant
import requests
from constants import (
    INGRESS_REQUIRER_APP_NAME,
    MOCK_HOSTNAME,
    NUM_TRAEFIK_UNITS,
    SOURCE_CHANNEL,
    TRAEFIK_APP_NAME,
    TRAEFIK_CHARM,
)
from helpers import (
    _get_with_retry,
    _ingress_url,
    _unit_address,
    _url_for_unit,
    all_settled,
    bring_up_certified_traefik,
    bring_up_self_signed_traefik,
    get_outstanding_csrs,
    verify_https_on_all_units,
    verify_https_on_unit,
)

logger = logging.getLogger(__name__)


def assert_traefik_revision(juju: jubilant.Juju, expected_revision: int) -> None:
    """Assert traefik's deployed charm revision matches *expected_revision*.

    The locally built charm reports revision ``0``; a charm refreshed to a
    specific Charmhub revision reports that revision.
    """
    actual_revision = juju.status().apps[TRAEFIK_APP_NAME].charm_rev
    assert actual_revision == expected_revision, (
        f"Expected traefik at revision {expected_revision}, but found {actual_revision}"
    )


def verify_http_on_all_units(
    juju: jubilant.Juju,
    expected_url: Optional[str] = None,
) -> str:
    """Assert HTTP is reachable through every traefik unit.

    Returns the ingress URL that was verified so callers can assert it is
    unchanged across an upgrade.
    """
    ingress_url = f"{_ingress_url(juju).rstrip('/')}/health"
    assert ingress_url.startswith("http://"), (
        f"expected plain HTTP proxied URL without a certificate provider, got {ingress_url!r}"
    )
    if expected_url is not None:
        assert ingress_url == expected_url, (
            f"Proxied URL changed across upgrade: {expected_url!r} -> {ingress_url!r}"
        )

    status = juju.status()
    units = status.apps[TRAEFIK_APP_NAME].units

    for unit_name, unit_status in units.items():
        unit_ip = unit_status.address
        logger.info("Verifying HTTP on %s (%s) -> %s", unit_name, unit_ip, ingress_url)
        session = requests.Session()
        session.headers["Host"] = MOCK_HOSTNAME
        _get_with_retry(session, _url_for_unit(ingress_url, unit_ip))

    return ingress_url


def verify_http_on_unit(juju: jubilant.Juju, unit_name: str, ingress_url: str) -> None:
    """Assert HTTP returns 200 on a specific traefik unit."""
    assert ingress_url.startswith("http://"), (
        f"expected plain HTTP proxied URL without a certificate provider, got {ingress_url!r}"
    )
    unit_ip = _unit_address(juju, unit_name)
    logger.info("Verifying HTTP on %s (%s) -> %s", unit_name, unit_ip, ingress_url)
    session = requests.Session()
    session.headers["Host"] = MOCK_HOSTNAME
    _get_with_retry(session, _url_for_unit(ingress_url, unit_ip))


def leader_unit_name(juju: jubilant.Juju, app: str = TRAEFIK_APP_NAME) -> str:
    """Return the name of the current leader unit of *app*."""
    for name, unit in juju.status().apps[app].units.items():
        if unit.leader:
            return name
    raise AssertionError(f"no leader found for {app!r}")


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


def bring_up_traefik_without_certificate_provider(juju: jubilant.Juju) -> str:
    """Integrate the ingress requirer and verify plain HTTP on all traefik units."""
    juju.integrate(f"{INGRESS_REQUIRER_APP_NAME}:require-ingress", TRAEFIK_APP_NAME)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    return verify_http_on_all_units(juju)


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
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_traefik_without_certificate_provider(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_http_on_all_units(juju, expected_url=url)


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
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_self_signed_traefik(juju, tmp_path)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_all_units(juju, expected_url=url)


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
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_self_signed_traefik(juju, tmp_path)
    unit_name = next(iter(juju.status().apps[TRAEFIK_APP_NAME].units))

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_unit(juju, unit_name, url)


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
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_certified_traefik(juju, tmp_path)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_all_units(juju, expected_url=url)
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
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_certified_traefik(juju, tmp_path)
    unit_name = next(iter(juju.status().apps[TRAEFIK_APP_NAME].units))

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_unit(juju, unit_name, url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )
