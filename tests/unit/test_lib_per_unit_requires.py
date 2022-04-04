# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from ipaddress import IPv4Address
from textwrap import dedent
from unittest.mock import Mock

import pytest
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.model import Binding
from ops.testing import Harness
from test_lib_helpers import MockIPUProvider


class MockRequirerCharm(CharmBase):
    META = dedent(
        """\
        name: test-requirer
        requires:
          ingress-per-unit:
            interface: ingress_per_unit
            limit: 1
        """
    )

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stored.set_default(num_events=0)
        self.ipu = IngressPerUnitRequirer(self, port=80)
        self.framework.observe(self.ipu.on.ingress_changed, self.record_events)

    def record_events(self, _):
        self._stored.num_events += 1


@pytest.fixture(autouse=True, scope="function")
def patch_network(monkeypatch):
    monkeypatch.setattr(Binding, "network", Mock(bind_address=IPv4Address("10.10.10.10")))


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness._backend.model_name = "test-model"
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def provider(harness):
    return MockIPUProvider(harness)


@pytest.fixture(scope="function")
def requirer(harness):
    requirer = harness.charm.ipu
    return requirer


def test_ingress_unit_requirer_uninitialized(requirer, provider, harness):
    assert not requirer.is_available()
    assert not requirer.is_ready()
    assert not requirer.is_failed()
    assert not provider.is_available()
    assert not provider.is_ready()
    assert not provider.is_failed()

    assert harness.charm._stored.num_events == 0


def test_ingress_unit_requirer_related(requirer, provider, harness):
    relation = provider.relate()

    assert harness.charm._stored.num_events == 0

    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)


def test_ingress_unit_requirer_leader(requirer, provider, harness):
    relation = provider.relate()
    harness.set_leader(True)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)

    request = provider.get_request(relation)
    assert request.units[0] is requirer.charm.unit
    assert request.app_name == "test-requirer"


def test_ingress_unit_requirer_request_response(requirer, provider, harness):
    relation = provider.relate()
    harness.set_leader(True)

    request = provider.get_request(relation)

    request.respond(requirer.charm.unit, "http://url/")
    # FIXME Change to 2 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 0
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"test-requirer/0": "http://url/"}
    assert requirer.url == "http://url/"


def test_unit_joining_does_not_trigger_ingress_changed(requirer, provider, harness):
    relation = provider.relate()
    harness.set_leader(True)
    request = provider.get_request(relation)
    request.respond(requirer.charm.unit, "http://url/")

    harness.add_relation_unit(relation.id, "ingress-remote/1")
    # FIXME Change to 2 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 0

    # respond with new url: should trigger data changed.
    request.respond(requirer.charm.unit, "http://url/2")
    # FIXME Change to 3 when https://github.com/canonical/operator/pull/705 ships
    assert (
        harness.charm._stored.num_events == 0
    )  # FIXME we should see some relation data change here, shouldn't we?
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"test-requirer/0": "http://url/2"}
    assert requirer.url == "http://url/2"

    # respond with same url: should not trigger another event
    request.respond(requirer.charm.unit, "http://url/2")
    # FIXME Change to 3 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 0


def test_ipu_on_new_related_unit_nonready(requirer, provider, harness):
    relation = provider.relate()
    harness.set_leader(True)
    request = provider.get_request(relation)
    request.respond(requirer.charm.unit, "http://url/")

    relation_id = harness._backend._relation_ids_map["ingress-per-unit"][0]
    harness.add_relation_unit(relation_id, remote_unit_name='remote/1')

    relation = harness.charm.model.relations["ingress-per-unit"][0]
    # provider reports ready even though remote/1 has shared no ingress data yet
    assert provider.is_ready()
    assert len(relation.units) == 2
    new_unit = next(u for u in relation.units if u is not requirer.charm.unit)

    request.respond(new_unit, "foo")
