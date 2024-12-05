# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import patch

import pytest
from interface_tester import InterfaceTester
from ops.pebble import Layer
from scenario.state import Container, ExecOutput, State

from charm import TraefikIngressCharm


# Interface tests are centrally hosted at https://github.com/canonical/charm-relation-interfaces.
# this fixture is used by the test runner of charm-relation-interfaces to test traefik's compliance
# with the interface specifications.
# DO NOT MOVE OR RENAME THIS FIXTURE! If you need to, you'll need to open a PR on
# https://github.com/canonical/charm-relation-interfaces and change traefik's test configuration
# to include the new identifier/location.
@pytest.fixture
def interface_tester(interface_tester: InterfaceTester):
    with patch("charm.KubernetesLoadBalancer", lambda **unused: None):
        interface_tester.configure(
            charm_type=TraefikIngressCharm,
            state_template=State(
                leader=True,
                config={
                    # if we don't pass external_hostname, we have to mock
                    # all sorts of lightkube calls
                    "external_hostname": "0.0.0.0",
                    # since we're passing a config, we have to provide all defaulted values
                    "routing_mode": "path",
                },
                containers=[
                    # unless the traefik service reports active, the
                    # charm won't publish the ingress url.
                    Container(
                        name="traefik",
                        can_connect=True,
                        exec_mock={
                            (
                                "find",
                                "/opt/traefik/juju",
                                "-name",
                                "*.yaml",
                                "-delete",
                            ): ExecOutput()
                        },
                        layers={
                            "foo": Layer(
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
                        },
                    )
                ],
            ),
        )
        yield interface_tester
