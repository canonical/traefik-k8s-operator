from unittest.mock import patch

import pytest
from interface_tester import InterfaceTester
from ops.pebble import Layer
from scenario.state import State, Container

from charm import TraefikIngressCharm


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.configure(
            # TODO: remove when the tester branch hits main
            repo="https://github.com/PietroPasotti/charm-relation-interfaces",
            branch="interface_tester/tester_plugin",
            charm_type=TraefikIngressCharm,
            state_template=State(
                leader=True,
                config={
                    # if we don't pass external_hostname, we have to mock all sorts of lightkube calls
                    "external_hostname": "0.0.0.0",
                    # since we're passing a config, we have to provide all defaulted values
                    "routing_mode": "path",
                },
                containers=[
                    # unless the traefik service reports active, the charm won't publish the ingress url.
                    Container(
                        name="traefik",
                        can_connect=True,
                        layers={"foo": Layer(
                            {
                                "summary": "foo",
                                "description": "bar",
                                "services": {
                                    "traefik": {
                                        "startup": "enabled",
                                        "current": "active",
                                        "name": "traefik",
                                    }
                                },
                                "checks": {},
                            }
                        )
                        }
                    )
                ],
            ),
        )
        yield interface_tester
