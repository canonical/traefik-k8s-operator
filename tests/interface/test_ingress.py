# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest
from interface_tester import InterfaceTester

# Add here any charm interfaces that are registered to charm-relation-interfaces
ALL_TESTABLE_INTERFACES = ["ingress", "ingress_per_unit"]


@pytest.mark.parametrize("interface_name", ALL_TESTABLE_INTERFACES, ids=ALL_TESTABLE_INTERFACES)
def test_ingress_interface(interface_tester: InterfaceTester, interface_name: str):
    interface_tester.configure(
        # TODO: remove when the tester branch hits main
        repo="https://github.com/PietroPasotti/charm-relation-interfaces",
        branch="interface_tester/tester_plugin",
        interface_name=interface_name,
    )
    interface_tester.run()
