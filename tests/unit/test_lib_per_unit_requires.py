# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from textwrap import dedent

import pytest
import yaml
from charms.traefik_k8s.v1.ingress_per_unit import (
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRequirer,
)
from ops.charm import CharmBase
from ops.model import Relation
from ops.testing import Harness

from tests.unit.capture import capture, capture_events


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
