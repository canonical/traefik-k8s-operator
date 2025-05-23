# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import yaml
from charms.harness_extensions.v0.capture_events import capture_events
from charms.traefik_k8s.v1.ingress_per_unit import (
    IngressPerUnitReadyEvent,
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRequirer,
    IngressPerUnitRevokedEvent,
    IngressPerUnitRevokedForUnitEvent,
)
from ops.charm import CharmBase
from ops.testing import Harness


@pytest.fixture(params=("only-this-unit", "all-units", "both"))
def listen_to(request):
    return request.param


@pytest.fixture
def charm_cls(listen_to):
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.ipu = IngressPerUnitRequirer(self, host="foo.com", port=80, listen_to=listen_to)

            self.framework.observe(self.ipu.on.ready, self._on_event)
            self.framework.observe(self.ipu.on.revoked, self._on_event)
            self.framework.observe(self.ipu.on.ready_for_unit, self._on_event)
            self.framework.observe(self.ipu.on.revoked_for_unit, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


META = yaml.safe_dump(
    {"name": "my_charm", "requires": {"ingress-per-unit": {"interface": "ingress-per-unit"}}}
)


@pytest.fixture
def harness(charm_cls):
    return Harness(charm_cls, meta=META)


@pytest.fixture
def charm(harness):
    harness.set_model_name("unittest_model")
    harness.begin()
    return harness.charm


@pytest.fixture(params=("url.com", "foo.org"))
def url(request):
    return request.param


def relate(harness: Harness):
    relation_id = harness.add_relation("ingress-per-unit", "remote")
    harness.add_relation_unit(relation_id, "remote/0")
    return harness.model.get_relation("ingress-per-unit", relation_id)


def _requirer_provide_ingress(harness: Harness, unit_name: str, url: str, relation):
    # same as provider.publish_url(relation, unit_name, url)
    data = harness.get_relation_data(relation.id, "remote").get("ingress")
    data = yaml.safe_load(data) if data else {}
    data[unit_name] = {"url": url}
    harness.update_relation_data(relation.id, "remote", {"ingress": yaml.safe_dump(data)})


IPUEvents = (
    IngressPerUnitReadyEvent,
    IngressPerUnitRevokedEvent,
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRevokedForUnitEvent,
)


def test_ready_single_unit(harness, charm, listen_to, url):
    with capture_events(charm, *IPUEvents) as captured:
        _requirer_provide_ingress(harness, charm.unit.name, url, relate(harness))

    if listen_to == "only-this-unit":
        assert len(captured) == 1
        event = captured[0]
        assert isinstance(event, IngressPerUnitReadyForUnitEvent)
    elif listen_to == "all-units":
        assert len(captured) == 1
        event = captured[0]
        assert isinstance(event, IngressPerUnitReadyEvent)
    else:  # 'both'
        assert len(captured) == 2
        forunit, forall = captured
        assert isinstance(forunit, IngressPerUnitReadyForUnitEvent)
        assert isinstance(forall, IngressPerUnitReadyEvent)

    assert charm.ipu.url == url
    assert charm.ipu.urls == {charm.unit.name: url}


def test_ready_other_unit(harness, charm, listen_to, url):
    relation = relate(harness)
    _requirer_provide_ingress(harness, charm.unit.name, url, relation)
    assert relation

    new_unit_name = relation.app.name + "1"
    new_unit_url = url + "/new_unit"
    harness.add_relation_unit(relation.id, new_unit_name)

    # we provide ingress to the new unit
    with capture_events(charm, *IPUEvents) as captured:
        _requirer_provide_ingress(harness, new_unit_name, new_unit_url, relation)

    if listen_to == "only-this-unit":
        # no event captured, because we're only listening to events
        # pertaining THIS unit.
        assert len(captured) == 0
    else:  # 'both' and 'all-units' are equivalent here
        # captured: we also want to be informed to peer events.
        assert len(captured) == 1
        event = captured[0]
        assert isinstance(event, IngressPerUnitReadyEvent)

    assert charm.ipu.url == url
    assert charm.ipu.urls == {charm.unit.name: url, new_unit_name: new_unit_url}
