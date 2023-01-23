from unittest.mock import patch

from pytest_interface_tester import InterfaceTester
from scenario.structs import State, NetworkSpec, network

from charm import TraefikIngressCharm


def test_ingress_interface(interface_tester: InterfaceTester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.configure(
            target=TraefikIngressCharm,
            repo="https://github.com/PietroPasotti/charm-relation-interfaces",
            branch='tester'
        )
        interface_tester.run(
            interface_name='ingress',
            state_template=State(
                config={"external_hostname": "0.0.0.0"},
                networks=[
                    NetworkSpec(
                        'metrics-endpoint',
                        bind_id=0,
                        network=network()
                    )
                ]
            )
        )
