# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from interface_tester import InterfaceTester


def test_ingress_v1_interface(interface_tester: InterfaceTester):
    interface_tester.configure(
        interface_name="ingress",
        interface_version=1,
    )
    interface_tester.run()


def test_ingress_v2_interface(interface_tester: InterfaceTester):
    interface_tester.configure(
        interface_name="ingress",
        interface_version=2,
    )
    interface_tester.run()
