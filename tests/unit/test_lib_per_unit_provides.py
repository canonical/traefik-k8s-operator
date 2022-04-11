# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent
from unittest.mock import Mock

import pytest
from charms.traefik_k8s.v0.ingress_per_unit import (
    IngressPerUnitProvider,
    RelationPermissionError,
)
from ops.charm import CharmBase
from ops.model import Binding
from ops.testing import Harness
from test_lib_helpers import MockIPURequirer


class MockProviderCharm(CharmBase):
    META = dedent(
        """\
        name: test-provider
        provides:
          ingress-per-unit:
            interface: ingress_per_unit
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitProvider(self)


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
    return MockIPURequirer(harness)


@pytest.fixture(scope="function")
def provider(harness):
    provider = harness.charm.ipu
    return provider


def test_ingress_unit_provider_uninitialized(provider, requirer):
    assert not provider.is_available()
    assert not provider.is_ready()
    assert not provider.is_failed()
    assert not requirer.is_available()
    assert not requirer.is_ready()
    assert not requirer.is_failed()


@pytest.mark.parametrize("leader", (True, False))
def test_ingress_unit_provider_related(provider, requirer, harness, leader):
    harness.set_leader(leader)
    relation = requirer.relate()

    assert provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)


@pytest.mark.parametrize("leader", (True, False))
def test_ingress_unit_provider_supported_versions_shim(provider, requirer, harness, leader):
    harness.set_leader(leader)
    relation = requirer.relate()
    if leader:
        assert relation.data[provider.charm.app]["_supported_versions"] == "- v1"


def test_ingress_unit_provider_request(provider, requirer, harness):
    relation = requirer.relate()
    requirer.provide_ingress_requirements(port=80)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)


@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response_nonleader(provider, requirer, harness, port, host):
    provider: IngressPerUnitProvider
    relation = requirer.relate()
    requirer.provide_ingress_requirements(port=port, host=host)

    unit_data = provider.get_data(relation, requirer.charm.unit, validate=True)
    assert unit_data["model"] == requirer.charm.model.name
    assert unit_data["name"] == requirer.charm.unit.name
    assert unit_data["host"] == host
    assert unit_data["port"] == port

    # fail because unit isn't leader
    with pytest.raises(RelationPermissionError):
        provider.publish_url(relation, unit_data["name"], "http://url/")


@pytest.mark.parametrize("url", ("http://url/", "http://url2/"))
def test_ingress_unit_provider_request_response(provider, requirer, harness, url):
    relation = requirer.relate()
    harness.set_leader(True)
    requirer.provide_ingress_requirements(port=80)

    provider.publish_url(relation, requirer.unit.name, url)
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"ingress-per-unit-remote/0": url}
    assert requirer.url == url
