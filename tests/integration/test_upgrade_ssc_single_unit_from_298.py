#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment with self-signed certificates from revision 298."""

import logging

import jubilant
import pytest
from conftest import TRAEFIK_APP_NAME, TRAEFIK_RESOURCES
from constants import MOCK_HOSTNAME, SOURCE_CHANNEL, TRAEFIK_CHARM
from helpers import (
    all_settled,
    any_error,
    assert_traefik_revision,
    bring_up_self_signed_traefik,
    verify_https_on_unit,
)

logger = logging.getLogger(__name__)

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_ssc_single_unit_from_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, alertmanager_app, tmp_path
):
    """A single traefik unit keeps serving HTTPS after upgrading from rev 298."""
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=SOURCE_REVISION,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=any_error, timeout=900, delay=5, successes=5)
    url = bring_up_self_signed_traefik(juju, tmp_path)
    unit_name = next(iter(juju.status().apps[TRAEFIK_APP_NAME].units))

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=TRAEFIK_RESOURCES)
    juju.wait(all_settled, error=any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_unit(juju, unit_name, url)
