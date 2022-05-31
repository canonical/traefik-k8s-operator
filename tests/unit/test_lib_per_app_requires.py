# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent
from unittest.mock import Mock

import pytest
from ops.model import Binding

from charms.traefik_k8s.v0.ingress import IngressPerAppRequirer
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness
from test_lib_helpers import MockIPAProvider


class MockRequirerCharm(CharmBase):
    META = dedent(
        """\
        name: test-requirer
        requires:
          ingress:
            interface: ingress
            limit: 1
        """
    )

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._stored.set_default(num_events=0)
        self.ipa = IngressPerAppRequirer(self, port=80)
        self.framework.observe(self.ipa.on.ready, self.record_events)
        self.framework.observe(self.ipa.on.revoked, self.record_events)

    def record_events(self, _):
        self._stored.num_events += 1


@pytest.fixture(autouse=True, scope="function")
def patch_network(monkeypatch):
    monkeypatch.setattr(Binding, "network", Mock(bind_address="10.10.10.10"))


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness._backend.model_name = "test-model"
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def provider(harness):
    return MockIPAProvider(harness)


@pytest.fixture(scope="function")
def requirer(harness):
    requirer = harness.charm.ipa
    return requirer


def test_ingress_app_requirer_uninitialized(
        requirer: IngressPerAppRequirer,
        provider: MockIPAProvider,
        harness):
    assert not requirer.is_ready()
    assert not provider.is_ready()

    assert harness.charm._stored.num_events == 0


def test_ingress_app_requirer_related(
        requirer: IngressPerAppRequirer,
        provider: MockIPAProvider,
        harness):
    harness.set_leader(True)
    relation = provider.relate()

    assert not requirer.is_ready()
    # provider goes to ready immediately because we inited ipa with port=80.
    # auto-data feature...
    assert provider.is_ready(relation)

    requirer.provide_ingress_requirements(host='foo', port=42)
    assert provider.is_ready(relation)
    assert not requirer.is_ready()

    assert harness.charm._stored.num_events == 0
    provider.publish_url(relation, 'url')
    assert harness.charm._stored.num_events == 1

    assert provider.is_ready(relation)
    assert requirer.is_ready()

    assert requirer.url == 'url'

    assert harness.charm._stored.num_events == 1
    provider.publish_url(relation, 'url2')
    assert harness.charm._stored.num_events == 2

    assert provider.is_ready(relation)
    assert requirer.is_ready()
    assert requirer.url == 'url2'
