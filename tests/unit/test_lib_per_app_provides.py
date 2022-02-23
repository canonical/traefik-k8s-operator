# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent

from charms.traefik_k8s.v0.ingress import IngressPerAppProvider
from ops.charm import CharmBase
from ops.testing import Harness
from test_lib_helpers import MockIPARequirer


class MockProviderCharm(CharmBase):
    META = dedent(
        """\
        name: test-provider
        provides:
          ingress:
            interface: ingress
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipa = IngressPerAppProvider(self)


def test_ingress_app_provider():
    harness = Harness(MockProviderCharm, meta=MockProviderCharm.META)
    harness._backend.model_name = "test-model"
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    provider = harness.charm.ipa
    requirer = MockIPARequirer(harness)

    assert not provider.is_available()
    assert not provider.is_ready()
    assert not provider.is_failed()
    assert not requirer.is_available()
    assert not requirer.is_ready()
    assert not requirer.is_failed()

    relation = requirer.relate()
    assert provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert not requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert requirer.is_failed(relation)  # because it has no versions

    harness.set_leader(True)
    assert provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)

    requirer.request(port=80)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)

    request = provider.get_request(relation)
    assert request.app_name == "ingress-remote"
    request.respond("http://url/")
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.url == "http://url/"
