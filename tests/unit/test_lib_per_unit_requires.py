# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from textwrap import dedent

import pytest
import yaml
from charms.harness_extensions.v0.capture_events import capture, capture_events
from charms.traefik_k8s.v1.ingress_per_unit import (
    DataValidationError,
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRequirer,
)
from ops.charm import CharmBase
from ops.model import Relation
from ops.testing import Harness


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitRequirer(self, port=80)


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness.set_model_name("test-model")
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def requirer(harness):
    requirer = harness.charm.ipu
    return requirer


def relate(harness: Harness[MockRequirerCharm]):
    relation_id = harness.add_relation("ingress-per-unit", "remote")
    harness.add_relation_unit(relation_id, "remote/0")
    return harness.model.get_relation("ingress-per-unit", relation_id)


def _requirer_provide_ingress(
    harness: Harness[MockRequirerCharm], unit_name: str, url: str, relation: Relation
):
    # same as provider.publish_url(relation, unit_name, url)
    data = harness.get_relation_data(relation.id, "remote").get("ingress")
    data = yaml.safe_load(data) if data else {}
    data[unit_name] = {"url": url}
    harness.update_relation_data(relation.id, "remote", {"ingress": yaml.safe_dump(data)})


def test_ingress_unit_requirer_uninitialized(requirer):
    assert not requirer.is_ready()


@pytest.mark.parametrize("url", ("http://foo.bar", "http://foo.bar.baz/42"))
@pytest.mark.parametrize("leader", (1, 0))
def test_ingress_unit_requirer_related(requirer, harness, url, leader):
    harness.set_leader(leader)
    relation = relate(harness)
    with capture_events(harness.charm) as captured:
        _requirer_provide_ingress(harness, harness.charm.unit.name, url, relation)

    assert requirer.is_ready()
    assert requirer.url == url
    assert requirer.urls == {harness.charm.unit.name: url}

    # a RelationChangedEvent and a IngressPerUnitReadyForUnitEvent
    assert len(captured) == 2
    event = captured[1]

    assert isinstance(event, IngressPerUnitReadyForUnitEvent)
    assert event.url == url


@pytest.mark.parametrize("url", ("http://url/", "http://url2/"))
def test_unit_joining_does_not_trigger_ingress_changed(requirer, harness, url):
    requirer: IngressPerUnitRequirer
    relation = relate(harness)

    with capture(harness.charm, IngressPerUnitReadyForUnitEvent):
        _requirer_provide_ingress(harness, harness.charm.unit.name, url, relation)

    new_peer = harness.charm.unit.name + "1"
    with capture_events(harness.charm, IngressPerUnitReadyForUnitEvent) as captured:
        # another unit joining shouldn't give this charm any changed event
        harness.add_relation_unit(relation.id, new_peer)
        _requirer_provide_ingress(harness, new_peer, "foo.bar.com", relation)

    assert len(captured) == 0
    assert requirer.is_ready()
    assert requirer.urls == {"test-requirer/0": url, new_peer: "foo.bar.com"}
    assert requirer.url == url

    # change to a new url: should trigger data changed.
    with capture(harness.charm, IngressPerUnitReadyForUnitEvent):
        _requirer_provide_ingress(
            harness, harness.charm.unit.name, "a_different_url.com", relation
        )


@pytest.mark.parametrize(
    "auto_data, ok",
    (
        ((True, 42), False),
        ((10, False), False),
        ((10, None), False),
        (("foo", 12), True),
    ),
)
def test_validator(requirer: IngressPerUnitRequirer, harness, auto_data, ok):
    harness.set_leader(True)
    harness.add_relation("ingress-per-unit", "remote")
    if not ok:
        with pytest.raises(DataValidationError):
            host, port = auto_data
            requirer.provide_ingress_requirements(host=host, port=port)
    else:
        host, port = auto_data
        requirer.provide_ingress_requirements(host=host, port=port)


class TestIPUEventsEmission(unittest.TestCase):
    class _RequirerCharm(CharmBase):
        META = dedent(
            """\
            name: ipu-requirer
            requires:
              ingress:
                interface: ingress_per_unit
                limit: 1
            """
        )

        ready_event_count: int = 0
        revoked_event_count: int = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ipu = IngressPerUnitRequirer(self, relation_name="ingress", port=80)
            self.framework.observe(self.ipu.on.ready_for_unit, self._on_ready)
            self.framework.observe(self.ipu.on.revoked_for_unit, self._on_revoked)

        def _on_ready(self, _event):
            self.ready_event_count += 1

        def _on_revoked(self, _event):
            self.revoked_event_count += 1

    def setUp(self):
        self.harness = Harness(self._RequirerCharm, meta=self._RequirerCharm.META)
        self.addCleanup(self.harness.cleanup)

        self.harness.set_model_name(self.__class__.__name__)
        self.harness.begin_with_initial_hooks()

    def test_ipu_events(self):
        # WHEN an ingress relation is formed
        before = self.harness.charm.ready_event_count
        self.rel_id = self.harness.add_relation("ingress", "traefik-app")
        self.harness.add_relation_unit(self.rel_id, "traefik-app/0")

        # AND an ingress is in effect
        data = {self.harness.charm.unit.name: {"url": "http://a.b/c"}}
        self.harness.update_relation_data(
            self.rel_id, "traefik-app", {"ingress": yaml.safe_dump(data)}
        )
        self.assertEqual(self.harness.charm.ipu.url, "http://a.b/c")

        # THEN the ready event is emitted
        after = self.harness.charm.ready_event_count
        self.assertGreater(after, before)

        # WHEN a relation with traefik is removed
        before = self.harness.charm.revoked_event_count
        self.harness.remove_relation_unit(self.rel_id, "traefik-app/0")
        self.harness.remove_relation(self.rel_id)

        # NOTE intentionally not emptying out relation data manually

        # THEN ingress.url returns a false-y value
        self.assertFalse(self.harness.charm.ipu.url)

        # AND a revoked event fires
        after = self.harness.charm.revoked_event_count
        self.assertGreater(after, before)
