# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import PropertyMock, patch

from ops.model import ActiveStatus
from scenario import Container, Context, State

from charm import TraefikIngressCharm


@patch("charm.KubernetesLoadBalancer")
@patch("lightkube.core.client.GenericSyncClient")
@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="foo.bar"))
@patch("traefik.Traefik.is_ready", PropertyMock(return_value=True))
@patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="1.2.3"))
class TestWorkloadVersion(unittest.TestCase):
    def setUp(self) -> None:
        self.containers = [Container(name="traefik", can_connect=True)]
        self.state = State(
            config={"routing_mode": "path"},
            containers=self.containers,
        )
        self.context = Context(charm_type=TraefikIngressCharm)

    def test_workload_version_is_set_on_update_status(self, *_):
        # GIVEN an initial state without the workload version set
        out = self.context.run("start", self.state)
        self.assertEqual(out.unit_status, ActiveStatus("Serving at foo.bar"))
        self.assertEqual(out.workload_version, "")

        # WHEN update-status is triggered
        out = self.context.run("update-status", out)

        # THEN the workload version is set
        self.assertEqual(out.workload_version, "1.2.3")

    def test_workload_version_clears_on_stop(self, *_):
        # GIVEN a state after update-status (which we know sets the workload version)
        # GIVEN an initial state with the workload version set
        out = self.context.run("update-status", self.state)
        self.assertEqual(out.unit_status, ActiveStatus("Serving at foo.bar"))
        self.assertEqual(out.workload_version, "1.2.3")

        # WHEN the charm is stopped
        out = self.context.run("stop", out)

        # THEN workload version is cleared
        self.assertEqual(out.workload_version, "")
