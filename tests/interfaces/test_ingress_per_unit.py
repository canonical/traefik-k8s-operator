from unittest.mock import patch

from pytest_interface_tester import InterfaceTester
from scenario.structs import State

from charm import TraefikIngressCharm


def test_ingress_per_unit_interface(itester: InterfaceTester, subtests):
    itester.configure(
        repo="https://github.com/PietroPasotti/charm-relation-interfaces",
        branch="tester",
        interface_name="ingress-per-unit",
    )
    itester.run(subtests=subtests)
