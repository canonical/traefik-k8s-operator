#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment with self-signed certificates from revision 298."""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from upgrade_tests_helper import run_ssc_single_unit_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_ssc_single_unit_from_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, ingress_app, tmp_path
):
    """A single traefik unit keeps serving HTTPS after upgrading from rev 298."""
    run_ssc_single_unit_upgrade_scenario(
        juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION
    )
