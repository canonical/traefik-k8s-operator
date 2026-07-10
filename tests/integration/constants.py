# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared constants for traefik integration tests."""

ALERTMANAGER_APP_NAME = "alertmanager"
TRAEFIK_APP_NAME = "traefik"
MANUAL_TLS_APP_NAME = "manual-tls-certificates"
MANUAL_TLS_CHANNEL = "1/stable"
SSC_APP_NAME = "ssc"
SSC_CHARM = "self-signed-certificates"
SSC_CHANNEL = "1/stable"
TRAEFIK_CHARM = "ch:traefik-k8s"
SOURCE_CHANNEL = "latest/edge"
NUM_TRAEFIK_UNITS = 3
MOCK_HOSTNAME = "traefik-demo.local"
