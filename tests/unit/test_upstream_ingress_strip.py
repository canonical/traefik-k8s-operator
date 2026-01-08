
import unittest
from unittest.mock import PropertyMock, patch

import ops.testing
from ops.testing import Harness

from charm import TraefikIngressCharm

ops.testing.SIMULATE_CAN_CONNECT = True


class TestUpstreamIngressStrip(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)
        self.harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)
        self.harness.handle_exec(
            "traefik", ["find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"], result=0
        )

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

    @patch("charm.TraefikIngressCharm._get_loadbalancer_status", new_callable=PropertyMock)
    def test_ingressed_address_strips_slash(self, mock_get_lb_status):
        mock_get_lb_status.return_value = "1.2.3.4"

        self.harness.set_leader(True)
        self.harness.begin()

        charm = self.harness.charm
        ingress_per_app_requirer_class = type(charm.upstream_ingress)

        with patch.object(ingress_per_app_requirer_class, "is_ready", autospec=True) as mock_is_ready:
            with patch.object(ingress_per_app_requirer_class, "url", new_callable=PropertyMock) as mock_url:

                # Mock is_ready to return True
                mock_is_ready.return_value = True

                # Mock url property
                mock_url.return_value = "https://upstream.example.com/some/path/"

                # Asserting what we WANT (stripped slash)
                self.assertEqual(charm._ingressed_address, "upstream.example.com/some/path")

    @patch("charm.TraefikIngressCharm._get_loadbalancer_status", new_callable=PropertyMock)
    def test_ingressed_address_base_url_strips_slash(self, mock_get_lb_status):
        mock_get_lb_status.return_value = "1.2.3.4"

        self.harness.set_leader(True)
        self.harness.begin()

        charm = self.harness.charm
        ingress_per_app_requirer_class = type(charm.upstream_ingress)

        with patch.object(ingress_per_app_requirer_class, "is_ready", autospec=True) as mock_is_ready:
            with patch.object(ingress_per_app_requirer_class, "url", new_callable=PropertyMock) as mock_url:

                # Mock is_ready to return True
                mock_is_ready.return_value = True

                # Mock url property
                mock_url.return_value = "https://upstream.example.com/"

                # Asserting what we WANT (stripped slash)
                self.assertEqual(charm._ingressed_address, "upstream.example.com")
