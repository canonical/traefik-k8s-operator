# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent

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
        self.framework.observe(self.ipa.on.ingress_changed, self.record_events)

    def record_events(self, _):
        self._stored.num_events += 1


def test_ingress_app_requirer():
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness._backend.model_name = "test-model"
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    requirer = harness.charm.ipa
    provider = MockIPAProvider(harness)

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
    assert provider.is_failed(relation)  # because it has no versions

    harness.set_leader(True)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert provider.is_available(relation)
    # assert provider.is_ready(relation)
    assert not provider.is_failed(relation)

    request = provider.get_request(relation)

    assert request.app_name == "ingress-remote"
    assert harness.charm._stored.num_events == 1
    request.respond("http://url/")
    # FIXME Change to 2 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 2
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.url == "http://url/"

    # Test that an ingress unit joining does not trigger a new ingress_changed event
    harness.add_relation_unit(relation.id, "ingress-remote/1")
    assert harness.charm._stored.num_events == 2

    request.respond("http://url2/")
    # FIXME Change to 3 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 3
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.url == "http://url2/"

    request.respond("http://url2/")
    # FIXME Change to 2 when https://github.com/canonical/operator/pull/705 ships
    assert harness.charm._stored.num_events == 3
