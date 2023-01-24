from pytest_interface_tester import InterfaceTester


def test_ingress_interface(itester: InterfaceTester, subtests):
    itester.configure(
        repo="https://github.com/PietroPasotti/charm-relation-interfaces",
        branch='tester',
        interface_name='ingress'
    )
    itester.run(subtests=subtests)
