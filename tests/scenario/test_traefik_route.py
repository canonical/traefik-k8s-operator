# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Scenario tests for TraefikRouteProvider and related changes."""

from unittest.mock import PropertyMock, patch


@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="0.0.0"))
class TestWipeIngressDataTraefikRoute:
    """Tests for wipe_ingress_data on TraefikRouteProvider."""

    def test_wipe_ingress_data_clears_relation_data(self, traefik_ctx, tr_rel, tr_state):
        """wipe_ingress_data removes external_host and scheme from traefik-route relation."""
        with traefik_ctx.manager(tr_rel.changed_event, tr_state) as mgr:
            charm = mgr.charm
            relation = charm.model.get_relation("traefik-route")

            # Pre-set data to simulate published ingress
            relation.data[charm.app]["external_host"] = "10.0.0.1"
            relation.data[charm.app]["scheme"] = "http"

            charm.traefik_route.wipe_ingress_data(relation)

            assert "external_host" not in relation.data[charm.app]
            assert "scheme" not in relation.data[charm.app]

    def test_wipe_ingress_data_resets_stored_state(self, traefik_ctx, tr_rel, tr_state):
        """wipe_ingress_data sets stored external_host and scheme to None."""
        with traefik_ctx.manager(tr_rel.changed_event, tr_state) as mgr:
            charm = mgr.charm
            relation = charm.model.get_relation("traefik-route")

            # Pre-set stored state
            charm.traefik_route._stored.external_host = "10.0.0.1"
            charm.traefik_route._stored.scheme = "http"

            # Pre-set relation data so pop works
            relation.data[charm.app]["external_host"] = "10.0.0.1"
            relation.data[charm.app]["scheme"] = "http"

            charm.traefik_route.wipe_ingress_data(relation)

            assert charm.traefik_route._stored.external_host is None
            assert charm.traefik_route._stored.scheme is None

    def test_wipe_ingress_data_noop_for_non_leader(
        self, traefik_ctx, tr_rel, tr_state
    ):
        """wipe_ingress_data does nothing when the unit is not leader."""
        non_leader_state = tr_state.replace(leader=False)

        with traefik_ctx.manager(tr_rel.changed_event, non_leader_state) as mgr:
            charm = mgr.charm
            relation = charm.model.get_relation("traefik-route")

            charm.traefik_route.wipe_ingress_data(relation)

            # Data should remain because non-leader cannot modify app data
            assert relation.data[charm.app].get("external_host") == "10.0.0.1"
            assert relation.data[charm.app].get("scheme") == "http"

    def test_wipe_ingress_for_all_relations_includes_traefik_route(
        self, traefik_ctx, tr_rel, tr_state
    ):
        """_wipe_ingress_for_all_relations clears traefik-route relation data."""
        with traefik_ctx.manager(tr_rel.changed_event, tr_state) as mgr:
            charm = mgr.charm
            relation = charm.model.get_relation("traefik-route")

            # Pre-set data
            relation.data[charm.app]["external_host"] = "10.0.0.1"
            relation.data[charm.app]["scheme"] = "http"

            charm._wipe_ingress_for_all_relations()

            assert "external_host" not in relation.data[charm.app]
            assert "scheme" not in relation.data[charm.app]
