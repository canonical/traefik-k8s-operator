# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from charm import TraefikIngressCharm
from scenario import Container, Context, State, Relation


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
class TestMiddlewares(unittest.TestCase):
    def setUp(self) -> None:
        self.containers = [Container(name="traefik", can_connect=True)]

        version_patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.version_patch = version_patcher.start()
        self.addCleanup(version_patcher.stop)

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="testhostname"))
    @patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
    @patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
    def test_start_traefik_is_not_running(self, *_):
        # GIVEN an ingress (per app) relation is requesting middlewares (strip prefix and
        #  redirect-https)
        relation = Relation(
            endpoint="ingress",
            interface="ingress",
            remote_app_name="remote",
            relation_id=0,
            remote_app_data={
                "port": str(9000),
                "host": "10.1.10.1",
                "model": "test-model",
                "name": "remote/0",
                "mode": "http",
                "strip-prefix": "true",
                "redirect-https": "true",
            }
        )

        # AND GIVEN external host is set (see also decorator)
        state = State(
            leader=True,
            config={"routing_mode": "path", "external_hostname": "testhostname"},
            containers=self.containers,
            relations=[relation],
        )

        # WHEN a `relation-changed` hook fires
        out = Context(charm_type=TraefikIngressCharm).run(relation.changed_event, state)

        # THEN the rendered config file contains middlewares
        with out.get_container("traefik").filesystem.open("/opt/traefik/juju/juju_ingress_ingress_now_what.yaml", "rt") as f:
            config_file = f.readlines()
        expected = {}  # TODO
        self.assertEqual(expected, config_file)


if __name__ == "__main__":
    unittest.main()
