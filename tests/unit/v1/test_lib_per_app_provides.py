# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent
from unittest.mock import Mock

import pytest
from charms.traefik_k8s.v0.ingress import IngressPerAppProvider
from ops.charm import CharmBase
from ops.model import Binding
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


@pytest.fixture(autouse=True, scope="function")
def patch_network(monkeypatch):
    monkeypatch.setattr(Binding, "network", Mock(bind_address="10.10.10.10"))


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockProviderCharm, meta=MockProviderCharm.META)
    harness._backend.model_name = "test-model"
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def requirer(harness):
    return MockIPARequirer(harness)


@pytest.fixture(scope="function")
def provider(harness):
    provider = harness.charm.ipa
    return provider


def test_ingress_app_provider_uninitialized(
    provider: IngressPerAppProvider, requirer: MockIPARequirer
):
    assert not provider.relations
    assert not provider.is_ready()
    assert not requirer.relations
    assert not requirer.is_ready()


def test_ingress_app_provider_related(provider: IngressPerAppProvider, requirer: MockIPARequirer):
    relation = requirer.relate()
    assert not provider.is_ready(relation)
    assert not requirer.is_ready(relation)


def test_ingress_app_provider_relate_provide(
    provider: IngressPerAppProvider, requirer: MockIPARequirer, harness
):
    harness.set_leader(True)
    relation = requirer.relate()
    requirer.provide_ingress_requirements(host="host", port=42)
    assert provider.is_ready(relation)
    assert not requirer.is_ready(relation)

    provider.publish_url(relation, "foo.com")
    assert requirer.is_ready(relation)


def test_ingress_app_provider_supported_versions_shim(provider, requirer, harness):
    harness.set_leader(True)
    relation = requirer.relate()
    assert relation.data[provider.charm.app]["_supported_versions"] == "- v1"
