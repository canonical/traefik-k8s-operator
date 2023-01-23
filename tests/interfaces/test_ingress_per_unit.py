from unittest.mock import patch

from pytest_interface_tester import InterfaceTester
from scenario.structs import State

from charm import TraefikIngressCharm


def test_ingress_per_unit_interface(interface_tester: InterfaceTester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.configure(
            target=TraefikIngressCharm,
            repo="https://github.com/PietroPasotti/charm-relation-interfaces",
            branch='tester'
        )
        interface_tester.run(
            interface_name='ingress_per_unit',
            state_template=State(
                config={"external_hostname": "0.0.0.0"}
            )
        )
