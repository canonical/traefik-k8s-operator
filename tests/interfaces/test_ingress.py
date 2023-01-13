from unittest.mock import patch

from interface_tester import InterfaceTester

from charm import TraefikIngressCharm


def test_ingress_interface(interface_tester: InterfaceTester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.run(
            TraefikIngressCharm,
            interface_name='ingress',
            config={"external_hostname": "0.0.0.0"},
        )


def test_ingress_per_unit_interface(interface_tester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.run(
            TraefikIngressCharm,
            interface_name='ingress_per_unit',
            config={"external_hostname": "0.0.0.0"},
        )


def test_all_interfaces(interface_tester):
    with patch("charm.KubernetesServicePatch", lambda **unused: None):
        interface_tester.run(
            TraefikIngressCharm,
            config={"external_hostname": "0.0.0.0"},
        )
