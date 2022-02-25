# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from ipaddress import IPv4Address
from textwrap import dedent
from unittest.mock import Mock

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


def test_ingress_unit_requirer(monkeypatch):
    monkeypatch.setattr(Binding, "network", Mock(bind_address=IPv4Address("10.10.10.10")))
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness._backend.model_name = "test-model"
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    requirer = harness.charm.ipu
    provider = MockIPUProvider(harness)

    assert not requirer.is_available()
    assert not requirer.is_ready()
    assert not requirer.is_failed()
    assert not provider.is_available()
    assert not provider.is_ready()
    assert not provider.is_failed()

    assert harness.charm._stored.num_events == 0

    relation = provider.relate()

    assert harness.charm._stored.num_events == 1

    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert not provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert provider.is_failed(relation)  # because it has a unit but no versions

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
    request.respond(requirer.charm.unit, "http://url/")
    # FIXME Change to 2 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 3
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"test-requirer/0": "http://url/"}
    assert requirer.url == "http://url/"

    # Test that an ingress unit joining does not trigger a new ingress_changed event
    harness.add_relation_unit(relation.id, "ingress-remote/1")
    # FIXME Change to 2 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 3

    request.respond(requirer.charm.unit, "http://url/2")
    # FIXME Change to 3 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 5
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"test-requirer/0": "http://url/2"}
    assert requirer.url == "http://url/2"

    request.respond(requirer.charm.unit, "http://url/2")
    # FIXME Change to 3 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 7
