# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for the logging relation (Loki log forwarding)."""

import json
from unittest.mock import PropertyMock, patch

from scenario import Relation, State

LOKI_URL = "http://loki:3100/loki/api/v1/push"

LOG_FORWARDING_LAYER = "traefik-log-forwarding"


def _logging_relation() -> Relation:
    return Relation(
        endpoint="logging",
        remote_app_name="loki",
        remote_units_data={0: {"endpoint": json.dumps({"url": LOKI_URL})}},
    )


def _log_targets(container) -> dict:
    return container.layers[LOG_FORWARDING_LAYER].to_dict().get("log-targets", {})


@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
class TestLogForwarding:
    """Tests for Pebble log forwarding to Loki via the logging relation."""

    def test_pebble_ready_configures_log_target(self, traefik_ctx, traefik_container):
        """pebble-ready with a ready Loki relation must add a Pebble log target."""
        # GIVEN a Loki logging relation whose provider already published an endpoint
        logging_rel = _logging_relation()
        state = State(
            leader=True,
            relations=[logging_rel],
            containers=[traefik_container],
        )

        # WHEN pebble-ready fires
        state_out = traefik_ctx.run(traefik_container.pebble_ready_event, state)

        # THEN the Pebble config contains a loki log target for the endpoint
        container_out = state_out.get_container("traefik")
        target = _log_targets(container_out)["loki/0"]
        assert target["type"] == "loki"
        assert target["services"] == ["all"]
        assert target["location"] == LOKI_URL
        labels = target["labels"]
        assert labels["juju_unit"] == "traefik-k8s/0"
        assert labels["charm"] == "traefik-k8s"

    def test_relation_changed_after_pebble_ready_configures_log_target(
        self, traefik_ctx, traefik_container
    ):
        """A relation-changed after pebble-ready must add the Pebble log target."""
        # GIVEN pebble-ready fired with no logging relation yet
        state_0 = State(
            leader=True,
            containers=[traefik_container],
        )
        state_1 = traefik_ctx.run(traefik_container.pebble_ready_event, state_0)
        assert LOG_FORWARDING_LAYER not in state_1.get_container("traefik").layers

        # WHEN the Loki relation is created and the provider publishes its endpoint
        logging_rel = _logging_relation()
        state_2 = traefik_ctx.run(
            logging_rel.changed_event,
            state_1.replace(relations=[logging_rel]),
        )

        # THEN a loki log target is added to the Pebble config
        container_out = state_2.get_container("traefik")
        assert _log_targets(container_out)["loki/0"]["location"] == LOKI_URL
