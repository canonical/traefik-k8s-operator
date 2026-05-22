# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for the Traefik workload class."""

from dataclasses import replace
from unittest.mock import PropertyMock, patch

from ops.model import ActiveStatus
from scenario import Relation, State


@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
class TestDeleteDynamicConfigs:
    """Tests for Traefik.delete_dynamic_configs."""

    def test_pebble_ready_no_dynamic_config_dir(self, traefik_ctx, traefik_container):
        """pebble-ready should not crash when /opt/traefik/juju does not exist.

        This is the scenario from GH issue #684: on first container start the
        dynamic config directory has not been created yet, and the find command
        would fail with a non-zero exit code.
        """
        # GIVEN a container where /opt/traefik/juju does NOT exist
        # Remove the find exec mock to prove it's never called (would error otherwise)
        exec_mock_without_find = {
            k: v
            for k, v in traefik_container.exec_mock.items()
            if k != ("find", "/opt/traefik/juju", "-name", "*.yaml", "-delete")
        }
        container = replace(traefik_container, exec_mock=exec_mock_without_find)

        state = State(
            leader=True,
            containers=[container],
        )

        # WHEN pebble-ready fires
        state_out = traefik_ctx.run(container.pebble_ready_event, state)

        # THEN the charm does not crash and the dynamic config dir is created by configure()
        traefik_fs = state_out.get_container("traefik").get_filesystem(traefik_ctx)
        assert (traefik_fs / "opt" / "traefik" / "juju").exists()

    def test_pebble_ready_with_dynamic_config_dir(self, traefik_ctx, traefik_container, tmp_path):
        """pebble-ready should delete yamls when /opt/traefik/juju exists."""
        # GIVEN a container where /opt/traefik/juju exists (with a yaml file in it)
        (tmp_path / "traefik" / "juju").mkdir(parents=True, exist_ok=True)
        (tmp_path / "traefik" / "juju" / "stale_config.yaml").write_text("http: {}")

        state = State(
            leader=True,
            containers=[traefik_container],
        )

        # WHEN pebble-ready fires
        # THEN the charm does not crash (find exec is called and mocked successfully)
        state_out = traefik_ctx.run(traefik_container.pebble_ready_event, state)
        assert state_out.unit_status.name == "active"


@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
@patch("charm.TraefikIngressCharm._ingressed_address", PropertyMock(return_value="10.0.0.1"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
class TestDeleteDynamicConfig:
    """Tests for Traefik.delete_dynamic_config."""

    def test_relation_broken_no_config_file(self, traefik_ctx, traefik_container, tmp_path):
        """Relation broken should not crash when the config file doesn't exist.

        When a relation is broken, _wipe_ingress_for_relation calls
        delete_dynamic_config for a file that may not exist (e.g. if pebble-ready
        already cleaned it or it was never created).
        """
        # GIVEN a container with the dynamic config dir but no config file for the relation
        (tmp_path / "traefik" / "juju").mkdir(parents=True, exist_ok=True)

        ingress_rel = Relation(
            endpoint="ingress",
            remote_app_name="remote-app",
            remote_app_data={
                "model": "test-model",
                "name": "remote-app",
                "port": "8080",
            },
            remote_units_data={0: {"host": '"remote-app-0.remote-app-endpoints"'}},
        )

        state = State(
            leader=True,
            containers=[traefik_container],
            relations=[ingress_rel],
            unit_status=ActiveStatus("Serving at https://10.0.0.1"),
        )

        # WHEN the relation broken event fires
        # THEN the charm does not crash even though no config file exists for this relation
        state_out = traefik_ctx.run(ingress_rel.broken_event, state)
        assert state_out.unit_status.name == "active"
