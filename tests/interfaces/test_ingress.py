from interface_tester import InterfaceTester


def test_ingress_interface(interface_tester: InterfaceTester):
    interface_tester.configure(
        # TODO: remove when the tester branch hits main
        repo="https://github.com/PietroPasotti/charm-relation-interfaces",
        branch="interface_tester/tester_plugin",
        interface_name="ingress",
    )
    interface_tester.run()
