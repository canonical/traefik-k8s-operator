# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import PropertyMock, patch

from charm import TraefikIngressCharm
from ops.model import ActiveStatus
from scenario import Container, State


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
class TestWorkloadVersion(unittest.TestCase):
    def setUp(self) -> None:
        self.containers = [Container(name="traefik", can_connect=True)]
        self.state = State(
            config={"routing_mode": "path"},
            containers=self.containers,
        )

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
    @patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
    @patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="1.2.3"))
    def test_workload_version_is_set_on_update_status(self, *_):
        # GIVEN an initial state without the workload version set
        out = self.state.trigger("start", TraefikIngressCharm)
        self.assertEqual(out.status.unit, ActiveStatus(""))
        self.assertEqual(out.status.app_version, "")

        # WHEN update-status is triggered
        out = out.trigger("update-status", TraefikIngressCharm)

        # THEN the workload version is set
        self.assertEqual(out.status.app_version, "1.2.3")

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
    @patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
    @patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="1.2.3"))
    def test_workload_version_clears_on_stop(self, *_):
        # GIVEN a state after update-status (which we know sets the workload version)
        # GIVEN an initial state with the workload version set
        out = self.state.trigger("update-status", TraefikIngressCharm)
        self.assertEqual(out.status.unit, ActiveStatus(""))
        self.assertEqual(out.status.app_version, "1.2.3")

        # WHEN the charm is stopped
        out = out.trigger("stop", TraefikIngressCharm)

        # THEN workload version is cleared
        self.assertEqual(out.status.app_version, "")
