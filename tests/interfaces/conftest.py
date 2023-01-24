from unittest.mock import patch

import pytest
from pytest_interface_tester import InterfaceTester


from pytest_interface_tester import InterfaceTester
from scenario.structs import State, NetworkSpec, network

from charm import TraefikIngressCharm

@pytest.fixture
def itester(interface_tester: InterfaceTester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.configure(
            target=TraefikIngressCharm,
            state_template=State(
                config={
                    "external_hostname": "0.0.0.0",
                },
                networks=[
                    NetworkSpec(
                        'metrics-endpoint',
                        bind_id=0,
                        network=network()
                    )
                ]
            )
        )
        yield interface_tester
