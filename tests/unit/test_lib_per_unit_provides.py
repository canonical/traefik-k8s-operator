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
    relation = requirer.relate()
    if leader:
        # no app data to write yet, so leadership shouldn't matter.
        harness.set_leader(True)

    assert provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)


def test_ingress_unit_provider_request(provider, requirer, harness):
    relation = requirer.relate()
    requirer.request(port=80)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)


def test_ingress_unit_provider_request_response_nonleader(provider, requirer, harness):
    relation = requirer.relate()
    requirer.request(port=80)
    request = provider.get_request(relation)
    assert request.units[0] is requirer.charm.unit
    assert request.app_name == "ingress-per-unit-remote"
    # fails because unit isn't leader
    with pytest.raises(RelationPermissionError):
        request.respond(requirer.charm.unit, "http://url/")


def test_ingress_unit_provider_request_response(provider, requirer, harness):
    relation = requirer.relate()
    harness.set_leader(True)
    requirer.request(port=80)
    request = provider.get_request(relation)
    assert request.units[0] is requirer.charm.unit
    assert request.app_name == "ingress-per-unit-remote"
    request.respond(requirer.charm.unit, "http://url/")
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"ingress-per-unit-remote/0": "http://url/"}
    assert requirer.url == "http://url/"
