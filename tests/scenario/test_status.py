import unittest
from unittest.mock import MagicMock, PropertyMock, patch
from scenario import Container, State
from charm import _TRAEFIK_SERVICE_NAME, TraefikIngressCharm


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
class TestUnitStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.containers = [Container(name="traefik", can_connect=True)]
        self.state = State(
            config={"routing_mode": "path"},
            containers=self.containers,
        )

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
    def test_start_traefik_is_not_running(self, *_):
        # GIVEN external host is set (see decorator)
        # WHEN a `start` hook fires
        out = self.state.trigger("start", TraefikIngressCharm)

        # THEN unit status is `waiting`
        self.assertEqual(out.status.unit, ("waiting", "waiting for service: 'traefik'"))

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
    def test_start_traefik_no_hostname(self, *_):
        # GIVEN external host is not set (see decorator)
        # WHEN a `start` hook fires
        out = self.state.trigger("start", TraefikIngressCharm)

        # THEN unit status is `waiting`
        self.assertEqual(out.status.unit, ("waiting", "gateway address unavailable"))

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value="foo.bar"))
    @patch("charm.TraefikIngressCharm._traefik_service_running", PropertyMock(return_value=True))
    @patch("charm.TraefikIngressCharm._tcp_entrypoints_changed", MagicMock(return_value=False))
    def test_start_traefik_active(self, *_):
        # GIVEN external host is set (see decorator), plus additional mockery
        # WHEN a `start` hook fires
        out = self.state.trigger("start", TraefikIngressCharm)

        # THEN unit status is `active`
        self.assertEqual(out.status.unit, ("active", ""))

    @patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value=False))
    def test_start_traefik_invalid_routing_mode(self, *_):
        # GIVEN external host is not set (see decorator)
        # AND an invalid config for routing mode
        state = State(
            config={"routing_mode": "invalid_routing"},
            containers=self.containers,
        )

        # WHEN a `start` hook fires
        out = state.trigger("start", TraefikIngressCharm)

        # THEN unit status is `blocked`
        self.assertEqual(out.status.unit, ("blocked", "invalid routing mode: invalid_routing; see logs."))


if __name__ == '__main__':
    unittest.main()
