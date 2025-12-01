#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for pebble connection checks in traefik-route ready event."""

from unittest.mock import PropertyMock, patch

import pytest
from scenario import Relation, State


@patch(
    "charm.TraefikIngressCharm._static_config_changed",
    new_callable=PropertyMock,
    return_value=False,
)
@patch("traefik.Traefik.generate_static_config")
@pytest.mark.parametrize("can_connect", [False, True])
def test_traefik_route_ready_handles_pebble_connection(
    mock_generate_static_config,
    mock_static_config_changed,
    traefik_ctx,
    traefik_container,
    model,
    can_connect,
):
    """Test that traefik-route ready event handler correctly checks pebble connection."""
    container = traefik_container.replace(can_connect=can_connect)

    traefik_route_relation = Relation(
        endpoint="traefik-route",
        remote_app_name="remote-app",
        remote_app_data={"config": "key: value"},
    )

    state = State(
        leader=True,
        containers=[container],
        relations=[traefik_route_relation],
        model=model,
    )

    out_state = traefik_ctx.run(
        traefik_route_relation.changed_event,
        state,
    )

    assert out_state is not None

    if not can_connect:
        mock_generate_static_config.assert_not_called()
    else:
        mock_generate_static_config.assert_called_once()
